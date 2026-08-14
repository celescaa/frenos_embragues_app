"""
Importa la planilla `plantillas/Plantilla_Carga_Datos.xlsx` a la base del sistema.

Uso (siempre desde la raíz del proyecto, no desde adentro de scripts/):
    python scripts/importar_datos.py                          # usa plantillas/Plantilla_Carga_Datos.xlsx
    python scripts/importar_datos.py otra_planilla.xlsx       # usa otro archivo
    python scripts/importar_datos.py --reemplazar             # borra los datos existentes antes de importar

Es seguro correrlo más de una vez: si un cliente/proveedor/producto ya existe
(mismo nombre o mismo código), lo actualiza en vez de duplicarlo.
"""
import sys
import os
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache

try:
    from openpyxl import load_workbook
except ImportError:
    print("Falta la librería openpyxl. Instalala con:  pip install openpyxl")
    sys.exit(1)

# database.py vive en el paquete core/, en la raíz del proyecto (un nivel
# arriba de scripts/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import database as db

PLANTILLA_POR_DEFECTO = "plantillas/Plantilla_Carga_Datos.xlsx"

# Categoría escrita en la planilla (sin importar mayúsculas/acentos) -> categoría
# válida del sistema. Se arma en el momento (no al importar el módulo) para
# reflejar las categorías cargadas en la tabla `categorias`, que se pueden
# agregar desde /categorias sin tocar código. Incluye también las viejas
# (Freno/Embrague/Otro), por si la planilla se completó con el desplegable
# anterior o alguien la tipeó a mano distinto.
@lru_cache(maxsize=1)
def _categorias_validas():
    categorias_db = db.obtener_categorias(solo_activas=False)
    validas = {nombre: nombre for nombre in categorias_db}
    validas.update(db.CATEGORIAS_RENOMBRADAS)
    return validas


def _normalizar_categoria(valor):
    """Mapea el texto de la celda CATEGORIA a una categoría válida del
    sistema, sin importar mayúsculas/acentos. Si no matchea nada, "Otros"."""
    texto = _limpiar(valor)
    if not texto:
        return "Otros"
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    ).lower()
    for candidata, destino in _categorias_validas().items():
        candidata_sin_acentos = "".join(
            c for c in unicodedata.normalize("NFD", candidata) if unicodedata.category(c) != "Mn"
        ).lower()
        if sin_acentos == candidata_sin_acentos:
            return destino
    return "Otros"


def _limpiar(valor):
    if valor is None:
        return ""
    return str(valor).strip()


def _numero(valor, entero=False):
    """Tolera el formato argentino (14.900,50) y separadores "$"/espacios.

    Para columnas de plata (entero=False) devuelve `Decimal`, nunca `float`
    -- las columnas son NUMERIC en Postgres y mezclar Decimal con float más
    adelante en una cuenta lanza TypeError, además de reintroducir el error
    de redondeo que esta migración vino a corregir. Para columnas enteras
    (stock, cantidad) sigue devolviendo `int`, sin cambios."""
    if valor is None or str(valor).strip() == "":
        return 0 if entero else Decimal("0")
    texto = str(valor).strip().replace("$", "").replace(" ", "")
    # tolera formato argentino: 14.900,50
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    if entero:
        try:
            return int(float(texto))
        except ValueError:
            return 0
    try:
        return Decimal(texto)
    except InvalidOperation:
        return Decimal("0")


def _es_ejemplo(fila):
    """La plantilla trae una fila de ejemplo en amarillo que hay que ignorar."""
    for celda in fila:
        if celda and str(celda).strip().upper().startswith("EJEMPLO"):
            return True
    return False


def _filas(ws):
    """Devuelve las filas con datos, salteando encabezado, ejemplos y vacías."""
    for fila in ws.iter_rows(min_row=2, values_only=True):
        if fila is None:
            continue
        if all(c is None or str(c).strip() == "" for c in fila):
            continue
        if _es_ejemplo(fila):
            continue
        yield fila


def _fecha(valor):
    """Misma tolerancia de formatos de siempre, pero ahora entrega un
    `datetime.date` (no una cadena "YYYY-MM-DD") -- las columnas de fecha
    son DATE en Postgres."""
    if isinstance(valor, datetime):
        return valor.date()
    texto = _limpiar(valor)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(texto[:10], fmt).date()
        except ValueError:
            continue
    # db.hoy() y no datetime.now(): "hoy" es el día en Argentina, no el del
    # reloj de la máquina donde se corra el script.
    return db.hoy()


