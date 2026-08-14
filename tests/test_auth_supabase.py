"""Login contra Supabase Auth, entrando por nombre de usuario o por email.

Contra el Supabase Auth local que levanta `npx supabase start`, no contra
mocks: lo que cambia acá es justamente el diálogo con ese servicio, así que un
mock probaría el mock y no el sistema.

Las tres cosas que Supabase NO trae de fábrica y este sistema conserva —
bloqueo por intentos fallidos, cambio de contraseña obligatorio y los roles —
siguen viviendo en la tabla `usuarios` y tienen su test acá.
"""
import pytest

from core.app import app as flask_app


@pytest.fixture
def cliente():
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        yield c


def test_se_puede_entrar_con_el_nombre_de_usuario(cliente, crear_usuario):
    usuario = crear_usuario("matias", password="clave-correcta-123")
    respuesta = cliente.post(
        "/login", data={"username": "matias", "password": "clave-correcta-123"},
    )
    assert respuesta.status_code == 302
    with cliente.session_transaction() as sesion:
        assert sesion["usuario_id"] == usuario["id"]
        assert sesion["usuario_rol"] == "empleado"


def test_se_puede_entrar_con_el_email(cliente, crear_usuario):
    """Supabase Auth se basa en email; el sistema acepta los dos."""
    usuario = crear_usuario("matias", password="clave-correcta-123")
    respuesta = cliente.post(
        "/login", data={"username": usuario["email"], "password": "clave-correcta-123"},
    )
    assert respuesta.status_code == 302
    with cliente.session_transaction() as sesion:
        assert sesion["usuario_id"] == usuario["id"]


def test_la_contrasena_incorrecta_no_inicia_sesion(cliente, crear_usuario):
    crear_usuario("matias", password="clave-correcta-123")
    respuesta = cliente.post(
        "/login", data={"username": "matias", "password": "clave-equivocada"},
    )
    assert respuesta.status_code == 200
    with cliente.session_transaction() as sesion:
        assert "usuario_id" not in sesion


def test_el_error_no_revela_si_el_usuario_existe(cliente, crear_usuario):
    """Mensajes distintos permitirían averiguar qué usuarios hay cargados
    probando nombres, que es el paso previo a atacar sus contraseñas."""
    crear_usuario("matias", password="clave-correcta-123")
    con_usuario_real = cliente.post(
        "/login", data={"username": "matias", "password": "mal"}
    ).data
    con_usuario_inventado = cliente.post(
        "/login", data={"username": "no_existe_nadie_asi", "password": "mal"}
    ).data
    assert "Usuario o contraseña incorrectos".encode() in con_usuario_real
    assert con_usuario_real == con_usuario_inventado


def test_el_usuario_inactivo_no_puede_entrar(cliente, crear_usuario):
    """Dar de baja a alguien tiene que cerrarle la puerta aunque su cuenta
    siga existiendo del lado de Supabase."""
    crear_usuario("baja", password="clave-correcta-123", activo=False)
    cliente.post("/login", data={"username": "baja", "password": "clave-correcta-123"})
    with cliente.session_transaction() as sesion:
        assert "usuario_id" not in sesion


def test_se_bloquea_tras_cinco_intentos_fallidos(cliente, crear_usuario, db_conn):
    """El bloqueo es nuestro, no de Supabase: se conserva tal cual estaba."""
    usuario = crear_usuario("matias", password="clave-correcta-123")
    for _ in range(5):
        cliente.post("/login", data={"username": "matias", "password": "mal"})

    fila = db_conn.execute(
        "SELECT intentos_fallidos, bloqueado_hasta FROM usuarios WHERE id=%s",
        (usuario["id"],),
    ).fetchone()
    assert fila["intentos_fallidos"] >= 5
    assert fila["bloqueado_hasta"] is not None

    # Y con la contraseña BUENA tampoco entra mientras dure el bloqueo.
    cliente.post("/login", data={"username": "matias", "password": "clave-correcta-123"})
    with cliente.session_transaction() as sesion:
        assert "usuario_id" not in sesion


