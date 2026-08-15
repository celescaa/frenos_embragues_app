"""
Conexión y helpers de datos para el sistema de gestión de ventas de frenos y
embragues, sobre Postgres.

El esquema (creación de tablas) y sus migraciones ya no viven acá: pasaron a
`supabase/migrations/` (ver Tarea 2 y 4 del plan de migración a Postgres).
Este módulo ya no crea ni migra nada — solo abre conexiones y expone los
helpers de consulta/siembra de datos de ejemplo que usa el resto del
sistema.
"""
import os
import random
import secrets
import string
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

# Cadena de conexión. En desarrollo apunta al Postgres local que levanta
# `npx supabase start`; en producción, al pooler de Supabase.
#
# El puerto es 54422, no el 54322 que la CLI de Supabase usa por defecto: ese
# default es idéntico para cualquier proyecto, así que dos proyectos locales de
# la misma persona se pelean por él (pasó dos veces con `hogar-gestion`). Los
# puertos de este proyecto están corridos +100 en supabase/config.toml.
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@127.0.0.1:54422/postgres",
)

# El negocio está en Ituzaingó, provincia de Buenos Aires. "Hoy" es el día
# ACÁ, no donde corra el servidor.
TZ_NEGOCIO = ZoneInfo("America/Argentina/Buenos_Aires")

# Lo mismo, para usar del lado de Postgres. Sirve para comparar contra
# columnas DATE dentro de una consulta sin tener que pasar la fecha como
# parámetro: así el criterio de "hoy" es uno solo, escrito en un solo lugar.
HOY_SQL = "(now() AT TIME ZONE 'America/Argentina/Buenos_Aires')::date"


def hoy():
    """La fecha de hoy para el negocio, en Argentina.

    Existe porque `datetime.now()` devuelve la hora local del servidor, y eso
    dejó de ser Argentina al desplegar en Vercel, que corre en UTC — tres
    horas adelante. Con `datetime.now()`, a partir de las 21:00 hora argentina
    el sistema empieza a fechar todo con el día siguiente: una venta cargada a
    las 21:30 no aparece en las ventas del día, una promoción creada a esa
    hora no se aplica hasta mañana, y el total del mes cambia de mes tres
    horas antes. Ninguno de esos casos tira un error; simplemente dan números
    equivocados.
    """
    return datetime.now(TZ_NEGOCIO).date()


def get_connection():
    """Conexión a Postgres.

    dict_row: las filas se acceden por nombre (venta["fecha"]), igual que con
    sqlite3.Row — por eso ningún template necesitó cambiar.

    prepare_threshold=None: OBLIGATORIO. En producción esto sale por el pooler
    de Supabase en modo transacción, que NO soporta prepared statements, y
    psycopg los activa solo a partir de la quinta ejecución de una consulta.
    Sin esta línea el sistema funciona al principio y empieza a fallar
    después, que es de los bugs más difíciles de diagnosticar.
    """
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        prepare_threshold=None,
    )


# Categorías del catálogo (local y tienda online). Ya NO es la lista fija:
# viven en la tabla `categorias`, editable desde /categorias. Esta lista es
# el dato de siembra inicial, cargado ahora vía
# supabase/migrations/20260813145208_esquema_inicial.sql (antes lo hacía
# _sembrar_categorias, en Python, eliminada en la Tarea 4 de la migración a
# Postgres porque correr eso en cada arranque en frío no tiene sentido en
# serverless). Se conserva acá como dato de referencia y porque
# scripts/importar_datos.py todavía la usa junto con CATEGORIAS_RENOMBRADAS
# para validar la categoría de cada fila.
CATEGORIAS_INICIALES = [
    "Frenos", "Suspensión", "Dirección", "Motor",
    "Encendido y Eléctrico", "Embrague", "Ferretería", "Varios",
]

# Cajón de sastre: la categoría a la que cae un producto cuyo rubro no se
# pudo reconocer (importador, alta rápida, limpieza de listas de proveedor).
# Estaba escrita como "Otros" en cinco lugares distintos y hubo que tocarlos
# todos al renombrarla a "Varios" en la taxonomía v3; que viva acá evita la
# próxima ronda de lo mismo.
CATEGORIA_CAJON_DE_SASTRE = "Varios"

