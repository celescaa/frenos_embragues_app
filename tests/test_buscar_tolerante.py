"""El mostrador escribe con errores: "bugia" por "bujía", "enbrague" por
"embrague". Con la búsqueda exacta sola, esas consultas devuelven cero
resultados y el vendedor se queda sin saber si el producto existe.

`buscar_productos_tolerante()` agrega un segundo intento por parecido, pero
SÓLO cuando el exacto no encontró nada: mientras el exacto funcione, manda
él. Estos tests fijan las dos mitades de esa regla — que rescata el error de
tipeo, y que no ensucia la búsqueda bien escrita.
"""
import pytest
from core import database as db


@pytest.fixture
def catalogo(db_conn):
    """Catálogo chico pero con los vecinos peligrosos incluidos a propósito:
    "Buje de parrilla" se parece mucho a "bugia" por trigramas, y
    "Paragolpe" contiene "gol" adentro."""
    filas = [
        ("Bujía NGK BKR6E", "Encendido y Eléctrico", "Bujías", "NGK", "VW Gol 1.6"),
        ("Cable de bujía juego", "Encendido y Eléctrico", "Cables de bujía", "NGK", "VW Gol 1.6"),
        ("Bujía Bosch Super", "Encendido y Eléctrico", "Bujías", "Bosch", "FIAT Palio"),
        ("Kit de embrague", "Embrague", "Kits de embrague (disco + plato + collarín)", "Sachs", "VW Gol 1.6"),
        ("Collarín de embrague", "Embrague", "Collarines / rulemanes de embrague", "Sachs", "VW Gol"),
        ("Pastilla de freno delantera", "Frenos", "Pastillas de freno", "Cobreq", "VW Gol"),
        ("Buje de parrilla", "Suspensión", "Bujes", "VTH", "VW Gol"),
        ("Amortiguador golpe seco paragolpe", "Suspensión", "Amortiguadores", "Monroe", "VW Gol"),
    ]
    for nombre, categoria, subcategoria, marca, modelo in filas:
        db_conn.execute(
            """INSERT INTO productos
               (nombre, categoria, subcategoria, marca, modelo_compatible,
                stock_actual, precio_costo, precio_venta)
               VALUES (%s, %s, %s, %s, %s, 5, 100, 130)""",
            (nombre, categoria, subcategoria, marca, modelo),
        )


def nombres(resultado):
    filas, _ = resultado
    return sorted(f["nombre"] for f in filas)


# ---------------------------------------------------------------------------
# El caso que pidió el negocio, textual: "bugia gol" tiene que traer las
# bujías de Gol.
# ---------------------------------------------------------------------------
def test_bugia_gol_encuentra_las_bujias_de_gol(db_conn, catalogo):
    encontrados = nombres(db.buscar_productos_tolerante(db_conn, q="bugia gol"))
    assert "Bujía NGK BKR6E" in encontrados
    assert "Cable de bujía juego" in encontrados
    # La bujía de Palio no es de Gol: el error de tipeo se perdona, pero el
    # auto sigue filtrando.
    assert "Bujía Bosch Super" not in encontrados


def test_embrague_gol_encuentra_los_embragues_de_gol(db_conn, catalogo):
    encontrados = nombres(db.buscar_productos_tolerante(db_conn, q="embrague gol"))
    assert encontrados == ["Collarín de embrague", "Kit de embrague"]


def test_enbrague_con_ene_tambien_encuentra(db_conn, catalogo):
    assert "Kit de embrague" in nombres(
        db.buscar_productos_tolerante(db_conn, q="enbrague gol")
    )


