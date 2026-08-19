"""
Clasifica un repuesto en (categoría, subcategoría) de la taxonomía v3 del
negocio a partir del texto que traiga la lista del proveedor.

Lo usan dos cosas que necesitan el MISMO criterio, y por eso vive acá y no
adentro de ninguna de las dos:

  1. `armar_planilla_stock.py`, para clasificar las listas de proveedores
     que llegan sin ninguna clasificación (Michelli, Devoto).
  2. ese mismo script, para reclasificar a v3 las ~184.000 filas que ya
     venían clasificadas con la taxonomía vieja (v2) de
     `Planilla_Stock_Por_Proveedor_completa_1.xlsx`.

NO abre la base de datos a propósito: es un clasificador de texto puro, se
puede correr sobre un Excel sin tener Postgres levantado. La taxonomía que
devuelve tiene que coincidir con `db.CATEGORIAS_INICIALES` /
`db.SUBCATEGORIAS_INICIALES`; `verificar_taxonomia()` lo comprueba contra la
base y hay un test que lo corre (`tests/test_clasificar_repuestos.py`), así
que si alguien renombra un rubro en una migración, salta ahí y no en una
carga de 200.000 filas.
"""
import re
import unicodedata

# --- Rubros y subrubros de la taxonomía v3 (15/08/2026) ---------------------
FRENOS = "Frenos"
SUSPENSION = "Suspensión"
DIRECCION = "Dirección"
MOTOR = "Motor"
ELECTRICO = "Encendido y Eléctrico"
EMBRAGUE = "Embrague"
FERRETERIA = "Ferretería"
VARIOS = "Varios"

# Subrubros escritos tal cual están en la migración de la taxonomía v3 --
# incluidas las comas y los paréntesis de adentro, que son parte del nombre.
PASTILLAS = "Pastillas de freno"
DISCOS = "Discos de freno"
CINTAS = "Cintas de freno"
CILINDROS_FRENO = "Cilindros (bomba freno, cilindros de rueda)"
SERVOFRENO = "Servofreno"
CABLES_FRENO = "Cables de freno (mano)"
CAMPANAS = "Campanas de freno"
ZAPATAS = "Zapatas de freno"
MANGUERAS = "Mangueras y flexibles"
SENSORES_DESGASTE = "Sensores de desgaste"
SEGUROS_ANTIRRUIDO = "Seguros antirruido"
LIQUIDO_FRENOS = "Líquido de frenos"

AMORTIGUADORES = "Amortiguadores"
BIELETAS = "Bieletas"
BARRAS = "Barras de torsión y estabilizadoras"
BUJES = "Bujes"
CAZOLETAS = "Cazoletas, crapodinas"
SOPORTES_SUSP = "Contrapesos, soportes de suspensión"
RESORTES = "Resortes / espirales"
MAZAS = "Mazas de rueda"
RODAMIENTOS = "Rodamientos y rulemanes"

BRAZOS_DIR = "Brazos de dirección"
CAJAS_DIR = "Cajas de dirección"
COLUMNAS_DIR = "Columnas de dirección"
TERMINALES_ROTULAS = "Terminales / rótulas"
CREMALLERAS = "Cremalleras"

BOMBA_AGUA = "Bomba de agua"
CADENAS = "Cadenas de distribución"
CORREAS = "Correas (distribución, alternador, etc.)"
JUNTAS = "Juntas y empaquetaduras"
RETENES = "Retenes"

BATERIAS = "Baterías"
BOBINAS = "Bobinas"
BUJIAS = "Bujías"
BUJIAS_DIESEL = "Bujías precalentadoras (diesel)"
CABLES_BUJIA = "Cables de bujía"
ARRANQUE = "Motores de arranque / alternadores"

KIT_EMBRAGUE = "Kits de embrague (disco + plato + collarín)"
COLLARINES = "Collarines / rulemanes de embrague"
BOMBAS_EMBRAGUE = "Bombas y cilindros de embrague"
VOLANTES_BIMASA = "Volantes bimasa"

ARANDELAS = "Arandelas"
BULONES = "Bulones"
TORNILLOS = "Tornillos"
TUERCAS = "Tuercas"

ABRAZADERAS = "Abrazaderas"
CONECTORES = "Terminales, conectores varios"
REPUESTOS_CHICOS = "Repuestos chicos sin categoría propia"


