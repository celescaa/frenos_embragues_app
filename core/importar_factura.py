"""
Lee una factura de compra (PDF, Excel o CSV) de un proveedor y trata de
reconocer los productos, cantidades y precios para precargar el formulario
de "Nueva compra". Es un asistente, no un lector infalible: cada línea se
matchea contra el catálogo con un nivel de confianza, y todo se muestra en
una pantalla de revisión donde hay que confirmar (o corregir) antes de que
se descuente/sume nada de stock — la actualización de stock real la sigue
haciendo /compras/nueva, este módulo solo arma los datos para precargarla.

Uso desde app.py:
    resultado = importar_factura.procesar_factura(ruta_archivo, nombre_archivo, conn)

`resultado` es un dict:
    {
        "error": None | "mensaje si no se pudo procesar el archivo",
        "formato": "excel" | "csv" | "pdf-posicion" | "pdf-tabla" | "pdf-texto",
        "proveedor_id_detectado": int | None,
        "proveedor_candidato": None | {"nombre": str|None, "cuit": str|None, "email": str|None},
        "numero_factura_detectado": str | None,
        "avisos": [str, ...],
        "filas": [
            {
                "descripcion_factura": str,   # texto tal cual salió de la factura
                "codigo_factura": str | None,
                "cantidad": float,
                "precio_unitario": float,
                "producto_id_sugerido": int | None,
                "producto_nombre_sugerido": str | None,
                "confianza": "codigo" | "texto" | "sin_match",
            }, ...
        ],
    }
"""
import csv
import re
import unicodedata
import difflib

import openpyxl

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


UMBRAL_TEXTO = 0.55  # similitud mínima para sugerir un producto por descripción

_CLAVES_COLUMNA = {
    "codigo": ["codigo", "cod.", "cod", "articulo", "item", "sku"],
    "descripcion": ["descripcion", "detalle", "producto", "concepto", "denominacion"],
    "cantidad": ["cantidad", "cant.", "cant", "unidades"],
    "precio_unitario": ["precio unit", "p. unit", "punit", "preciounitario", "precio", "p.unitario"],
    "importe": ["importe", "subtotal", "total item", "total línea", "total linea"],
}

_PALABRAS_TOTALES = ["total", "subtotal", "iva", "cae", "percepcion", "percepción", "retencion", "retención"]


def _sin_acentos(s):
    if s is None:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn").lower().strip()


def _numero(valor):
    if valor is None:
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().replace("$", "").replace(" ", "")
    if not texto:
        return 0.0
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return 0.0


def _mapear_encabezado(fila):
    """Dada una fila de celdas, devuelve {campo: indice_columna} para las que
    reconoce, o {} si la fila no parece un encabezado."""
    mapa = {}
    for i, celda in enumerate(fila):
        texto = _sin_acentos(celda)
        if not texto:
            continue
        for campo, claves in _CLAVES_COLUMNA.items():
            if campo in mapa.values():
                continue
            if any(clave in texto for clave in claves):
                mapa[i] = campo
                break
    # se considera encabezado válido si reconoce al menos descripción y (cantidad o precio)
    campos = set(mapa.values())
    if "descripcion" in campos and ("cantidad" in campos or "precio_unitario" in campos or "importe" in campos):
        return mapa
    return {}


def _es_fila_total(fila):
    texto = _sin_acentos(" ".join(str(c) for c in fila if c is not None))
    return any(p in texto for p in _PALABRAS_TOTALES) and len(texto) < 60


