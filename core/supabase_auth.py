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
