# Nomenclatura de productos — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el nombre de cada producto diga qué es la pieza, que la marca y el auto queden en su propia columna bien escritos, y que todo eso se mantenga solo tanto al cargar una planilla como al tipear en la ficha.

**Architecture:** Un módulo de texto puro (`scripts/nomenclatura.py`, sin acceso a la base, hermano de `scripts/clasificar_repuestos.py`) con todas las tablas de reglas y funciones que reciben y devuelven texto. Tres consumidores lo usan: el importador de planillas, un script nuevo que limpia una planilla existente, y el generador de planillas. Aparte, las dos capas de mayúscula en la ficha de producto.

**Tech Stack:** Python 3.11, openpyxl (`read_only`/`write_only` por el volumen), `difflib` para el parecido de palabras, pytest. Nada nuevo en `requirements.txt`.

**Spec:** `docs/superpowers/specs/2026-08-21-nomenclatura-productos-design.md`

## Global Constraints

- **Nombre, marca y modelo van en MAYÚSCULAS y SIN acentos.** `CITROEN`, no `CITROËN`.
- **Rubro y subrubro NUNCA se pasan a mayúscula ni se les sacan acentos.** Van letra por letra como los escribe la taxonomía (`Motor`, `Bomba de agua`, `Suspensión`). `db.facetas_productos()` agrupa esas columnas crudas: `MOTOR` y `Motor` saldrían como dos rubros distintos en el filtro de `/productos`.
- **El código de barras nunca se toca.** Es lo que dispara la pistola lectora.
- **Los typos de modelo se proponen, nunca se aplican solos.** Sólo `ALIAS_MODELO` (confirmado a mano) se aplica. Las marcas de auto sí se corrigen automáticamente: son un conjunto chico y cerrado.
- **`scripts/nomenclatura.py` no importa `core.database`.** Es texto puro, testeable sin Postgres. `verificar_taxonomia()` recibe la taxonomía por parámetro, igual que `clasificar_repuestos.verificar_taxonomia()`.
- **La plata no se toca**: este trabajo no lee ni escribe ninguna columna de precio.
- Los scripts se corren desde la raíz del proyecto: `python scripts/<nombre>.py`.

---

### Task 1: El módulo de nomenclatura

**Files:**
- Create: `scripts/nomenclatura.py`
- Test: `tests/test_nomenclatura.py`

