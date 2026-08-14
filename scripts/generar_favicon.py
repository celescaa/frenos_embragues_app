"""
Genera el favicon del sistema a partir del logo de la marca.

Los archivos que produce ya están commiteados en static/img/, así que este
script solo hace falta si cambia el logo. Uso (desde la raíz del proyecto):

    python scripts/generar_favicon.py

Genera, todos sobre el negro de la marca (--si-black):

    static/img/favicon.ico          16/32/48 px en un solo archivo
    static/img/favicon-32.png       pestaña del navegador
    static/img/favicon-192.png      Android
    static/img/apple-touch-icon.png 180 px, "Agregar a inicio" en iPhone

Los <link> que apuntan a estos archivos viven en templates/_favicon.html,
incluido desde los tres templates que tienen <head> propio (base.html,
base_publica.html y login.html).

Necesita Pillow (`pip install pillow`), que a propósito NO está en
requirements.txt: la app no la usa en runtime y ese archivo es el que
instala Vercel en cada deploy.
"""

import sys
from pathlib import Path

from PIL import Image, ImageEnhance

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
CARPETA_IMG = RAIZ_PROYECTO / "static" / "img"
LOGO = CARPETA_IMG / "logo_icon_soft.png"

NEGRO = (17, 17, 17, 255)  # --si-black, el mismo de templates/base.html


def preparar_logo():
    """Deja el logo cuadrado y sin el halo difuso que trae el PNG original."""
    logo = Image.open(LOGO).convert("RGBA")

    # El PNG trae margen transparente alrededor: sin recortarlo, el disco
    # queda chico dentro del ícono y se pierde todavía más a 16 px.
    logo = logo.crop(logo.getbbox())
    lado = max(logo.size)
    cuadrado = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    cuadrado.paste(logo, ((lado - logo.width) // 2, (lado - logo.height) // 2), logo)

    # El logo tiene un halo blanco difuso alrededor del disco. En tamaños
    # chicos ese halo empasta las aspas y el ícono se ve como una mancha
    # gris, así que se corta con una curva dura sobre el canal alfa y queda
    # solo el trazo nítido del disco.
    r, g, b, a = cuadrado.split()
    a = a.point(lambda v: 0 if v < 120 else min(255, int((v - 120) * 2.6)))
    return Image.merge("RGBA", (r, g, b, a))


def render(base, tam, margen=0.04):
    """Ícono cuadrado: el disco de la marca sobre el negro de la marca."""
    fondo = Image.new("RGBA", (tam, tam), NEGRO)
    interior = int(tam * (1 - margen * 2))
    disco = base.resize((interior, interior), Image.LANCZOS)
    disco = ImageEnhance.Sharpness(disco).enhance(1.6)
    pos = (tam - interior) // 2
    fondo.paste(disco, (pos, pos), disco)
    return fondo


def main():
    if not LOGO.exists():
        print(f"No encuentro el logo en {LOGO}")
        return 1

    base = preparar_logo()
    render(base, 180).save(CARPETA_IMG / "apple-touch-icon.png")
    render(base, 192).save(CARPETA_IMG / "favicon-192.png")
    render(base, 32).save(CARPETA_IMG / "favicon-32.png")
    render(base, 48).save(
        CARPETA_IMG / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)]
    )

    print(f"Favicon generado en {CARPETA_IMG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
