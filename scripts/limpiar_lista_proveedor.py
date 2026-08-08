"""
Limpia una lista de precios de un proveedor (Excel) y deja solo lo relevante
para frenos/embragues, con precio de venta sugerido y una columna para
marcar qué productos cargar al sistema.

Uso (desde la raíz del proyecto): python scripts/limpiar_lista_proveedor.py [carpeta_entrada] [archivo_salida.xlsx]
  Por defecto lee de la carpeta listas_proveedores/ y escribe ahí mismo
  Lista_Proveedores_Limpia.xlsx.

Pensado para ser reutilizable: cada proveedor nuevo solo necesita su propio
"adaptador" (función que sabe leer sus columnas) — ver ADAPTADORES abajo.
Para sumar un proveedor nuevo en el futuro: agregar una función
adaptador_<nombre>(ws) que devuelva codigo/descripcion/marca/precio_costo
por fila, y una entrada en el diccionario ADAPTADORES con el nombre de
archivo, la hoja y el nombre real del proveedor.
"""
import sys
import unicodedata
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

MARGEN_DEFAULT = 0.30  # 30%, indicado por Celes

PALABRAS_RELEVANTES = [
    "FRENO", "EMBRAGUE", "PASTILLA", "CAMPANA", "COLLARIN", "CORREA DISTRIB",
    "CORREA POLY", "CANERIA DE FRENO", "LIQUIDO DE FRENO", "DISCO DE FRENO",
    "DISCO DE EMBRAGUE",
]


