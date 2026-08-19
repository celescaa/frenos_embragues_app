"""El clasificador decide en qué rubro entra cada uno de los ~200.000
productos de las listas de proveedores. Una regla mal ordenada no tira
ningún error: deja miles de filas en el rubro equivocado y eso recién se
nota cuando alguien busca un repuesto en el sistema y no aparece.

Los casos de acá son los que se rompieron de verdad mientras se armaba la
planilla, no ejemplos inventados."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from core import database as db
from scripts import clasificar_repuestos as cl


def test_los_rubros_que_usa_el_clasificador_existen_en_la_base():
    """El clasificador escribe los nombres de rubro y subrubro a mano, sin
    leer la base. Si una migración renombra uno, el desajuste hay que verlo
    acá y no en medio de una carga de 200.000 filas, donde el importador los
    mandaría en silencio al cajón de sastre."""
    problemas = cl.verificar_taxonomia(db.CATEGORIAS_INICIALES, db.SUBCATEGORIAS_INICIALES)
    assert problemas == [], "\n".join(problemas)


@pytest.mark.parametrize("texto,categoria,subcategoria", [
    # Lo específico le tiene que ganar a lo genérico: las dos palabras están
    # en la descripción y la pieza que se vende es la primera.
    ("CAZOLETA AMORTIGUADOR DELANTERA", "Suspensión", "Cazoletas, crapodinas"),
    ("CRAPODINA DE EMBRAGUE", "Embrague", "Collarines / rulemanes de embrague"),
    ("DISCO DE EMBRAGUE 215MM", "Embrague", "Kits de embrague (disco + plato + collarín)"),
    ("BUJES DE CALIPER CHEVROLET", "Frenos", None),
    # La misma palabra en dos sistemas distintos.
    ("BOMBA DE FRENO CORSA", "Frenos", "Cilindros (bomba freno, cilindros de rueda)"),
    ("CILINDRO MAESTRO DE EMBRAGUE", "Embrague", "Bombas y cilindros de embrague"),
    ("BOMBA AGUA RENAULT MEGANE", "Motor", "Bomba de agua"),
    ("CABLE DE ENCENDIDO", "Encendido y Eléctrico", "Cables de bujía"),
    ("CABLE FRENO DE MANO", "Frenos", "Cables de freno (mano)"),
    # En la taxonomía v3 las rótulas viven en Dirección aunque la descripción
    # diga "de suspensión", que es como las escriben los proveedores.
    ("ROTULA DE SUSPENSION", "Dirección", "Terminales / rótulas"),
    # "resorte" solo es el espiral de suspensión; el de gas es otra cosa.
    ("RESORTE TOYOTA HILUX DELANTERO", "Suspensión", "Resortes / espirales"),
    ("RESORTE A GAS VW SURAN", "Varios", None),
    # El negocio no vende transmisión: la v3 no tiene ese rubro y estas
    # piezas van al cajón de sastre a propósito, sin que las capturen las
    # reglas de motor o de suspensión que comparten vocabulario.
    ("JUNTA HOMOCINETICA FIAT PALIO", "Varios", None),
    ("FUELLE DE SEMIEJE RENAULT", "Varios", None),
    ("FILTRO DE ACEITE", "Varios", None),
    # Una descripción que es solo marca y número no alcanza para clasificar:
    # tiene que caer en Varios y no en un rubro adivinado.
    ("SKF VKJC9666", "Varios", None),
])
def test_clasifica_los_casos_ambiguos(texto, categoria, subcategoria):
    assert cl.clasificar(texto) == (categoria, subcategoria)


def test_el_codigo_de_barras_numerico_no_rompe_la_clasificacion():
    """Las celdas de Excel llegan como int/float cuando el proveedor cargó un
    código sin letras. El join reventaba a mitad de la corrida."""
    assert cl.clasificar("PASTILLA DE FRENO", 82011436, 1.4)[0] == "Frenos"


def test_clasificar_sin_texto_cae_en_varios():
    assert cl.clasificar(None, "", None) == ("Varios", None)


# --- Reclasificación de la taxonomía vieja ----------------------------------

def test_traduce_el_rubro_viejo_cuando_alcanza_con_el_nombre():
    """`Suspensión y Dirección` se partió en dos rubros en la v3: el subrubro
    viejo es lo único que dice de cuál de los dos se trata."""
    assert cl.reclasificar_v2(
        "Suspensión y Dirección", "Rótulas y extremos", "ROTULA FIAT IDEA INFERIOR",
    ) == ("Dirección", "Terminales / rótulas")
    assert cl.reclasificar_v2(
        "Suspensión y Dirección", "Amortiguadores", "AMORTIGUADOR VW FOX",
    ) == ("Suspensión", "Amortiguadores")


def test_el_cajon_de_sastre_viejo_no_se_traduce_a_ciegas():
    """`Otros` de la v2 son 31.259 filas y adentro hay cosas perfectamente
    clasificables. Traducirlo literalmente a `Varios` hacía que el texto ni
    se mirara."""
    assert cl.reclasificar_v2("Otros", None, "BARRA TORSION FORD") == (
        "Suspensión", "Barras de torsión y estabilizadoras",
    )


def test_una_clasificacion_vieja_equivocada_no_gana_sobre_el_nombre():
    """La v2 no es infalible: tenía este precap de dirección etiquetado como
    `Transmisión / Coronas y diferencial`. "Varios" nunca es un destino con
    confianza, así que si el nombre reconoce la pieza, gana el nombre."""
    assert cl.reclasificar_v2(
        "Transmisión", "Coronas y diferencial",
        "PRECAP AXIAL DE SALIDA DE CAJA DE DIRECCION",
    )[0] == "Dirección"


def test_el_rubro_viejo_sostiene_a_las_filas_que_no_se_describen_a_si_mismas():
    """Infofren nombra sus productos por el auto y no por la pieza
    ("SONIC / TRACKER"), así que el texto no alcanza. El rubro que la v2 ya
    tenía funciona de piso en vez de tirar la fila a Varios."""
    assert cl.reclasificar_v2("Frenos", "Válvulas y actuadores", "SONIC / TRACKER") == (
        "Frenos", None,
    )


def test_no_deja_un_subrubro_colgado_de_un_rubro_ajeno():
    """Si el rubro lo decide la taxonomía vieja y el subrubro sale del texto,
    solo se puede usar el subrubro cuando los dos coinciden -- si no, el
    producto queda con un subrubro que no pertenece a su rubro y la ficha lo
    muestra en un desplegable donde esa opción no existe."""
    categoria, subcategoria = cl.reclasificar_v2("Motor", "Otros de motor", "SOPORTE MOTOR PEUGEOT")
    assert categoria == "Motor"
    assert subcategoria is None or subcategoria in db.SUBCATEGORIAS_INICIALES["Motor"]


def test_no_distingue_mayusculas_ni_acentos():
    """Las listas escriben la misma pieza de las dos formas."""
    assert cl.clasificar("PASTILLA DE FRENO HIDRÁULICO") == cl.clasificar("pastilla de freno hidraulico")