**Interfaces:**
- Consumes: nada (módulo hoja).
- Produces, para las tareas 2, 3 y 5:
  - `normalizar_fila(proveedor, descripcion, marca, rubro, subrubro, modelo, codigo) -> dict` con las claves `nombre`, `marca`, `modelo`, `rubro`, `subrubro`, `revisar` (todas `str`; `revisar` es `""` cuando no hay nada que revisar).
  - `mayusculas_sin_acentos(texto) -> str`
  - `normalizar_marca(marca) -> str`
  - `normalizar_modelo(modelo) -> str`
  - `extraer_especificaciones(texto) -> tuple[list[str], str]`
  - `verificar_taxonomia(categorias_validas, subcategorias_validas) -> list[str]`
  - `construir_vocabulario(textos) -> dict[str, int]`
  - `proponer_alias(modelo_normalizado, vocabulario) -> list[tuple[str, int, str, int]]`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_nomenclatura.py`:

```python
"""El nombre de un producto es lo que ve el que atiende el mostrador y lo que
imprime el remito. Estos casos son los que se rompieron de verdad con la
primera carga real de stock (25 bombas, 20/08/2026), no ejemplos inventados."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from core import database as db
from scripts import nomenclatura as nom


def test_los_rubros_que_usa_el_modulo_existen_en_la_base():
    """El módulo escribe los nombres de rubro y subrubro a mano, sin leer la
    base. Si una migración renombra uno, el desajuste tiene que verse acá y
    no en medio de una carga."""
    problemas = nom.verificar_taxonomia(db.CATEGORIAS_INICIALES, db.SUBCATEGORIAS_INICIALES)
    assert problemas == [], "\n".join(problemas)


@pytest.mark.parametrize("crudo", ["Bomba", "Bomba ", "bomba", " BOMBA"])
def test_las_grafias_del_rubro_bomba_de_rodamitre_caen_todas_en_el_mismo_lugar(crudo):
    """Rodamitre manda el rubro escrito de tres formas distintas. Sin esto,
    `_normalizar_categoria` las mandaba a las tres a 'Varios' sin subrubro:
    24 de las 25 filas de la primera carga real."""
    fila = nom.normalizar_fila(
        proveedor="Rodamitre", descripcion="VMG BA013", marca="VMG",
        rubro=crudo, subrubro="", modelo="Fiat 128", codigo="BA013")
    assert (fila["rubro"], fila["subrubro"]) == ("Motor", "Bomba de agua")


def test_el_rubro_y_el_subrubro_no_se_pasan_a_mayuscula():
    """`db.facetas_productos()` agrupa estas dos columnas CRUDAS, no
    normalizadas. 'MOTOR' y 'Motor' aparecerían como dos rubros distintos en
    el filtro de /productos, cada uno con su propio contador."""
    fila = nom.normalizar_fila(
        proveedor="Rodamitre", descripcion="VMG BA013", marca="VMG",
        rubro="Bomba", subrubro="", modelo="Fiat 128", codigo="BA013")
    assert fila["rubro"] == "Motor"
    assert fila["subrubro"] == "Bomba de agua"


def test_el_nombre_arranca_con_la_pieza_y_termina_con_el_codigo():
    fila = nom.normalizar_fila(
        proveedor="Rodamitre", descripcion="VMG BA446", marca="VMG",
        rubro="Bomba", subrubro="", codigo="BA446",
        modelo="Peugeot Citroen -P206-207 Parnet 1.6 Polea 19 dientes")
    assert fila["nombre"] == "BOMBA DE AGUA VMG POLEA 19 DIENTES BA446"


def test_sin_codigo_el_nombre_no_queda_terminado_en_espacio():
    fila = nom.normalizar_fila(
        proveedor="Rodamitre", descripcion="VMG", marca="VMG",
        rubro="Bomba", subrubro="", modelo="Fiat 128", codigo="")
    assert fila["nombre"] == fila["nombre"].strip()
    assert not fila["nombre"].endswith("  ")


def test_la_marca_pierde_el_ruido_comercial():
    """'OFERTA VMG' venía cargado como marca. OFERTA es una nota comercial,
    la marca es VMG."""
    fila = nom.normalizar_fila(
        proveedor="Rodamitre", descripcion="OFERTA VMG BA442", marca="OFERTA VMG",
        rubro="Bomba", subrubro="", modelo="Ford -Fiesta", codigo="BA442")
    assert fila["marca"] == "VMG"


def test_la_especificacion_sale_del_modelo_y_entra_al_nombre():
    """La polea y la turbina no son un auto: son lo que diferencia una bomba
    de otra. Mezcladas en el modelo ensucian la búsqueda por auto."""
    fila = nom.normalizar_fila(
        proveedor="Rodamitre", descripcion="VMG BA470", marca="VMG",
        rubro="Bomba", subrubro="", codigo="BA470",
        modelo="Renault Megane 2- Laguna 2.0 -Turbina 70mm y polea 54mm-")
    assert "TURBINA 70 MM" in fila["nombre"]
    assert "TURBINA" not in fila["modelo"]
    assert "MEGANE" in fila["modelo"]


def test_todo_en_mayusculas_y_sin_acentos():
    fila = nom.normalizar_fila(
        proveedor="Rodamitre", descripcion="VMG BA712", marca="VMG",
        rubro="Bomba", subrubro="", codigo="BA712",
        modelo="Citroën -Peugeot -C3-C Picasso")
    assert fila["modelo"] == fila["modelo"].upper()
    assert "CITROEN" in fila["modelo"]
    assert "Ë" not in fila["modelo"] and "É" not in fila["modelo"]


def test_las_marcas_de_auto_mal_escritas_se_corrigen_solas():
    """Conjunto chico y cerrado, verificable de una vez. A diferencia de los
    modelos, que son una lista abierta."""
    fila = nom.normalizar_fila(
        proveedor="Rodamitre", descripcion="VMG BA429", marca="VMG",
        rubro="Bomba", subrubro="", codigo="BA429",
        modelo="Peuget-Citroen -Susuki- Chevolet -Renaut -M beanz -fort")
    for esperada in ("PEUGEOT", "SUZUKI", "CHEVROLET", "RENAULT", "MERCEDES BENZ", "FORD"):
        assert esperada in fila["modelo"], f"falta {esperada} en {fila['modelo']!r}"


def test_los_alias_de_modelo_se_aplican_aunque_la_palabra_venga_pegada_a_un_guion():
    """Bug encontrado armando la vista previa: si los alias se aplican antes
    de separar por guiones, 'Parnert-208' es UNA palabra y el alias no la
    agarra nunca."""
    assert "PARTNER" in nom.normalizar_modelo("Peugeot-Parnert-208-301")


def test_un_modelo_que_no_esta_en_alias_no_se_toca():
    """'DASTER' es DUSTER, pero mientras nadie lo confirme se deja como está.
    El parecido propone MASTER, que también es un Renault: aplicarlo solo
    manda al cliente a casa con la bomba de otro auto."""
    assert "DASTER" in nom.normalizar_modelo("Renault -Daster Oroch")


def test_una_fila_sin_pieza_deducible_queda_marcada_y_conserva_su_descripcion():
    fila = nom.normalizar_fila(
        proveedor="Proveedor Nuevo", descripcion="cosa rara sin identificar",
        marca="", rubro="Rubro Inventado", subrubro="", modelo="", codigo="X1")
    assert fila["revisar"] != ""
    assert "COSA RARA SIN IDENTIFICAR" in fila["nombre"]


def test_cuando_no_hay_especificacion_el_nombre_usa_las_marcas_de_auto():
    """Sin esto, 14 de las 25 filas de la primera carga quedaban con el
    nombre idéntico 'BOMBA DE AGUA VMG'."""
    fila = nom.normalizar_fila(
        proveedor="Rodamitre", descripcion="VMG BA013", marca="VMG",
        rubro="Bomba", subrubro="", modelo="Fiat 128", codigo="BA013")
    assert fila["nombre"] == "BOMBA DE AGUA VMG FIAT BA013"


def test_el_vocabulario_solo_toma_en_serio_las_palabras_frecuentes():
    vocab = nom.construir_vocabulario(["PARTNER BERLINGO"] * 400 + ["PARNERT"])
    assert vocab["PARTNER"] == 400
    assert vocab["PARNERT"] == 1


def test_una_palabra_frecuente_nunca_se_propone_como_typo():
    """MOBI (802 apariciones), MITO (536) y TORO (1003) son autos reales. Los
    salva únicamente el filtro de frecuencia."""
    vocab = nom.construir_vocabulario(["MOBI UNO FIORINO"] * 500 + ["VITO SPRINTER"] * 500)
    propuestas = nom.proponer_alias("MOBI UNO FIORINO", vocab)
    assert propuestas == []
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_nomenclatura.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.nomenclatura'`

- [ ] **Step 3: Escribir el módulo**

Crear `scripts/nomenclatura.py`:

```python
"""Decide cómo se llama un producto y deja marca y modelo en su columna.