def _filas_desde_tabla(tabla):
    """tabla: lista de filas (listas de celdas). Busca el encabezado y arma
    los items reconocidos a partir de ahí."""
    items = []
    indice_encabezado = None
    mapa = {}
    for i, fila in enumerate(tabla):
        candidato = _mapear_encabezado(fila)
        if candidato:
            mapa = candidato
            indice_encabezado = i
            break
    if indice_encabezado is None:
        return items

    idx_cod = next((i for i, c in mapa.items() if c == "codigo"), None)
    idx_desc = next((i for i, c in mapa.items() if c == "descripcion"), None)
    idx_cant = next((i for i, c in mapa.items() if c == "cantidad"), None)
    idx_precio = next((i for i, c in mapa.items() if c == "precio_unitario"), None)
    idx_importe = next((i for i, c in mapa.items() if c == "importe"), None)

    for fila in tabla[indice_encabezado + 1:]:
        if fila is None or all(c is None or str(c).strip() == "" for c in fila):
            continue
        if _es_fila_total(fila):
            continue
        descripcion = str(fila[idx_desc]).strip() if idx_desc is not None and idx_desc < len(fila) and fila[idx_desc] else ""
        descripcion = re.sub(r"\s+", " ", descripcion)  # celdas de PDF que se envuelven en varias líneas
        if not descripcion:
            continue
        cantidad = _numero(fila[idx_cant]) if idx_cant is not None and idx_cant < len(fila) else 0
        if not cantidad:
            cantidad = 1
        precio_unitario = _numero(fila[idx_precio]) if idx_precio is not None and idx_precio < len(fila) else 0
        # Se prioriza Importe/Cantidad por sobre el precio unitario tal cual viene en la
        # celda: es más confiable (algunas facturas tienen la columna de precio unitario
        # apretada contra la descripción y el texto se mezcla; el importe final, al ser
        # la última columna, casi no tiene ese problema) y además ya refleja cualquier
        # bonificación aplicada por línea.
        if idx_importe is not None and idx_importe < len(fila):
            importe = _numero(fila[idx_importe])
            if importe and cantidad:
                precio_unitario = round(importe / cantidad, 2)
        codigo = str(fila[idx_cod]).strip() if idx_cod is not None and idx_cod < len(fila) and fila[idx_cod] else None
        items.append({
            "descripcion_factura": descripcion,
            "codigo_factura": codigo,
            "cantidad": cantidad,
            "precio_unitario": precio_unitario,
        })
    return items


# Línea de texto suelta: cantidad + descripción + ... + precio unitario (al final o casi).
# Es un formato de respaldo cuando el PDF no tiene una tabla real detectable;
# funciona razonable en facturas simples pero conviene revisar bien estas líneas.
_LINEA_TEXTO_RE = re.compile(
    r"^\s*(?P<cantidad>\d+(?:[.,]\d+)?)\s+(?P<descripcion>.+?)\s+(?P<precio>[\d.,]+)\s*$"
)


def _filas_desde_texto(texto):
    items = []
    for linea in texto.splitlines():
        linea = linea.strip()
        if not linea or _es_fila_total([linea]):
            continue
        m = _LINEA_TEXTO_RE.match(linea)
        if not m:
            continue
        cantidad = _numero(m.group("cantidad"))
        precio = _numero(m.group("precio"))
        descripcion = m.group("descripcion").strip()
        if not descripcion or not precio:
            continue
        items.append({
            "descripcion_factura": descripcion,
            "codigo_factura": None,
            "cantidad": cantidad or 1,
            "precio_unitario": precio,
        })
    return items


def _leer_excel(path, ext):
    filas = []
    if ext == ".csv":
        with open(path, newline="", encoding="utf-8-sig", errors="ignore") as f:
            for fila in csv.reader(f):
                filas.append(fila)
    else:
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb.worksheets[0]
        for fila in ws.iter_rows(values_only=True):
            filas.append(list(fila))
    return filas


def _fila_de_encabezado(palabras):
    """Busca, entre las palabras de una página, una que matchee cada campo
    conocido (por texto) y devuelve {campo: (x0, top)} de la primera vez que
    aparece cada uno, siempre que reconozca al menos descripción + otro
    campo (mismo criterio que _mapear_encabezado, pero sobre texto libre en
    vez de celdas de una tabla con grilla)."""
    encontrados = {}
    for palabra in palabras:
        texto = _sin_acentos(palabra["text"])
        if not texto:
            continue
        for campo, claves in _CLAVES_COLUMNA.items():
            if campo in encontrados:
                continue
            if any(clave in texto for clave in claves):
                encontrados[campo] = (palabra["x0"], palabra["top"])
                break
    if "descripcion" in encontrados and len(encontrados) >= 2:
        return encontrados
    return {}


