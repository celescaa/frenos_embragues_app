"""Vincular autos a un producto desde su ficha, y que la marca escrita quede
disponible para el filtro sin pantalla de administración de por medio."""
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
def autos(db_conn):
    palio = db_conn.execute(
        "INSERT INTO vehiculos (marca_auto, modelo, motor) VALUES ('FIAT','Palio','1.4') RETURNING id"
    ).fetchone()["id"]
    gol = db_conn.execute(
        "INSERT INTO vehiculos (marca_auto, modelo, motor) VALUES ('VW','Gol','1.6') RETURNING id"
    ).fetchone()["id"]
    db_conn.commit()
    return {"palio": palio, "gol": gol}


DATOS_BASE = {
    "nombre": "Pastilla de freno", "categoria": "Frenos", "marca": "Cobreq",
    "precio_costo": "100", "precio_venta": "130",
    "stock_actual": "5", "stock_minimo": "2",
}


def test_crear_un_producto_vinculando_dos_autos(client, db_conn, autos):
    client.post("/productos/nuevo", data={
        **DATOS_BASE, "vehiculo_id": [str(autos["palio"]), str(autos["gol"])],
    }, follow_redirects=True)
    vinculados = db_conn.execute(
        """SELECT v.modelo FROM producto_vehiculos pv
           JOIN vehiculos v ON v.id = pv.vehiculo_id ORDER BY v.modelo"""
    ).fetchall()
    assert [f["modelo"] for f in vinculados] == ["Gol", "Palio"]


def test_un_producto_sin_autos_se_guarda_igual(client, db_conn, autos):
    """Vincular autos es opcional: el sistema no puede empeorar para quien
    todavía no los cargó."""
    respuesta = client.post("/productos/nuevo", data=DATOS_BASE, follow_redirects=True)
    assert respuesta.status_code == 200
    total = db_conn.execute("SELECT count(*) AS n FROM productos").fetchone()["n"]
    assert total == 1
    assert db_conn.execute("SELECT count(*) AS n FROM producto_vehiculos").fetchone()["n"] == 0


def test_editar_reemplaza_los_autos_vinculados(client, db_conn, autos):
    client.post("/productos/nuevo", data={
        **DATOS_BASE, "vehiculo_id": [str(autos["palio"]), str(autos["gol"])],
    }, follow_redirects=True)
    producto_id = db_conn.execute("SELECT id FROM productos").fetchone()["id"]
    client.post(f"/productos/{producto_id}/editar", data={
        **DATOS_BASE, "vehiculo_id": [str(autos["gol"])],
    }, follow_redirects=True)
    vinculados = db_conn.execute(
        """SELECT v.modelo FROM producto_vehiculos pv
           JOIN vehiculos v ON v.id = pv.vehiculo_id"""
    ).fetchall()
    assert [f["modelo"] for f in vinculados] == ["Gol"]


def test_la_marca_escrita_queda_disponible_para_el_filtro(client, db_conn, autos):
    """No hay pantalla de marcas: la lista se mantiene sola al guardar."""
    client.post("/productos/nuevo", data={**DATOS_BASE, "marca": "Fric-Rot"},
                follow_redirects=True)
    marcas = [m["nombre"] for m in db_conn.execute("SELECT nombre FROM marcas")]
    assert "Fric-Rot" in marcas


def test_la_marca_no_se_duplica_por_mayusculas(client, db_conn, autos):
    client.post("/productos/nuevo", data={**DATOS_BASE, "marca": "Cobreq"},
                follow_redirects=True)
    client.post("/productos/nuevo", data={
        **DATOS_BASE, "nombre": "Otra pastilla", "marca": "COBREQ",
    }, follow_redirects=True)
    total = db_conn.execute("SELECT count(*) AS n FROM marcas").fetchone()["n"]
    assert total == 1
