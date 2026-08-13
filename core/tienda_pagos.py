"""
Cobro online de la tienda pública vía Mercado Pago Checkout Pro.

Flujo (ver también las rutas /tienda/* en app.py):
  1. El comprador arma el carrito (sesión) y completa sus datos de contacto
     en /tienda/checkout.
  2. Se crea un `pedido_web` (estado 'pendiente_pago') con sus items y se
     arma una "preferencia" de pago acá (`crear_preferencia`). Se redirige
     al comprador a la URL de Checkout Pro que devuelve Mercado Pago.
  3. Mercado Pago notifica el resultado por webhook (nunca hay que confiar
     en la URL de vuelta del navegador). La ruta /webhooks/mercadopago en
     app.py llama a `obtener_pago` para confirmar el estado real del pago,
     y si está aprobado, genera ahí la venta real (mismas tablas que una
     venta del local — una sola fuente de verdad de stock).

Configuración (variables de entorno, ver .env.example):
  MERCADOPAGO_ACCESS_TOKEN - access token de la cuenta de Mercado Pago del
                              negocio (obligatorio para poder cobrar).
  STORE_BASE_URL            - URL pública (https) donde corre el sistema,
                              por ejemplo https://frenosi.com.ar o una URL
                              de ngrok mientras se prueba en local. Mercado
                              Pago la necesita para las back_urls y para
                              poder llamar al webhook — nunca puede ser
                              127.0.0.1.
  MERCADOPAGO_WEBHOOK_SECRET - "Clave secreta" configurada en el panel de
                              Mercado Pago (Tus integraciones > Webhooks)
                              para validar la firma de las notificaciones.
                              Opcional pero recomendada.

Mientras falte el access_token o STORE_BASE_URL, la tienda sigue mostrando
el catálogo con normalidad: solo el checkout avisa que el cobro online
todavía no está disponible, sin romper nada.
"""
import os

from . import database as db


def tienda_configurada():
    """True si hay lo mínimo para poder armar un cobro: token + URL pública."""
    return bool(os.environ.get("MERCADOPAGO_ACCESS_TOKEN")) and bool(os.environ.get("STORE_BASE_URL"))


def get_mp_sdk():
    """Devuelve un cliente de Mercado Pago, o None si falta el access_token."""
    access_token = os.environ.get("MERCADOPAGO_ACCESS_TOKEN")
    if not access_token:
        return None
    import mercadopago  # import diferido: no hace falta si no está configurado
    return mercadopago.SDK(access_token)


def crear_preferencia(pedido_id):
    """Crea la preferencia de Checkout Pro para un pedido_web y guarda su id.

    Devuelve la URL a la que hay que redirigir al comprador (init_point en
    producción, sandbox_init_point si MERCADOPAGO_PRODUCTION no está en "1"),
    o None si no está configurado o algo falla (el pedido queda en
    'pendiente_pago' para reintentar).
    """
    if not tienda_configurada():
        return None

    base_url = os.environ.get("STORE_BASE_URL").rstrip("/")
    sdk = get_mp_sdk()

    conn = db.get_connection()
    try:
        pedido = conn.execute("SELECT * FROM pedidos_web WHERE id=%s", (pedido_id,)).fetchone()
        items_db = conn.execute(
            """SELECT pwi.*, p.nombre AS producto_nombre
               FROM pedido_web_items pwi JOIN productos p ON p.id = pwi.producto_id
               WHERE pwi.pedido_id=%s""",
            (pedido_id,),
        ).fetchall()
        if not pedido or not items_db:
            return None

        preference_data = {
            "items": [
                {
                    "title": it["producto_nombre"],
                    "quantity": it["cantidad"],
                    "unit_price": float(it["precio_unitario"]),
                    "currency_id": "ARS",
                }
                for it in items_db
            ],
            "payer": {
                "name": pedido["nombre_cliente"],
                "email": pedido["email"] or None,
                "phone": {"number": pedido["telefono"]} if pedido["telefono"] else None,
            },
            "back_urls": {
                "success": f"{base_url}/tienda/pedido/{pedido_id}/exito",
                "pending": f"{base_url}/tienda/pedido/{pedido_id}/pendiente",
                "failure": f"{base_url}/tienda/pedido/{pedido_id}/fallo",
            },
            "auto_return": "approved",
            "notification_url": f"{base_url}/webhooks/mercadopago",
            "external_reference": str(pedido_id),
            "statement_descriptor": "REPUESTOS SAN IGNACIO",
        }

        resultado = sdk.preference().create(preference_data)
        preference = resultado.get("response", {})
        preference_id = preference.get("id")
        if not preference_id:
            return None

        conn.execute("UPDATE pedidos_web SET mp_preference_id=%s WHERE id=%s", (preference_id, pedido_id))
        conn.commit()

        production = os.environ.get("MERCADOPAGO_PRODUCTION", "").strip() == "1"
        return preference.get("init_point") if production else preference.get("sandbox_init_point")
    except Exception:
        return None
    finally:
        conn.close()


def obtener_pago(payment_id):
    """Consulta un pago por id contra la API de Mercado Pago. Devuelve el dict de respuesta o None."""
    sdk = get_mp_sdk()
    if not sdk:
        return None
    try:
        resultado = sdk.payment().get(payment_id)
        return resultado.get("response")
    except Exception:
        return None


def validar_firma_webhook(x_signature, x_request_id, data_id):
    """Valida la firma de una notificación de webhook si hay un secreto configurado.

    Si MERCADOPAGO_WEBHOOK_SECRET no está configurado, no se puede validar
    (se avisa en el log del servidor) pero no se rechaza la notificación
    para no bloquear el flujo mientras se termina de configurar todo.
    """
    secret = os.environ.get("MERCADOPAGO_WEBHOOK_SECRET")
    if not secret:
        return True, "sin validar (falta MERCADOPAGO_WEBHOOK_SECRET)"

    from mercadopago.webhook import WebhookSignatureValidator, InvalidWebhookSignatureError
    try:
        WebhookSignatureValidator.validate(x_signature, x_request_id, data_id, secret)
        return True, "firma válida"
    except InvalidWebhookSignatureError as e:
        return False, "firma inválida (%s)" % e.reason.value