_UMBRAL_GAP_COLUMNA = 15  # pt de espacio en blanco horizontal que se interpreta como salto de columna


def _es_dinero(texto):
    t = texto.replace("$", "").replace(" ", "")
    return bool(t) and bool(re.fullmatch(r"[\d.,]+", t)) and any(ch.isdigit() for ch in t)


def _agrupar_por_gaps(palabras_fila):
    """Junta palabras consecutivas de una misma fila en 'campos' separados
    por un espacio en blanco grande (típico salto de columna en facturas sin
    grilla). Un espacio chico (el de dentro de una descripción con varias
    palabras) no separa nada."""
    grupos = [[palabras_fila[0]]]
    for anterior, actual in zip(palabras_fila, palabras_fila[1:]):
        gap = actual["x0"] - anterior["x1"]
        if gap > _UMBRAL_GAP_COLUMNA:
            grupos.append([actual])
        else:
            grupos[-1].append(actual)
    return grupos


def _texto_grupo(grupo):
    return " ".join(p["text"] for p in grupo)


def _fila_por_gaps(palabras_fila, campo_precio_tipo, cantidad_antes_de_desc):
    """A partir de las palabras de una fila (ya separadas del resto de la
    página), reconstruye código / cantidad / descripción, y el precio de la
    línea. No confía en la posición exacta de cada columna (los encabezados
    no siempre están alineados con los datos, y columnas numéricas angostas
    suelen ir pegadas a la de al lado) — en cambio agrupa por espacios en
    blanco grandes, que en la práctica separan mejor las columnas reales.

    `campo_precio_tipo` indica si la última columna de precio que reconoció
    el encabezado de esta factura es "importe" (total de la línea, hay que
    dividir por la cantidad) o "precio_unitario" (ya es por unidad).
    `cantidad_antes_de_desc` indica si en el encabezado la columna Cantidad
    aparece antes o después de Descripción, para saber de qué lado de la
    descripción buscar el número de cantidad."""
    grupos = _agrupar_por_gaps(palabras_fila)
    if len(grupos) < 2:
        return None

    codigo = _texto_grupo(grupos[0]).strip() or None
    resto = grupos[1:]

    valor_precio = None
    if resto and _es_dinero(_texto_grupo(resto[-1])):
        valor_precio = _numero(_texto_grupo(resto[-1]))
        resto = resto[:-1]

    # bonificación (no se usa para nada, solo se descarta si aparece)
    if resto and "%" in _texto_grupo(resto[-1]):
        resto = resto[:-1]

    cantidad = None
    if not cantidad_antes_de_desc and resto and re.fullmatch(r"\d{1,4}", _texto_grupo(resto[-1]).strip()):
        # la cantidad va después de la descripción (ej: Código/Descripción/Cantidad/Precio)
        cantidad = int(_texto_grupo(resto[-1]).strip())
        resto = resto[:-1]
    elif len(resto) > 1 and _es_dinero(_texto_grupo(resto[-1])):
        # columna de precio unitario ya separada y sin corromper (factura con
        # columnas más anchas): no es parte de la descripción, pero tampoco
        # se usa (se prioriza el importe, o el precio que se toma más abajo).
        resto = resto[:-1]

    if not resto:
        return None

    palabras_cant_desc = [p for grupo in resto for p in grupo]
    if cantidad is None:
        if palabras_cant_desc and re.fullmatch(r"\d{1,4}", palabras_cant_desc[0]["text"]):
            cantidad = int(palabras_cant_desc[0]["text"])
            palabras_cant_desc = palabras_cant_desc[1:]
        else:
            cantidad = 1

    descripcion = re.sub(r"\s+", " ", " ".join(p["text"] for p in palabras_cant_desc)).strip()
    # si la descripción se pisó con el precio unitario (columnas muy
    # apretadas y descripción larga), suele colarse un '$' suelto: se corta ahí.
    if "$" in descripcion:
        descripcion = descripcion.split("$")[0].strip()
    if not descripcion:
        return None

    if campo_precio_tipo == "importe" and valor_precio and cantidad:
        precio_unitario = round(valor_precio / cantidad, 2)
    else:
        precio_unitario = valor_precio or 0

    return {
        "descripcion_factura": descripcion,
        "codigo_factura": codigo,
        "cantidad": cantidad,
        "precio_unitario": precio_unitario,
    }