# Subcategorías iniciales por categoría. Mismo criterio que
# CATEGORIAS_INICIALES de arriba: el dato de siembra en sí vive en la
# migración de Supabase (20260815120000_taxonomia_v3_rubros_del_negocio.sql),
# esto queda como referencia y como fuente de la resiembra que hace la suite
# de tests entre caso y caso.
#
# Los nombres van tal cual los escribió el negocio, con sus comas y sus
# paréntesis adentro ("Cazoletas, crapodinas"). No se normalizaron a propósito:
# son las palabras del mostrador, y el buscador ya ignora mayúsculas y acentos.
SUBCATEGORIAS_INICIALES = {
    "Frenos": [
        "Pastillas de freno", "Discos de freno", "Cintas de freno",
        "Cilindros (bomba freno, cilindros de rueda)", "Servofreno",
        "Cables de freno (mano)",
        # Sumados en 20260815130000: la lista original no tenía dónde poner
        # estas piezas, que el local vende igual.
        "Campanas de freno", "Zapatas de freno", "Mangueras y flexibles",
        "Sensores de desgaste", "Seguros antirruido", "Líquido de frenos",
    ],
    "Suspensión": [
        "Amortiguadores", "Bieletas", "Barras de torsión y estabilizadoras",
        "Bujes", "Cazoletas, crapodinas",
        "Contrapesos, soportes de suspensión", "Resortes / espirales",
        # Rodamientos y mazas no quedaron como rubro propio en la lista
        # nueva; van acá, que es el sistema del que forman parte.
        "Mazas de rueda", "Rodamientos y rulemanes",
    ],
    "Dirección": [
        "Brazos de dirección", "Cajas de dirección", "Columnas de dirección",
        "Terminales / rótulas", "Cremalleras",
    ],
    "Motor": [
        "Bomba de agua", "Cadenas de distribución",
        "Correas (distribución, alternador, etc.)", "Juntas y empaquetaduras",
        "Retenes",
    ],
    "Encendido y Eléctrico": [
        "Baterías", "Bobinas", "Bujías", "Bujías precalentadoras (diesel)",
        "Cables de bujía", "Motores de arranque / alternadores",
    ],
    "Embrague": [
        "Kits de embrague (disco + plato + collarín)",
        "Collarines / rulemanes de embrague",
        # Una bomba de embrague o un volante bimasa no son ninguna de las
        # dos de arriba.
        "Bombas y cilindros de embrague", "Volantes bimasa",
    ],
    "Ferretería": ["Arandelas", "Bulones", "Tornillos", "Tuercas"],
    "Varios": [
        "Abrazaderas", "Terminales, conectores varios",
        "Repuestos chicos sin categoría propia",
    ],
}

# Nombres de categoría que quedaron en el camino -> su equivalente de hoy.
# Sirve para dos cosas: actualizar productos ya cargados, y que el importador
# siga aceptando una planilla completada con un desplegable viejo. Cada
# entrada corresponde a un renombre que ya hizo alguna migración:
#   Freno/Embrague/Otro -> plural (taxonomía v1)
#   Embragues -> Embrague, Otros -> Varios (taxonomía v3, la actual)
CATEGORIAS_RENOMBRADAS = {
    "Freno": "Frenos",
    "Embrague": "Embrague",
    "Embragues": "Embrague",
    "Otro": CATEGORIA_CAJON_DE_SASTRE,
    "Otros": CATEGORIA_CAJON_DE_SASTRE,
}


def obtener_categorias(conn=None, solo_activas=True):
    """Nombres de categorías cargadas en la tabla `categorias`, para
    dropdowns y validación. Si no se pasa una conexión abierta, abre y
    cierra una propia."""
    conn_propia = conn is None
    if conn_propia:
        conn = get_connection()
    consulta = "SELECT nombre FROM categorias"
    if solo_activas:
        consulta += " WHERE activo = true"
    consulta += " ORDER BY nombre"
    nombres = [r["nombre"] for r in conn.execute(consulta)]
    if conn_propia:
        conn.close()
    return nombres


def obtener_subcategorias(conn=None, categoria_id=None, solo_activas=True):
    """Subcategorías cargadas, opcionalmente filtradas a una categoría
    puntual. Devuelve filas completas (id, nombre, categoria_id, activo,
    categoria_nombre) para poder armar tanto dropdowns como el JSON de
    cascada categoría->subcategoría."""
    conn_propia = conn is None
    if conn_propia:
        conn = get_connection()
    consulta = """SELECT s.*, c.nombre AS categoria_nombre FROM subcategorias s
                  JOIN categorias c ON c.id = s.categoria_id"""
    condiciones, params = [], []
    if categoria_id:
        condiciones.append("s.categoria_id = %s")
        params.append(categoria_id)
    if solo_activas:
        condiciones.append("s.activo = true")
    if condiciones:
        consulta += " WHERE " + " AND ".join(condiciones)
    consulta += " ORDER BY c.nombre, s.nombre"
    filas = conn.execute(consulta, params).fetchall()
    if conn_propia:
        conn.close()
    return filas


