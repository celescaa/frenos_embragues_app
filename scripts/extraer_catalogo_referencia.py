"""
Toma un archivo con el mismo formato de Planilla_Stock_Por_Proveedor.xlsx
(generada por generar_planilla_stock_proveedores.py) pero donde, en vez de
cargar el stock real, alguien pegó la lista de precios completa de uno o
varios proveedores (código, categoría, descripción, marca, precio de costo
— sin "Precio venta" ni "Cantidad en stock" reales). Es un caso real: pasó
con Planilla_Stock_Por_Proveedor_completa.xlsx que mandó la hermana de
Celes el 06/08/2026 con 107.140 filas así en 5 de las 12 hojas.

Esas filas NO se cargan como productos (serían productos fantasma con
stock 0 y sin precio de venta, y el negocio no vende ni la mitad de esos
rubros todavía). En cambio, esto arma un catálogo de referencia por
proveedor — solo costo, sin tocar la base de datos — para consultar el
precio de un proveedor el día que se decida sumar ese producto de verdad.

Detecta solas qué hojas son "catálogo" (tienen Descripción y Precio costo
cargados pero NO tienen ninguna fila con "Cantidad en stock") vs. hojas
vacías o que sí tienen stock real cargado (esas se ignoran, no son el caso
de uso de este script).

Uso: python scripts/extraer_catalogo_referencia.py <entrada.xlsx> [salida.xlsx]
  Por defecto escribe en plantillas/Catalogo_Referencia_Proveedores.xlsx.
"""
import sys
import openpyxl

SALIDA_POR_DEFECTO = "listas_proveedores/Catalogo_Referencia_Proveedores.xlsx"

HEADERS_SALIDA = ["Código", "Categoría", "Subcategoría", "Descripción", "Marca", "Modelo compatible", "Precio costo"]
ANCHOS_SALIDA = [18, 20, 28, 50, 18, 20, 14]

HOJAS_IGNORADAS = {"INSTRUCCIONES", "Listas"}


def _limpiar(v):
    return str(v).strip() if v is not None else ""


def extraer(entrada, salida=SALIDA_POR_DEFECTO):
    wb_in = openpyxl.load_workbook(entrada, data_only=True, read_only=True)
    wb_out = openpyxl.Workbook(write_only=True)

    resumen = []

    for nombre_hoja in wb_in.sheetnames:
        if nombre_hoja in HOJAS_IGNORADAS:
            continue
        ws = wb_in[nombre_hoja]
        filas_iter = ws.iter_rows(values_only=True)
        headers = next(filas_iter, None)
        if not headers or "Descripción / Nombre (*)" not in headers:
            continue
        idx = {h: i for i, h in enumerate(headers)}
        i_desc = idx["Descripción / Nombre (*)"]
        i_stock = idx.get("Cantidad en stock (*)")
        i_cod = idx.get("Código interno")
        i_cat = idx.get("Categoría")
        i_sub = idx.get("Subcategoría")
        i_marca = idx.get("Marca")
        i_modelo = idx.get("Modelo compatible")
        i_costo = idx.get("Precio costo (*)")

        def _get(row, i):
            return row[i] if i is not None and i < len(row) else None

        filas = []
        tiene_stock_real = False
        for row in filas_iter:
            if _limpiar(_get(row, i_stock)):
                tiene_stock_real = True
                break  # esta hoja sí tiene stock real cargado, no es catálogo
            desc = _limpiar(_get(row, i_desc))
            if not desc:
                continue
            filas.append((
                _limpiar(_get(row, i_cod)),
                _limpiar(_get(row, i_cat)),
                _limpiar(_get(row, i_sub)),
                desc,
                _limpiar(_get(row, i_marca)),
                _limpiar(_get(row, i_modelo)),
                _get(row, i_costo),
            ))

        if tiene_stock_real or not filas:
            continue

        filas.sort(key=lambda f: (f[1], f[3]))

        nombre_out = nombre_hoja[:31] if len(nombre_hoja) <= 31 else nombre_hoja[:28] + "..."
        ws_out = wb_out.create_sheet(nombre_out)
        ws_out.append(HEADERS_SALIDA)
        for fila in filas:
            ws_out.append(fila)

        resumen.append((nombre_hoja, len(filas)))

    wb_in.close()

    total = sum(cant for _, cant in resumen)
    ws_info = wb_out.create_sheet("INFO", 0)
    lineas_info = [
        "Catálogo de referencia de proveedores (solo costo, no es stock real)",
        "",
        "Esto NO se cargó como productos en el sistema: son listas de precios completas",
        "de cada proveedor (código, categoría, descripción, marca, precio de costo), sin",
        "cantidad en stock real ni precio de venta definido. Sirve para consultar cuánto",
        "cobra cada proveedor el día que se decida sumar un producto nuevo de verdad —",
        "ahí sí se carga a mano en el sistema, con su stock y precio de venta reales.",
        "",
        "Proveedores incluidos y cantidad de productos en su lista de precios:",
    ]
    for linea in lineas_info:
        ws_info.append([linea])
    for nombre_hoja, cant in resumen:
        ws_info.append([f"  - {nombre_hoja}: {cant} productos"])
    ws_info.append([f"Total: {total} productos"])

    wb_out.save(salida)
    print(f"Guardado en: {salida}")
    for nombre_hoja, cant in resumen:
        print(f"  {nombre_hoja}: {cant} productos")
    print(f"Total: {total} productos")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python scripts/extraer_catalogo_referencia.py <entrada.xlsx> [salida.xlsx]")
        sys.exit(1)
    entrada = sys.argv[1]
    salida = sys.argv[2] if len(sys.argv) > 2 else SALIDA_POR_DEFECTO
    extraer(entrada, salida)