def test_un_login_exitoso_limpia_los_intentos_fallidos(cliente, crear_usuario, db_conn):
    """Si no se limpiaran, cinco errores de tipeo repartidos a lo largo de
    semanas terminarían bloqueando a alguien que nunca falló dos veces
    seguidas."""
    usuario = crear_usuario("matias", password="clave-correcta-123")
    cliente.post("/login", data={"username": "matias", "password": "mal"})
    cliente.post("/login", data={"username": "matias", "password": "clave-correcta-123"})
    fila = db_conn.execute(
        "SELECT intentos_fallidos FROM usuarios WHERE id=%s", (usuario["id"],)
    ).fetchone()
    assert fila["intentos_fallidos"] == 0


def test_quien_debe_cambiar_la_contrasena_va_a_esa_pantalla(cliente, crear_usuario):
    usuario = crear_usuario("nuevo", password="temporal-123", debe_cambiar_password=True)
    respuesta = cliente.post(
        "/login", data={"username": "nuevo", "password": "temporal-123"}
    )
    assert respuesta.status_code == 302
    assert "/cambiar-password" in respuesta.headers["Location"]
    with cliente.session_transaction() as sesion:
        assert sesion["debe_cambiar_password"] is True


def test_cambiar_la_contrasena_permite_entrar_con_la_nueva(cliente, crear_usuario):
    usuario = crear_usuario("matias", password="clave-vieja-123")
    cliente.post("/login", data={"username": "matias", "password": "clave-vieja-123"})
    cliente.post("/cambiar-password", data={
        "actual": "clave-vieja-123", "nueva": "clave-nueva-456", "confirmar": "clave-nueva-456",
    })
    cliente.get("/logout")

    cliente.post("/login", data={"username": "matias", "password": "clave-nueva-456"})
    with cliente.session_transaction() as sesion:
        assert sesion.get("usuario_id") == usuario["id"]


def test_no_se_puede_cambiar_sin_saber_la_contrasena_actual(cliente, crear_usuario):
    """Si no se validara, alguien que encuentra una sesión abierta se queda
    con la cuenta cambiándole la contraseña al dueño."""
    crear_usuario("matias", password="clave-vieja-123")
    cliente.post("/login", data={"username": "matias", "password": "clave-vieja-123"})
    respuesta = cliente.post("/cambiar-password", data={
        "actual": "no-es-la-actual", "nueva": "clave-nueva-456", "confirmar": "clave-nueva-456",
    })
    assert "actual no es correcta".encode() in respuesta.data

    cliente.get("/logout")
    cliente.post("/login", data={"username": "matias", "password": "clave-nueva-456"})
    with cliente.session_transaction() as sesion:
        assert "usuario_id" not in sesion, "la contraseña se cambió sin validar la actual"


def test_el_cambio_obligatorio_no_pide_la_contrasena_actual(cliente, crear_usuario):
    """Tras un reseteo el usuario entra con una temporal y tiene que cambiarla;
    pedirle la 'actual' ahí sería redundante (acaba de escribirla al entrar)."""
    crear_usuario("nuevo", password="temporal-123", debe_cambiar_password=True)
    cliente.post("/login", data={"username": "nuevo", "password": "temporal-123"})
    cliente.post("/cambiar-password", data={
        "actual": "", "nueva": "elegida-por-mi-456", "confirmar": "elegida-por-mi-456",
    })
    cliente.get("/logout")

    cliente.post("/login", data={"username": "nuevo", "password": "elegida-por-mi-456"})
    with cliente.session_transaction() as sesion:
        assert "usuario_id" in sesion
        assert sesion["debe_cambiar_password"] is False


def test_una_contrasena_corta_no_se_guarda_en_supabase(cliente, crear_usuario):
    """El orden importa: si se mandara a Supabase antes de validar el largo,
    quedaría guardada allá y rechazada acá -- el usuario terminaría con una
    contraseña que el sistema le dijo que no aceptaba."""
    crear_usuario("matias", password="clave-vieja-123")
    cliente.post("/login", data={"username": "matias", "password": "clave-vieja-123"})
    respuesta = cliente.post("/cambiar-password", data={
        "actual": "clave-vieja-123", "nueva": "corta", "confirmar": "corta",
    })
    assert "al menos 8".encode() in respuesta.data

    cliente.get("/logout")
    cliente.post("/login", data={"username": "matias", "password": "corta"})
    with cliente.session_transaction() as sesion:
        assert "usuario_id" not in sesion