def obtener_vehiculos(conn=None, solo_activos=True):
    """Autos cargados, para el desplegable del filtro y para vincularlos a un
    producto. Mismo patrón que obtener_categorias(): si no se pasa una
    conexión abierta, abre y cierra una propia."""
    conn_propia = conn is None
    if conn_propia:
        conn = get_connection()
    consulta = "SELECT * FROM vehiculos"
    if solo_activos:
        consulta += " WHERE activo = true"
    consulta += " ORDER BY marca_auto, modelo, motor"
    filas = conn.execute(consulta).fetchall()
    if conn_propia:
        conn.close()
    return filas


# Campos de `productos` sobre los que busca el texto libre, concatenados y
# normalizados. La expresión coincide con la del índice `productos_texto_trgm`
# de la migración, pero eso NO alcanza para que el índice se use: la
# condición real de más abajo la combina con `OR p.codigo_barras = %s OR
# {TEXTO_VEHICULOS_SQL}`, y un OR con un EXISTS no es indexable — Postgres
# recorre la tabla entera (visto con EXPLAIN sobre 3.000 productos: Seq Scan,
# el índice nunca aparece en el plan). El índice sí sirve para
# `marcas_nombre_normalizado`. Si algún día hace falta que esta búsqueda use
# el índice trigram, hay que sacar el EXISTS del OR: resolver los ids que
# matchean por auto en una consulta aparte y meterlos como `p.id = ANY(%s)`.
TEXTO_PRODUCTO_SQL = """texto_busqueda(
    coalesce(p.nombre, '') || ' ' || coalesce(p.codigo, '') || ' ' ||
    coalesce(p.marca, '') || ' ' || coalesce(p.modelo_compatible, '')
)"""

# Lo mismo para los autos vinculados, para que escribir "palio" encuentre un
# producto que no dice "Palio" en ninguno de sus campos pero está vinculado
# a un Palio. Incluye el motor: el desplegable y /vehiculos muestran el auto
# como "FIAT Palio 1.4", así que si alguien copia ese texto al buscador, la
# palabra del motor tiene que matchear igual que la marca y el modelo — si
# no, esa palabra no aparece en ningún campo y la búsqueda se vacía.
TEXTO_VEHICULOS_SQL = """EXISTS (
    SELECT 1 FROM producto_vehiculos pv JOIN vehiculos v ON v.id = pv.vehiculo_id
    WHERE pv.producto_id = p.id
      AND texto_busqueda(v.marca_auto || ' ' || v.modelo || ' ' || v.motor) LIKE '%%' || texto_busqueda(%s) || '%%'
)"""


# Parecido mínimo (0 a 1) para dar por buena una palabra mal escrita.
# Medido contra casos reales de mostrador: "bugia" contra "bujia ngk ..." da
# 0.333 y "enbrague" contra "kit embrague ..." da 0.556, mientras que una
# palabra que no tiene nada que ver ("bugia" contra "disco de freno") da 0.
# Subirlo deja sin rescate el error de una sola letra, que es el más común.
UMBRAL_PALABRA_PARECIDA = 0.3

# Largo mínimo para que una palabra se busque por parecido. Con tres letras
# el parecido deja de discriminar: "gol" da 0.75 contra "golpe" y 0.5 contra
# "goma", así que perdonarle errores a una palabra corta convierte cualquier
# búsqueda en un cajón de cosas al azar. Las cortas se buscan exactas nomás.
LARGO_MINIMO_PARECIDO = 4


