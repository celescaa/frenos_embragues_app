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


# ---------------------------------------------------------------------------
# Gestión de usuarios (/usuarios). El alta tiene que dejar la cuenta lista de
# punta a punta: si creara el perfil pero no la cuenta, la persona nueva no
# podría entrar y nadie se enteraría hasta que lo intentara.
# ---------------------------------------------------------------------------
import re


def _sesion_admin(cliente, crear_usuario, username="jefe"):
    admin = crear_usuario(username, rol="admin", password="clave-admin-123")
    cliente.post("/login", data={"username": username, "password": "clave-admin-123"})
    return admin


def _temporal_del_mensaje(datos):
    """La contraseña temporal se muestra una sola vez, en el mensaje."""
    match = re.search(r"temporal:\s*(\S+?)\s", datos.decode())
    assert match, "no se mostró la contraseña temporal"
    return match.group(1)


def test_un_admin_crea_un_usuario_que_puede_entrar(cliente, crear_usuario, db_conn):
    _sesion_admin(cliente, crear_usuario)
    respuesta = cliente.post("/usuarios/nuevo", data={
        "username": "empleado_nuevo", "email": "empleado_nuevo@ejemplo.test",
        "nombre": "Empleado Nuevo", "rol": "empleado",
    }, follow_redirects=True)
    temporal = _temporal_del_mensaje(respuesta.data)

    fila = db_conn.execute(
        "SELECT id, email, debe_cambiar_password FROM usuarios WHERE username=%s",
        ("empleado_nuevo",),
    ).fetchone()
    assert fila is not None, "no se creó el perfil"
    assert fila["email"] == "empleado_nuevo@ejemplo.test"
    assert fila["debe_cambiar_password"] is True

    cliente.get("/logout")
    cliente.post("/login", data={"username": "empleado_nuevo", "password": temporal})
    with cliente.session_transaction() as sesion:
        assert sesion.get("usuario_id") == str(fila["id"])
        assert sesion.get("debe_cambiar_password") is True


def test_no_se_crea_el_perfil_si_falla_la_cuenta(cliente, crear_usuario, db_conn):
    """Un email ya usado hace fallar la creación de la cuenta. El perfil no
    tiene que quedar igual: sería alguien con rol y permisos pero sin forma de
    autenticarse."""
    admin = _sesion_admin(cliente, crear_usuario)
    cliente.post("/usuarios/nuevo", data={
        "username": "colado", "email": admin["email"],
        "nombre": "Colado", "rol": "empleado",
    }, follow_redirects=True)

    fila = db_conn.execute(
        "SELECT id FROM usuarios WHERE username=%s", ("colado",)
    ).fetchone()
    assert fila is None


def test_borrar_un_usuario_borra_tambien_su_cuenta(cliente, crear_usuario, db_conn):
    """Si quedara la cuenta viva sin perfil, esa persona seguiría pudiendo
    autenticarse contra Supabase."""
    _sesion_admin(cliente, crear_usuario)
    victima = crear_usuario("se_va", password="clave-123")

    cliente.post(f"/usuarios/{victima['id']}/eliminar")

    assert db_conn.execute(
        "SELECT id FROM usuarios WHERE id=%s", (victima["id"],)
    ).fetchone() is None

    from core import supabase_auth
    cuentas = supabase_auth.cliente_admin().auth.admin.list_users()
    assert victima["id"] not in [c.id for c in cuentas]


def test_resetear_la_contrasena_da_una_temporal_que_funciona(cliente, crear_usuario, db_conn):
    _sesion_admin(cliente, crear_usuario)
    olvidadizo = crear_usuario("olvidadizo", password="la-que-olvido-123")

    respuesta = cliente.post(
        f"/usuarios/{olvidadizo['id']}/resetear-password", follow_redirects=True
    )
    temporal = _temporal_del_mensaje(respuesta.data)

    cliente.get("/logout")
    cliente.post("/login", data={"username": "olvidadizo", "password": temporal})
    with cliente.session_transaction() as sesion:
        assert sesion.get("usuario_id") == olvidadizo["id"]
        assert sesion.get("debe_cambiar_password") is True


def test_el_reseteo_invalida_la_contrasena_anterior(cliente, crear_usuario):
    """Resetear es lo que hace un admin cuando alguien perdió el acceso o se
    fue: la contraseña vieja tiene que dejar de servir."""
    _sesion_admin(cliente, crear_usuario)
    olvidadizo = crear_usuario("olvidadizo", password="la-que-olvido-123")
    cliente.post(f"/usuarios/{olvidadizo['id']}/resetear-password", follow_redirects=True)

    cliente.get("/logout")
    cliente.post("/login", data={"username": "olvidadizo", "password": "la-que-olvido-123"})
    with cliente.session_transaction() as sesion:
        assert "usuario_id" not in sesion