# ---------------------------------------------------------------------------
def importar_proveedores(ws, conn, resumen):
    for fila in _filas(ws):
        nombre = _limpiar(fila[0])
        if not nombre:
            continue
        datos = (nombre, _limpiar(fila[1]), _limpiar(fila[2]), _limpiar(fila[3]), _limpiar(fila[4]))
        existente = conn.execute("SELECT id FROM proveedores WHERE nombre = %s", (nombre,)).fetchone()
        if existente:
            conn.execute(
                "UPDATE proveedores SET telefono=%s, email=%s, direccion=%s, cuit=%s WHERE id=%s",
                (*datos[1:], existente["id"]),
            )
            resumen["proveedores_actualizados"] += 1
        else:
            conn.execute(
                "INSERT INTO proveedores (nombre, telefono, email, direccion, cuit) VALUES (%s, %s, %s, %s, %s)",
                datos,
            )
            resumen["proveedores_nuevos"] += 1


def importar_productos(ws, conn, resumen):
    for fila in _filas(ws):
        nombre = _limpiar(fila[1])
        if not nombre:
            continue
        codigo = _limpiar(fila[0]) or None
        categoria_original = _limpiar(fila[2])
        categoria = _normalizar_categoria(fila[2])
        if categoria_original and categoria == "Otros" and categoria_original.lower() != "otros":
            resumen["avisos"].append(
                f"'{nombre}': no reconocí la categoría '{categoria_original}', se cargó como 'Otros'."
            )

        proveedor_nombre = _limpiar(fila[9])
        proveedor_id = None
        if proveedor_nombre:
            p = conn.execute("SELECT id FROM proveedores WHERE nombre = %s", (proveedor_nombre,)).fetchone()
            if p:
                proveedor_id = p["id"]
            else:
                nuevo = conn.execute(
                    "INSERT INTO proveedores (nombre) VALUES (%s) RETURNING id", (proveedor_nombre,)
                ).fetchone()
                proveedor_id = nuevo["id"]
                resumen["proveedores_nuevos"] += 1
                resumen["avisos"].append(
                    f"Se creó el proveedor '{proveedor_nombre}' porque figuraba en un producto pero no en la hoja PROVEEDORES."
                )

        valores = (
            codigo, nombre, categoria, _limpiar(fila[3]), _limpiar(fila[4]),
            _numero(fila[5]), _numero(fila[6]), _numero(fila[7], entero=True),
            _numero(fila[8], entero=True) or 2, proveedor_id, _limpiar(fila[10]) or None,
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


def importar_clientes(ws, conn, resumen):
    hoy = db.hoy()
    for fila in _filas(ws):
        nombre = _limpiar(fila[0])
        if not nombre:
            continue
        datos = (nombre, _limpiar(fila[1]), _limpiar(fila[2]), _limpiar(fila[3]), _limpiar(fila[4]))
        existente = conn.execute("SELECT id FROM clientes WHERE nombre = %s", (nombre,)).fetchone()
        if existente:
            conn.execute(
                "UPDATE clientes SET telefono=%s, email=%s, direccion=%s, cuit_dni=%s WHERE id=%s",
                (*datos[1:], existente["id"]),
            )
            resumen["clientes_actualizados"] += 1
        else:
            conn.execute(
                "INSERT INTO clientes (nombre, telefono, email, direccion, cuit_dni, fecha_alta) VALUES (%s, %s, %s, %s, %s, %s)",
                (*datos, hoy),
            )
            resumen["clientes_nuevos"] += 1


def importar_ventas(ws, conn, resumen):
    """Agrupa las filas por (fecha, cliente, n° comprobante) en una sola venta."""
    agrupadas = {}
    orden = []
    for fila in _filas(ws):
        producto_ref = _limpiar(fila[2])
        if not producto_ref:
            continue
        fecha = _fecha(fila[0])
        cliente_nombre = _limpiar(fila[1])
        comprobante = _limpiar(fila[6])
        clave = (fecha, cliente_nombre, comprobante or f"__fila_{len(orden)}")
        if clave not in agrupadas:
            agrupadas[clave] = {"metodo": _limpiar(fila[5]) or "Efectivo", "items": []}
            orden.append(clave)
        agrupadas[clave]["items"].append(
            (producto_ref, _numero(fila[3], entero=True) or 1, _numero(fila[4]))
        )

    for clave in orden:
        fecha, cliente_nombre, comprobante = clave
        datos = agrupadas[clave]

        cliente_id = None
        if cliente_nombre:
            c = conn.execute("SELECT id FROM clientes WHERE nombre = %s", (cliente_nombre,)).fetchone()
            if c:
                cliente_id = c["id"]
            else:
                nuevo = conn.execute(
                    "INSERT INTO clientes (nombre, fecha_alta) VALUES (%s, %s) RETURNING id",
                    (cliente_nombre, db.hoy()),
                ).fetchone()
                cliente_id = nuevo["id"]
                resumen["clientes_nuevos"] += 1

        items = []
        total = Decimal("0")
        for producto_ref, cantidad, precio in datos["items"]:
            p = conn.execute(
                "SELECT id, precio_venta FROM productos WHERE codigo = %s OR nombre = %s",
                (producto_ref, producto_ref),
            ).fetchone()
            if not p:
                resumen["avisos"].append(
                    f"Venta del {fecha}: no se encontró el producto '{producto_ref}', se salteó esa línea."
                )
                continue
            precio = precio or p["precio_venta"]
            subtotal = cantidad * precio
            total += subtotal
            items.append((p["id"], cantidad, precio, subtotal))

        if not items:
            continue

        numero = comprobante if not comprobante.startswith("__fila_") else ""
        venta = conn.execute(
            """INSERT INTO ventas (fecha, cliente_id, total, metodo_pago, tipo_comprobante, numero_comprobante)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (fecha, cliente_id, total, datos["metodo"], "Remito", numero),
        ).fetchone()
        venta_id = venta["id"]
        for producto_id, cantidad, precio, subtotal in items:
            conn.execute(
                "INSERT INTO venta_items (venta_id, producto_id, cantidad, precio_unitario, subtotal) VALUES (%s, %s, %s, %s, %s)",
                (venta_id, producto_id, cantidad, precio, subtotal),
            )
        resumen["ventas_nuevas"] += 1


# ---------------------------------------------------------------------------
def main():
    args = [a for a in sys.argv[1:]]
    reemplazar = "--reemplazar" in args
    args = [a for a in args if not a.startswith("--")]
    ruta = args[0] if args else PLANTILLA_POR_DEFECTO

    if not os.path.exists(ruta):
        print(f"No encontré el archivo '{ruta}'.")
        print("Poné la planilla completada en esta carpeta y volvé a intentar.")
        sys.exit(1)

    wb = load_workbook(ruta, data_only=True)
    conn = db.get_connection()

    if reemplazar:
        print("Borrando los datos existentes...")
        for tabla in ["venta_items", "ventas", "compra_items", "compras", "productos", "clientes", "proveedores"]:
            conn.execute(f"DELETE FROM {tabla}")
        conn.commit()

    resumen = {
        "proveedores_nuevos": 0, "proveedores_actualizados": 0,
        "productos_nuevos": 0, "productos_actualizados": 0,
        "clientes_nuevos": 0, "clientes_actualizados": 0,
        "ventas_nuevas": 0, "avisos": [],
    }

    orden_hojas = [
        ("PROVEEDORES", importar_proveedores),
        ("PRODUCTOS", importar_productos),
        ("CLIENTES", importar_clientes),
        ("VENTAS HISTORICAS", importar_ventas),
    ]
    for nombre_hoja, funcion in orden_hojas:
        if nombre_hoja in wb.sheetnames:
            funcion(wb[nombre_hoja], conn, resumen)
            conn.commit()
        else:
            resumen["avisos"].append(f"La planilla no tiene la hoja '{nombre_hoja}', se salteó.")

    conn.close()

    print()
    print("=" * 52)
    print("  IMPORTACION TERMINADA")
    print("=" * 52)
    print(f"  Proveedores:  {resumen['proveedores_nuevos']} nuevos, {resumen['proveedores_actualizados']} actualizados")
    print(f"  Productos:    {resumen['productos_nuevos']} nuevos, {resumen['productos_actualizados']} actualizados")
    print(f"  Clientes:     {resumen['clientes_nuevos']} nuevos, {resumen['clientes_actualizados']} actualizados")
    print(f"  Ventas:       {resumen['ventas_nuevas']} importadas")
    if resumen["avisos"]:
        print()
        print("  Avisos:")
        for aviso in resumen["avisos"][:20]:
            print(f"   - {aviso}")
        if len(resumen["avisos"]) > 20:
            print(f"   ... y {len(resumen['avisos']) - 20} avisos más.")
    print("=" * 52)
    print()
    print("Listo. Abrí el sistema con:  python app.py")


if __name__ == "__main__":
    main()