def _filas_desde_posicion_pdf(pagina):
    """Reconstruye las filas de productos a partir de las palabras del PDF y
    su posición, en vez de depender de que tenga líneas de grilla real
    (extract_tables() no encuentra nada en facturas donde los ítems son una
    simple lista sin bordes, que es el caso más común). El precio unitario
    siempre se calcula como Importe / Cantidad en vez de leer la columna de
    precio directo: en columnas apretadas esa columna puede salir mezclada
    con el final de la descripción, mientras que el importe (al ser la
    última columna, pegada al margen derecho) casi nunca se corrompe."""
    palabras = pagina.extract_words()
    encabezado = _fila_de_encabezado(palabras)
    if not encabezado:
        return []

    top_encabezado = max(top for _x0, top in encabezado.values())

    top_fin = None
    for p in palabras:
        if p["top"] <= top_encabezado + 2:
            continue
        if _sin_acentos(p["text"]) and any(clave in _sin_acentos(p["text"]) for clave in _PALABRAS_TOTALES):
            top_fin = p["top"]
            break

    palabras_filas = [
        p for p in palabras
        if p["top"] > top_encabezado + 2 and (top_fin is None or p["top"] < top_fin - 1)
    ]
    if not palabras_filas:
        return []

    campo_precio_tipo = "importe" if "importe" in encabezado else "precio_unitario"
    cantidad_antes_de_desc = (
        "cantidad" in encabezado and "descripcion" in encabezado
        and encabezado["cantidad"][0] < encabezado["descripcion"][0]
    )
    x0_codigo = encabezado["codigo"][0] if "codigo" in encabezado else None

    # agrupa palabras en filas por posición vertical (tolerancia de 3pt para
    # no partir una fila por pequeñas diferencias de fuente/baseline)
    palabras_filas.sort(key=lambda p: (p["top"], p["x0"]))
    filas = []
    fila_actual = []
    top_referencia = None
    for p in palabras_filas:
        if top_referencia is None or p["top"] - top_referencia > 3:
            if fila_actual:
                filas.append(fila_actual)
            fila_actual = [p]
            top_referencia = p["top"]
        else:
            fila_actual.append(p)
    if fila_actual:
        filas.append(fila_actual)

    # una descripción larga puede envolver a una segunda línea dentro de la
    # misma celda (PDFs con grilla real y descripciones que no entran en el
    # ancho de columna). Esa segunda línea no repite el código, así que se
    # reconoce porque no tiene ninguna palabra cerca de la columna Código, y
    # se junta como continuación de la fila anterior (como texto, no se
    # vuelve a mezclar con las palabras de la fila ancla para no desordenar
    # la posición de cantidad/precio ya reconocidas en esa fila).
    grupos_de_filas = []  # cada elemento: [fila_ancla, [continuacion1, continuacion2, ...]]
    for fila in filas:
        fila.sort(key=lambda p: p["x0"])
        es_continuacion = grupos_de_filas and (x0_codigo is None or fila[0]["x0"] > x0_codigo + 25)
        if es_continuacion:
            grupos_de_filas[-1][1].append(fila)
        else:
            grupos_de_filas.append([fila, []])

    items = []
    for fila_ancla, continuaciones in grupos_de_filas:
        item = _fila_por_gaps(fila_ancla, campo_precio_tipo, cantidad_antes_de_desc)
        if not item:
            continue
        for continuacion in continuaciones:
            texto_extra = re.sub(r"\s+", " ", " ".join(p["text"] for p in continuacion)).strip()
            if texto_extra and "$" not in texto_extra:
                item["descripcion_factura"] = (item["descripcion_factura"] + " " + texto_extra).strip()
        items.append(item)
    return items