def sin_acentos(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").upper()


def es_relevante(desc):
    d = sin_acentos(desc)
    return any(p in d for p in PALABRAS_RELEVANTES)


def categorizar(desc):
    d = sin_acentos(desc)
    if "EMBRAGUE" in d or "COLLARIN" in d:
        return "Embragues"
    if "CORREA" in d:
        return "Correas"
    if "LIQUIDO" in d and "FRENO" in d:
        return "Líquidos"
    if any(p in d for p in ("FRENO", "PASTILLA", "CAMPANA", "DISCO")):
        return "Frenos"
    return "Otros"


def parsear_precio_ar(valor):
    """Convierte '14.233,53' o '14233,53' o 14233.53 a float."""
    if valor is None:
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip()
    if not texto:
        return 0.0
    texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# Adaptadores: cada proveedor tiene su propio formato de columnas.
# Devuelven una lista de dicts: codigo, descripcion, marca, precio_costo.
# ---------------------------------------------------------------------------
def adaptador_roncal(ws):
    items = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        codigo, cod_roncal, desc, marca, precio = row[0], row[1], row[2], row[3], row[4]
        if not desc:
            continue
        items.append({
            "codigo": str(cod_roncal or codigo or "").strip(),
            "descripcion": str(desc).strip(),
            "marca": str(marca).strip() if marca and str(marca).upper() not in ("SIN MARCA", "VARIOS") else "",
            "precio_costo": parsear_precio_ar(precio),
        })
    return items


def adaptador_exportacion(ws):
    items = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        desc, codigo = row[0], row[1]
        precio_iva = row[6]
        if not desc:
            continue
        items.append({
            "codigo": str(codigo or "").strip(),
            "descripcion": str(desc).strip(),
            "marca": "",
            # Se usa Precio+IVA como costo real de compra (incluye el IVA que
            # como monotributista no se discrimina/recupera). Si esto no es
            # así, avisar para usar la columna "Precio" en su lugar.
            "precio_costo": parsear_precio_ar(precio_iva),
        })
    return items


def adaptador_desconocido(ws):
    """Lista de precios sin nombre de proveedor ni CUIT en el archivo (columnas:
    Código, Marca, Nombre, Lista, Costo, Costo IVA, + columnas de stock por sucursal).
    Se usa 'Costo IVA' como costo real, mismo criterio que adaptador_exportacion."""
    items = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        codigo, marca, desc = row[0], row[1], row[2]
        costo_iva = row[5]
        if not desc:
            continue
        items.append({
            "codigo": str(codigo or "").strip(),
            "descripcion": str(desc).strip(),
            "marca": str(marca).strip() if marca else "",
            "precio_costo": parsear_precio_ar(costo_iva),
        })
    return items


ADAPTADORES = {
    "roncal": ("roncal.xlsx", "roncal", adaptador_roncal, "Roncal"),
    "exportacion": ("Exportación.xlsx", "Exportación", adaptador_exportacion, "Eine Frenos"),
    "desconocido": ("lista_desconocida.xlsx", "Lista de Precios", adaptador_desconocido, "SIN IDENTIFICAR"),
}


def limpiar(nombre_adaptador, carpeta_entrada, margen=MARGEN_DEFAULT):
    archivo, hoja, fn_adaptador, proveedor_nombre = ADAPTADORES[nombre_adaptador]
    wb_in = openpyxl.load_workbook(f"{carpeta_entrada}/{archivo}", data_only=True, read_only=True)
    ws_in = wb_in[hoja]
    items = fn_adaptador(ws_in)
    wb_in.close()

    limpios = []
    for it in items:
        if not es_relevante(it["descripcion"]):
            continue
        if it["precio_costo"] <= 0:
            continue
        it["categoria"] = categorizar(it["descripcion"])
        it["proveedor"] = proveedor_nombre
        limpios.append(it)

    return limpios, proveedor_nombre


def escribir_hoja_revision(wb, nombre_hoja, items, margen):
    ws = wb.create_sheet(nombre_hoja)

    ws["A1"] = "Margen sugerido sobre el costo:"
    ws["B1"] = margen
    ws["B1"].number_format = "0%"
    ws["A1"].font = Font(bold=True)
    ws["B1"].fill = PatternFill("solid", fgColor="FFFF00")

    headers = ["Cargar (SI/NO)", "Categoría", "Código proveedor", "Descripción", "Marca",
               "Proveedor", "Precio costo", "Precio venta sugerido"]
    header_row = 3
    for col, h in enumerate(headers, start=1):
        c = ws.cell(row=header_row, column=col, value=h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="111111")

    for i, it in enumerate(items, start=header_row + 1):
        ws.cell(row=i, column=1, value="NO")
        ws.cell(row=i, column=2, value=it["categoria"])
        ws.cell(row=i, column=3, value=it["codigo"])
        ws.cell(row=i, column=4, value=it["descripcion"])
        ws.cell(row=i, column=5, value=it["marca"])
        ws.cell(row=i, column=6, value=it["proveedor"])
        ws.cell(row=i, column=7, value=round(it["precio_costo"], 2))
        ws.cell(row=i, column=7).number_format = "#,##0.00"
        # Valor calculado (no fórmula): con miles de filas, Excel/LibreOffice
        # tardan demasiado en recalcular en este entorno. Si cambiás el
        # costo o el margen a mano, actualizá el precio sugerido vos mismo
        # (o pedime que regenere el archivo).
        precio_sugerido = round(it["precio_costo"] * (1 + margen), 2)
        ws.cell(row=i, column=8, value=precio_sugerido)
        ws.cell(row=i, column=8).number_format = "#,##0.00"

    dv = DataValidation(type="list", formula1='"SI,NO"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add(f"A{header_row+1}:A{header_row+len(items)}")

    widths = [12, 12, 16, 55, 16, 30, 14, 18]
    for col, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = w

    ws.freeze_panes = f"A{header_row+1}"
    ws.auto_filter.ref = f"A{header_row}:H{header_row+len(items)}"
    return ws


def escribir_hoja_coincidencias(wb, coincidencias, indice=1):
    """coincidencias: lista de (item_roncal, item_eine, score), score 0-1."""
    ws = wb.create_sheet("Coincidencias", indice)

    aviso = (
        "Posibles productos iguales entre Roncal y Eine Frenos, detectados por parecido de texto en la "
        "descripción. NO es un match garantizado: revisá cada fila (marca, descripción completa) antes de "
        "confirmar, sobre todo los de 'Parecido' más bajo — puede haber piezas distintas del mismo vehículo "
        "que se redactan parecido (ej. 'kit de embrague' vs 'flexible de embrague')."
    )
    ws.merge_cells("A1:H1")
    ws["A1"] = aviso
    ws["A1"].font = Font(bold=True, color="9C0006")
    ws["A1"].fill = PatternFill("solid", fgColor="FFC7CE")
    ws["A1"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[1].height = 45

    headers = ["Confirmar (SI/NO)", "Parecido", "Roncal - Descripción", "Roncal - Costo",
               "Eine Frenos - Descripción", "Eine Frenos - Costo", "Diferencia", "Más barato"]
    header_row = 3
    for col, h in enumerate(headers, start=1):
        c = ws.cell(row=header_row, column=col, value=h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="111111")

    coincidencias_ordenadas = sorted(coincidencias, key=lambda t: t[2], reverse=True)
    for i, (r, e, score) in enumerate(coincidencias_ordenadas, start=header_row + 1):
        costo_r = round(r["precio_costo"], 2)
        costo_e = round(e["precio_costo"], 2)
        ws.cell(row=i, column=1, value="NO")
        ws.cell(row=i, column=2, value=round(score, 2))
        ws.cell(row=i, column=3, value=r["descripcion"])
        ws.cell(row=i, column=4, value=costo_r)
        ws.cell(row=i, column=4).number_format = "#,##0.00"
        ws.cell(row=i, column=5, value=e["descripcion"])
        ws.cell(row=i, column=6, value=costo_e)
        ws.cell(row=i, column=6).number_format = "#,##0.00"
        # Valores calculados (no fórmulas) por el mismo motivo que en las hojas de proveedor.
        ws.cell(row=i, column=7, value=round(costo_e - costo_r, 2))
        ws.cell(row=i, column=7).number_format = "#,##0.00"
        ws.cell(row=i, column=8, value="Roncal" if costo_r < costo_e else "Eine Frenos")

    dv = DataValidation(type="list", formula1='"SI,NO"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add(f"A{header_row+1}:A{header_row+len(coincidencias_ordenadas)}")

    widths = [14, 10, 50, 12, 50, 12, 12, 14]
    for col, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = w

    ws.freeze_panes = f"A{header_row+1}"
    ws.auto_filter.ref = f"A{header_row}:H{header_row+len(coincidencias_ordenadas)}"
    return ws


if __name__ == "__main__":
    carpeta_entrada = sys.argv[1] if len(sys.argv) > 1 else "listas_proveedores"
    salida = sys.argv[2] if len(sys.argv) > 2 else "listas_proveedores/Lista_Proveedores_Limpia.xlsx"

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    ws_instr = wb.create_sheet("INSTRUCCIONES", 0)
    ws_instr["A1"] = "Cómo usar esta planilla"
    ws_instr["A1"].font = Font(bold=True, size=14)
    instrucciones = [
        "",
        "Cada hoja es la lista limpia de un proveedor: se sacó todo lo que no es de frenos/embragues",
        "y los productos sin precio cargado (discontinuados). La hoja 'SIN IDENTIFICAR' es una lista de",
        "precios que llegó sin nombre de proveedor ni CUIT en el archivo — si la reconocés, avisame el",
        "proveedor real y actualizo el archivo.",
        "",
        "1. Revisá cada hoja. Podés ordenar/filtrar por Categoría, Marca, Precio, etc. (ya tienen autofiltro).",
        "2. En la columna 'Cargar (SI/NO)' marcá SI en los productos que querés sumar a tu stock real.",
        "3. El 'Precio venta sugerido' ya viene calculado con el margen indicado en la celda B1 de cada",
        "   hoja (30% por defecto). Es un valor fijo, no una fórmula en vivo (el archivo es muy grande",
        "   para que Excel recalcule miles de fórmulas al abrirlo). Si querés otro margen o cambiás algún",
        "   costo, avisame y regenero el archivo con los precios actualizados.",
        "4. La hoja 'Coincidencias' junta productos que parecen ser el mismo repuesto en los dos",
        "   proveedores (para comparar precio y elegir el más barato). Es una detección automática por",
        "   texto, así que puede haber errores: revisá cada fila antes de confirmar.",
        "5. Guardá el archivo y avisame: con eso cargo al sistema solo los productos marcados SI",
        "   (quedan con stock en 0 para que sumes cantidad real a medida que compres).",
    ]
    for i, linea in enumerate(instrucciones, start=2):
        ws_instr.cell(row=i, column=1, value=linea)
    ws_instr.column_dimensions["A"].width = 100

    resumen_filas = []
    for clave in ("roncal", "exportacion", "desconocido"):
        items, proveedor = limpiar(clave, carpeta_entrada)
        nombre_hoja = proveedor[:31] if len(proveedor) <= 31 else proveedor[:28] + "..."
        escribir_hoja_revision(wb, nombre_hoja, items, MARGEN_DEFAULT)
        resumen_filas.append((proveedor, len(items)))
        print(f"{proveedor}: {len(items)} productos relevantes con precio válido")

    # Si ya se calcularon coincidencias entre proveedores (ver buscar_coincidencias.py),
    # se agregan como una hoja extra para comparar precios entre proveedores.
    import os
    import pickle
    pkl_path = os.path.join("/tmp", "coincidencias.pkl")
    if os.path.exists(pkl_path):
        with open(pkl_path, "rb") as f:
            coincidencias = pickle.load(f)
        escribir_hoja_coincidencias(wb, coincidencias, indice=1)
        print(f"Coincidencias: {len(coincidencias)} posibles productos iguales entre proveedores")

    wb.save(salida)
    print("Guardado en:", salida)
