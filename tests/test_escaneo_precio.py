"""Consulta de precio al escanear con la pistola en cualquier pantalla.

El listener que dispara el popup es JavaScript puro y no se puede testear
desde acá (mismo caso ya anotado en CLAUDE.md para producto_form.html): estos
tests cubren el endpoint que consulta, que es lo que sí vive en el servidor.
"""
import pytest
from core.app import app as flask_app


@pytest.fixture
def client(db_conn):
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        with c.session_transaction() as sesion:
            sesion["usuario_id"] = "00000000-0000-0000-0000-000000000001"
            sesion["usuario_nombre"] = "Test"
            sesion["usuario_rol"] = "admin"
            sesion["debe_cambiar_password"] = False
        yield c


@pytest.fixture
def producto(db_conn):
    db_conn.execute(
        """INSERT INTO productos
               (nombre, codigo, codigo_barras, categoria, marca, modelo_compatible,
                precio_costo, precio_venta, stock_actual, stock_minimo)
           VALUES ('Pastilla Delantera', 'FR-PAS-001', '7791234567890', 'Frenos',
                   'Bosch', 'VW Gol / Voyage', 8000, 12500.50, 4, 2)"""
    )
    db_conn.commit()


def test_el_popup_recibe_lo_que_necesita_para_mostrarse(client, producto):
    """El popup muestra precio, nombre, marca/modelo y stock: si el endpoint no
    devuelve alguno de esos campos, el cartel sale incompleto sin dar error."""
    datos = client.get("/api/producto-por-codigo?codigo=7791234567890").get_json()

    assert datos["encontrado"] is True
    assert datos["nombre"] == "Pastilla Delantera"
    assert datos["marca"] == "Bosch"
    assert datos["modelo_compatible"] == "VW Gol / Voyage"
    assert datos["stock_actual"] == 4
    assert datos["stock_minimo"] == 2
    assert datos["id"]


def test_el_precio_llega_con_los_centavos_exactos(client, producto):
    """La plata es NUMERIC en Postgres: si alguien la pasa por float en el
    camino al JSON, el precio que se le muestra al cliente puede no ser el
    cargado."""
    datos = client.get("/api/producto-por-codigo?codigo=7791234567890").get_json()
    assert str(datos["precio_venta"]) == "12500.50"


def test_tambien_encuentra_por_codigo_interno(client, producto):
    """No todos los productos tienen código de barras; el interno se puede
    tipear a mano en el mismo campo."""
    datos = client.get("/api/producto-por-codigo?codigo=FR-PAS-001").get_json()
    assert datos["encontrado"] is True
    assert datos["nombre"] == "Pastilla Delantera"


def test_codigo_desconocido_no_es_un_error(client, producto):
    """El popup avisa "no está cargado" y ofrece darlo de alta: para eso
    necesita una respuesta normal, no un 404 ni una excepción."""
    respuesta = client.get("/api/producto-por-codigo?codigo=0000000000000")
    assert respuesta.status_code == 200
    assert respuesta.get_json() == {"encontrado": False}


@pytest.mark.parametrize("ruta", ["/", "/productos", "/clientes", "/ventas", "/proveedores", "/pedidos"])
def test_el_popup_se_carga_en_las_pantallas_de_consulta(client, ruta):
    assert b"modalPrecio" in client.get(ruta).data


@pytest.mark.parametrize("ruta", ["/ventas/nueva", "/compras/nueva", "/productos/nuevo", "/stock/no-facturado"])
def test_el_popup_no_se_carga_donde_escanear_ya_carga_el_producto(client, ruta):
    """Sin esto, escanear en Nueva venta con el foco fuera del campo taparía la
    venta a medio cargar con un cartel de precio."""
    assert b"modalPrecio" not in client.get(ruta).data


def test_la_tienda_publica_no_lleva_el_popup(client):
    """Es una pantalla para el comprador por internet, no para el mostrador."""
    assert b"modalPrecio" not in client.get("/tienda").data


def test_producto_sin_marca_ni_modelo_no_rompe(client, db_conn):
    """Los productos cargados a las apuradas no tienen marca ni modelo."""
    db_conn.execute(
        """INSERT INTO productos (nombre, codigo_barras, categoria, precio_costo, precio_venta)
           VALUES ('Producto pelado', '111', 'Otros', 10, 20)"""
    )
    db_conn.commit()
    datos = client.get("/api/producto-por-codigo?codigo=111").get_json()
    assert datos["encontrado"] is True
    assert datos["marca"] is None
    assert datos["modelo_compatible"] is None
