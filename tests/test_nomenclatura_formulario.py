"""El CSS text-transform es SOLO visual: el valor que llega al servidor sigue
siendo lo que la persona tipeó. Sin la normalización del lado del servidor, la
mayúscula del formulario es una mentira prolija."""
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
    # aparecería como un rubro distinto de 'Motor' en el filtro de /productos.
    assert fila["categoria"] == "Motor"
    assert fila["subcategoria"] == "Bomba de agua"


def test_el_alta_rapida_desde_una_compra_normaliza_igual(client, db_conn):
    """Es la otra puerta por la que entra un producto tipeado a mano. Si sólo
    se normalizara la ficha, el mismo producto quedaría escrito distinto según
    por dónde se cargó."""
    respuesta = client.post("/api/productos-nuevo", data={
        "nombre": "bomba de agua fiat", "codigo": "TEST-MAY-2",
        "categoria": "Motor", "marca": "vmg",
        "precio_costo": "100", "precio_venta": "130",
    })
    assert respuesta.status_code == 200
    fila = db_conn.execute(
        "SELECT nombre, marca FROM productos WHERE codigo = %s", ("TEST-MAY-2",)).fetchone()
    assert fila["nombre"] == "BOMBA DE AGUA FIAT"
    assert fila["marca"] == "VMG"


def test_el_formulario_muestra_la_mayuscula_mientras_se_escribe():
    """La otra capa: sin esto la persona escribe en minúscula y ve minúscula, y
    la mayúscula aparece recién después de guardar, que sorprende."""
    html = Path(__file__).resolve().parents[1].joinpath(
        "templates/producto_form.html").read_text()
    assert html.count("text-transform: uppercase") >= 3, (
        "faltan campos: nombre, marca y modelo_compatible")


def test_crear_una_categoria_no_la_pasa_a_mayuscula(client, db_conn):
    """Regresión: al cablear la normalización se aplicó por error a
    categorias_nueva(). Una categoría en mayúsculas rompe el filtro de
    /productos, que agrupa esa columna cruda: 'MOTOR' aparecería como un rubro
    distinto de 'Motor', cada uno con su propio contador."""
    client.post("/categorias/nueva", data={"nombre": "Prueba Rubro"},
                follow_redirects=True)
    fila = db_conn.execute(
        "SELECT nombre FROM categorias WHERE nombre ILIKE %s", ("prueba rubro",)).fetchone()
    assert fila is not None, "no se creó la categoría"
    assert fila["nombre"] == "Prueba Rubro"
