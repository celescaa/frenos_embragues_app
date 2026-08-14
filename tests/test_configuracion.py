"""Configuración de despliegue: clave de sesión, proxy y arranque del módulo.

En Vercel no hay disco persistente ni conexión directa del navegador: la app
corre detrás de un proxy y el módulo se vuelve a importar en cada arranque en
frío. Estos tests fijan las consecuencias de eso, que no se notan corriendo
local pero rompen (o ensucian la base) en producción.
"""
import importlib
import os

import pytest


def test_la_clave_de_sesion_sale_del_entorno_si_esta_definida(monkeypatch):
    """En producción la clave NO puede salir de un archivo: cada arranque en
    frío generaría una distinta y tiraría abajo todas las sesiones abiertas."""
    monkeypatch.setenv("SECRET_KEY", "clave-de-prueba-no-secreta")
    import core.app
    modulo = importlib.reload(core.app)
    assert modulo.app.secret_key == "clave-de-prueba-no-secreta"


def test_la_app_confia_en_los_headers_del_proxy():
    """Vercel termina el HTTPS en su proxy y reenvía por HTTP. Sin ProxyFix,
    `request.host` sale del header Host crudo (que el cliente puede
    falsificar, y que manejar_csrf_error usa para su chequeo de mismo origen)
    y url_for(_external=True) arma URLs http:// en un sitio https://."""
    from core.app import app
    assert app.wsgi_app.__class__.__name__ == "ProxyFix", (
        "wsgi_app no está envuelto con ProxyFix"
    )


def test_la_cookie_de_sesion_es_segura_cuando_hay_https(monkeypatch):
    """Se activa por variable de entorno y no fijo, porque corriendo local
    (http://127.0.0.1:5050) una cookie "secure" no viajaría nunca y no se
    podría iniciar sesión."""
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "1")
    import core.app
    modulo = importlib.reload(core.app)
    assert modulo.app.config["SESSION_COOKIE_SECURE"] is True


def test_sin_la_variable_la_cookie_no_es_segura(monkeypatch):
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    import core.app
    modulo = importlib.reload(core.app)
    assert modulo.app.config["SESSION_COOKIE_SECURE"] is False


def test_importar_la_app_no_siembra_datos_de_ejemplo(db_conn):
    """En serverless el módulo se importa en cada arranque en frío, y una base
    de producción recién creada está vacía -- que es justo la condición que
    dispara la siembra. Sin esto, el primer visitante del sistema real le
    metería a la base del negocio 5 clientes, 14 productos y 45 ventas de
    mentira."""
    db_conn.execute("TRUNCATE TABLE venta_items, ventas, productos CASCADE")
    db_conn.commit()

    import core.app
    importlib.reload(core.app)

    cuantos = db_conn.execute("SELECT COUNT(*) AS c FROM productos").fetchone()["c"]
    assert cuantos == 0, "importar core.app sembró datos de ejemplo"


def test_sin_secret_key_y_sin_disco_el_error_dice_que_falta_la_variable(tmp_path, monkeypatch):
    """En Vercel el filesystem es de solo lectura. Sin SECRET_KEY, el sistema
    intentaba crear el archivo .secret_key y moría con un PermissionError
    sobre un archivo oculto -- un mensaje que no sugiere en ningún momento
    cuál es la variable que hay que cargar.

    Se corta en vez de seguir con una clave en memoria a propósito: esa clave
    sería distinta en cada arranque en frío, así que las sesiones se cerrarían
    solas y el problema aparecería como "me desloguea todo el tiempo".
    """
    import subprocess
    import sys
    import shutil

    proyecto = tmp_path / "proy"
    shutil.copytree(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        proyecto,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "supabase",
                                      ".pytest_cache", "listas_proveedores"),
    )
    (proyecto / ".secret_key").unlink(missing_ok=True)
    proyecto.chmod(0o555)  # solo lectura, como en Vercel
    try:
        entorno = dict(os.environ)
        entorno.pop("SECRET_KEY", None)
        resultado = subprocess.run(
            [sys.executable, "-c", "from app import app"],
            cwd=proyecto, env=entorno, capture_output=True, text=True,
        )
        assert resultado.returncode != 0
        assert "SECRET_KEY" in resultado.stderr, (
            "el error no nombra la variable que falta:\n" + resultado.stderr[-500:]
        )
    finally:
        proyecto.chmod(0o755)
