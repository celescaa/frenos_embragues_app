"""Único punto de contacto con Supabase Auth.

Supabase Auth guarda el email y la contraseña; todo lo demás (username,
nombre, rol, bloqueo por intentos fallidos, cambio obligatorio de contraseña)
sigue en la tabla `usuarios` de este sistema. Flask sigue manejando la sesión
con su cookie firmada, así que la protección CSRF queda intacta.

Mismo criterio defensivo que `facturacion_afip.py` y `tienda_pagos.py`: nada
de acá deja escapar excepciones de red o de configuración. Un login que falla
tiene que mostrar "usuario o contraseña incorrectos", nunca una página de
error con el detalle de por qué.
"""
import os

from supabase import Client, create_client
from supabase_auth.errors import AuthApiError

# Las variables se leen dentro de cada función, no una vez al importar el
# módulo: así el valor vigente es siempre el actual, sin depender de en qué
# orden se importaron las cosas (los tests apuntan al Supabase local, y en
# Vercel el entorno se arma antes del import pero no hay motivo para atarse a
# ese detalle).
def _url():
    return os.environ.get("SUPABASE_URL", "")


def _clave_publica():
    return os.environ.get("SUPABASE_ANON_KEY", "")


def _clave_de_servicio():
    return os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def configurado():
    return bool(_url() and _clave_publica())


def cliente_publico() -> Client:
    """Cliente con la clave pública: alcanza para iniciar sesión."""
    return create_client(_url(), _clave_publica())


def cliente_admin() -> Client:
    """Cliente con la clave de servicio, que SALTEA todas las políticas de la
    base. Solo para las operaciones de /usuarios (alta, reseteo, baja). Nunca
    en un camino que llegue al navegador."""
    return create_client(_url(), _clave_de_servicio())


def verificar_credenciales(email, password):
    """Devuelve el id (UUID como string) si el email y la contraseña son
    correctos, o None en cualquier otro caso.

    Nunca lanza: quien llama solo necesita saber si entró o no. Distinguir
    hacia afuera entre "contraseña incorrecta" y "Supabase no responde" sería
    darle información de más a quien está probando contraseñas.
    """
    if not configurado() or not email or not password:
        return None
    try:
        respuesta = cliente_publico().auth.sign_in_with_password(
            {"email": email, "password": password}
        )
    except AuthApiError:
        return None  # credenciales inválidas, cuenta sin confirmar, etc.
    except Exception:
        return None  # red, configuración, servicio caído
    return respuesta.user.id if respuesta and respuesta.user else None


def cambiar_password(usuario_id, nueva):
    """Cambia la contraseña de una cuenta. Devuelve True si salió bien.

    Usa la admin API y no `update_user`, porque este sistema no guarda la
    sesión de Supabase del usuario: solo le pregunta por sus credenciales en
    el momento del login, y sin sesión activa no hay contra quién aplicar
    `update_user`.

    Ojo con el orden en quien llama: esto tiene que ir DESPUÉS de validar el
    largo y la coincidencia. Si se llamara antes, una contraseña rechazada por
    el sistema ya habría quedado guardada del lado de Supabase, y el usuario
    terminaría con una contraseña que la pantalla le dijo que no aceptaba.
    """
    if not _clave_de_servicio() or not _url():
        return False
    try:
        cliente_admin().auth.admin.update_user_by_id(str(usuario_id), {"password": nueva})
    except Exception:
        return False
    return True


def crear_cuenta(email, password):
    """Crea la cuenta en Supabase Auth y devuelve su id, o None si falló.

    `email_confirm=True` no es opcional: sin eso la cuenta queda pendiente de
    confirmación por mail y no puede iniciar sesión. Acá el alta la hace un
    administrador del negocio en persona, así que no hay nada que confirmar.

    Quien llama tiene que crear la cuenta ANTES del perfil: si el perfil se
    creara primero y esto fallara, quedaría alguien con rol y permisos pero
    sin forma de autenticarse.
    """
    if not _clave_de_servicio() or not _url():
        return None
    try:
        respuesta = cliente_admin().auth.admin.create_user(
            {"email": email, "password": password, "email_confirm": True}
        )
    except Exception:
        return None  # email inválido, ya registrado, servicio caído
    return respuesta.user.id if respuesta and respuesta.user else None


def borrar_cuenta(usuario_id):
    """Borra la cuenta. La fila de `usuarios` se va sola por ON DELETE CASCADE.

    Se borra la cuenta y NO el perfil por separado: si el DELETE local saliera
    bien y el borrado de la cuenta fallara, quedaría alguien que todavía puede
    autenticarse contra Supabase pero ya no tiene perfil ni rol.
    """
    if not _clave_de_servicio() or not _url():
        return False
    try:
        cliente_admin().auth.admin.delete_user(str(usuario_id))
    except Exception:
        return False
    return True
