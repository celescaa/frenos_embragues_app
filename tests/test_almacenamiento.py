"""Fotos de producto en Supabase Storage.

Contra el Storage local que levanta `npx supabase start`, no contra un mock.

En Vercel no hay disco: una foto guardada en el sistema de archivos desaparece
en el siguiente arranque en frío, y mientras tanto las otras invocaciones de la
función ni siquiera la ven — o sea que la foto que acaba de subir un empleado
puede no existir para el cliente que entra a la tienda un segundo después.
"""
import io

import pytest
from werkzeug.datastructures import FileStorage

from core import almacenamiento
from core.app import eliminar_imagen_producto, guardar_imagen_producto

# PNG mínimo válido (8 bytes de firma alcanzan: acá no se valida el contenido,
# solo la extensión, igual que hacía la versión que guardaba en disco).
PNG = bytes.fromhex("89504e470d0a1a0a")


@pytest.fixture(autouse=True)
def bucket_de_pruebas():
    """El bucket lo crea a mano quien despliega (ver README). Acá se crea si
    falta, para que la suite corra en una instancia local recién levantada."""
    almacenamiento.asegurar_bucket()
    yield


def test_guardar_una_foto_la_deja_en_una_url_publica():
    archivo = FileStorage(
        stream=io.BytesIO(PNG), filename="foto.png", content_type="image/png"
    )
    nombre = guardar_imagen_producto(4242, archivo)
    assert nombre == "producto_4242.png"

    url = almacenamiento.url_publica(nombre)
    assert nombre in url
    assert url.startswith("http")

    eliminar_imagen_producto(nombre)


def test_reemplazar_la_foto_de_un_producto_funciona():
    """El nombre del archivo se deriva del id del producto, así que cambiarle
    la foto a un producto sube el MISMO nombre. Sin `upsert`, Storage lo
    rechaza por duplicado y la foto nueva se pierde sin avisar."""
    primera = FileStorage(
        stream=io.BytesIO(PNG), filename="a.png", content_type="image/png"
    )
    assert guardar_imagen_producto(777, primera) == "producto_777.png"

    segunda = FileStorage(
        stream=io.BytesIO(PNG + b"distinto"), filename="b.png", content_type="image/png"
    )
    assert guardar_imagen_producto(777, segunda) == "producto_777.png", (
        "el reemplazo falló: probablemente falte upsert"
    )
    eliminar_imagen_producto("producto_777.png")


def test_solo_se_aceptan_las_extensiones_permitidas():
    archivo = FileStorage(
        stream=io.BytesIO(b"no soy una imagen"), filename="virus.exe",
        content_type="application/octet-stream",
    )
    assert guardar_imagen_producto(1, archivo) is None


def test_sin_archivo_no_pasa_nada():
    assert guardar_imagen_producto(1, None) is None


def test_borrar_una_foto_que_no_existe_no_rompe():
    """El borrado corre cuando se reemplaza una foto; que la anterior ya no
    esté no puede tumbar el guardado del producto."""
    eliminar_imagen_producto("producto_inexistente_99999.png")
    eliminar_imagen_producto(None)


def test_la_url_de_un_producto_sin_foto_queda_vacia():
    """Los templates la usan directo en el src de la imagen: si devolviera una
    URL a medio armar, el navegador pediría una dirección inválida en cada
    producto sin foto."""
    assert almacenamiento.url_publica(None) == ""
    assert almacenamiento.url_publica("") == ""
