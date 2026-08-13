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


def _procesar_hoja(ws, proveedor_id, proveedor_nombre, conn, resumen):
    for fila in _filas_de_hoja(ws):
        cargar = idatos._limpiar(fila[0]).upper()
        if cargar == "NO":
            continue

        nombre = idatos._limpiar(fila[3])
        if not nombre:
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

        if not precio_venta:
            resumen["avisos"].append(f"'{nombre}' ({proveedor_nombre}): sin precio de venta, revisalo a mano.")

        valores = (
            codigo, nombre, categoria, marca, modelo_compatible,
            precio_costo, precio_venta, stock_actual, stock_minimo,
            proveedor_id, codigo_barras,
        )

        existente = None
        if codigo:
            existente = conn.execute("SELECT id FROM productos WHERE codigo = %s", (codigo,)).fetchone()
        if not existente:
            existente = conn.execute("SELECT id FROM productos WHERE nombre = %s", (nombre,)).fetchone()

        if existente:
            conn.execute(
                """UPDATE productos SET codigo=%s, nombre=%s, categoria=%s, marca=%s, modelo_compatible=%s,
                   precio_costo=%s, precio_venta=%s, stock_actual=%s, stock_minimo=%s, proveedor_id=%s,
                   codigo_barras=%s WHERE id=%s""",
                (*valores, existente["id"]),
            )
            resumen["productos_actualizados"] += 1
        else:
            conn.execute(
                """INSERT INTO productos
                   (codigo, nombre, categoria, marca, modelo_compatible, precio_costo, precio_venta,
                    stock_actual, stock_minimo, proveedor_id, codigo_barras)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                valores,
            )
            resumen["productos_nuevos"] += 1


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    archivo = sys.argv[1] if len(sys.argv) > 1 else ARCHIVO_POR_DEFECTO
    wb = load_workbook(archivo, data_only=True)
    conn = db.get_connection()

    resumen = {"proveedores_nuevos": 0, "productos_nuevos": 0, "productos_actualizados": 0, "avisos": []}

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
        conn.commit()

    conn.close()

    print()
    print("=" * 52)
    print("  IMPORTACION TERMINADA")
    print("=" * 52)
    print(f"  Proveedores nuevos: {resumen['proveedores_nuevos']}")
    print(f"  Productos nuevos: {resumen['productos_nuevos']}")
    print(f"  Productos actualizados: {resumen['productos_actualizados']}")
    if resumen["avisos"]:
        print(f"  Avisos ({len(resumen['avisos'])}):")
        for aviso in resumen["avisos"]:
            print(f"   - {aviso}")
    print("=" * 52)
    if resumen["proveedores_nuevos"]:
        print(f"\nOjo: se creó '{NOMBRE_PROVEEDOR_SIN_IDENTIFICAR}' si había filas en esa hoja.")
        print("Revisá esos productos y reasignales el proveedor real apenas lo identifiques.")


if __name__ == "__main__":
    main()