def normalizar(texto):
    """Minúsculas, sin acentos y con los espacios colapsados.

    Mismo criterio que la función SQL `texto_busqueda()` del sistema: las
    listas de proveedores escriben "HIDRÁULICO" y "hidraulico" para la misma
    cosa, y una regla que solo matchea una de las dos formas deja miles de
    filas mal clasificadas sin que nada avise.
    """
    if texto is None:
        return ""
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", str(texto))
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", sin_acentos).strip().lower()


# --- Reglas -----------------------------------------------------------------
# (patrón, categoría, subcategoría). Se evalúan EN ORDEN y gana la primera que
# matchea, así que lo específico va antes que lo genérico: "bomba de embrague"
# tiene que ganarle a "bomba", y "disco de embrague" a "disco".
#
# El patrón es una expresión regular sobre el texto ya normalizado. Se usan
# alternativas (a|b) en vez de una regla por sinónimo para que la tabla se
# pueda leer de arriba a abajo como lo que es: una lista de prioridades.
REGLAS = [
    # -- Transmisión y filtros: la v3 no tiene esos rubros porque el negocio
    # no los vende, así que van al cajón de sastre A PROPÓSITO. Van primero
    # porque si no otras reglas se las llevan mal clasificadas: una "JUNTA
    # HOMOCINETICA" es de transmisión y terminaba en Motor / Juntas y
    # empaquetaduras, y un "FUELLE DE SEMIEJE" terminaba en Suspensión.
    (r"\bhomocinetica", VARIOS, None),
    (r"\b(semieje|palier|cruceta|diferencial)\b", VARIOS, None),
    (r"\bcorona\b.{0,20}\b(pinon|diferencial)\b", VARIOS, None),
    (r"\bcaja de (cambio|velocidad)", VARIOS, None),
    (r"\bfiltro\b", VARIOS, None),

    # -- Embrague (antes que Frenos y Motor: comparte casi todo el vocabulario)
    (r"\b(kit|conjunto|juego)\b.{0,20}\bembrague\b", EMBRAGUE, KIT_EMBRAGUE),
    (r"\bembrague\b.{0,20}\b(kit|conjunto|juego)\b", EMBRAGUE, KIT_EMBRAGUE),
    (r"\bvolante\b.{0,12}\b(bimasa|bi-masa|doble masa)\b", EMBRAGUE, VOLANTES_BIMASA),
    (r"\bbimasa\b", EMBRAGUE, VOLANTES_BIMASA),
    (r"\b(crapodina|collarin|collarines|rulemam?n?)\b.{0,20}\bembrague\b", EMBRAGUE, COLLARINES),
    (r"\bembrague\b.{0,20}\b(crapodina|collarin)\b", EMBRAGUE, COLLARINES),
    (r"\b(bomba|bombin|cilindro|cilindros|actuador|bulon de purga)\b.{0,25}\bembrague\b", EMBRAGUE, BOMBAS_EMBRAGUE),
    (r"\bembrague\b.{0,25}\b(bomba|bombin|cilindro|actuador|hidraulico)\b", EMBRAGUE, BOMBAS_EMBRAGUE),
    (r"\b(cilindro (maestro|receptor|esclavo)|actuador hidraulico)\b", EMBRAGUE, BOMBAS_EMBRAGUE),
    (r"\b(disco|plato|prensa)\b.{0,20}\bembrague\b", EMBRAGUE, KIT_EMBRAGUE),
    (r"\b(horquilla|caño|cano|bolita|guia)\b.{0,20}\bembrague\b", EMBRAGUE, None),
    (r"\bembrague\b", EMBRAGUE, None),

    # -- Frenos
    (r"\bpastilla", FRENOS, PASTILLAS),
    (r"\bbalata", FRENOS, PASTILLAS),
    (r"\bzapata", FRENOS, ZAPATAS),
    (r"\bcampana", FRENOS, CAMPANAS),
    (r"\bdisco\b.{0,15}\bfreno\b|\bfreno\b.{0,15}\bdisco\b", FRENOS, DISCOS),
    (r"\bcinta\b.{0,15}\bfreno\b|\bcinta en rollo\b|\bplasbestos\b", FRENOS, CINTAS),
    (r"\bservo ?freno\b|\bservofreno\b|\bbooster de freno\b", FRENOS, SERVOFRENO),
    (r"\b(cable|palanca)\b.{0,25}\bfreno de mano\b|\bfreno de mano\b", FRENOS, CABLES_FRENO),
    (r"\bcable\b.{0,15}\bfreno\b", FRENOS, CABLES_FRENO),
    (r"\b(sensor|cable sensor)\b.{0,20}\bdesgaste\b|\bwear indicator\b", FRENOS, SENSORES_DESGASTE),
    (r"\bantirruidos?\b", FRENOS, SEGUROS_ANTIRRUIDO),
    (r"\b(manguera|flexible|latiguillo)\b.{0,20}\bfreno\b", FRENOS, MANGUERAS),
    (r"\bliquido\b.{0,20}\bfreno\b|\bdot ?[345]\b", FRENOS, LIQUIDO_FRENOS),
    # El buje/kit de reparación de un caliper es una pieza suelta, no el
    # cilindro: va antes que la regla de cilindros, que si no se lo lleva.
    (r"\b(buje|bujes|kit|repar\w*)\b.{0,20}\bcaliper\b", FRENOS, None),
    (r"\b(bomba|bombin|cilindro|caliper|pinza|mordaza|valvula compensadora|regulador de freno)\b.{0,25}\bfreno\b",
     FRENOS, CILINDROS_FRENO),
    (r"\bfreno\b.{0,25}\b(bomba|bombin|cilindro|caliper|pinza)\b", FRENOS, CILINDROS_FRENO),
    (r"\b(cilindro de rueda|bomba de freno|caliper)\b", FRENOS, CILINDROS_FRENO),
    (r"\bfreno\b", FRENOS, None),
    # Últimos recursos del rubro: en una casa de frenos, un "disco" a secas es
    # de freno y una "cinta" a secas es la cinta de freno. Van al final del
    # bloque, después de que el bloque de Embrague (que está más arriba) ya se
    # llevó "disco de embrague" y "plato".
    (r"\bdiscos?\b", FRENOS, DISCOS),
    (r"\bcintas?\b", FRENOS, CINTAS),

    # -- Suspensión
    # Cazoleta y crapodina van antes que amortiguador: la descripción típica es
    # "CAZOLETA AMORTIGUADOR DELANTERA", y al revés la pieza que se vende
    # (la cazoleta) queda clasificada como si fuera el amortiguador entero.
    (r"\bcazoleta", SUSPENSION, CAZOLETAS),
    (r"\bcrapodina", SUSPENSION, CAZOLETAS),
    (r"\bamortiguador", SUSPENSION, AMORTIGUADORES),
    (r"\bbieleta", SUSPENSION, BIELETAS),
    (r"\b(barra|barral)\b.{0,20}\b(estabilizadora|torsion)\b|\bestabilizadora\b", SUSPENSION, BARRAS),
    # "resorte" solo no alcanza: el resorte a gas es el del portón trasero
    # (no es suspensión) y el resorte de zapata es de freno. Los dos casos se
    # descartan antes de que el genérico se lleve el espiral de suspensión,
    # que es lo que la palabra significa en el resto de las listas.
    (r"\bresorte\b.{0,20}\b(zapata|freno)\b|\bconjunto de resortes\b", FRENOS, SEGUROS_ANTIRRUIDO),
    (r"\bresorte a gas\b", VARIOS, None),
    (r"\bespiral(es)?\b|\bresorte", SUSPENSION, RESORTES),
    (r"\bmaza\b.{0,15}\brueda\b|\bmazas?\b(?!.{0,10}\bcorrea\b)", SUSPENSION, MAZAS),
    (r"\b(rodamiento|ruleman|rulemanes|rulman)\b", SUSPENSION, RODAMIENTOS),
    (r"\b(buje|bujes)\b", SUSPENSION, BUJES),
    (r"\bparrilla", SUSPENSION, BUJES),
    (r"\b(soporte|contrapeso|tope|almohadilla|aislador|apoya espiral)\b.{0,25}\b(suspension|amortiguador|espiral)\b",
     SUSPENSION, SOPORTES_SUSP),
    (r"\b(topes? suspension|kit suspension|fuelles? suspension)\b", SUSPENSION, SOPORTES_SUSP),

    # -- Dirección
    # Va antes del "\bsuspension\b" genérico de más abajo: la rótula se
    # describe casi siempre como "ROTULA DE SUSPENSION", y en la taxonomía v3
    # las rótulas viven en Dirección ("Terminales / rótulas"), no en
    # Suspensión. Con el genérico primero, todas caían en Suspensión sin
    # subrubro.
    (r"\b(rotula|rotulas)\b", DIRECCION, TERMINALES_ROTULAS),
    (r"\b(extremo|terminal)\b.{0,25}\bdireccion\b", DIRECCION, TERMINALES_ROTULAS),
    (r"\b(extremo|articulacion axial|barra de acoplamiento)\b", DIRECCION, TERMINALES_ROTULAS),
    (r"\bcremallera", DIRECCION, CREMALLERAS),
    (r"\bcolumna\b.{0,15}\bdireccion\b", DIRECCION, COLUMNAS_DIR),
    (r"\b(caja|bomba)\b.{0,15}\bdireccion\b", DIRECCION, CAJAS_DIR),
    (r"\bbrazo\b.{0,20}\b(pitman|direccion|auxiliar|rotula)\b|\bbrazo pitman\b|\bmanchon\b", DIRECCION, BRAZOS_DIR),
    # "precap" es el guardapolvo de la articulación axial de la dirección.
    # No lo nombra ninguna otra regla y son ~1.000 filas de una sola lista.
    (r"\bprecap\b", DIRECCION, None),
    (r"\bfuelle\b.{0,30}\b(direccion|cremallera|axial)\b", DIRECCION, None),
    (r"\bfuelle\b.{0,30}\b(amortiguador|suspension|espiral)\b", SUSPENSION, SOPORTES_SUSP),
    (r"\bdireccion\b", DIRECCION, None),
    (r"\bsuspension\b", SUSPENSION, None),

    # -- Motor
    (r"\bbomba\b.{0,15}\bagua\b", MOTOR, BOMBA_AGUA),
    (r"\bcadena\b.{0,20}\bdistribucion\b", MOTOR, CADENAS),
    (r"\bcorrea", MOTOR, CORREAS),
    (r"\b(tensor|polea)\b", MOTOR, CORREAS),
    (r"\bkit\b.{0,15}\bdistribucion\b", MOTOR, CORREAS),
    (r"\breten(es)?\b|\bguard\w*\b.{0,10}\b(aceite|polvo)\b", MOTOR, RETENES),
    (r"\b(junta|empaquetadura|empaque)\b", MOTOR, JUNTAS),
    (r"\bmotor\b", MOTOR, None),

    # -- Encendido y Eléctrico
    (r"\bbujia\b.{0,25}\b(incandescente|precalentamiento|calentador|diesel)\b|\bbujia incandescente\b",
     ELECTRICO, BUJIAS_DIESEL),
    (r"\bcable\b.{0,20}\b(bujia|encendido)\b", ELECTRICO, CABLES_BUJIA),
    (r"\bbujia", ELECTRICO, BUJIAS),
    (r"\bbobina\b.{0,20}\bencendido\b|\bbobina\b", ELECTRICO, BOBINAS),
    (r"\bbateria", ELECTRICO, BATERIAS),
    (r"\b(motor de arranque|arranque|alternador|burro de arranque)\b", ELECTRICO, ARRANQUE),
    (r"\b(distribuidor|rotor distribuidor|tapa distribuidor|encendido)\b", ELECTRICO, None),

    # -- Ferretería
    (r"\barandela", FERRETERIA, ARANDELAS),
    (r"\bbulon(es)?\b", FERRETERIA, BULONES),
    (r"\btornillo", FERRETERIA, TORNILLOS),
    (r"\btuerca", FERRETERIA, TUERCAS),

    # -- Varios
    (r"\babrazadera", VARIOS, ABRAZADERAS),
    (r"\b(terminal|conector|borne|fich[ae])\b", VARIOS, CONECTORES),
]

