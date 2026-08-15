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

# Puerto 54422, no el 54322 que la CLI de Supabase usa por defecto: ese default
# es el mismo para CUALQUIER proyecto, así que dos proyectos locales de la misma
# persona se pelean por él. Ya pasó dos veces (con `hogar-gestion`), y la segunda
# dejó a este proyecto sin base en el medio de una corrida. Los puertos de este
# proyecto están corridos +100 en supabase/config.toml para que puedan convivir.
PG_URL_TEST = os.environ.get(
    "DATABASE_URL_TEST",
    "postgresql://postgres:postgres@127.0.0.1:54422/postgres",
)

# Las 21 tablas de datos del esquema (ver supabase/migrations/), en cualquier
# orden -- TRUNCATE ... CASCADE no necesita que respete las FK.
TABLAS = [
    "clientes", "proveedores", "categorias", "subcategorias", "productos",
    "ventas", "venta_items", "compras", "compra_items", "producto_proveedor",
    "pedidos_web", "pedido_web_items", "usuarios",
    "cuenta_corriente_movimientos", "cuenta_corriente_movimiento_items",
    "movimientos_no_facturados", "promociones_aplicadas", "promocion_productos",
    "marcas", "vehiculos", "producto_vehiculos",
]


def pytest_configure(config):
    """Comprueba que la base de pruebas sea la de ESTE proyecto, antes de nada.

    Va en `pytest_configure` (no en un fixture) porque tiene que correr antes
    de que pytest importe los módulos de test: varios importan `core.app`, que
    abre la conexión y siembra datos de ejemplo en tiempo de importación. Un
    fixture llegaría tarde.

    El chequeo no es paranoia. Este proyecto ya no usa el puerto default de la
    CLI (ver el comentario de PG_URL_TEST arriba), justamente porque otro
    proyecto local se lo apropió dos veces —`hogar-gestion`, el 13/08/2026 y de
    nuevo el 14—, la segunda vez en el medio de una corrida. Correr los puertos
    baja mucho la probabilidad de que vuelva a pasar, pero no la elimina: basta
    con que alguien apunte `DATABASE_URL_TEST` a otro lado. Y
    `_limpiar_base_de_pruebas` hace TRUNCATE de una lista fija de tablas: contra
    la base equivocada, eso es borrar datos ajenos. Zafaría de casualidad —el
    TRUNCATE es una sola sentencia y aborta entera si alguna tabla no existe—,
    pero eso depende de que los esquemas no se parezcan. Mejor fallar acá, con
    un mensaje que diga qué pasó.
    """
    try:
        conn = psycopg.connect(PG_URL_TEST, row_factory=dict_row)
    except psycopg.OperationalError as e:
        pytest.exit(
            f"No hay Postgres escuchando en {PG_URL_TEST} ({e.__class__.__name__}). "
            "Levantalo con `npx supabase start`.",
            returncode=1,
        )
    try:
        faltantes = [
            t for t in TABLAS
            if not conn.execute("SELECT to_regclass(%s) AS t", (t,)).fetchone()["t"]
        ]
    finally:
        conn.close()
    if faltantes:
        pytest.exit(
            f"La base en {PG_URL_TEST} no es la de este proyecto: le faltan "
            f"{len(faltantes)} de las {len(TABLAS)} tablas del esquema (por "
            f"ejemplo {', '.join(faltantes[:3])}).\n"
            "Suele pasar cuando otro proyecto de Supabase quedó levantado y se "
            "adueñó del puerto. Fijate con `docker ps` quién tiene el 54422, "
            "levantá el Postgres de este proyecto con `npx supabase start`, o "
            "apuntá la suite a otra base con DATABASE_URL_TEST.",
            returncode=1,
        )


@pytest.fixture(scope="session")
def pg_url():
    return PG_URL_TEST