La nomenclatura es:

    NOMBRE = PIEZA + MARCA + [ESPECIFICACIÓN] + CÓDIGO

todo en MAYÚSCULAS y SIN acentos. El auto NO va en el nombre: vive en
`modelo_compatible`, que es lo que el buscador ya mira (ver
`TEXTO_PRODUCTO_SQL` en core/database.py).

Es texto puro: NO importa core.database, así que se puede testear sin
Postgres levantado y usar desde cualquier script. Los nombres de rubro y
subrubro están escritos a mano acá; `verificar_taxonomia()` los compara
contra la base y tiene test propio.

Regla que no conviene revertir: las MARCAS de auto se corrigen solas
(conjunto chico y cerrado), los MODELOS no. Medido sobre las 25 filas de la
primera carga real: de 23 palabras sospechosas el parecido acierta 12 y se
equivoca en 6, y todos los pares equivocados son autos que existen los dos
(DASTER->MASTER cuando es DUSTER, LAGAN->LOGAN cuando es LAGUNA). Un error
ahí no se nota mirando el resultado: se nota cuando el cliente vuelve con la
bomba que no era.
"""
import re
import unicodedata
import difflib

# --- taxonomía v3, escrita a mano (ver verificar_taxonomia) -----------------
FRENOS = "Frenos"
SUSPENSION = "Suspensión"
MOTOR = "Motor"
EMBRAGUE = "Embrague"

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
# ("turbina 70mm", "polea 54mm", "alabes alto" — una bomba de embrague no
# tiene ninguna de las tres).
#
# Lo que no está acá NO se adivina: se marca para revisar.
ALIAS_RUBRO_CRUDO = {
    ("rodamitre", "bomba"): (MOTOR, BOMBA_DE_AGUA),
}

# --- marcas de auto: se aplican SIEMPRE -------------------------------------
MARCAS_AUTO = {
    r"\bpeug?[eo]?[tv]?o?t?\b|\bpeuget\b": "PEUGEOT",
    r"\brenau?lt?\b|\brenaut\b": "RENAULT",
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
# Crece con lo que una persona tilda en la hoja REVISAR. Nada entra acá
# automáticamente.
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
    """MAYÚSCULAS, sin acentos y sin espacios de más. El buscador ya normaliza
    acentos de los dos lados (texto_busqueda en SQL), así que sacarlos no le
    cuesta nada a la búsqueda y evita tener la misma palabra escrita de dos
    formas distintas en la base."""
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
    ALIAS_MODELO. Al revés, 'Parnert-208' es una sola palabra y el alias no
    la agarra nunca (bug real, encontrado armando la vista previa).
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

    Se usan en el nombre sólo cuando no hay ninguna especificación técnica
    que diferencie la pieza. Sin esto, 14 de las 25 filas de la primera carga
    real quedaban con el nombre idéntico.
    """
    vistas = []
    for m in re.finditer(r"[A-Z]+(?: BENZ| ROMEO| ROVER)?", modelo):
        if m.group(0) in _MARCAS_CANONICAS and m.group(0) not in vistas:
            vistas.append(m.group(0))
    return vistas[:tope]


