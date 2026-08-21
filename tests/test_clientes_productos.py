"""El buscador es lo más frágil de la migración: en SQLite LIKE no distingue
mayúsculas, en Postgres sí. Si alguien olvida un ILIKE, el buscador deja de
encontrar cosas sin lanzar ningún error."""
from decimal import Decimal
import pytest
from core.app import app as flask_app, a_decimal


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


def test_buscar_producto_no_distingue_mayusculas(client, db_conn):
    db_conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta)
           VALUES ('Pastilla Delantera Bosch', 'Frenos', 100, 130)"""
    )
    db_conn.commit()
    for texto in ["pastilla", "PASTILLA", "PaStIlLa"]:
        respuesta = client.get(f"/productos?q={texto}")
        assert b"Pastilla Delantera Bosch" in respuesta.data, f"falló con '{texto}'"


def test_buscar_producto_por_modelo_compatible(client, db_conn):
    """Escribir 'Gol' tiene que encontrar 'VW Gol / Voyage'."""
    db_conn.execute(
        """INSERT INTO productos (nombre, categoria, modelo_compatible, precio_costo, precio_venta)
           VALUES ('Kit embrague', 'Embragues', 'VW Gol / Voyage', 100, 130)"""
    )
    db_conn.commit()
    respuesta = client.get("/productos?q=gol")
    assert b"Kit embrague" in respuesta.data


def test_buscar_cliente_no_distingue_mayusculas(client, db_conn):
    db_conn.execute(
        "INSERT INTO clientes (nombre, fecha_alta) VALUES ('Taller Rodríguez', CURRENT_DATE)"
    )
    db_conn.commit()
    respuesta = client.get("/clientes?q=rodr")
    assert b"Rodr" in respuesta.data


def test_codigo_duplicado_da_mensaje_claro_y_no_rompe(client, db_conn):
    """productos.codigo es UNIQUE: el error se captura y se muestra, no
    revienta con una página de error."""
    db_conn.execute(
        """INSERT INTO productos (nombre, categoria, codigo, precio_costo, precio_venta)
           VALUES ('Existente', 'Frenos', 'ABC123', 100, 130)"""
    )
    db_conn.commit()
    respuesta = client.post("/api/productos-nuevo", data={
        "nombre": "Otro", "categoria": "Frenos", "codigo": "ABC123",
        "precio_costo": "100", "precio_venta": "130",
    })
    assert respuesta.status_code < 500


def test_precio_se_guarda_como_decimal_exacto(client, db_conn):
    """Prueba de punta a punta: el alta de un producto por la ruta persiste
    el precio correcto en la base.

    OJO, esto NO es un test de regresión contra el uso de float() para la
    plata (para eso ver test_a_decimal_convierte_a_decimal_no_a_float, más
    abajo): se verificó a mano que este test sigue pasando igual si
    a_decimal() se revierte a float(valor or 0) -- el cast de Postgres a
    NUMERIC(12,2) redondea a 2 decimales y absorbe el error del flotante
    para cualquier monto realista, y psycopg siempre deserializa una
    columna NUMERIC como Decimal sin importar qué tipo de Python la
    escribió. Por eso el guardián real vive en el test de la función pura,
    no acá."""
    respuesta = client.post("/productos/nuevo", data={
        "nombre": "Producto con decimales",
        "categoria": "Frenos",
        "precio_costo": "1234.56",
        "precio_venta": "2345.67",
    })
    assert respuesta.status_code < 400
    fila = db_conn.execute(
        # En mayúsculas porque la ficha de producto guarda el nombre
        # normalizado (mayusculas_sin_acentos, 21/08/2026).
        "SELECT precio_costo, precio_venta FROM productos WHERE nombre = %s",
        ("PRODUCTO CON DECIMALES",),
    ).fetchone()
    assert fila is not None
    assert fila["precio_costo"] == Decimal("1234.56")
    assert fila["precio_venta"] == Decimal("2345.67")
    assert isinstance(fila["precio_costo"], Decimal)


def test_a_decimal_convierte_a_decimal_no_a_float():
    """Guardián real contra volver a usar float() en a_decimal(): test
    unitario de la función pura, sin base de datos de por medio. A
    diferencia de test_precio_se_guarda_como_decimal_exacto, este SÍ falla
    si alguien revierte a_decimal() a float(valor or 0) -- no hay cast de
    NUMERIC ni deserialización de psycopg que lo disimule acá."""
    resultado = a_decimal("1234.56")
    assert isinstance(resultado, Decimal)
    assert not isinstance(resultado, float)
    assert resultado == Decimal("1234.56")

    # campo ausente (None) y campo vacío ("") -- mismo criterio que el
    # `or 0` que ya usaba cada sitio antes de existir el helper.
    assert a_decimal(None) == Decimal("0")
    assert isinstance(a_decimal(None), Decimal)
    assert a_decimal("") == Decimal("0")
    assert isinstance(a_decimal(""), Decimal)
