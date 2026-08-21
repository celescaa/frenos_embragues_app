"""Decide cómo se llama un producto y deja marca y modelo en su columna.

La nomenclatura es:

    NOMBRE = PIEZA + MARCA + [ESPECIFICACIÓN] + CÓDIGO

todo en MAYÚSCULAS y SIN acentos. El auto NO va en el nombre: vive en
`modelo_compatible`, que es lo que el buscador ya mira (ver
`TEXTO_PRODUCTO_SQL` en core/database.py), así que buscar "palio 1.6"
encuentra el producto sin necesidad de repetir el auto en el nombre.

Es texto puro: NO importa core.database, así que se puede testear sin
Postgres levantado y usar desde cualquier script. Los nombres de rubro y
subrubro están escritos a mano acá; `verificar_taxonomia()` los compara
contra la base y tiene test propio.

Regla que no conviene revertir: las MARCAS de auto se corrigen solas
(conjunto chico y cerrado), los MODELOS no. Medido sobre las 25 filas de la
primera carga real: de 23 palabras sospechosas el parecido acierta 12 y se
equivoca en 6, y todos los pares equivocados son autos que existen los dos
(DASTER->MASTER cuando es DUSTER, LAGAN->LOGAN cuando es LAGUNA,
CAPTUS->CAPTUR cuando es CACTUS). Un error ahí no se nota mirando el
resultado: se nota cuando el cliente vuelve con la bomba que no era.
"""
import re
import unicodedata
import difflib

# --- taxonomía v3, escrita a mano (ver verificar_taxonomia) -----------------
MOTOR = "Motor"

BOMBA_DE_AGUA = "Bomba de agua"
CILINDROS_FRENO = "Cilindros (bomba freno, cilindros de rueda)"
BOMBAS_EMBRAGUE = "Bombas y cilindros de embrague"

# Subrubro de la taxonomía -> forma canónica de la pieza, que es con lo que
# arranca el nombre. Es lo que hace que todas las bombas de agua se llamen
# igual sin importar cómo las escribió cada proveedor.
PIEZA_POR_SUBRUBRO = {
    BOMBA_DE_AGUA: "BOMBA DE AGUA",
    CILINDROS_FRENO: "BOMBA DE FRENO",
    BOMBAS_EMBRAGUE: "BOMBA DE EMBRAGUE",
}

# (proveedor, rubro crudo normalizado) -> (rubro, subrubro) de la taxonomía.
#
# La clave lleva el proveedor a propósito: "Bomba" a secas es ambiguo en este
# negocio (de freno va a Frenos, de embrague a Embrague, de agua a Motor),
# pero dentro de Rodamitre no lo es. Celes lo confirmó el 21/08/2026 para los
# códigos BA###: son bombas de agua, y sus propios modelos lo dicen
# ("turbina 70mm", "polea 54mm", "alabes alto" -- una bomba de embrague no
# tiene ninguna de las tres).
#
# Lo que no está acá NO se adivina: se marca para revisar.
ALIAS_RUBRO_CRUDO = {
    ("rodamitre", "bomba"): (MOTOR, BOMBA_DE_AGUA),
}

# --- marcas de auto: se aplican SIEMPRE -------------------------------------
MARCAS_AUTO = {
    r"\bpeuge?[o]?t\b|\bpeuget\b": "PEUGEOT",
    r"\brenaul?t\b|\brenaut\b": "RENAULT",
    r"\bchev[ro]*let\b|\bchevolet\b": "CHEVROLET",
    r"\bm\s*bean?z\b|\bmb\b|\bmercedes\b": "MERCEDES BENZ",
    r"\bfort\b|\bford\b": "FORD",
    r"\bsus?uki\b": "SUZUKI",
    r"\bcitroen\b": "CITROEN",
    r"\bvolkswagen\b|\bvw\b": "VOLKSWAGEN",
    r"\bfiat\b": "FIAT",
    r"\btoyota\b": "TOYOTA",
    r"\bvolvo\b": "VOLVO",
    r"\bnissan\b": "NISSAN",
    r"\bdaewoo\b": "DAEWOO",
    r"\balfa\s*romeo\b": "ALFA ROMEO",
    r"\bland\s*ro[bv]er?t?\b": "LAND ROVER",
    r"\bmini\b": "MINI",
    r"\bbmw\b": "BMW",
    r"\bmazda\b": "MAZDA",
    r"\bjeep\b": "JEEP",
    r"\bopen\b|\bopel\b": "OPEL",
}

