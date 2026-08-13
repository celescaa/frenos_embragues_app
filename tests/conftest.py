"""Fixtures compartidas por toda la suite.

La base de pruebas es el Postgres local que levanta `npx supabase start`
(ver README). La mayoría de los tests usa `db_conn`, que corre dentro de
una transacción que se revierte al terminar, así que no ensucian la base.

Pero varios tests de ruta (Nueva venta, Nueva compra, /clientes, /productos,
etc.) necesitan que el `test_client` de Flask -- que abre su PROPIA conexión
psycopg a través de `db.get_connection()`, distinta de `db_conn` -- vea los
datos que el test insertó. Postgres solo hace visibles esos datos entre
conexiones si se commitearon de verdad, así que esos tests llaman
`db_conn.commit()` a propósito. Eso dejaría basura commiteada y volvería la
suite no repetible (una segunda corrida chocaría, por ejemplo, contra el
UNIQUE de productos.codigo) -- por eso el fixture `_limpiar_base_de_pruebas`
de acá abajo, autouse, deja la base como recién migrada después de CADA
test.
"""
import os
import pytest
import psycopg
from psycopg.rows import dict_row
from core import database as db

PG_URL_TEST = os.environ.get(
    "DATABASE_URL_TEST",
    "postgresql://postgres:postgres@127.0.0.1:54322/postgres",
)

# Las 18 tablas de datos del esquema (ver supabase/migrations/), en cualquier
# orden -- TRUNCATE ... CASCADE no necesita que respete las FK.
TABLAS = [
    "clientes", "proveedores", "categorias", "subcategorias", "productos",
    "ventas", "venta_items", "compras", "compra_items", "producto_proveedor",
    "pedidos_web", "pedido_web_items", "usuarios",
    "cuenta_corriente_movimientos", "cuenta_corriente_movimiento_items",
    "movimientos_no_facturados", "promociones_aplicadas", "promocion_productos",
]


@pytest.fixture(scope="session")
def pg_url():
    return PG_URL_TEST


@pytest.fixture
def db_conn(pg_url):
    """Conexión con rollback automático: nada de lo que escribe un test queda."""
    conn = psycopg.connect(pg_url, row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture(autouse=True)
def _limpiar_base_de_pruebas(pg_url):
    """Deja la base de pruebas como recién migrada después de cada test.

    Existe porque algunos tests de ruta commitean a propósito (ver el
    docstring del módulo) -- sin esta limpieza, esos commits se acumulan y
    una segunda corrida de la suite falla contra datos de la primera. Usa
    su PROPIA conexión (no `db_conn`): `db_conn` vive dentro de una
    transacción que se revierte, así que un TRUNCATE hecho ahí no
    persistiría.

    Repuebla `categorias`/`subcategorias` con `db.CATEGORIAS_INICIALES` /
    `db.SUBCATEGORIAS_INICIALES` -- la misma fuente de la que sale la
    siembra real de la migración -- porque son datos de referencia de los
    que dependen tanto la app (dropdowns, validación) como varios tests.
    """
    yield
    conn = psycopg.connect(pg_url, row_factory=dict_row)
    try:
        conn.execute("TRUNCATE TABLE " + ", ".join(TABLAS) + " RESTART IDENTITY CASCADE")
        for nombre in db.CATEGORIAS_INICIALES:
            conn.execute("INSERT INTO categorias (nombre) VALUES (%s)", (nombre,))
        categoria_ids = {
            fila["nombre"]: fila["id"]
            for fila in conn.execute("SELECT id, nombre FROM categorias").fetchall()
        }
        for categoria_nombre, subcategorias in db.SUBCATEGORIAS_INICIALES.items():
            for subcategoria in subcategorias:
                conn.execute(
                    "INSERT INTO subcategorias (nombre, categoria_id) VALUES (%s, %s)",
                    (subcategoria, categoria_ids[categoria_nombre]),
                )
        conn.commit()
    finally:
        conn.close()
