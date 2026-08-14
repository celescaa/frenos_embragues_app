"""Fotos de producto en Supabase Storage.

En Vercel no hay disco persistente: una foto guardada en el sistema de
archivos desaparece en el siguiente arranque en frío, y mientras tanto las
otras invocaciones de la función ni siquiera la ven — o sea que la foto que
acaba de subir un empleado puede no existir para el cliente que entra a la
tienda un segundo después.

El bucket es público porque las fotos se muestran en la tienda online, que no
tiene login. Lo que se sube son fotos de repuestos: no hay nada sensible.

Mismo criterio defensivo que el resto de los módulos que hablan con servicios
externos (`facturacion_afip.py`, `tienda_pagos.py`, `supabase_auth.py`): nada
de acá lanza excepciones hacia afuera. Que falle la subida de una foto no
puede impedir guardar el producto.
"""
import os

from supabase import create_client

BUCKET = "productos"


def _url():
    return os.environ.get("SUPABASE_URL", "")


def _clave_de_servicio():
    return os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def configurado():
    return bool(_url() and _clave_de_servicio())


def _bucket():
    return create_client(_url(), _clave_de_servicio()).storage.from_(BUCKET)


def asegurar_bucket():
    """Crea el bucket si no existe. Lo normal es crearlo una vez desde el
    panel de Supabase (ver README); esto está para que la suite corra contra
    una instancia local recién levantada sin pasos manuales."""
    if not configurado():
        return False
    try:
        cliente = create_client(_url(), _clave_de_servicio())
        existentes = [b.name for b in cliente.storage.list_buckets()]
        if BUCKET not in existentes:
            cliente.storage.create_bucket(BUCKET, options={"public": True})
    except Exception:
        return False
    return True


def subir_imagen(nombre_archivo, contenido, content_type):
    """Sube (o reemplaza) una imagen. Devuelve True si salió bien.

    `upsert` es necesario: el nombre del archivo se deriva del id del producto
    (`producto_42.png`), así que cambiarle la foto a un producto sube el mismo
    nombre. Sin upsert, Storage lo rechaza por duplicado y la foto nueva se
    pierde sin que nadie se entere.
    """
    if not configurado():
        return False
    try:
        _bucket().upload(
            nombre_archivo,
            contenido,
            {"content-type": content_type or "application/octet-stream",
             "upsert": "true"},
        )
    except Exception:
        return False
    return True


def borrar_imagen(nombre_archivo):
    if not nombre_archivo or not configurado():
        return False
    try:
        _bucket().remove([nombre_archivo])
    except Exception:
        return False
    return True


def url_publica(nombre_archivo):
    """URL pública de una foto, o cadena vacía si el producto no tiene foto.

    Los templates la usan directo en el `src` de la imagen: devolver una URL a
    medio armar haría que el navegador pidiera una dirección inválida por cada
    producto sin foto.
    """
    if not nombre_archivo:
        return ""
    return f"{_url()}/storage/v1/object/public/{BUCKET}/{nombre_archivo}"