def _leer_pdf(path):
    """Devuelve (items, formato, texto_completo). Prueba, en orden:
    1) reconstruir filas por posición de caracteres (funciona con o sin
       líneas de grilla, que es el caso más común en facturas reales);
    2) tablas con grilla real detectadas por pdfplumber;
    3) un parseo línea por línea del texto plano (el más frágil, último
       recurso cuando ninguno de los anteriores encuentra nada)."""
    items = []
    texto_partes = []
    formato = "pdf-texto"
    with pdfplumber.open(path) as pdf:
        for pagina in pdf.pages:
            texto_partes.append(pagina.extract_text() or "")
            items_posicion = _filas_desde_posicion_pdf(pagina)
            if items_posicion:
                items.extend(items_posicion)
                formato = "pdf-posicion"
                continue
            for tabla in pagina.extract_tables():
                items_tabla = _filas_desde_tabla(tabla)
                if items_tabla:
                    items.extend(items_tabla)
                    formato = "pdf-tabla"
    texto_completo = "\n".join(texto_partes)
    if items:
        return items, formato, texto_completo
    return _filas_desde_texto(texto_completo), "pdf-texto", texto_completo


_RE_NUMERO_FACTURA = re.compile(
    r"(?:factura|comp\.?\s*nro\.?|comprobante)\D{0,15}(\d{1,5}[\-\s]?\d{6,8})", re.IGNORECASE
)


def _detectar_numero_factura(texto):
    m = _RE_NUMERO_FACTURA.search(texto or "")
    return m.group(1) if m else None


_RE_CUIT = re.compile(r"\b(\d{2}-\d{7,8}-\d)\b")
_RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _detectar_cuit(texto):
    m = _RE_CUIT.search(texto or "")
    return m.group(1) if m else None


def _detectar_email(texto):
    m = _RE_EMAIL.search(texto or "")
    return m.group(0) if m else None


def _detectar_nombre_candidato(texto):
    """Intenta adivinar la razón social cuando no matchea ningún proveedor
    ya cargado: toma la línea de texto justo antes de donde aparece el CUIT
    (en la mayoría de las facturas argentinas el encabezado pone el nombre
    del emisor pegado arriba del CUIT). Es una sugerencia para que la
    persona la confirme o corrija, no algo que se use sin mostrarlo."""
    if not texto:
        return None
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
    for i, linea in enumerate(lineas):
        if "cuit" in _sin_acentos(linea) and i > 0:
            candidata = lineas[i - 1]
            if candidata and not _RE_CUIT.search(candidata) and len(candidata) < 60:
                return candidata
    return None


def _detectar_proveedor(texto, proveedores):
    """Devuelve el id del proveedor si matchea por CUIT (más confiable) o,
    si no, por el nombre ya cargado apareciendo en el texto de la factura."""
    cuit = _detectar_cuit(texto)
    if cuit:
        for p in proveedores:
            if p["cuit"] and _normalizar_codigo(p["cuit"]) == _normalizar_codigo(cuit):
                return p["id"]

    texto_norm = _sin_acentos(texto)
    for p in proveedores:
        nombre_norm = _sin_acentos(p["nombre"])
        if nombre_norm and nombre_norm in texto_norm:
            return p["id"]
    return None


def _normalizar_codigo(c):
    """Saca espacios de más (algunas listas de proveedor traen códigos con
    varios espacios internos) para que comparar códigos sea más tolerante."""
    if not c:
        return ""
    return re.sub(r"\s+", " ", str(c).strip()).lower()