# --- modelos: SOLO lo confirmado a mano -------------------------------------
# Crece con lo que una persona tilda en la hoja REVISAR que arma
# normalizar_planilla_stock.py. Nada entra acá automáticamente.
ALIAS_MODELO = {
    "REGAT": "REGATTA", "PARNERT": "PARTNER", "PARNET": "PARTNER",
    "DEFENDERT": "DEFENDER", "BLEAZER": "BLAZER", "SIMBOL": "SYMBOL",
    "FIETA": "FIESTA", "DIENTAS": "DIENTES", "CUGA": "KUGA",
    "PLEA": "POLEA", "FKA": "KA",
}

# --- especificaciones: lo que diferencia dos piezas iguales ------------------
# Se extraen del modelo (donde vienen mezcladas con los autos) y se llevan al
# nombre.
ESPECIFICACIONES = [
    (r"pole?a?\s*(?:de\s*)?(\d+)\s*d(?:ientes?|ientas?|\b)",
     lambda m: f"POLEA {m.group(1)} DIENTES"),
    (r"turbina\s*(?:de\s*)?(\d+)\s*mm", lambda m: f"TURBINA {m.group(1)} MM"),
    (r"polea\s*(\d+(?:[.,]\d+)?)\s*mm",
     lambda m: f"POLEA {m.group(1).replace('.', ',')} MM"),
    (r"ancho\s*(\d+(?:[.,]\d+)?)\s*mm",
     lambda m: f"ANCHO {m.group(1).replace('.', ',')} MM"),
    (r"\balabes?\s+alto\b", lambda m: "ALABES ALTO"),
    (r"\b(?:rod\.?\s*|premium\s*)?refor\.?(?=\s|$)", lambda m: "REFORZADA"),
]

RUIDO_COMERCIAL = [r"\boferta\b", r"\bpromo\b", r"\bliquidacion\b"]

# Debajo de esto una palabra es demasiado rara para ser "la forma correcta".
APARICIONES_PALABRA_CONFIABLE = 300
# Debajo de esto dos palabras no se parecen lo suficiente como para proponer.
PARECIDO_MINIMO = 0.75
# Palabras más cortas no se proponen: "gol" se parece a "golpe" y a "goma".
LARGO_MINIMO_PALABRA = 4

_MARCAS_CANONICAS = sorted(set(MARCAS_AUTO.values()), key=len, reverse=True)