REGLAS_COMPILADAS = [(re.compile(p), c, s) for p, c, s in REGLAS]


def clasificar(*textos):
    """Devuelve (categoría, subcategoría) para las partes de texto que le pasen.

    Los textos se concatenan (descripción, tipo de producto, rubro del
    proveedor, lo que haya) porque ninguno alcanza solo: la descripción de
    Devoto dice "BRAZO PITMAN (CURVO) L-200" sin nombrar el sistema, y su
    columna UBICACION dice "PITMAN" sin decir qué pieza es.

    Si nada matchea devuelve (VARIOS, None) -- nunca inventa un rubro. Una
    fila en Varios se ve y se corrige; una mal clasificada como Frenos no.
    """
    # str() explícito: las celdas de Excel llegan como int/float cuando el
    # proveedor cargó un código o una medida sin letras, y un join sobre eso
    # revienta a mitad de una corrida de 200.000 filas.
    texto = normalizar(" ".join(str(t) for t in textos if t))
    if not texto:
        return VARIOS, None
    for patron, categoria, subcategoria in REGLAS_COMPILADAS:
        if patron.search(texto):
            return categoria, subcategoria
    return VARIOS, None


# --- Reclasificación de la taxonomía vieja (v2) ------------------------------
# La planilla `Planilla_Stock_Por_Proveedor_completa_1.xlsx` trae ~184.000
# filas ya clasificadas con la taxonomía v2, que el sistema ya no tiene. El
# importador manda a "Varios" todo rubro que no reconoce, así que subirla tal
# cual dejaría ~110.000 productos ahí adentro.
#
# Estas dos tablas traducen v2 -> v3. Un destino `None` en la subcategoría
# significa "esto no se puede decidir por el rubro solo, resolvelo mirando el
# texto" y cae en `clasificar()`.
SUBCATEGORIA_V2_A_V3 = {
    "pastillas": (FRENOS, PASTILLAS),
    "discos": (FRENOS, DISCOS),
    "campanas": (FRENOS, CAMPANAS),
    "zapatas": (FRENOS, ZAPATAS),
    "seguros antirruido": (FRENOS, SEGUROS_ANTIRRUIDO),
    "cables y sensores de desgaste": (FRENOS, SENSORES_DESGASTE),
    "mangueras y flexibles": (FRENOS, MANGUERAS),
    "cables y cintas": (FRENOS, CINTAS),
    "bombas y cilindros": (FRENOS, CILINDROS_FRENO),
    "vacio y servofreno": (FRENOS, SERVOFRENO),
    "discos y platos": (EMBRAGUE, KIT_EMBRAGUE),
    "crapodinas y collarines": (EMBRAGUE, COLLARINES),
    "volantes bimasa": (EMBRAGUE, VOLANTES_BIMASA),
    "amortiguadores": (SUSPENSION, AMORTIGUADORES),
    "parrillas y bujes": (SUSPENSION, BUJES),
    "bieletas": (SUSPENSION, BIELETAS),
    "mazas de rueda": (SUSPENSION, MAZAS),
    "rodamientos y rulemanes": (SUSPENSION, RODAMIENTOS),
    "rotulas y extremos": (DIRECCION, TERMINALES_ROTULAS),
    "cremalleras y bombas de direccion": (DIRECCION, CREMALLERAS),
    "correas": (MOTOR, CORREAS),
    "encendido": (ELECTRICO, None),
    "refrigeracion": (MOTOR, None),
    # "Tensores y poleas" de la v2 mete adentro las bombas de agua (van con
    # el kit de distribución), así que el subrubro lo decide el texto: si no,
    # cada bomba de agua quedaba etiquetada como correa.
    "tensores y poleas": (MOTOR, None),
    # Ambiguas por definición: el nombre v2 no alcanza, hay que leer el texto.
    "valvulas y actuadores": (None, None),
    "otros de frenos": (FRENOS, None),
    "otros de embrague": (EMBRAGUE, None),
    "otros de suspension/direccion": (None, None),
    "otros de motor": (MOTOR, None),
    "otros de transmision": (None, None),
    # Rubros de transmisión: v3 no tiene ese rubro (el negocio no lo vende),
    # así que caen al cajón de sastre en vez de inventarle una casa.
    "homocineticas": (VARIOS, None),
    "semiejes y palieres": (VARIOS, None),
    "crucetas": (VARIOS, None),
    "coronas y diferencial": (VARIOS, None),
    "comando": (VARIOS, None),
}