def _condiciones_busqueda(q=None, categoria=None, subcategoria=None, marca=None,
                          vehiculo_id=None, solo_con_stock=False, excluir=(),
                          difuso=()):
    """Arma el WHERE compartido por buscar_productos() y facetas_productos().

    `excluir` nombra filtros a NO aplicar: los contadores de cada filtro se
    calculan sin aplicarse a sí mismos, para que digan cuántos productos
    habría si el usuario cambiara de opción (si no, el filtro elegido siempre
    mostraría su propio total y el resto en cero).

    `difuso` es el conjunto de palabras a las que se les permite matchear
    por parecido, además de exacto. Vacío (el default) = búsqueda exacta.
    Quién decide ese conjunto es buscar_productos_tolerante(); ver ahí por
    qué no son todas las palabras de la búsqueda.
    """
    condiciones, params = [], []

    # Cada palabra por separado, en cualquier orden: alguien que busca
    # "palio pastilla" tiene que encontrar "PASTILLA DE FRENO FIAT PALIO".
    # Se compara sobre texto ya normalizado con LIKE (no ILIKE): ILIKE sobre
    # la columna cruda no podría usar el índice trigram. El patrón se arma
    # en SQL con texto_busqueda(%s), no en Python: normalizar la palabra con
    # .lower() de este lado saca las mayúsculas pero no los acentos, y
    # texto_busqueda() sí los saca, así que los dos lados quedaban
    # normalizados distinto y buscar escribiendo el acento no encontraba
    # nada.
    for palabra in (q or "").split():
        alternativas = [
            f"{TEXTO_PRODUCTO_SQL} LIKE '%%' || texto_busqueda(%s) || '%%'",
            # El código de barras matchea EXACTO, nunca por parecido: es lo
            # que dispara la pistola y un match aproximado sería cargar el
            # producto equivocado en la venta. Por eso queda afuera del
            # bloque difuso de más abajo.
            "p.codigo_barras = %s",
            TEXTO_VEHICULOS_SQL,
        ]
        params += [palabra, palabra, palabra]

        if palabra in difuso:
            # word_similarity() y no similarity(): compara la palabra tipeada
            # contra el mejor tramo del texto del producto, no contra el texto
            # entero. Con el nombre completo, una descripción larga diluye el
            # parecido de una palabra sola muy por debajo del umbral aunque la
            # palabra que importa matchee casi perfecto. Mismo criterio que
            # sugerencias_busqueda(), más abajo.
            alternativas.append(
                f"word_similarity(texto_busqueda(%s), {TEXTO_PRODUCTO_SQL}) >= %s"
            )
            params += [palabra, UMBRAL_PALABRA_PARECIDA]

        condiciones.append("(" + " OR ".join(alternativas) + ")")

    if categoria and "categoria" not in excluir:
        condiciones.append("p.categoria = %s")
        params.append(categoria)
    if subcategoria and "subcategoria" not in excluir:
        condiciones.append("p.subcategoria = %s")
        params.append(subcategoria)
    if marca and "marca" not in excluir:
        condiciones.append("texto_busqueda(p.marca) = texto_busqueda(%s)")
        params.append(marca)
    if vehiculo_id and "vehiculo_id" not in excluir:
        condiciones.append(
            "EXISTS (SELECT 1 FROM producto_vehiculos pv "
            "WHERE pv.producto_id = p.id AND pv.vehiculo_id = %s)"
        )
        params.append(vehiculo_id)
    if solo_con_stock:
        condiciones.append("p.stock_actual > 0")

    return condiciones, params


def buscar_productos(conn, q=None, categoria=None, subcategoria=None, marca=None,
                     vehiculo_id=None, solo_con_stock=False, limite=None,
                     difuso=()):
    """Punto único de búsqueda de productos del sistema.

    Antes este criterio estaba escrito tres veces (la pantalla de Stock, el
    JSON del buscador tipo autocompletar y el catálogo de la tienda) y ya
    habían divergido entre sí. Cualquier pantalla que busque productos llama
    acá: si no, vuelve a haber una pantalla que busca mejor que otra.

    Es EXACTA por default. Para perdonar errores de tipeo hay que llamar a
    buscar_productos_tolerante(), que la usa a ella por debajo.
    """
    condiciones, params = _condiciones_busqueda(
        q, categoria, subcategoria, marca, vehiculo_id, solo_con_stock,
        difuso=difuso,
    )
    consulta = "SELECT p.* FROM productos p"
    if condiciones:
        consulta += " WHERE " + " AND ".join(condiciones)
    consulta += " ORDER BY p.categoria, p.nombre"
    if limite:
        consulta += " LIMIT %s"
        params = params + [limite]
    return conn.execute(consulta, params).fetchall()