def resolver_rubro(proveedor, rubro_crudo, subrubro_crudo):
    """Devuelve (rubro, subrubro, aviso). El aviso es "" cuando resolvió.

    Nunca adivina: lo que no está en ALIAS_RUBRO_CRUDO y no trae ya un
    subrubro conocido vuelve tal cual con un aviso para revisar.
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

    El vocabulario sale de los datos reales, no de una lista que yo escriba:
    una palabra bien escrita aparece miles de veces y un typo un puñado.
    """
    frecuencias = {}
    for texto in textos:
        for palabra in re.findall(r"[A-ZÁÉÍÓÚÜÑ]{%d,}" % LARGO_MINIMO_PALABRA,
                                  mayusculas_sin_acentos(texto)):
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
    for palabra in re.findall(r"[A-Z]{%d,}" % LARGO_MINIMO_PALABRA, modelo_normalizado):
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

    Existe para que un renombre de rubro en una migración explote en un test
    y no en medio de una carga.
    """
    problemas = []
    destinos = set(ALIAS_RUBRO_CRUDO.values())
    for subrubro in PIEZA_POR_SUBRUBRO:
        for categoria, subs in subcategorias_validas.items():
            if subrubro in subs:
                destinos.add((categoria, subrubro))
                break
        else:
            problemas.append(f"subcategoría inexistente en toda la taxonomía: {subrubro!r}")
    for categoria, subcategoria in sorted(destinos):
        if categoria not in categorias_validas:
            problemas.append(f"categoría inexistente: {categoria!r}")
        elif subcategoria not in subcategorias_validas.get(categoria, []):
            problemas.append(f"subcategoría inexistente: {categoria!r} / {subcategoria!r}")
    return sorted(set(problemas))
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/test_nomenclatura.py -v`
Expected: PASS, los 15.

Si `test_los_rubros_que_usa_el_modulo_existen_en_la_base` falla, el nombre de
un subrubro en `PIEZA_POR_SUBRUBRO` no coincide letra por letra con
`db.SUBCATEGORIAS_INICIALES` — copiarlo de ahí, no escribirlo de memoria.

- [ ] **Step 5: Correr la suite entera para verificar que no rompió nada**

Run: `python -m pytest tests/ -q`
Expected: PASS (302 tests + los 15 nuevos).

- [ ] **Step 6: Commit**

```bash
git add scripts/nomenclatura.py tests/test_nomenclatura.py
git commit -m "Nombrar los productos por la pieza, no por el código del proveedor"
```

---

### Task 2: El importador aplica la nomenclatura y sabe simular

**Files:**
- Modify: `scripts/cargar_stock_por_proveedor.py:100-135` (normalizar cada fila) y `:198-201` (los argumentos)
- Test: `tests/test_nomenclatura_importador.py`

**Interfaces:**
- Consumes: `nomenclatura.normalizar_fila(...)` de la Task 1.
- Produces: `cargar_stock_por_proveedor.importar(archivo, revisar=False)`, que con `revisar=True` no abre conexión a la base y devuelve `resumen["revision"]`, una lista de dicts con `proveedor`, `codigo`, `antes` y `ahora`.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_nomenclatura_importador.py`:

```python
"""El importador es el último lugar donde se puede arreglar una fila antes de
que entre a la base. Estos tests usan una planilla armada en memoria, no la
real: la real son datos del negocio y no está en el repositorio."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from openpyxl import Workbook

from scripts import cargar_stock_por_proveedor as cargar

ENCABEZADO = ["Cargar (SI/NO)", "Código interno", "Categoría",
              "Descripción / Nombre (*)", "Marca", "Modelo compatible",
              "Precio costo (*)", "Precio venta (*)", "Cantidad en stock (*)",
              "Stock mínimo", "Código de barras", "Subcategoría"]