CATEGORIA_V2_A_V3 = {
    "frenos": FRENOS,
    "embragues": EMBRAGUE,
    "embrague": EMBRAGUE,
    "motor": MOTOR,
    "ferreteria": FERRETERIA,
    "rodamientos y mazas": SUSPENSION,
    "correas": MOTOR,
    # Sin destino fijo: hay que mirar el texto.
    #
    # "Otros" NO va mapeado a Varios aunque sea su traducción literal: es el
    # cajón de sastre de la v2 (31.259 filas) y adentro hay barras de torsión,
    # espirales y cintas de freno perfectamente clasificables. Mapearlo duro
    # a Varios hacía que el texto ni se mirara y las mandaba a todas al cajón
    # de sastre de la v3. Dejándolo en None el texto decide, y lo que el texto
    # no reconoce cae igual en Varios por el camino normal.
    "otros": None,
    "otro": None,
    "varios": None,
    "suspension y direccion": None,
    "transmision": None,
    "filtros": None,
    "retenes y juntas": None,
    "liquidos": None,
}


def reclasificar_v2(categoria_v2, subcategoria_v2, *textos):
    """Traduce una fila de la taxonomía v2 a la v3.

    Prioriza la subcategoría v2 sobre la categoría v2 porque es más
    específica: una fila `Suspensión y Dirección / Rótulas y extremos` va a
    Dirección, mientras que su categoría sola no alcanza para decidir entre
    Suspensión y Dirección, que en v3 son dos rubros separados.

    Cuando la traducción directa no alcanza, cae en `clasificar()` sobre el
    texto -- el mismo camino que usan los proveedores que llegan sin
    clasificar, así las dos mitades de la planilla quedan con un solo criterio.

    El rubro que la v2 ya tenía funciona de piso cuando el texto no dice
    nada: Infofren describe sus productos por el auto y no por la pieza
    ("SONIC / TRACKER"), así que ahí el texto no alcanza para clasificar y
    tirar esas filas a "Varios" sería perder la clasificación que ya estaba
    bien.
    """
    por_texto_cat, por_texto_sub = clasificar(*textos)
    categoria_v2_traducida = CATEGORIA_V2_A_V3.get(normalizar(categoria_v2))
    sub_norm = normalizar(subcategoria_v2)

    # "Varios" nunca es un destino con confianza: es la ausencia de uno. Si el
    # mapeo v2 termina ahí pero el texto sí reconoce la pieza, gana el texto.
    # Sin esto, un "PRECAP AXIAL DE SALIDA DE CAJA DE DIRECCION" que la v2
    # había etiquetado mal como Transmisión / Coronas y diferencial se iba al
    # cajón de sastre en vez de a Dirección, que es lo que dice su propio
    # nombre. La v2 no es infalible y acá se nota.
    texto_es_confiable = por_texto_cat != VARIOS

    if sub_norm in SUBCATEGORIA_V2_A_V3:
        categoria, subcategoria = SUBCATEGORIA_V2_A_V3[sub_norm]
        if categoria == VARIOS and texto_es_confiable:
            return por_texto_cat, por_texto_sub
        if categoria and subcategoria:
            return categoria, subcategoria
        if categoria:
            # El rubro lo decide la v2; el subrubro sale del texto, pero solo
            # si el texto coincide con ese rubro -- si no, quedaría un
            # subrubro colgado de un rubro que no es el suyo.
            return categoria, (por_texto_sub if por_texto_cat == categoria else None)
        # Subcategoría ambigua ("Válvulas y actuadores" puede ser de freno o
        # de embrague): manda el texto, y si el texto no dijo nada, el rubro.
        if texto_es_confiable or not categoria_v2_traducida:
            return por_texto_cat, por_texto_sub
        return categoria_v2_traducida, None

    if categoria_v2_traducida:
        return categoria_v2_traducida, (
            por_texto_sub if por_texto_cat == categoria_v2_traducida else None
        )
    return por_texto_cat, por_texto_sub


def verificar_taxonomia(categorias_validas, subcategorias_validas):
    """Devuelve los nombres que este módulo usa y la base no tiene.

    `subcategorias_validas` es el dict {categoría: [subcategorías]} de la
    base. Existe para que un renombre de rubro en una migración explote en un
    test y no en medio de una carga de 200.000 filas.
    """
    problemas = []
    destinos = set()
    for _, categoria, subcategoria in REGLAS_COMPILADAS:
        destinos.add((categoria, subcategoria))
    for categoria, subcategoria in SUBCATEGORIA_V2_A_V3.values():
        if categoria:
            destinos.add((categoria, subcategoria))
    for categoria in CATEGORIA_V2_A_V3.values():
        if categoria:
            destinos.add((categoria, None))

    for categoria, subcategoria in sorted(destinos, key=lambda x: (x[0] or "", x[1] or "")):
        if categoria not in categorias_validas:
            problemas.append(f"categoría inexistente: {categoria!r}")
        elif subcategoria and subcategoria not in subcategorias_validas.get(categoria, []):
            problemas.append(f"subcategoría inexistente: {categoria!r} / {subcategoria!r}")
    return problemas