def _palabras_a_perdonar(conn, q):
    """De lo que se escribió, qué palabras conviene buscar por parecido.

    Sólo las que no aparecen tal cual en NINGÚN producto del catálogo. Una
    palabra que sí existe está bien escrita, y aflojarla de todos modos
    arruina la búsqueda: con "pastila palio", perdonarle el "palio" (que
    existe) traía además las pastillas de Gol y de Onix, que es justo cómo
    alguien termina llevándose la pieza de otro auto.

    Las palabras de menos de LARGO_MINIMO_PARECIDO nunca se perdonan, aunque
    no existan: son demasiado cortas para que el parecido signifique algo.
    """
    a_perdonar = set()
    for palabra in set(q.split()):
        if len(palabra) < LARGO_MINIMO_PARECIDO:
            continue
        existe = conn.execute(
            f"""SELECT EXISTS (
                    SELECT 1 FROM productos p
                    WHERE {TEXTO_PRODUCTO_SQL} LIKE '%%' || texto_busqueda(%s) || '%%'
                       OR p.codigo_barras = %s
                       OR {TEXTO_VEHICULOS_SQL}
                ) AS existe""",
            (palabra, palabra, palabra),
        ).fetchone()["existe"]
        if not existe:
            a_perdonar.add(palabra)
    return a_perdonar


def buscar_productos_tolerante(conn, q=None, **filtros):
    """Igual que buscar_productos(), pero perdona errores de tipeo.

    Devuelve `(filas, difusas)`, donde `difusas` es el conjunto de palabras
    que hubo que buscar por parecido -- vacío si alcanzó con la búsqueda
    exacta. La pantalla lo usa para dos cosas: avisarle a la persona que lo
    que ve no es literal lo que escribió, y pedir los contadores de los
    filtros con el mismo criterio con el que se buscó.

    Son DOS intentos, no uno con el parecido siempre prendido, y el orden es
    lo que hace que funcione:

    1. Exacto. Si encuentra algo, listo.
    2. Recién si vino vacío, de nuevo perdonando SÓLO las palabras que no
       existen en el catálogo (ver _palabras_a_perdonar).

    Buscar siempre por parecido ensuciaría las búsquedas bien escritas:
    "bujia" tiene 0.333 de parecido con "Buje de parrilla", así que quien
    escribe bien terminaría viendo bujes entre las bujías. Con el parecido
    como segundo intento, escribir bien devuelve exactamente lo pedido y
    escribir mal ("bugia gol") igual encuentra las bujías de Gol en vez de
    dejar la pantalla vacía.
    """
    filas = buscar_productos(conn, q=q, **filtros)
    if filas or not q:
        return filas, set()

    a_perdonar = _palabras_a_perdonar(conn, q)
    if not a_perdonar:
        # No hay nada que aflojar: repetir la consulta daría el mismo vacío.
        return filas, set()

    return buscar_productos(conn, q=q, difuso=a_perdonar, **filtros), a_perdonar


# Parecido mínimo (0 a 1) para ofrecer una sugerencia. 0.3 es el default
# histórico de pg_trgm y tolera un par de letras cambiadas ("pastila" ->
# "pastilla") sin ofrecer cualquier cosa. Subirlo deja sin sugerencia
# errores reales; bajarlo sugiere productos que no tienen nada que ver.
UMBRAL_SUGERENCIA = 0.3


def sugerencias_busqueda(conn, q, limite=5):
    """Nombres parecidos a lo que se escribió, para cuando la búsqueda no
    devuelve nada. Es una sugerencia que se le muestra al usuario, NO un
    reemplazo automático: no se le cambia a alguien lo que buscó sin avisarle.

    Usa word_similarity() en vez de similarity(): similarity() compara las
    dos cadenas completas, así que un nombre de producto largo ("Pastilla de
    freno delantera") diluye el parecido de una palabra sola tipeada con
    error ("pastila") muy por debajo de 0.3 aunque la palabra que importa
    matchee casi perfecto. word_similarity() busca el mejor tramo delimitado
    por palabra dentro del nombre completo, que es el caso real de mostrador
    (el cliente escribe una palabra, no el nombre entero del producto).
    """
    texto = (q or "").strip()
    if not texto:
        return []
    filas = conn.execute(
        """SELECT p.nombre,
                  word_similarity(texto_busqueda(%s), texto_busqueda(p.nombre)) AS parecido
           FROM productos p
           WHERE word_similarity(texto_busqueda(%s), texto_busqueda(p.nombre)) >= %s
           ORDER BY parecido DESC, p.nombre
           LIMIT %s""",
        (texto, texto, UMBRAL_SUGERENCIA, limite),
    ).fetchall()
    return [f["nombre"] for f in filas]


# Las tres dimensiones que llevan contador al lado de cada opción. El auto no
# lleva contador: la lista de vehículos puede ser larga y el contador exigiría
# una consulta por vehículo cargado.
DIMENSIONES_FACETAS = ["categoria", "subcategoria", "marca"]


