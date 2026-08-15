"""El ABM de autos. Sigue el mismo patrón activo/inactivo que proveedores y
categorías: no se borra lo que está en uso, se desactiva."""
import pytest
from core.app import app as flask_app
from core import database as db


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


def test_crear_un_vehiculo(client, db_conn):
    respuesta = client.post("/vehiculos/nuevo", data={
        "marca_auto": "FIAT", "modelo": "Palio", "motor": "1.4",
        "anio_desde": "2008", "anio_hasta": "2012",
    }, follow_redirects=True)
    assert respuesta.status_code == 200
    fila = db_conn.execute("SELECT * FROM vehiculos").fetchone()
    assert (fila["marca_auto"], fila["modelo"], fila["motor"]) == ("FIAT", "Palio", "1.4")
    assert fila["anio_desde"] == 2008


def test_el_anio_es_opcional(client, db_conn):
    """Celes fue explícita: el motor sí o sí, el año no importa si no se llena."""
    client.post("/vehiculos/nuevo", data={
        "marca_auto": "VW", "modelo": "Gol", "motor": "1.6",
        "anio_desde": "", "anio_hasta": "",
    }, follow_redirects=True)
    fila = db_conn.execute("SELECT * FROM vehiculos").fetchone()
    assert fila["anio_desde"] is None and fila["anio_hasta"] is None


def test_no_deja_repetir_el_mismo_auto(client, db_conn):
    datos = {"marca_auto": "FIAT", "modelo": "Palio", "motor": "1.4",
             "anio_desde": "", "anio_hasta": ""}
    client.post("/vehiculos/nuevo", data=datos, follow_redirects=True)
    respuesta = client.post("/vehiculos/nuevo", data=datos, follow_redirects=True)
    assert respuesta.status_code == 200, "avisa, no revienta"
    total = db_conn.execute("SELECT count(*) AS n FROM vehiculos").fetchone()["n"]
    assert total == 1


def test_no_se_puede_borrar_uno_en_uso(client, db_conn):
    """Mismo criterio que un proveedor con compras: se avisa y se ofrece
    desactivarlo, no se rompe con un error de base de datos."""
    producto_id = db_conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta)
           VALUES ('Buje', 'Otros', 100, 130) RETURNING id"""
    ).fetchone()["id"]
    vehiculo_id = db_conn.execute(
        """INSERT INTO vehiculos (marca_auto, modelo, motor)
           VALUES ('FIAT', 'Palio', '1.4') RETURNING id"""
    ).fetchone()["id"]
    db_conn.execute(
        "INSERT INTO producto_vehiculos (producto_id, vehiculo_id) VALUES (%s, %s)",
        (producto_id, vehiculo_id),
    )
    db_conn.commit()
    respuesta = client.post(f"/vehiculos/{vehiculo_id}/eliminar", follow_redirects=True)
    assert respuesta.status_code == 200
    queda = db_conn.execute(
        "SELECT count(*) AS n FROM vehiculos WHERE id = %s", (vehiculo_id,)
    ).fetchone()["n"]
    assert queda == 1


def test_obtener_vehiculos_omite_los_desactivados(db_conn):
    db_conn.execute(
        """INSERT INTO vehiculos (marca_auto, modelo, motor, activo)
           VALUES ('FIAT', 'Palio', '1.4', true), ('VW', 'Gol', '1.6', false)"""
    )
    activos = [v["modelo"] for v in db.obtener_vehiculos(db_conn, solo_activos=True)]
    assert activos == ["Palio"]
    todos = [v["modelo"] for v in db.obtener_vehiculos(db_conn, solo_activos=False)]
    assert sorted(todos) == ["Gol", "Palio"]
