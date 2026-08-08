"""
ARCHIVADO — no forma parte del flujo de trabajo habitual. Se usó una sola
vez (04/08/2026) para cargar un piloto de prueba de Roncal/Eine Frenos a la
base real; ese piloto ya se borró (ver CLAUDE.md, "Estado actual") cuando se
decidió esperar a la carga de stock real por proveedor en su lugar. Se deja
acá solo como referencia de cómo se hizo, no para volver a correrlo.

Carga una tanda de ejemplo desde Lista_Proveedores_Limpia.xlsx (generada por
scripts/limpiar_lista_proveedor.py) a la base real, para probar el flujo
antes de hacer la carga completa ya revisada.

Toma las primeras N filas de cada hoja de proveedor (por defecto 100) tal
como están: no filtra por la columna "Cargar (SI/NO)" ni por "Coincidencias"
todavía (eso se afina en una carga posterior, ya revisada a mano). Crea el
proveedor si no existe, el producto (stock en 0, para ajustarlo a mano según
lo que realmente haya en el local) y la cotización en producto_proveedor
para que el comparador de precios de /pedidos ya lo tenga en cuenta.

Es seguro correrlo más de una vez: usa el código de proveedor (con prefijo)
como clave, así que no duplica si ya se cargó.

Uso (desde la raíz del proyecto): python scripts/archivo/cargar_ejemplo_proveedores.py [archivo.xlsx] [cantidad_por_hoja]
"""
import sys
import sqlite3
import os

# Dos niveles arriba: scripts/archivo/ -> raíz del proyecto (donde vive data.db).
RAIZ_PROYECTO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.environ.get("SI_DB_PATH") or os.path.join(RAIZ_PROYECTO, "data.db")

try:
    import openpyxl
except ImportError:
    print("Falta la librería openpyxl. Instalala con: pip install openpyxl")
    sys.exit(1)

# (nombre de hoja en el Excel, nombre del proveedor en el sistema, prefijo de código)
HOJAS = [
    ("Roncal", "Roncal", "RON"),
    ("Eine Frenos", "Eine Frenos", "EIN"),
]

HEADER_ROW = 3  # fila 1: margen, fila 2: vacía, fila 3: encabezados, datos desde la 4


def get_or_create_proveedor(conn, nombre):
    row = conn.execute("SELECT id FROM proveedores WHERE nombre = ?", (nombre,)).fetchone()
    if row:
        return row[0]
    cur = conn.execute("INSERT INTO proveedores (nombre) VALUES (?)", (nombre,))
    return cur.lastrowid


def cargar_hoja(ws, proveedor_nombre, prefijo, conn, cantidad, resumen):
    proveedor_id = get_or_create_proveedor(conn, proveedor_nombre)
    cargados = 0
    fila = HEADER_ROW + 1
    while cargados < cantidad:
        valores = [ws.cell(row=fila, column=c).value for c in range(1, 9)]
        descripcion = valores[3]
        if descripcion is None or str(descripcion).strip() == "":
            break  # se acabaron los datos de la hoja

        categoria = valores[1] or "Otros"
        codigo_proveedor = str(valores[2]).strip() if valores[2] is not None else ""
        marca = valores[4] or None
        costo = float(valores[6] or 0)
        precio_venta = float(valores[7] or 0)
        codigo_sistema = f"{prefijo}-{codigo_proveedor}" if codigo_proveedor else f"{prefijo}-F{fila}"

        existente = conn.execute("SELECT id FROM productos WHERE codigo = ?", (codigo_sistema,)).fetchone()
        if existente:
            producto_id = existente[0]
            resumen["ya_existian"] += 1
        else:
            cur = conn.execute(
                """INSERT INTO productos
                   (codigo, nombre, categoria, marca, precio_costo, precio_venta,
                    stock_actual, stock_minimo, proveedor_id)
                   VALUES (?, ?, ?, ?, ?, ?, 0, 2, ?)""",
                (codigo_sistema, descripcion, categoria, marca, costo, precio_venta, proveedor_id),
            )
            producto_id = cur.lastrowid
            resumen["nuevos"] += 1

        conn.execute(
            """INSERT OR IGNORE INTO producto_proveedor
               (producto_id, proveedor_id, precio_costo, codigo_proveedor)
               VALUES (?, ?, ?, ?)""",
            (producto_id, proveedor_id, costo, codigo_proveedor),
        )

        cargados += 1
        fila += 1
    return cargados


def main():
    archivo = sys.argv[1] if len(sys.argv) > 1 else "listas_proveedores/Lista_Proveedores_Limpia.xlsx"
    cantidad = int(sys.argv[2]) if len(sys.argv) > 2 else 100

    wb = openpyxl.load_workbook(archivo, data_only=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    resumen = {"nuevos": 0, "ya_existian": 0}
    for hoja, proveedor_nombre, prefijo in HOJAS:
        ws = wb[hoja]
        cargados = cargar_hoja(ws, proveedor_nombre, prefijo, conn, cantidad, resumen)
        print(f"{proveedor_nombre}: {cargados} productos procesados (de la hoja '{hoja}')")

    conn.commit()
    conn.close()
    print(f"Listo. Nuevos: {resumen['nuevos']} — ya existían: {resumen['ya_existian']}")


if __name__ == "__main__":
    main()