def facetas_productos(conn, q=None, categoria=None, subcategoria=None, marca=None,
                      vehiculo_id=None, solo_con_stock=False, difuso=()):
    """Cuántos productos hay en cada opción de cada filtro, para mostrarlo al
    lado (`Frenos (128)`), más el total que cumple TODOS los filtros.

    Cada dimensión se cuenta SIN aplicar su propio filtro: si al elegir Frenos
    el contador de Embragues cayera a cero, el usuario no podría ver que hay
    otra opción con productos y quedaría encerrado en su propia elección.

    `difuso` tiene que venir con el MISMO valor que usó la búsqueda que se
    está mostrando (lo devuelve buscar_productos_tolerante). Si no, los
    contadores cuentan un conjunto y la tabla muestra otro: la pantalla
    diría "Frenos (0)" arriba de una lista con frenos adentro.
    """
    filtros = dict(q=q, categoria=categoria, subcategoria=subcategoria,
                   marca=marca, vehiculo_id=vehiculo_id,
                   solo_con_stock=solo_con_stock, difuso=difuso)

    condiciones, params = _condiciones_busqueda(**filtros)
    consulta = "SELECT count(*) AS n FROM productos p"
    if condiciones:
        consulta += " WHERE " + " AND ".join(condiciones)
    resultado = {"total": conn.execute(consulta, params).fetchone()["n"]}

    for dimension in DIMENSIONES_FACETAS:
        condiciones, params = _condiciones_busqueda(**filtros, excluir=(dimension,))
        if dimension == "marca":
            # Agrupado por texto normalizado, no por la columna p.marca cruda:
            # el catálogo real sale de listas de precios de proveedores con
            # la misma marca escrita distinto (COBREQ / Cobreq / cobreq).
            # Agrupar por la columna cruda mostraba esa marca tres veces en
            # el desplegable, cada una con su propio contador de 1, aunque
            # el filtro de marca (más abajo) ya comparaba normalizado y
            # devolvía las tres al elegir cualquiera. min(btrim(...)) elige
            # una grafía cualquiera de display para el grupo; cuál de las
            # tres queda no importa, lo que importa es que sea una sola.
            consulta = "SELECT min(btrim(p.marca)) AS valor, count(*) AS n FROM productos p"
            if condiciones:
                consulta += " WHERE " + " AND ".join(condiciones)
            consulta += " GROUP BY texto_busqueda(p.marca)"
        else:
            consulta = f"SELECT p.{dimension} AS valor, count(*) AS n FROM productos p"
            if condiciones:
                consulta += " WHERE " + " AND ".join(condiciones)
            consulta += f" GROUP BY p.{dimension}"
        resultado[dimension] = {
            fila["valor"]: fila["n"]
            for fila in conn.execute(consulta, params).fetchall()
            if fila["valor"]  # los productos sin subcategoría/marca no son una opción
        }
    return resultado


def obtener_cotizaciones_producto(conn, producto_id):
    """Cotizaciones de proveedores activos para un producto, de menor a
    mayor precio_costo. Es la fuente única del criterio de "mejor precio"
    que usan tanto /pedidos (agrupa por el proveedor más conveniente) como
    la columna "Mejor precio" de /productos — no duplicar esta consulta en
    los dos lugares."""
    return conn.execute(
        """SELECT pp.precio_costo, pp.codigo_proveedor, pr.id AS proveedor_id, pr.nombre AS proveedor_nombre,
                  pr.email AS proveedor_email, pr.telefono AS proveedor_telefono
           FROM producto_proveedor pp JOIN proveedores pr ON pr.id = pp.proveedor_id
           WHERE pp.producto_id = %s AND pr.activo = true ORDER BY pp.precio_costo ASC""",
        (producto_id,),
    ).fetchall()


def obtener_mejor_precio_por_producto(conn, producto_id):
    """La cotización más barata de un producto (ver obtener_cotizaciones_producto
    de arriba), o None si no hay ninguna cargada."""
    cotizaciones = obtener_cotizaciones_producto(conn, producto_id)
    return cotizaciones[0] if cotizaciones else None


def _generar_password_temporal(largo=10):
    alfabeto = string.ascii_letters + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(largo))