# ---------------------------------------------------------------------------
# La otra mitad: escribir bien no puede salir peor que escribir mal.
# ---------------------------------------------------------------------------
def test_bien_escrito_no_arrastra_parecidos(db_conn, catalogo):
    """"bujia gol" está bien escrito, así que el intento exacto alcanza y el
    parecido no llega a correr. Sin esta regla, "Buje de parrilla" (0.333 de
    parecido contra "bujia") se colaría en una búsqueda correcta."""
    filas, difuso = db.buscar_productos_tolerante(db_conn, q="bujia gol")
    assert difuso == set()
    assert sorted(f["nombre"] for f in filas) == [
        "Bujía NGK BKR6E", "Cable de bujía juego",
    ]


def test_avisa_cuando_tuvo_que_usar_el_parecido(db_conn, catalogo):
    """El segundo valor del retorno es lo que la pantalla necesita para
    avisar "no encontré 'bugia', te muestro lo más parecido" — y para que los
    contadores de los filtros se calculen sobre el mismo conjunto."""
    _, difuso = db.buscar_productos_tolerante(db_conn, q="bugia gol")
    assert difuso


def test_solo_se_perdona_la_palabra_que_no_existe(db_conn, catalogo):
    """Con "pastila palio", "palio" existe en el catálogo (es un auto real) y
    "pastila" no. Perdonar las dos traía además las pastillas de Gol, que es
    justo cómo alguien se lleva la pieza de otro auto. Se afloja sólo la
    palabra que no existe."""
    filas, difuso = db.buscar_productos_tolerante(db_conn, q="pastila palio")
    assert difuso == {"pastila"}
    # No hay pastillas de Palio en este catálogo, y "palio" sigue filtrando en
    # serio: la pastilla de Gol NO puede colarse.
    assert [f["nombre"] for f in filas] == []


def test_sin_texto_nunca_es_difuso(db_conn, catalogo):
    filas, difuso = db.buscar_productos_tolerante(db_conn, categoria="Frenos")
    assert difuso == set()
    assert [f["nombre"] for f in filas] == ["Pastilla de freno delantera"]


# ---------------------------------------------------------------------------
# Los límites del perdón: una palabra corta y un disparate no se rescatan.
# ---------------------------------------------------------------------------
def test_palabra_corta_no_se_busca_por_parecido(db_conn, catalogo):
    """Una palabra de menos de 4 letras es demasiado ambigua para el parecido:
    "gol" da 0.75 contra "golpe" y 0.5 contra "goma". Rescatarla convertiría
    cualquier búsqueda corta fallida en un cajón de cosas al azar."""
    filas, difuso = db.buscar_productos_tolerante(db_conn, q="zzz")
    assert filas == []
    assert difuso == set()


def test_un_disparate_no_devuelve_cualquier_cosa(db_conn, catalogo):
    filas, _ = db.buscar_productos_tolerante(db_conn, q="heladera")
    assert filas == []


def test_el_parecido_respeta_los_demas_filtros(db_conn, catalogo):
    """El rescate por parecido no puede saltearse la categoría elegida."""
    filas, difuso = db.buscar_productos_tolerante(
        db_conn, q="bugia", categoria="Frenos"
    )
    assert difuso
    assert filas == []


# ---------------------------------------------------------------------------
# buscar_productos() sigue siendo exacto: es lo que usan el escaneo con
# pistola y el resto del sistema, donde un match aproximado sería cargar el
# producto equivocado en una venta.
# ---------------------------------------------------------------------------
def test_buscar_productos_sigue_siendo_exacto_por_default(db_conn, catalogo):
    assert db.buscar_productos(db_conn, q="bugia gol") == []


def test_el_codigo_de_barras_nunca_matchea_por_parecido(db_conn):
    db_conn.execute(
        """INSERT INTO productos (nombre, codigo_barras, categoria,
                                  stock_actual, precio_costo, precio_venta)
           VALUES ('Pastilla escaneable', '7791234567890', 'Frenos', 5, 100, 130)"""
    )
    # Un dígito cambiado no puede traer el producto: sería cobrar otra cosa.
    filas, _ = db.buscar_productos_tolerante(db_conn, q="7791234567891")
    assert filas == []
