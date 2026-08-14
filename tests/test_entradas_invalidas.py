"""Entradas inválidas en campos que van a columnas INTEGER.

Regresión introducida por la migración a Postgres, no detectada por el resto
de la suite porque todos los tests mandan ids bien formados.

En SQLite, `SELECT ... WHERE id = 'abc'` simplemente no devolvía filas: la
comparación entre un entero y un texto daba falso y la app seguía por la rama
de "no existe". Postgres es estricto — castea el parámetro a INTEGER y, si no
puede, aborta la consulta con `invalid input syntax for type integer`. Esa
excepción sube sin capturar y la ruta devuelve 500.

Importa sobre todo en `/tienda/carrito/*`, que es **pública y sin login**:
cualquiera puede postear un `producto_id` arbitrario. Y el caso peor no es el
500 puntual sino el carrito envenenado: `/tienda/carrito/actualizar` guarda la
clave en la sesión sin validarla, así que un solo POST inválido deja
`/tienda/carrito` y `/tienda/checkout` rotos para ese visitante hasta que borre
la cookie.

El contrato que fijan estos tests es el que ya tenía el sistema con SQLite:
una entrada inválida se ignora (o avisa), nunca rompe la página.
"""
import pytest

from core.app import app as flask_app


def _producto(conn, nombre="Disco Ventilado", stock=5):
    return conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta, stock_actual)
           VALUES (%s, 'Frenos', 100, 200, %s) RETURNING id""",
        (nombre, stock),
    ).fetchone()["id"]




@pytest.fixture
def cliente_publico():
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def cliente_admin(crear_usuario):
    # Vía `crear_usuario`: desde que usuarios.id es clave foránea de
    # auth.users, un perfil insertado a mano no tiene cuenta donde apoyarse.
    usuario_id = crear_usuario("admin_entradas", rol="admin", nombre="Admin Test")["id"]
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        with c.session_transaction() as sesion:
            sesion["usuario_id"] = str(usuario_id)
            sesion["usuario_nombre"] = "Admin Test"
            sesion["usuario_rol"] = "admin"
            sesion["debe_cambiar_password"] = False
        yield c


def test_agregar_al_carrito_con_producto_id_no_numerico_no_rompe(cliente_publico):
    """Ruta pública: el id llega crudo del form, nadie garantiza que sea un número."""
    respuesta = cliente_publico.post(
        "/tienda/carrito/agregar", data={"producto_id": "abc", "cantidad": "1"}
    )
    assert respuesta.status_code < 500


def test_agregar_al_carrito_con_cantidad_no_numerica_no_rompe(cliente_publico, db_conn):
    producto_id = _producto(db_conn)
    db_conn.commit()
    respuesta = cliente_publico.post(
        "/tienda/carrito/agregar", data={"producto_id": str(producto_id), "cantidad": "muchas"}
    )
    assert respuesta.status_code < 500


def test_un_carrito_envenenado_no_deja_la_tienda_rota(cliente_publico):
    """El caso peor: `/tienda/carrito/actualizar` guardaba la clave sin validar,
    y después `_carrito_detalle()` hacía int() sobre ella. El daño persiste en
    la sesión, así que rompe el carrito Y el checkout hasta borrar la cookie."""
    cliente_publico.post(
        "/tienda/carrito/actualizar", data={"producto_id": "abc", "cantidad": "2"}
    )
    assert cliente_publico.get("/tienda/carrito").status_code < 500
    assert cliente_publico.get("/tienda/checkout").status_code < 500


def test_movimiento_sin_factura_con_producto_id_no_numerico_no_rompe(cliente_admin):
    """El buscador de productos completa un input oculto por JavaScript; si no
    llega a completarlo, viaja el texto que escribió la persona."""
    respuesta = cliente_admin.post(
        "/stock/no-facturado",
        data={"tipo": "compra", "producto_id": "Disco", "cantidad": "2", "precio": "10"},
    )
    assert respuesta.status_code < 500
