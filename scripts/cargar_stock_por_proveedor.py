"""
Importa la planilla generada por generar_planilla_stock_proveedores.py (una
hoja por proveedor, con el stock real completado a mano) a la base del
sistema.

A diferencia de importar_datos.py (que espera una sola hoja PRODUCTOS con
una columna PROVEEDOR por fila), acá el proveedor de cada producto es el
nombre de la hoja donde está — no hace falta repetirlo por fila.

Es seguro correrlo más de una vez: si un producto ya existe (mismo código o
mismo nombre), actualiza sus datos en vez de duplicarlo. "Cantidad en stock"
reemplaza el stock actual (no lo suma) — es para cargar el estado real, no
para registrar una compra.

Si el mismo código ya está cargado bajo OTRO proveedor, no lo pisa: guarda
el precio de este proveedor como una cotización más (tabla
`producto_proveedor`, la que usa el comparador de precios de /pedidos). Pasa
mucho — 12.347 filas de la planilla completa — porque dos distribuidores
venden la misma pieza con el mismo código de fábrica.

Solo carga las filas que tengan "Cantidad en stock" completada. La planilla
lista el catálogo entero de cada proveedor (cientos de miles de filas) y el
local trabaja una fracción; la cantidad escrita a mano es lo que distingue
"esto lo tenemos" de "esto el proveedor lo vende". Una fila sin cantidad se
saltea, y el resumen final dice cuántas fueron.

Uso (desde la raíz del proyecto): python scripts/cargar_stock_por_proveedor.py [archivo.xlsx]
  Por defecto lee plantillas/Planilla_Stock_Por_Proveedor.xlsx.
"""
import sys
import os
from openpyxl import load_workbook

# database.py vive en el paquete core/, en la raíz del proyecto (un nivel
# arriba de scripts/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import database as db
# reutiliza _limpiar/_numero/_normalizar_categoria (sibling en scripts/). Se
# importa como `scripts.importar_datos` (no `import importar_datos` a secas)
# para que este módulo se pueda importar como `scripts.cargar_stock_por_proveedor`
# (por ejemplo desde tests/test_scripts.py) sin depender de que scripts/ esté
# en sys.path -- algo que solo pasa solo cuando se corre como script suelto.
from scripts import importar_datos as idatos

ARCHIVO_POR_DEFECTO = "plantillas/Planilla_Stock_Por_Proveedor.xlsx"
NOMBRE_PROVEEDOR_SIN_IDENTIFICAR = "Proveedor sin identificar (revisar)"


def _filas_de_hoja(ws):
    """Se salta el encabezado (busca la fila que dice 'Cargar' en A) y,
    en la hoja SIN IDENTIFICAR, también el aviso de arriba."""
    encabezado_visto = False
    for fila in ws.iter_rows(values_only=True):
        if fila is None:
            continue
        primera_celda = idatos._limpiar(fila[0]).upper()
        if not encabezado_visto:
            if primera_celda.startswith("CARGAR"):
                encabezado_visto = True
            continue
        if all(c is None or str(c).strip() == "" for c in fila):
            continue
        yield fila


def obtener_o_crear_proveedor(conn, nombre, resumen=None):
    fila = conn.execute("SELECT id FROM proveedores WHERE nombre = %s", (nombre,)).fetchone()
    if fila:
        return fila["id"]
    nuevo = conn.execute(
        "INSERT INTO proveedores (nombre) VALUES (%s) RETURNING id", (nombre,)
    ).fetchone()
    if resumen is not None:
        resumen["proveedores_nuevos"] += 1
    return nuevo["id"]


def _guardar_cotizacion(conn, producto_id, proveedor_id, precio_costo, codigo_proveedor):
    """Deja registrado a qué precio vende ESTE proveedor ESTE producto.

    Es la tabla que lee el comparador de precios de /pedidos para agrupar
    cada faltante bajo el proveedor más barato. Antes este importador no la
    tocaba nunca, así que una carga masiva dejaba el comparador vacío por
    más que la planilla tuviera el costo de cada proveedor."""
    conn.execute(
        """INSERT INTO producto_proveedor (producto_id, proveedor_id, precio_costo, codigo_proveedor)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (producto_id, proveedor_id)
           DO UPDATE SET precio_costo = EXCLUDED.precio_costo,
                         codigo_proveedor = EXCLUDED.codigo_proveedor""",
        (producto_id, proveedor_id, precio_costo or 0, codigo_proveedor),
    )


