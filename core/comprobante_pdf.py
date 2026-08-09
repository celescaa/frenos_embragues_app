"""
Genera el PDF de un comprobante de venta (remito/recibo/Factura A/B), para
adjuntarlo en el mail al cliente (ver envio_mail.py).

Usa xhtml2pdf (pip install xhtml2pdf) en vez de WeasyPrint/wkhtmltopdf a
propósito: es una librería 100% Python (se apoya en reportlab), sin
dependencias de sistema (Pango/Cairo/GTK). Eso importa acá porque este
sistema corre en la compu del negocio, no en un servidor controlado — no
hay que pedirle al hermano que instale nada aparte de `pip install -r
requirements.txt`.

No reutiliza comprobante.html (esa plantilla depende de Bootstrap/CDN y del
navbar de la app, pensada para verse en el navegador) — usa su propia
plantilla standalone `comprobante_pdf.html` con HTML/CSS simple, que es lo
que xhtml2pdf soporta bien.
"""
import os
from flask import render_template
from xhtml2pdf import pisa

# Un nivel arriba de core/: ahí viven static/ y templates/, no adentro de core/.
RAIZ_PROYECTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _link_callback(uri, rel):
    """Resuelve rutas de imágenes para xhtml2pdf: los archivos locales
    (static/...) se convierten a ruta absoluta en disco; las URLs http(s)
    (por ejemplo el QR de ARCA, generado por api.qrserver.com) se dejan
    igual para que xhtml2pdf las baje directo."""
    if uri.startswith("http://") or uri.startswith("https://"):
        return uri
    return os.path.join(RAIZ_PROYECTO, uri.lstrip("/"))


def generar_pdf_comprobante(venta, items, qr_url=None):
    """Devuelve los bytes del PDF del comprobante, o None si falló el render
    (nunca lanza excepción hacia afuera: quien llama decide qué avisar)."""
    try:
        html = render_template("comprobante_pdf.html", venta=venta, items=items, qr_url=qr_url)
        from io import BytesIO
        buffer = BytesIO()
        resultado = pisa.CreatePDF(html, dest=buffer, link_callback=_link_callback)
        if resultado.err:
            return None
        return buffer.getvalue()
    except Exception:
        return None