@pytest.fixture
def planilla(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Rodamitre"
    ws.append(ENCABEZADO)
    ws.append(["SI", "BA446", "Bomba ", "VMG BA446", "OFERTA VMG",
               "Peugeot Citroen -P206-207 Parnet 1.6 Polea 19 dientes",
               1000, 1300, 2, 2, None, None])
    # sin cantidad: no se carga, y tampoco tiene que aparecer en la revisión
    ws.append(["SI", "BA999", "Bomba", "VMG BA999", "VMG", "Fiat 128",
               1000, 1300, None, 2, None, None])
    destino = tmp_path / "planilla.xlsx"
    wb.save(destino)
    return str(destino)


def test_revisar_no_toca_la_base_y_devuelve_el_antes_y_despues(planilla):
    """--revisar existe para poder mirar qué haría antes de que lo haga.
    Si abriera conexión, este test fallaría sin Postgres levantado."""
    resumen = cargar.importar(planilla, revisar=True)
    assert len(resumen["revision"]) == 1
    fila = resumen["revision"][0]
    assert fila["codigo"] == "BA446"
    assert fila["antes"]["nombre"] == "VMG BA446"
    assert fila["ahora"]["nombre"] == "BOMBA DE AGUA VMG POLEA 19 DIENTES BA446"
    assert fila["ahora"]["rubro"] == "Motor"
    assert fila["ahora"]["subrubro"] == "Bomba de agua"
    assert fila["ahora"]["marca"] == "VMG"


def test_las_filas_sin_cantidad_no_entran_en_la_revision(planilla):
    """La planilla trae el catálogo entero del proveedor. La cantidad escrita
    a mano es lo único que distingue 'esto lo tenemos' de 'esto el proveedor
    lo vende'."""
    resumen = cargar.importar(planilla, revisar=True)
    assert [f["codigo"] for f in resumen["revision"]] == ["BA446"]
    assert resumen["sin_cantidad"] == 1
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_nomenclatura_importador.py -v`
Expected: FAIL — `TypeError: importar() got an unexpected keyword argument 'revisar'`

- [ ] **Step 3: Modificar el importador**

En `scripts/cargar_stock_por_proveedor.py`, agregar el import arriba, junto al de `importar_datos`:

```python
from scripts import nomenclatura as nom
```

Cambiar la firma de `importar` para aceptar el modo revisión, y en el
diccionario `resumen` inicial agregar `"revision": []`.

Reemplazar el bloque que arma los valores de cada fila (hoy toma `nombre`,
`categoria`, `marca`, `modelo_compatible` y `subcategoria` crudos) por lo de
abajo. **Dejar intactas** las líneas que ya asignan `codigo`, `precio_costo`,
`precio_venta`, `stock_actual`, `stock_minimo` y `codigo_barras`: este cambio
sólo toca los cinco campos de texto, y `codigo` en particular se sigue usando
más abajo para buscar el producto existente.

```python
        # La nomenclatura corre acá, sobre las filas que de verdad se cargan,
        # y no sobre las 202.381 de la planilla: la cantidad escrita a mano ya
        # descartó el resto unas líneas más arriba.
        crudo = {
            "nombre": nombre, "marca": idatos._limpiar(fila[4]),
            "rubro": idatos._limpiar(fila[2]),
            "subrubro": idatos._limpiar(fila[11]) if len(fila) > 11 else "",
            "modelo": idatos._limpiar(fila[5]),
        }
        limpio = nom.normalizar_fila(
            proveedor=proveedor_nombre, descripcion=crudo["nombre"],
            marca=crudo["marca"], rubro=crudo["rubro"],
            subrubro=crudo["subrubro"], modelo=crudo["modelo"],
            codigo=idatos._limpiar(fila[1]),
        )
        if limpio["revisar"]:
            resumen["avisos"].append(f"'{nombre}' ({proveedor_nombre}): {limpio['revisar']}")

        nombre = limpio["nombre"]
        marca = limpio["marca"]
        modelo_compatible = limpio["modelo"]
        # El rubro ya viene resuelto contra la taxonomía; si el módulo no lo
        # pudo resolver, _normalizar_categoria lo manda al cajón de sastre
        # como siempre.
        categoria = idatos._normalizar_categoria(limpio["rubro"])
        subcategoria = limpio["subrubro"]

        if revisar:
            resumen["revision"].append({
                "proveedor": proveedor_nombre, "codigo": codigo or "",
                "antes": crudo, "ahora": limpio,
            })
            continue
```

Y en modo revisión no hay que abrir la base. Envolver la obtención de la
conexión para que sólo ocurra cuando `revisar` es falso, y saltear el
`commit`/`close` al final por el mismo motivo.

En el bloque `if __name__ == "__main__":`, aceptar el flag:

```python
    revisar = "--revisar" in sys.argv
    argumentos = [a for a in sys.argv[1:] if not a.startswith("--")]
    archivo = argumentos[0] if argumentos else ARCHIVO_POR_DEFECTO
    resumen = importar(archivo, revisar=revisar)
    if revisar:
        print(f"\nSIMULACIÓN: no se tocó la base. {len(resumen['revision'])} filas se cargarían.\n")
        for f in resumen["revision"]:
            print(f"  {f['codigo']} ({f['proveedor']})")
            print(f"    antes  {f['antes']['nombre']!r}  [{f['antes']['rubro']}]")
            print(f"    ahora  {f['ahora']['nombre']!r}  [{f['ahora']['rubro']} / {f['ahora']['subrubro']}]")
```

Actualizar también el docstring del módulo para que mencione `--revisar`.

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/test_nomenclatura_importador.py -v`
Expected: PASS, los 2.

- [ ] **Step 5: Correr la suite entera**

Run: `python -m pytest tests/ -q`
Expected: PASS. `tests/test_scripts.py` ya ejercita este importador — si algo
ahí falla, es que la firma de `importar()` cambió de forma incompatible.

- [ ] **Step 6: Commit**

```bash
git add scripts/cargar_stock_por_proveedor.py tests/test_nomenclatura_importador.py
git commit -m "Limpiar cada fila al cargarla, y poder simular la carga antes"
```

---

### Task 3: Limpiar la planilla que el negocio ya tiene

**Files:**
- Create: `scripts/normalizar_planilla_stock.py`
- Modify: `scripts/armar_planilla_stock.py` (aplicar el módulo al generar)

**Interfaces:**
- Consumes: `nomenclatura.normalizar_fila`, `construir_vocabulario`, `proponer_alias` de la Task 1.
- Produces: nada que consuman otras tareas.

- [ ] **Step 1: Escribir el script**

Crear `scripts/normalizar_planilla_stock.py`:

```python
"""Limpia una planilla de stock ya existente y escribe una copia prolija.

Toma LA PLANILLA QUE EL NEGOCIO YA TIENE, no la regenera desde las listas de
precios: regenerarla borraría las cantidades cargadas a mano, que son el
único trabajo humano que no se puede reponer.

Además de limpiar, agrega una hoja REVISAR con los typos de modelo que
detectó y NO aplicó, con una columna SI/NO. Lo que alguien tilde ahí se copia
a ALIAS_MODELO en scripts/nomenclatura.py y a partir de entonces se aplica
solo.

Uso (desde la raíz del proyecto):
    python scripts/normalizar_planilla_stock.py <archivo.xlsx> [salida.xlsx]
"""
import os
import sys

from openpyxl import load_workbook, Workbook

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import nomenclatura as nom

COL_CODIGO, COL_RUBRO, COL_NOMBRE = 1, 2, 3
COL_MARCA, COL_MODELO, COL_SUBRUBRO = 4, 5, 11


def _hojas_con_datos(wb):
    for ws in wb.worksheets:
        if ws.title.upper() != "INSTRUCCIONES":
            yield ws


def _es_encabezado(fila):
    return fila and fila[0] and str(fila[0]).strip().upper().startswith("CARGAR")


def normalizar(entrada, salida):
    # Primera pasada: el vocabulario sale de los datos reales del archivo.
    wb = load_workbook(entrada, read_only=True, data_only=True)
    textos = []
    for ws in _hojas_con_datos(wb):
        for fila in ws.iter_rows(values_only=True):
            if _es_encabezado(fila) or not fila or not fila[0]:
                continue
            textos.append(f"{fila[COL_NOMBRE] or ''} {fila[COL_MODELO] or ''}")
    vocabulario = nom.construir_vocabulario(textos)
    wb.close()

    # Segunda pasada: escribir. write_only por el volumen (~202.000 filas).
    wb = load_workbook(entrada, read_only=True, data_only=True)
    salida_wb = Workbook(write_only=True)
    propuestas, vistas, total, marcadas = {}, set(), 0, 0

    for ws in _hojas_con_datos(wb):
        hoja = salida_wb.create_sheet(ws.title)
        encabezado_visto = False
        for fila in ws.iter_rows(values_only=True):
            if not encabezado_visto:
                hoja.append(list(fila) if fila else [])
                if _es_encabezado(fila):
                    encabezado_visto = True
                continue
            if not fila or not fila[COL_NOMBRE]:
                hoja.append(list(fila) if fila else [])
                continue

            limpio = nom.normalizar_fila(
                proveedor=ws.title, descripcion=fila[COL_NOMBRE],
                marca=fila[COL_MARCA], rubro=fila[COL_RUBRO],
                subrubro=fila[COL_SUBRUBRO] if len(fila) > COL_SUBRUBRO else "",
                modelo=fila[COL_MODELO], codigo=fila[COL_CODIGO],
            )
            nueva = list(fila)
            nueva[COL_NOMBRE] = limpio["nombre"]
            nueva[COL_MARCA] = limpio["marca"]
            nueva[COL_MODELO] = limpio["modelo"]
            nueva[COL_RUBRO] = limpio["rubro"]
            if len(nueva) > COL_SUBRUBRO:
                nueva[COL_SUBRUBRO] = limpio["subrubro"]
            hoja.append(nueva)
            total += 1
            if limpio["revisar"]:
                marcadas += 1

            for palabra, veces, candidato, veces_c in nom.proponer_alias(
                    limpio["modelo"], vocabulario):
                if palabra in vistas:
                    continue
                vistas.add(palabra)
                propuestas[palabra] = (veces, candidato, veces_c,
                                       f"{fila[COL_CODIGO]} — {limpio['nombre']}")

    hoja = salida_wb.create_sheet("REVISAR")
    hoja.append(["Palabra encontrada", "Apariciones", "Candidato sugerido",
                 "Apariciones del candidato", "Ejemplo", "¿Aplicar? (SI/NO)"])
    for palabra, (veces, candidato, veces_c, ejemplo) in sorted(propuestas.items()):
        hoja.append([palabra, veces, candidato, veces_c, ejemplo, ""])

    salida_wb.save(salida)
    wb.close()
    return {"filas": total, "marcadas": marcadas, "propuestas": len(propuestas)}


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        raise SystemExit(0)
    entrada = sys.argv[1]
    salida = sys.argv[2] if len(sys.argv) > 2 else entrada.replace(".xlsx", "_limpia.xlsx")
    print(f"Leyendo {entrada} ... (con la planilla completa tarda unos minutos)")
    r = normalizar(entrada, salida)
    print(f"\nListo: {salida}")
    print(f"  {r['filas']} filas normalizadas")
    print(f"  {r['marcadas']} marcadas para revisar (no pude deducir la pieza)")
    print(f"  {r['propuestas']} typos de modelo propuestos en la hoja REVISAR, ninguno aplicado")
```

- [ ] **Step 2: Probarlo contra una planilla chica**

```bash
python - <<'EOF'
from openpyxl import Workbook
wb = Workbook(); ws = wb.active; ws.title = "Rodamitre"
ws.append(["Cargar (SI/NO)", "Código interno", "Categoría", "Descripción / Nombre (*)",
           "Marca", "Modelo compatible", "Precio costo (*)", "Precio venta (*)",
           "Cantidad en stock (*)", "Stock mínimo", "Código de barras", "Subcategoría"])
ws.append(["SI", "BA446", "Bomba ", "VMG BA446", "OFERTA VMG",
           "Peugeot Citroen -P206-207 Parnet 1.6 Polea 19 dientes", 1000, 1300, 2, 2, None, None])
wb.save("/tmp/mini.xlsx")
EOF
python scripts/normalizar_planilla_stock.py /tmp/mini.xlsx /tmp/mini_limpia.xlsx
```

Expected: dice `1 filas normalizadas`, `0 marcadas para revisar`, y crea
`/tmp/mini_limpia.xlsx` con la hoja Rodamitre y la hoja REVISAR.

- [ ] **Step 3: Verificar el contenido de la salida**

```bash
python -c "
from openpyxl import load_workbook
ws = load_workbook('/tmp/mini_limpia.xlsx')['Rodamitre']
f = list(ws.iter_rows(min_row=2, values_only=True))[0]
assert f[3] == 'BOMBA DE AGUA VMG POLEA 19 DIENTES BA446', f[3]
assert f[4] == 'VMG', f[4]
assert f[2] == 'Motor', f[2]
assert f[11] == 'Bomba de agua', f[11]
print('ok:', f[3])
"
```

Expected: imprime `ok: BOMBA DE AGUA VMG POLEA 19 DIENTES BA446`.

- [ ] **Step 4: Que la próxima planilla nazca prolija**

En `scripts/armar_planilla_stock.py`, agregar el import junto a los otros:

```python
from scripts import nomenclatura as nom
```

y en el bucle que escribe las filas (línea ~382, `for p in consolidados:`),
normalizar antes del `ws.append`:

```python
    for p in consolidados:
        costo = p["costo"] or None
        venta = precio_venta_sugerido(costo)
        if not costo:
            resumen["sin_costo"] += 1
        # La nomenclatura se aplica ya al generar, así la planilla nace
        # prolija y no necesita pasar después por normalizar_planilla_stock.py.
        limpio = nom.normalizar_fila(
            proveedor=ws.title, descripcion=p["nombre"], marca=p["marca"],
            rubro=p["categoria"], subrubro=p["subcategoria"],
            modelo=p["modelo"], codigo=p["codigo"],
        )
        if limpio["rubro"] == clasif.VARIOS:
            resumen["en_varios"] += 1
        ws.append([
            "SI",
            p["codigo"] or None,
            limpio["rubro"],
            limpio["nombre"],
            limpio["marca"] or None,
            limpio["modelo"] or None,
            float(costo) if costo else None,
            float(venta) if venta else None,
            None,                       # Cantidad en stock: lo completa el negocio
            STOCK_MINIMO_POR_DEFECTO,
            None,                       # Código de barras: ninguna lista lo trae
            limpio["subrubro"],
        ])
        resumen["filas"] += 1
```

Ojo con el contador `en_varios`: antes miraba `p["categoria"]` y ahora tiene
que mirar `limpio["rubro"]`, porque es el rubro que de verdad se escribe.

- [ ] **Step 5: Correr la suite entera**

Run: `python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/normalizar_planilla_stock.py scripts/armar_planilla_stock.py
git commit -m "Limpiar la planilla que el negocio ya tiene, sin borrarle las cantidades"
```

---

### Task 4: Mayúscula al tipear en la ficha de producto

**Files:**
- Modify: `core/app.py` — `productos_nuevo()` (~línea 1083), `productos_editar()` (~línea 1135), `api_productos_nuevo()` (~línea 1802)
- Modify: `templates/producto_form.html:18,56,63`
- Test: `tests/test_nomenclatura_formulario.py`

**Interfaces:**
- Consumes: `nomenclatura.mayusculas_sin_acentos` de la Task 1.
- Produces: nada.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_nomenclatura_formulario.py`:

```python
"""El CSS text-transform es SOLO visual: el valor que llega al servidor sigue
siendo lo que la persona tipeó. Sin la normalización del lado del servidor,
la mayúscula del formulario es una mentira prolija."""
from pathlib import Path

import pytest

from core.app import app as flask_app


@pytest.fixture
def client(db_conn):
    """Mismo patrón que tests/test_producto_vehiculos.py: la sesión se falsea
    a mano porque el login real vive en Supabase Auth."""
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        with c.session_transaction() as sesion:
            sesion["usuario_id"] = "00000000-0000-0000-0000-000000000001"
            sesion["usuario_nombre"] = "Test"
            sesion["usuario_rol"] = "admin"
            sesion["debe_cambiar_password"] = False
        yield c


def test_lo_que_se_guarda_queda_en_mayusculas_sin_acentos(client, db_conn):
    respuesta = client.post("/productos/nuevo", data={
        "codigo": "TEST-MAY-1", "nombre": "bomba de agua citroën",
        "categoria": "Motor", "subcategoria": "Bomba de agua",
        "marca": "vmg", "modelo_compatible": "peugeot 206",
        "precio_costo": "100", "precio_venta": "130",
        "stock_actual": "1", "stock_minimo": "2",
    }, follow_redirects=True)
    assert respuesta.status_code == 200

    fila = db_conn.execute(
        "SELECT nombre, marca, modelo_compatible, categoria, subcategoria"
        " FROM productos WHERE codigo = %s", ("TEST-MAY-1",)).fetchone()
    assert fila["nombre"] == "BOMBA DE AGUA CITROEN"
    assert fila["marca"] == "VMG"
    assert fila["modelo_compatible"] == "PEUGEOT 206"
    # El rubro NO: facetas_productos() agrupa esta columna cruda y 'MOTOR'
    # aparecería como un rubro distinto de 'Motor' en el filtro.
    assert fila["categoria"] == "Motor"
    assert fila["subcategoria"] == "Bomba de agua"


def test_el_formulario_muestra_la_mayuscula_mientras_se_escribe():
    """La otra capa: sin esto la persona escribe en minúscula y ve minúscula,
    y la mayúscula aparece recién después de guardar, que sorprende."""
    html = Path("templates/producto_form.html").read_text()
    assert "text-transform: uppercase" in html or "text-transform:uppercase" in html
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_nomenclatura_formulario.py -v`
Expected: FAIL — el nombre guardado es `'bomba de agua citroën'`.

- [ ] **Step 3: Normalizar del lado del servidor**

En `core/app.py`, importar el módulo arriba con el resto:

```python
from scripts import nomenclatura as nom
```

En `productos_nuevo()` y `productos_editar()`, reemplazar los tres valores
correspondientes de la tupla:

```python
                nom.mayusculas_sin_acentos(request.form["nombre"]),
                request.form["categoria"],
                request.form.get("subcategoria") or None,
                nom.mayusculas_sin_acentos(request.form.get("marca", "")),
                nom.mayusculas_sin_acentos(request.form.get("modelo_compatible", "")),
```

Dejar `categoria` y `subcategoria` intactas: son las que `facetas_productos()`
agrupa crudas.

En `api_productos_nuevo()`, cambiar las dos asignaciones:

```python
    nombre = nom.mayusculas_sin_acentos(request.form.get("nombre", ""))
    ...
    marca = nom.mayusculas_sin_acentos(request.form.get("marca", "")) or None
```

- [ ] **Step 4: Mostrar la mayúscula mientras se escribe**

En `templates/producto_form.html`, agregar `style="text-transform: uppercase"`
a los tres inputs de las líneas 18 (`nombre`), 56 (`marca`) y 63
(`modelo_compatible`), con un comentario Jinja arriba del primero:

```html
{# La mayúscula visual es solo eso: lo que garantiza lo que se guarda es
   mayusculas_sin_acentos() del lado del servidor (core/app.py). #}
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/test_nomenclatura_formulario.py -v`
Expected: PASS, los 2.

- [ ] **Step 6: Correr la suite entera**

Run: `python -m pytest tests/ -q`
Expected: PASS. Ojo con los tests que crean productos y después los buscan por
nombre exacto en minúsculas: si alguno falla, la expectativa del test hay que
subirla a mayúsculas, no apagar la normalización.

- [ ] **Step 7: Commit**

```bash
git add core/app.py templates/producto_form.html tests/test_nomenclatura_formulario.py
git commit -m "Tomar mayúscula al tipear en la ficha de producto, y garantizarla al guardar"
```

---

### Task 5: Cargar las 25 filas reales y documentar

**Files:**
- Modify: `CLAUDE.md` (sección nueva)

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: nada.

- [ ] **Step 1: Simular la carga real, sin tocar la base**

```bash
python scripts/cargar_stock_por_proveedor.py \
  "/Users/celescaa/Downloads/Lista De Precios San Ignacio/Planilla_Stock_Carga_prueba_20260820.xlsx" \
  --revisar
```

Expected: dice que se cargarían **25** filas, las 24 de Rodamitre con rubro
`Motor / Bomba de agua`, y ningún nombre repetido.

- [ ] **Step 2: Cargar de verdad contra la base local**

Con `npx supabase start` levantado:

```bash
python scripts/cargar_stock_por_proveedor.py \
  "/Users/celescaa/Downloads/Lista De Precios San Ignacio/Planilla_Stock_Carga_prueba_20260820.xlsx"
```

- [ ] **Step 3: Verificar contra la base que la búsqueda encuentra lo que tiene que encontrar**

```bash
python -c "
import sys; sys.path.insert(0, '.')
from core import database as db
conn = db.get_connection()
for q in ['bomba fiat', 'bomba agua peugeot', 'partner', 'bomba freno']:
    filas, _ = db.buscar_productos_tolerante(conn, q)
    print(f'{q:<22} {len(filas)}')
"
```

Expected: `bomba fiat` ≥ 5, `bomba agua peugeot` ≥ 6, `partner` ≥ 3, y
`bomba freno` **0** (ninguna de estas es de freno; si diera resultados, algo
quedó mal clasificado).

- [ ] **Step 4: Verificar que ninguna cayó en Varios**

```bash
python -c "
import sys; sys.path.insert(0, '.')
from core import database as db
conn = db.get_connection()
for f in conn.execute(\"SELECT categoria, subcategoria, count(*) n FROM productos WHERE codigo LIKE 'BA%' GROUP BY 1,2\").fetchall():
    print(f['categoria'], '/', f['subcategoria'], '->', f['n'])
"
```

Expected: una sola línea, `Motor / Bomba de agua -> 24`.

- [ ] **Step 5: Documentar en CLAUDE.md**

Agregar una sección nueva, con fecha 21/08/2026, después de "Planilla única de
stock". Tiene que cubrir:

- La nomenclatura `PIEZA + MARCA + [ESPECIFICACIÓN] + CÓDIGO`, en mayúsculas
  sin acentos, y que el auto va en su columna porque el buscador ya la mira.
- **Que rubro y subrubro no se pasan a mayúscula, y por qué**
  (`facetas_productos()` agrupa esas columnas crudas). Es el gotcha que más
  fácil se revierte por prolijidad.
- Que las marcas de auto se corrigen solas y los modelos no, con los números
  que lo justifican: 12 aciertos, 6 errores sobre 23 casos, todos los pares
  errados son autos reales.
- Que la mayúscula del formulario son dos capas y el CSS solo es visual.
- El bug de orden: los separadores se normalizan antes que `ALIAS_MODELO`.
- Cómo crece `ALIAS_MODELO`: desde la hoja REVISAR, a mano.
- Qué se probó de verdad y qué no.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "Anotar la nomenclatura y el porqué de que los modelos no se corrijan solos"
```
