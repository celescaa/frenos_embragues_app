"""
Envío del comprobante de venta por mail al cliente, como PDF adjunto.

Mismo criterio defensivo que facturacion_afip.py y tienda_pagos.py: nunca
lanza una excepción hacia afuera. Si falta configuración o algo falla al
mandar el mail, devuelve (False, "motivo") para que quien llama lo muestre
como aviso, sin romper nada de lo ya guardado (la venta ya está registrada
antes de intentar mandar el mail).

Configuración (variables de entorno — ver .env.example):
  SMTP_HOST      - servidor SMTP (ej: smtp.gmail.com).
  SMTP_PORT      - puerto (587 para STARTTLS, 465 para SSL). Default: 587.
  SMTP_USER      - usuario/cuenta de mail que manda los comprobantes.
  SMTP_PASSWORD  - contraseña. Con Gmail tiene que ser una "contraseña de
                   aplicación" (myaccount.google.com/apppasswords), no la
                   contraseña normal de la cuenta.
  SMTP_FROM      - remitente que ve el cliente. Si no se completa, se usa
                   SMTP_USER.
  SMTP_USE_SSL   - "1" para conectar por SSL directo (puerto 465).
                   Vacío o cualquier otro valor = STARTTLS (puerto 587).
"""
import os
import smtplib
from email.message import EmailMessage

from . import comprobante_pdf


def mail_configurado():
    """True si hay credenciales SMTP configuradas por variable de entorno."""
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD"))


def enviar_comprobante_por_mail(venta, items, destinatario, qr_url=None, negocio=None):
    """Genera el PDF del comprobante y lo manda por mail a `destinatario`.

    Devuelve (ok: bool, error: str|None). No lanza excepciones."""
    if not destinatario:
        return False, "El cliente no tiene un email cargado."

    if not mail_configurado():
        return False, "Falta configurar el envío de mail (ver .env.example: SMTP_HOST, SMTP_USER, SMTP_PASSWORD)."

    pdf_bytes = comprobante_pdf.generar_pdf_comprobante(venta, items, qr_url)
    if not pdf_bytes:
        return False, "No se pudo generar el PDF del comprobante."

    nombre_negocio = (negocio or {}).get("nombre", "el negocio")

    try:
        msg = EmailMessage()
        msg["Subject"] = f"{venta['tipo_comprobante']} N° {venta['numero_comprobante']} - {nombre_negocio}"
        msg["From"] = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER")
        msg["To"] = destinatario
        msg.set_content(
            f"Hola{', ' + venta['cliente_nombre'] if venta['cliente_nombre'] else ''}!\n\n"
            f"Te adjuntamos el comprobante de tu compra en {nombre_negocio}.\n\n"
            f"{venta['tipo_comprobante']} N° {venta['numero_comprobante']} — Total: ${venta['total']:,.2f}\n\n"
            "Gracias por tu compra."
        )
        nombre_archivo = f"comprobante_{venta['numero_comprobante'] or venta['id']}.pdf"
        msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=nombre_archivo)

        host = os.environ.get("SMTP_HOST")
        port = int(os.environ.get("SMTP_PORT", "587"))
        usuario = os.environ.get("SMTP_USER")
        password = os.environ.get("SMTP_PASSWORD")
        usar_ssl = os.environ.get("SMTP_USE_SSL", "").strip() == "1"

        if usar_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=20) as server:
                server.login(usuario, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as server:
                server.starttls()
                server.login(usuario, password)
                server.send_message(msg)

        return True, None
    except Exception as e:
        return False, str(e)
