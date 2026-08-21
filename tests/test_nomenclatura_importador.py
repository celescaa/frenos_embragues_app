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
    lo vende'. Una cantidad en 0 SÍ se carga: significa 'lo trabajamos pero se
    acabó', que es distinto de la celda vacía."""
    resumen = cargar.importar(planilla, revisar=True)
    assert [f["codigo"] for f in resumen["revision"]] == ["BA446"]
    assert resumen["sin_cantidad"] == 1


def test_revisar_no_abre_conexion_a_la_base(planilla, monkeypatch):
    """Si esto se rompe, --revisar deja de ser seguro para correr contra
    producción, que es el único motivo por el que existe."""
    def explotar(*a, **k):
        raise AssertionError("--revisar no tiene que abrir la base")
    monkeypatch.setattr(cargar.db, "get_connection", explotar)
    resumen = cargar.importar(planilla, revisar=True)
    assert len(resumen["revision"]) == 1
