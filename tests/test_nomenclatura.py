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
    assert "  " not in fila["nombre"]


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
