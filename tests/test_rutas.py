"""Recorre todas las rutas GET sin parámetros y verifica que ninguna
devuelva un error de servidor. Es la red que atrapa una consulta mal
portada que ningún test específico haya tocado."""
import pytest
from core.app import app as flask_app

RUTAS_PRIVADAS = [
    "/", "/clientes", "/clientes/top", "/clientes/top-deudores",
    "/productos", "/categorias", "/proveedores", "/compras",
    "/compras/importar-factura", "/pedidos", "/ventas", "/ventas/dia",
    "/ventas/nueva", "/compras/nueva", "/stock/no-facturado",
    "/usuarios", "/clientes/nuevo", "/productos/nuevo", "/proveedores/nuevo",
]

RUTAS_PUBLICAS = ["/login", "/tienda", "/tienda/carrito"]


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def client_logueado(client):
    with client.session_transaction() as sesion:
        sesion["usuario_id"] = "00000000-0000-0000-0000-000000000001"
        sesion["usuario_nombre"] = "Test"
        sesion["usuario_rol"] = "admin"
        sesion["debe_cambiar_password"] = False
    return client


@pytest.mark.parametrize("ruta", RUTAS_PRIVADAS)
def test_las_rutas_privadas_responden(client_logueado, ruta):
    respuesta = client_logueado.get(ruta)
    assert respuesta.status_code < 500, f"{ruta} devolvió {respuesta.status_code}"


@pytest.mark.parametrize("ruta", RUTAS_PUBLICAS)
def test_las_rutas_publicas_responden_sin_login(client, ruta):
    respuesta = client.get(ruta)
    assert respuesta.status_code < 500, f"{ruta} devolvió {respuesta.status_code}"


@pytest.mark.parametrize("ruta", RUTAS_PRIVADAS)
def test_sin_sesion_redirige_al_login(client, ruta):
    respuesta = client.get(ruta)
    assert respuesta.status_code in (301, 302), f"{ruta} no pidió login"