def _procesar_hoja(ws, proveedor_id, proveedor_nombre, conn, resumen):
    for fila in _filas_de_hoja(ws):
        cargar = idatos._limpiar(fila[0]).upper()
        if cargar == "NO":
            continue

        nombre = idatos._limpiar(fila[3])
        if not nombre:
            continue

        # Sin cantidad cargada, el producto no entra. La planilla trae el
        # catálogo COMPLETO de cada proveedor (cientos de miles de filas) y
        # solo unas pocas son cosas que el local realmente tiene: la cantidad
        # escrita a mano es la única señal de eso. Cargar igual las filas
        # vacías llenaría el sistema de productos en stock 0 que nadie vende
        # -- el mismo problema que ya se decidió evitar el 06/08/2026 al no
        # importar los catálogos de referencia de proveedores.
        if idatos._limpiar(fila[8]) == "":
            resumen["sin_cantidad"] += 1
            continue

        codigo = idatos._limpiar(fila[1]) or None
        categoria = idatos._normalizar_categoria(fila[2])
        marca = idatos._limpiar(fila[4])
        modelo_compatible = idatos._limpiar(fila[5])
        precio_costo = idatos._numero(fila[6])
        precio_venta = idatos._numero(fila[7])
        stock_actual = idatos._numero(fila[8], entero=True)
        stock_minimo = idatos._numero(fila[9], entero=True) if idatos._limpiar(fila[9]) != "" else 2
        codigo_barras = idatos._limpiar(fila[10]) or None
        # La columna 12 (subcategoría) existe en la planilla desde que se
        # sumaron las subcategorías (06/08/2026) pero este importador nunca la
        # leía: los productos entraban con el rubro cargado y el subrubro
        # vacío, sin que nada avisara.
        subcategoria = idatos._limpiar(fila[11]) if len(fila) > 11 else ""

        if not precio_venta:
            resumen["avisos"].append(f"'{nombre}' ({proveedor_nombre}): sin precio de venta, revisalo a mano.")

        valores = (
            codigo, nombre, categoria, subcategoria or None, marca, modelo_compatible,
            precio_costo, precio_venta, stock_actual, stock_minimo,
            proveedor_id, codigo_barras,
        )

        existente = None
        if codigo:
            existente = conn.execute(
                "SELECT id, proveedor_id FROM productos WHERE codigo = %s", (codigo,)
            ).fetchone()
        # El match por nombre es SOLO para las filas sin código. Con código,
        # que no aparezca en la base significa que es un producto nuevo, y
        # punto: buscarlo igual por nombre lo hace chocar con otro producto
        # que se llama igual pero es otra pieza. Zerbini lista 12 rodamientos
        # distintos (30203, 30205, 30208, 30211...) con la descripción
        # idéntica "RODAMIENTO DE RODILLOS (CON JAULA) CONO Y CUBETA": se
        # colapsaban todos en uno, cada uno pisando al anterior y llevándose
        # el código del último.
        if not existente and not codigo:
            existente = conn.execute(
                "SELECT id, proveedor_id FROM productos WHERE nombre = %s AND codigo IS NULL",
                (nombre,),
            ).fetchone()

        # El mismo código en la hoja de otro proveedor NO es un producto para
        # pisar: casi siempre es la misma pieza que dos distribuidores venden
        # (el extremo LT10006 está en Distrisuper y en Zerbini, la homocinética
        # NJH25-129A en tres listas). Como `productos.codigo` es UNIQUE, el
        # UPDATE de más abajo le cambiaría al producto ya cargado el nombre, el
        # precio, el stock y hasta el proveedor, sin avisar -- 12.347 filas de
        # la planilla completa caen en este caso.
        #
        # En vez de eso se guarda el precio de este proveedor como una
        # cotización más, que es justo lo que necesita el comparador de precios
        # de /pedidos para elegir a quién comprarle.
        if existente and existente["proveedor_id"] not in (None, proveedor_id):
            _guardar_cotizacion(conn, existente["id"], proveedor_id, precio_costo, codigo)
            resumen["cotizaciones"] += 1
            continue

        if existente:
            conn.execute(
                """UPDATE productos SET codigo=%s, nombre=%s, categoria=%s, subcategoria=%s, marca=%s,
                   modelo_compatible=%s, precio_costo=%s, precio_venta=%s, stock_actual=%s, stock_minimo=%s,
                   proveedor_id=%s, codigo_barras=%s WHERE id=%s""",
                (*valores, existente["id"]),
            )
            producto_id = existente["id"]
            resumen["productos_actualizados"] += 1
        else:
            producto_id = conn.execute(
                """INSERT INTO productos
                   (codigo, nombre, categoria, subcategoria, marca, modelo_compatible, precio_costo,
                    precio_venta, stock_actual, stock_minimo, proveedor_id, codigo_barras)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                valores,
            ).fetchone()["id"]
            resumen["productos_nuevos"] += 1

        _guardar_cotizacion(conn, producto_id, proveedor_id, precio_costo, codigo)


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    archivo = sys.argv[1] if len(sys.argv) > 1 else ARCHIVO_POR_DEFECTO
    wb = load_workbook(archivo, data_only=True)
    conn = db.get_connection()

    resumen = {"proveedores_nuevos": 0, "productos_nuevos": 0, "productos_actualizados": 0,
               "sin_cantidad": 0, "sin_identificar": 0, "cotizaciones": 0, "avisos": []}

    for nombre_hoja in wb.sheetnames:
        if nombre_hoja == "INSTRUCCIONES":
            continue
        ws = wb[nombre_hoja]

        if nombre_hoja == "SIN IDENTIFICAR":
            proveedor_nombre = NOMBRE_PROVEEDOR_SIN_IDENTIFICAR
        else:
            proveedor_nombre = nombre_hoja

        proveedor_id = obtener_o_crear_proveedor(conn, proveedor_nombre, resumen)
        antes = resumen["productos_nuevos"] + resumen["productos_actualizados"]
        _procesar_hoja(ws, proveedor_id, proveedor_nombre, conn, resumen)
        cargados = resumen["productos_nuevos"] + resumen["productos_actualizados"] - antes
        if cargados:
            print(f"{proveedor_nombre}: {cargados} productos")
        if proveedor_nombre == NOMBRE_PROVEEDOR_SIN_IDENTIFICAR:
            resumen["sin_identificar"] = cargados
        conn.commit()

    # La tabla `marcas` (la que alimenta el desplegable de sugerencias de la
    # ficha de producto) se llena sola al guardar un producto desde la
    # pantalla, pero este importador no pasa por ahí: sin esta llamada, una
    # carga masiva deja miles de marcas cargadas en productos y el
    # desplegable vacío. La función SQL es idempotente y agrupa por texto
    # normalizado, así que COBREQ/Cobreq/cobreq no entran tres veces.
    conn.execute("SELECT sembrar_marcas_desde_productos()")
    conn.commit()

    conn.close()

    print()
    print("=" * 52)
    print("  IMPORTACION TERMINADA")
    print("=" * 52)
    print(f"  Proveedores nuevos: {resumen['proveedores_nuevos']}")
    print(f"  Productos nuevos: {resumen['productos_nuevos']}")
    print(f"  Productos actualizados: {resumen['productos_actualizados']}")
    print(f"  Filas salteadas por no tener cantidad: {resumen['sin_cantidad']}")
    print(f"  Cotizaciones de otro proveedor para un producto ya cargado: {resumen['cotizaciones']}")
    if resumen["avisos"]:
        print(f"  Avisos ({len(resumen['avisos'])}):")
        for aviso in resumen["avisos"]:
            print(f"   - {aviso}")
    print("=" * 52)
    # El aviso se daba con solo haber creado algún proveedor, así que aparecía
    # aunque la hoja SIN IDENTIFICAR estuviera vacía -- mandaba a revisar
    # productos que no existían. Ahora se avisa solo si de verdad cayó alguno ahí.
    if resumen["sin_identificar"]:
        print(f"\nOjo: {resumen['sin_identificar']} productos quedaron en "
              f"'{NOMBRE_PROVEEDOR_SIN_IDENTIFICAR}'.")
        print("Revisalos y reasignales el proveedor real apenas lo identifiques.")


if __name__ == "__main__":
    main()