def seed_demo_data(conn):
    """Carga datos de ejemplo solo si la base está vacía. Antes abría su
    propia conexión (`seed_demo_data()`); ahora la recibe, para poder
    correr dentro de la transacción de un test o de un script que ya tenga
    una abierta."""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM productos")
    if cur.fetchone()["c"] > 0:
        return  # ya hay datos, no pisar nada

    hoy = datetime.now()

    proveedores = [
        ("Frenos del Sur SA", "0341-4550022", "ventas@frenosdelsur.com", "Rosario, Santa Fe", "30-71234567-8"),
        ("Embragues Rosario SRL", "0341-4551133", "info@embraguesrosario.com", "Rosario, Santa Fe", "30-70987654-3"),
        ("Distribuidora Autopartes Litoral", "0341-4559900", "contacto@dal.com.ar", "Rosario, Santa Fe", "30-69876543-2"),
    ]
    # Uno por uno (no executemany) para capturar el id real que les asigna
    # Postgres: a diferencia del rowid de SQLite, la secuencia de un
    # IDENTITY no es transaccional, así que no se puede asumir que van a
    # quedar en 1/2/3 acá (por ejemplo, si este mismo seed ya corrió antes
    # en una transacción que se revirtió, la secuencia ya avanzó).
    # id_proveedor[i] es el id real del proveedor que antes se
    # referenciaba como el entero i+1 en `productos` de abajo.
    id_proveedor = [
        cur.execute(
            "INSERT INTO proveedores (nombre, telefono, email, direccion, cuit) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            p,
        ).fetchone()["id"]
        for p in proveedores
    ]

    clientes = [
        ("Juan Pérez", "341-5551234", "juanperez@gmail.com", "Av. Pellegrini 1200", "20-30111222-3"),
        ("Transporte Cargas del Litoral", "341-5559876", "administracion@cargaslitoral.com", "Ruta 9 Km 12", "30-65432198-7"),
        ("María Gómez", "341-5556655", "mariagomez@hotmail.com", "Bv. Oroño 850", "27-28999123-4"),
        ("Taller Mecánico El Rápido", "341-5552211", "elrapido.taller@gmail.com", "San Martín 2300", "30-71122334-5"),
        ("Carlos Fernández", "341-5558877", "", "Córdoba 3400", ""),
    ]
    cur.executemany(
        "INSERT INTO clientes (nombre, telefono, email, direccion, cuit_dni, fecha_alta) VALUES (%s, %s, %s, %s, %s, %s)",
        [(n, t, e, d, c, hoy.strftime("%Y-%m-%d")) for n, t, e, d, c in clientes],
    )

    productos = [
        ("FR-001", "Juego de pastillas de freno delanteras", "Frenos", "Bosch", "VW Gol / Voyage", Decimal("8500.00"), Decimal("14900.00"), 18, 5, id_proveedor[0]),
        ("FR-002", "Juego de pastillas de freno traseras", "Frenos", "Bosch", "VW Gol / Voyage", Decimal("7200.00"), Decimal("12500.00"), 14, 5, id_proveedor[0]),
        ("FR-003", "Disco de freno delantero ventilado", "Frenos", "Fremax", "Fiat Cronos", Decimal("12500.00"), Decimal("21900.00"), 10, 4, id_proveedor[0]),
        ("FR-004", "Disco de freno trasero macizo", "Frenos", "Fremax", "Fiat Cronos", Decimal("9800.00"), Decimal("16900.00"), 3, 4, id_proveedor[0]),
        ("FR-005", "Cilindro maestro de freno", "Frenos", "TRW", "Chevrolet Onix", Decimal("15400.00"), Decimal("26900.00"), 6, 2, id_proveedor[0]),
        ("FR-006", "Cañería de freno flexible", "Frenos", "TRW", "Universal", Decimal("3200.00"), Decimal("6200.00"), 25, 6, id_proveedor[0]),
        ("FR-007", "Líquido de frenos DOT 4 (500ml)", "Líquidos", "Bosch", "Universal", Decimal("2100.00"), Decimal("4200.00"), 40, 10, id_proveedor[0]),
        ("EMB-001", "Kit de embrague completo (disco+plato+collarín)", "Embragues", "Luk", "VW Gol / Voyage", Decimal("42000.00"), Decimal("68900.00"), 8, 3, id_proveedor[1]),
        ("EMB-002", "Kit de embrague completo", "Embragues", "Sachs", "Fiat Cronos / Argo", Decimal("45500.00"), Decimal("74900.00"), 5, 3, id_proveedor[1]),
        ("EMB-003", "Collarín hidráulico", "Embragues", "Luk", "Chevrolet Onix / Prisma", Decimal("18700.00"), Decimal("31900.00"), 2, 3, id_proveedor[1]),
        ("EMB-004", "Cable de embrague", "Embragues", "Fremax", "Renault Kangoo", Decimal("5600.00"), Decimal("9900.00"), 12, 5, id_proveedor[1]),
        ("EMB-005", "Bomba de embrague hidráulica", "Embragues", "Sachs", "Ford Ka", Decimal("21300.00"), Decimal("35900.00"), 4, 3, id_proveedor[1]),
        ("COR-001", "Correa de distribución", "Correas", "Gates", "VW Gol / Voyage", Decimal("6800.00"), Decimal("11900.00"), 15, 5, id_proveedor[2]),
        ("COR-002", "Correa poly-V (accesorios)", "Correas", "Gates", "Fiat Cronos / Argo", Decimal("4200.00"), Decimal("7900.00"), 20, 5, id_proveedor[2]),
        ("OTR-001", "Kit de fijación de disco de freno", "Otros", "Genérico", "Universal", Decimal("900.00"), Decimal("1900.00"), 30, 10, id_proveedor[2]),
        ("OTR-002", "Grasa para embrague/frenos (pomo)", "Otros", "Genérico", "Universal", Decimal("1500.00"), Decimal("2900.00"), 20, 8, id_proveedor[2]),
    ]
    cur.executemany(
        """INSERT INTO productos
           (codigo, nombre, categoria, marca, modelo_compatible, precio_costo, precio_venta, stock_actual, stock_minimo, proveedor_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        productos,
    )

    # Algunos productos con cotizaciones de más de un proveedor, para mostrar
    # el comparador de precios (a quién le conviene comprarle cada producto).
    cotizaciones = [
        ("FR-001", "Frenos del Sur SA", Decimal("8500.00"), "BOS-4501"),
        ("FR-001", "Distribuidora Autopartes Litoral", Decimal("8100.00"), "DAL-9012"),
        ("FR-003", "Frenos del Sur SA", Decimal("12500.00"), "FRX-2201"),
        ("FR-003", "Distribuidora Autopartes Litoral", Decimal("12900.00"), "DAL-2202"),
        ("EMB-001", "Embragues Rosario SRL", Decimal("42000.00"), "LUK-7701"),
        ("EMB-001", "Distribuidora Autopartes Litoral", Decimal("43500.00"), "DAL-7701"),
    ]
    for codigo, proveedor_nombre, precio, codigo_prov in cotizaciones:
        producto = cur.execute("SELECT id FROM productos WHERE codigo=%s", (codigo,)).fetchone()
        proveedor = cur.execute("SELECT id FROM proveedores WHERE nombre=%s", (proveedor_nombre,)).fetchone()
        if producto and proveedor:
            cur.execute(
                """INSERT INTO producto_proveedor (producto_id, proveedor_id, precio_costo, codigo_proveedor)
                   VALUES (%s, %s, %s, %s)""",
                (producto["id"], proveedor["id"], precio, codigo_prov),
            )

    # Ventas de ejemplo de los últimos ~4 meses, para que el dashboard tenga datos
    cur.execute("SELECT id, precio_venta FROM productos")
    productos_db = cur.fetchall()
    cur.execute("SELECT id FROM clientes")
    clientes_ids = [r["id"] for r in cur.fetchall()]

    random.seed(7)
    for i in range(45):
        dias_atras = random.randint(0, 120)
        fecha = (hoy - timedelta(days=dias_atras)).strftime("%Y-%m-%d")
        cliente_id = random.choice(clientes_ids)
        metodo = random.choice(["Efectivo", "Transferencia", "Tarjeta"])
        tipo = random.choice(["Remito", "Recibo"])
        n_items = random.randint(1, 3)
        elegidos = random.sample(productos_db, n_items)
        total = Decimal("0")
        venta_id = cur.execute(
            "INSERT INTO ventas (fecha, cliente_id, total, metodo_pago, tipo_comprobante, numero_comprobante) VALUES (%s, %s, 0, %s, %s, %s) RETURNING id",
            (fecha, cliente_id, metodo, tipo, f"{1000+i:06d}"),
        ).fetchone()["id"]
        for prod in elegidos:
            cantidad = random.randint(1, 4)
            subtotal = cantidad * prod["precio_venta"]
            total += subtotal
            cur.execute(
                "INSERT INTO venta_items (venta_id, producto_id, cantidad, precio_unitario, subtotal) VALUES (%s, %s, %s, %s, %s)",
                (venta_id, prod["id"], cantidad, prod["precio_venta"], subtotal),
            )
        cur.execute("UPDATE ventas SET total = %s WHERE id = %s", (total, venta_id))


if __name__ == "__main__":
    _conn = get_connection()
    try:
        seed_demo_data(_conn)
        _conn.commit()
    finally:
        _conn.close()
    print("Datos de ejemplo cargados en:", DATABASE_URL)