# Supabase local (el que levanta `npx supabase start`). Estas claves son los
# valores por defecto de la CLI: son idénticas en cualquier máquina, no dan
# acceso a nada real y no son un secreto. Quedan overrideables por si alguien
# corre la suite contra otra instancia.
SUPABASE_URL_TEST = os.environ.get("SUPABASE_URL_TEST", "http://127.0.0.1:54421")
SUPABASE_ANON_KEY_TEST = os.environ.get(
    "SUPABASE_ANON_KEY_TEST", "sb_publishable_ACJWlzQHlZjBrEguHvfOxg_3BJgxAaH"
)
SUPABASE_SERVICE_KEY_TEST = os.environ.get(
    "SUPABASE_SERVICE_ROLE_KEY_TEST", "sb_secret_N7UND0UgjKTVK-Uodkm0Hg_xSvEMPvz"
)

# El código de la app lee estas tres del entorno. Se apuntan al Supabase local
# para toda la suite, sin pisar lo que ya hubiera definido (por ejemplo un
# .env con credenciales del proyecto en la nube, contra el que NO queremos
# correr tests).
os.environ.setdefault("SUPABASE_URL", SUPABASE_URL_TEST)
os.environ.setdefault("SUPABASE_ANON_KEY", SUPABASE_ANON_KEY_TEST)
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", SUPABASE_SERVICE_KEY_TEST)


def _borrar_cuentas_de_prueba():
    """Vacía Supabase Auth de la instancia de pruebas."""
    from supabase import create_client

    admin = create_client(SUPABASE_URL_TEST, SUPABASE_SERVICE_KEY_TEST)
    try:
        for cuenta in admin.auth.admin.list_users():
            admin.auth.admin.delete_user(cuenta.id)
    except Exception:
        pass  # sin Supabase local levantado, los tests de auth ya fallan solos


@pytest.fixture
def crear_usuario(db_conn):
    """Crea un usuario completo: la cuenta en Supabase Auth (donde viven email
    y contraseña) más su fila en `usuarios` (el perfil).

    Contra el Supabase Auth LOCAL, no contra un mock: lo que esta migración
    cambia es justamente el diálogo con ese servicio, así que un mock no
    probaría nada de lo que hay que probar.

    `email_confirm=True` es obligatorio -- sin eso la cuenta queda pendiente
    de confirmación por mail y no puede iniciar sesión.

    La limpieza la hace `_limpiar_base_de_pruebas` para TODAS las cuentas, no
    solo las de este fixture: varios tests crean usuarios a través de la
    pantalla `/usuarios/nuevo`, que también deja una cuenta en Supabase.
    """
    from supabase import create_client

    admin = create_client(SUPABASE_URL_TEST, SUPABASE_SERVICE_KEY_TEST)

    def _crear(username, password="clave-de-prueba-123", rol="empleado",
               nombre="Usuario Test", activo=True, debe_cambiar_password=False,
               email=None):
        email = email or f"{username}@ejemplo.test"
        cuenta = admin.auth.admin.create_user(
            {"email": email, "password": password, "email_confirm": True}
        )
        usuario_id = cuenta.user.id
        db_conn.execute(
            """INSERT INTO usuarios (id, username, email, nombre, rol,
                                     activo, debe_cambiar_password)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (usuario_id, username, email, nombre, rol, activo, debe_cambiar_password),
        )
        db_conn.commit()
        return {"id": usuario_id, "username": username, "email": email,
                "password": password, "rol": rol, "nombre": nombre}

    return _crear


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

    Y borra las cuentas de Supabase Auth, que el TRUNCATE no alcanza: viven
    en otro servicio. Se borran TODAS y no solo las que creó un fixture,
    porque varios tests dan de alta usuarios a través de `/usuarios/nuevo`,
    que también crea su cuenta. Sin esto, la segunda corrida de la suite
    falla con "email ya registrado". Es seguro porque `pytest_configure` ya
    verificó que estamos apuntando a la base de pruebas de este proyecto.
    """
    yield
    _borrar_cuentas_de_prueba()
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