def _matchear_producto(item, catalogo, catalogo_nombres_norm):
    codigo = _normalizar_codigo(item.get("codigo_factura"))
    if codigo:
        for p in catalogo:
            if _normalizar_codigo(p["codigo"]) == codigo:
                return p["id"], p["nombre"], "codigo"
            if _normalizar_codigo(p["codigo_proveedor"]) == codigo:
                return p["id"], p["nombre"], "codigo"

    desc_norm = _sin_acentos(item["descripcion_factura"])
    mejor = None
    mejor_score = 0
    for p, nombre_norm in zip(catalogo, catalogo_nombres_norm):
        score = difflib.SequenceMatcher(None, desc_norm, nombre_norm).ratio()
        if score > mejor_score:
            mejor_score = score
            mejor = p
    if mejor and mejor_score >= UMBRAL_TEXTO:
        return mejor["id"], mejor["nombre"], "texto"
    return None, None, "sin_match"


def procesar_factura(path, nombre_archivo, conn):
    ext = nombre_archivo.lower()
    ext = ext[ext.rfind("."):] if "." in ext else ""

    avisos = []
    texto_completo = ""
    try:
        if ext in (".xlsx", ".xls", ".csv"):
            filas = _leer_excel(path, ext)
            items = _filas_desde_tabla(filas)
            formato = "csv" if ext == ".csv" else "excel"
            if not items:
                avisos.append("No reconocí una tabla de productos en el archivo (busco columnas tipo "
                               "Código/Descripción/Cantidad/Precio). Revisá los encabezados o cargá manual.")
        elif ext == ".pdf":
            if pdfplumber is None:
                return {"error": "Falta la librería pdfplumber. Instalala con: pip install pdfplumber", "filas": []}
            items, formato, texto_completo = _leer_pdf(path)
            if formato == "pdf-posicion" and items:
                avisos.append("Esta factura no tiene una tabla con bordes, así que reconstruí las columnas "
                               "por la posición del texto. El precio unitario lo calculé como Importe/Cantidad "
                               "(más confiable que leer la columna de precio directo) — revisá cada línea igual.")
            elif formato == "pdf-texto" and items:
                avisos.append("Este PDF no tiene una tabla reconocible, así que lo leí línea por línea. "
                               "Es menos confiable — revisá cada línea con cuidado.")
            elif not items:
                avisos.append("No pude reconocer productos en este PDF. Puede ser una imagen escaneada "
                               "(sin texto seleccionable) — en ese caso hay que cargar la compra a mano.")
        else:
            return {"error": "Formato no soportado. Subí un PDF, Excel (.xlsx/.xls) o CSV.", "filas": []}
    except Exception as e:
        return {"error": f"No pude leer el archivo: {e}", "filas": []}

    proveedores = conn.execute("SELECT id, nombre, cuit FROM proveedores WHERE activo IS TRUE ORDER BY nombre").fetchall()
    catalogo = conn.execute(
        """SELECT p.id, p.codigo, p.nombre, pp.codigo_proveedor
           FROM productos p LEFT JOIN producto_proveedor pp ON pp.producto_id = p.id"""
    ).fetchall()
    catalogo_nombres_norm = [_sin_acentos(p["nombre"]) for p in catalogo]

    filas_resultado = []
    for item in items:
        producto_id, producto_nombre, confianza = _matchear_producto(item, catalogo, catalogo_nombres_norm)
        filas_resultado.append({
            **item,
            "producto_id_sugerido": producto_id,
            "producto_nombre_sugerido": producto_nombre,
            "confianza": confianza,
        })

    proveedor_id_detectado = _detectar_proveedor(texto_completo, proveedores) if texto_completo else None

    proveedor_candidato = None
    if not proveedor_id_detectado and texto_completo:
        cuit = _detectar_cuit(texto_completo)
        email = _detectar_email(texto_completo)
        nombre = _detectar_nombre_candidato(texto_completo)
        if cuit or email or nombre:
            proveedor_candidato = {"nombre": nombre, "cuit": cuit, "email": email}

    return {
        "error": None,
        "formato": formato,
        "proveedor_id_detectado": proveedor_id_detectado,
        "proveedor_candidato": proveedor_candidato,
        "numero_factura_detectado": _detectar_numero_factura(texto_completo),
        "avisos": avisos,
        "filas": filas_resultado,
    }