def mayusculas_sin_acentos(texto):
    """MAYÚSCULAS, sin acentos y sin espacios de más.

    El buscador ya normaliza acentos de los dos lados (texto_busqueda en SQL),
    así que sacarlos no le cuesta nada a la búsqueda y evita tener la misma
    palabra escrita de dos formas distintas en la base.
    """
    plano = "".join(
        c for c in unicodedata.normalize("NFD", str(texto or ""))
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", plano).strip().upper()


def normalizar_marca(marca):
    """Marca del repuesto, sin las palabras comerciales que algunos
    proveedores meten adentro del campo ('OFERTA VMG')."""
    limpia = mayusculas_sin_acentos(marca)
    for patron in RUIDO_COMERCIAL:
        limpia = re.sub(patron, " ", limpia, flags=re.I)
    return re.sub(r"\s+", " ", limpia).strip()


def extraer_especificaciones(texto):
    """Devuelve (especificaciones encontradas, texto sin ellas).

    Las specs vienen mezcladas con los autos en el mismo campo. Dejarlas ahí
    ensucia la búsqueda por auto; llevarlas al nombre es lo que diferencia
    dos bombas que sirven para el mismo coche.
    """
    encontradas, resto = [], str(texto or "")
    for patron, formatear in ESPECIFICACIONES:
        for m in re.finditer(patron, resto, flags=re.I):
            encontradas.append(formatear(m))
        resto = re.sub(patron, " ", resto, flags=re.I)
    # dict.fromkeys en vez de set: conserva el orden en que aparecen
    return list(dict.fromkeys(encontradas)), resto


def normalizar_modelo(modelo):
    """Mayúsculas sin acentos, marcas de auto canónicas y un solo separador.

    El ORDEN importa: los separadores se normalizan ANTES de aplicar
    ALIAS_MODELO. Al revés, 'Parnert-208' es una sola palabra y el alias no la
    agarra nunca (bug real, encontrado armando la vista previa).
    """
    texto = mayusculas_sin_acentos(modelo)
    for patron, canonica in MARCAS_AUTO.items():
        texto = re.sub(patron, canonica, texto, flags=re.I)
    texto = re.sub(r"\s*[-/]\s*", " / ", texto)
    texto = re.sub(r"\b(\d+)\s*V\s*MOTOR\b", r"\1V MOTOR", texto)
    texto = " ".join(ALIAS_MODELO.get(p, p) for p in texto.split())
    texto = re.sub(r"\b(\d)\s*[.,]\s*(\d)\b", r"\1.\2", texto)
    texto = re.sub(r"(\s*/\s*)+", " / ", texto)
    texto = re.sub(r"^\s*/\s*|\s*/\s*$", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


def marcas_auto_de(modelo, tope=2):
    """Las marcas de auto que aparecen en el modelo, en orden y sin repetir.

    Se usan en el nombre sólo cuando no hay ninguna especificación técnica que
    diferencie la pieza. Sin esto, 14 de las 25 filas de la primera carga real
    quedaban con el nombre idéntico 'BOMBA DE AGUA VMG'.
    """
    vistas = []
    for m in re.finditer(r"[A-Z]+(?: BENZ| ROMEO| ROVER)?", modelo):
        if m.group(0) in _MARCAS_CANONICAS and m.group(0) not in vistas:
            vistas.append(m.group(0))
    return vistas[:tope]


def resolver_rubro(proveedor, rubro_crudo, subrubro_crudo):
    """Devuelve (rubro, subrubro, aviso). El aviso es "" cuando resolvió.

    Nunca adivina: lo que no está en ALIAS_RUBRO_CRUDO y no trae ya un
    subrubro conocido vuelve tal cual, con un aviso para revisar.
    """
    rubro = str(rubro_crudo or "").strip()
    subrubro = str(subrubro_crudo or "").strip()
    clave = (mayusculas_sin_acentos(proveedor).lower(),
             mayusculas_sin_acentos(rubro).lower())
    if clave in ALIAS_RUBRO_CRUDO:
        return (*ALIAS_RUBRO_CRUDO[clave], "")
    if subrubro in PIEZA_POR_SUBRUBRO:
        return rubro, subrubro, ""
    return rubro, subrubro, f"no reconocí el rubro {rubro_crudo!r} de {proveedor!r}"


def normalizar_fila(proveedor, descripcion, marca, rubro, subrubro, modelo, codigo):
    """Punto de entrada. Devuelve dict con nombre, marca, modelo, rubro,
    subrubro y revisar (cadena vacía si no hay nada que revisar)."""
    rubro, subrubro, aviso = resolver_rubro(proveedor, rubro, subrubro)
    pieza = PIEZA_POR_SUBRUBRO.get(subrubro)

    marca_limpia = normalizar_marca(marca)
    specs_modelo, resto = extraer_especificaciones(modelo)
    specs_desc, _ = extraer_especificaciones(descripcion)
    specs = list(dict.fromkeys(specs_modelo + specs_desc))
    modelo_limpio = normalizar_modelo(resto)
    codigo_limpio = mayusculas_sin_acentos(codigo)

    if pieza:
        cola = specs if specs else marcas_auto_de(modelo_limpio)
        partes = [pieza, marca_limpia] + cola + [codigo_limpio]
        nombre = " ".join(p for p in partes if p)
        revisar = aviso
    else:
        # No inventa la pieza: deja lo que había, en mayúsculas, y avisa.
        nombre = mayusculas_sin_acentos(descripcion)
        revisar = aviso or "no pude deducir la pieza: revisá el nombre a mano"

    return {"nombre": nombre, "marca": marca_limpia, "modelo": modelo_limpio,
            "rubro": rubro, "subrubro": subrubro, "revisar": revisar}


def construir_vocabulario(textos):
    """Cuántas veces aparece cada palabra en las listas de los proveedores.

    El vocabulario sale de los datos reales, no de una lista escrita a mano:
    una palabra bien escrita aparece miles de veces y un typo un puñado.
    """
    frecuencias = {}
    patron = r"[A-Z]{%d,}" % LARGO_MINIMO_PALABRA
    for texto in textos:
        for palabra in re.findall(patron, mayusculas_sin_acentos(texto)):
            frecuencias[palabra] = frecuencias.get(palabra, 0) + 1
    return frecuencias


def proponer_alias(modelo_normalizado, vocabulario):
    """Typos candidatos en un modelo ya normalizado. NO los aplica.

    Devuelve [(palabra, apariciones, candidato, apariciones_candidato)].
    Una palabra frecuente nunca se propone: MOBI, MITO y TORO son autos
    reales y sólo los salva este filtro.
    """
    confiables = [p for p, n in vocabulario.items()
                  if n >= APARICIONES_PALABRA_CONFIABLE]
    propuestas, vistas = [], set()
    patron = r"[A-Z]{%d,}" % LARGO_MINIMO_PALABRA
    for palabra in re.findall(patron, modelo_normalizado):
        if (palabra in vistas or palabra in _MARCAS_CANONICAS
                or palabra in ALIAS_MODELO or palabra in ALIAS_MODELO.values()
                or vocabulario.get(palabra, 0) >= APARICIONES_PALABRA_CONFIABLE):
            continue
        vistas.add(palabra)
        candidatos = [c for c in difflib.get_close_matches(
            palabra, confiables, n=1, cutoff=PARECIDO_MINIMO) if c != palabra]
        if candidatos:
            propuestas.append((palabra, vocabulario.get(palabra, 0),
                               candidatos[0], vocabulario[candidatos[0]]))
    return propuestas


def verificar_taxonomia(categorias_validas, subcategorias_validas):
    """Devuelve los nombres que este módulo usa y la base no tiene.

    Existe para que un renombre de rubro en una migración explote en un test y
    no en medio de una carga de 200.000 filas.
    """
    problemas = []
    destinos = set(ALIAS_RUBRO_CRUDO.values())
    for subrubro in PIEZA_POR_SUBRUBRO:
        for categoria, subs in subcategorias_validas.items():
            if subrubro in subs:
                destinos.add((categoria, subrubro))
                break
        else:
            problemas.append(
                f"subcategoría inexistente en toda la taxonomía: {subrubro!r}")
    for categoria, subcategoria in sorted(destinos):
        if categoria not in categorias_validas:
            problemas.append(f"categoría inexistente: {categoria!r}")
        elif subcategoria not in subcategorias_validas.get(categoria, []):
            problemas.append(
                f"subcategoría inexistente: {categoria!r} / {subcategoria!r}")
    return sorted(set(problemas))
