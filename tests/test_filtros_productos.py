"""La pantalla de Stock con la barra de filtros. Lo que se prueba acá es que
la ruta pase los filtros a db.buscar_productos() y muestre lo que hay que
mostrar; el criterio de búsqueda en sí tiene sus propios tests."""
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
def catalogo(db_conn):
    filas = [
        ("Pastilla delantera", "Frenos", "Pastillas", "Cobreq", 5),
        ("Disco de freno", "Frenos", "Discos", "Fric-Rot", 0),
        ("Kit de embrague", "Embragues", "Kits de embrague", "Sachs", 3),
    ]
    for nombre, categoria, subcategoria, marca, stock in filas:
        db_conn.execute(
            """INSERT INTO productos
               (nombre, categoria, subcategoria, marca, stock_actual, precio_costo, precio_venta)
               VALUES (%s, %s, %s, %s, %s, 100, 130)""",
            (nombre, categoria, subcategoria, marca, stock),
        )
    db_conn.commit()


def test_filtra_por_marca(client, catalogo):
    respuesta = client.get("/productos?marca=Cobreq")
    assert b"Pastilla delantera" in respuesta.data
    assert b"Kit de embrague" not in respuesta.data


def test_filtra_solo_con_stock(client, catalogo):
    respuesta = client.get("/productos?solo_con_stock=1")
    assert b"Disco de freno" not in respuesta.data
    assert b"Pastilla delantera" in respuesta.data


def test_filtra_por_auto(client, catalogo, db_conn):
    vehiculo_id = db_conn.execute(
        "INSERT INTO vehiculos (marca_auto, modelo, motor) VALUES ('FIAT','Palio','1.4') RETURNING id"
    ).fetchone()["id"]
    producto_id = db_conn.execute(
        "SELECT id FROM productos WHERE nombre = 'Pastilla delantera'"
    ).fetchone()["id"]
    db_conn.execute(
        "INSERT INTO producto_vehiculos (producto_id, vehiculo_id) VALUES (%s, %s)",
        (producto_id, vehiculo_id),
    )
    db_conn.commit()
    respuesta = client.get(f"/productos?vehiculo_id={vehiculo_id}")
    assert b"Pastilla delantera" in respuesta.data
    assert b"Kit de embrague" not in respuesta.data


def test_un_auto_invalido_no_rompe_la_pantalla(client, catalogo):
    """Postgres aborta la consulta con un id no numérico; sin a_entero() esto
    es un error 500."""
    respuesta = client.get("/productos?vehiculo_id=abc")
    assert respuesta.status_code == 200


def test_muestra_sugerencias_cuando_no_hay_resultados(client, catalogo):
    respuesta = client.get("/productos?q=pastila")
    assert "quisiste decir" in respuesta.data.decode().lower()
    assert b"Pastilla delantera" in respuesta.data


def test_avisa_cuando_recorta_los_resultados(client, db_conn):
    """Con el catálogo real dibujar la tabla entera cuelga el navegador. El
    aviso dice la verdad en vez de aparentar que hay 200 nomás."""
    from core import app as core_app

    for i in range(core_app.LIMITE_RESULTADOS + 5):
        db_conn.execute(
            """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta)
               VALUES (%s, 'Frenos', 100, 130)""",
            (f"Producto {i:04d}",),
        )
    db_conn.commit()
    respuesta = client.get("/productos")
    assert b"Mostrando" in respuesta.data
    assert str(core_app.LIMITE_RESULTADOS + 5).encode() in respuesta.data


def test_los_filtros_se_combinan(client, catalogo):
    respuesta = client.get("/productos?categoria=Frenos&marca=Sachs")
    assert b"Kit de embrague" not in respuesta.data
    assert b"Pastilla delantera" not in respuesta.data
