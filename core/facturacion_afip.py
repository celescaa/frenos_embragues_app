"""
Facturación electrónica AFIP/ARCA vía Afip SDK (https://afipsdk.com).

El negocio es **Responsable Inscripto** (alta IVA 12-2024, ver CLAUDE.md),
no monotributista — corregido el 09/08/2026, esta era una asunción
equivocada de una versión anterior de este módulo, que solo emitía
Factura C. Como Responsable Inscripto, el comprobante correcto depende de
la condición frente al IVA del receptor:
  - **Factura A**: receptor Responsable Inscripto con CUIT cargado (ARCA
    exige CUIT para Factura A, no alcanza con DNI).
  - **Factura B**: cualquier otro caso (Consumidor Final, Monotributista,
    Exento, o sin CUIT/DNI cargado).
Las dos discriminan IVA (tasa general 21%) sobre el precio final que ya
tiene el sistema (`precio_venta`/`total` se asumen con IVA incluido, como
se muestra habitualmente al público).

Regla de negocio (decidida con Celes, ver CLAUDE.md): las ventas en efectivo
generan el remito/recibo interno de siempre (ya implementado). Las ventas con
tarjeta o transferencia generan además una Factura A o B electrónica
autorizada por ARCA (con CAE), según a quién se le vende.

Limitación conocida: no hay forma de consultar el padrón de AFIP desde acá,
así que "es Responsable Inscripto" se determina por lo que se carga a mano
en `clientes.condicion_iva` (o `tercero_condicion_iva` en un cargo de cuenta
corriente) — si se carga mal (ej. un CUIT de un monotributista marcado como
Responsable Inscripto), la factura sale con el tipo equivocado. No es
responsabilidad de este módulo validarlo contra AFIP.

Configuración (variables de entorno — ver .env.example, nunca hardcodear
ni pegar en el chat):
  AFIPSDK_ACCESS_TOKEN  - token de la cuenta creada en https://app.afipsdk.com
                          (obligatorio para poder facturar).
  AFIPSDK_CUIT          - CUIT a facturar, sin guiones. Default: CUIT de
                          prueba compartido de Afip SDK (modo desarrollo).
  AFIPSDK_PRODUCTION    - "1" para facturar en producción (además hace falta
                          certificado/clave reales). Cualquier otro valor
                          (o ausente) usa el ambiente de homologación (test).
  AFIPSDK_PUNTO_VENTA   - punto de venta de ARCA a usar. Default: 1.
  AFIPSDK_CERT / AFIPSDK_KEY - certificado y clave, solo hacen falta para
                          facturar en producción con el CUIT real.

Mientras no haya un AFIPSDK_ACCESS_TOKEN configurado, emitir_factura() no
intenta ninguna llamada de red: deja la venta marcada como
facturacion_estado='sin_configurar' y NUNCA bloquea ni revierte la venta ya
registrada en el sistema.
"""
import os
import base64
import json
from datetime import datetime

from . import database as db

# CUIT de prueba compartido por Afip SDK para el ambiente de desarrollo
# (homologación). Sirve para programar y probar sin certificado real, pero
# igual hace falta un access_token real de una cuenta en app.afipsdk.com.
CUIT_PRUEBA_AFIPSDK = "20409378472"
PUNTO_VENTA_DEFAULT = 1

CBTE_TIPO_FACTURA_A = 1
CBTE_TIPO_FACTURA_B = 6
CBTE_TIPO_POR_NOMBRE = {"Factura A": CBTE_TIPO_FACTURA_A, "Factura B": CBTE_TIPO_FACTURA_B}

# Tasa general de IVA (21%) y el Id de esa alícuota en la tabla
# FEParamGetTiposIva de ARCA. Simplificación: todo el catálogo se factura a
# la tasa general — si algún producto tuviera otra alícuota (10.5%/27%) habría
# que discriminarlo aparte por ítem, no soportado hoy.
ALICUOTA_IVA = 0.21
IVA_ALICUOTA_ID_ARCA = 5

# Monto a partir del cual ARCA exige identificar al receptor (no alcanza con
# Consumidor Final, hace falta CUIT/DNI cargado). Este valor lo fija
# AFIP/ARCA por resolución y cambia periódicamente — revisar contra la
# normativa vigente antes de confiar en él en producción. Usado por
# core/app.py al cargar un cargo de cuenta corriente (ver /clientes/<id>/cuenta-corriente).
UMBRAL_IDENTIFICACION_RECEPTOR = 419405

# Tipos de documento del receptor (tabla FEParamGetTiposDoc de ARCA)
DOC_TIPO_CUIT = 80
DOC_TIPO_DNI = 96
DOC_TIPO_CONSUMIDOR_FINAL = 99

# Condición frente al IVA del receptor (obligatorio en comprobantes desde la
# RG 5259/2022, tabla CondicionIVAReceptorId de ARCA). Solo se ofrecen las
# condiciones relevantes para un negocio chico — Proveedor/Cliente del
# Exterior, Liberado Ley 19.640, etc. no aplican acá.
CONDICION_IVA_MAP = {
    "responsable_inscripto": 1,
    "exento": 4,
    "consumidor_final": 5,
    "monotributista": 6,
}
# (valor, etiqueta) para los <select> de clientes/cuenta corriente.
CONDICIONES_IVA = [
    ("responsable_inscripto", "Responsable Inscripto"),
    ("monotributista", "Monotributista"),
    ("consumidor_final", "Consumidor Final"),
    ("exento", "Exento"),
]


def afip_configurado():
    """True si hay un access_token de Afip SDK configurado por variable de entorno."""
    return bool(os.environ.get("AFIPSDK_ACCESS_TOKEN"))


def get_afip_client():
    """Devuelve un cliente Afip configurado, o None si falta el access_token."""
    access_token = os.environ.get("AFIPSDK_ACCESS_TOKEN")
    if not access_token:
        return None

    from afip import Afip  # import diferido: no hace falta si no está configurado

    cuit = os.environ.get("AFIPSDK_CUIT", CUIT_PRUEBA_AFIPSDK)
    production = os.environ.get("AFIPSDK_PRODUCTION", "").strip() == "1"

    opciones = {
        "CUIT": int(cuit),
        "access_token": access_token,
        "production": production,
    }
    if production:
        cert = os.environ.get("AFIPSDK_CERT")
        key = os.environ.get("AFIPSDK_KEY")
        if cert:
            opciones["cert"] = cert
        if key:
            opciones["key"] = key

    return Afip(opciones)


def _limpiar_cuit_dni(valor):
    """Deja solo dígitos de un CUIT/DNI cargado como texto (puede tener guiones/espacios)."""
    if not valor:
        return ""
    return "".join(ch for ch in str(valor) if ch.isdigit())


def datos_receptor(cuit_dni, condicion_iva=None):
    """Determina DocTipo/DocNro/condición IVA/tipo de comprobante del receptor.

    `condicion_iva`: uno de CONDICION_IVA_MAP ('responsable_inscripto',
    'monotributista', 'consumidor_final', 'exento'). Si no se pasa (o el
    CUIT/DNI está vacío), se asume Consumidor Final.

    Solo corresponde Factura A cuando el receptor es Responsable Inscripto
    Y tiene un CUIT de 11 dígitos cargado (ARCA no admite Factura A con DNI
    ni sin documento) — en cualquier otro caso, Factura B.
    """
    limpio = _limpiar_cuit_dni(cuit_dni)
    condicion_iva = condicion_iva if condicion_iva in CONDICION_IVA_MAP else "consumidor_final"
    cond_iva_id = CONDICION_IVA_MAP[condicion_iva]

    if not limpio:
        return {
            "DocTipo": DOC_TIPO_CONSUMIDOR_FINAL, "DocNro": 0,
            "CondicionIVAReceptorId": CONDICION_IVA_MAP["consumidor_final"],
            "tipo_comprobante": "Factura B",
        }

    es_factura_a = condicion_iva == "responsable_inscripto" and len(limpio) == 11
    doc_tipo = DOC_TIPO_CUIT if len(limpio) == 11 else DOC_TIPO_DNI
    return {
        "DocTipo": doc_tipo, "DocNro": int(limpio),
        "CondicionIVAReceptorId": cond_iva_id,
        "tipo_comprobante": "Factura A" if es_factura_a else "Factura B",
    }


def _construir_url_qr(cuit_negocio, punto_venta, tipo_cbte, numero_cbte, fecha_yyyymmdd, importe, doc_tipo, doc_nro, cae):
    """Arma la URL del código QR del comprobante según la especificación RG 4291 de AFIP."""
    payload = {
        "ver": 1,
        "fecha": "%s-%s-%s" % (fecha_yyyymmdd[:4], fecha_yyyymmdd[4:6], fecha_yyyymmdd[6:8]),
        "cuit": int(cuit_negocio),
        "ptoVta": int(punto_venta),
        "tipoCmp": int(tipo_cbte),
        "nroCmp": int(numero_cbte),
        "importe": round(float(importe), 2),
        "moneda": "PES",
        "ctz": 1,
        "tipoDocRec": int(doc_tipo),
        "nroDocRec": int(doc_nro),
        "tipoCodAut": "E",
        "codAut": int(cae),
    }
    data_b64 = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
    return "https://www.afip.gob.ar/fe/qr/?p=%s" % data_b64


def _emitir_factura_arca(cuit_dni, condicion_iva, total, fecha):
    """Llamada cruda a ARCA vía Afip SDK: no toca ninguna tabla, solo
    devuelve el resultado. Punto único usado tanto por emitir_factura()
    (ventas del local/tienda) como por emitir_factura_movimiento() (cargos
    de cuenta corriente) — mismo criterio de facturación en los dos casos.

    `total` se asume con IVA incluido (el precio que ya maneja el sistema);
    acá se discrimina en neto + IVA a la tasa general (ALICUOTA_IVA) para
    mandarlo a ARCA como corresponde en Factura A/B.

    Devuelve un dict:
      {"estado": "sin_configurar"} si falta AFIPSDK_ACCESS_TOKEN
      {"estado": "error", "error": <detalle>} si falló la llamada a ARCA
      {"estado": "emitida", "cae", "cae_vencimiento", "punto_venta", "numero",
       "tipo_comprobante", "imp_neto", "imp_iva"}
    """
    if not afip_configurado():
        return {
            "estado": "sin_configurar",
            "error": "Falta configurar AFIPSDK_ACCESS_TOKEN (ver .env.example y README.md).",
        }

    try:
        afip = get_afip_client()
        punto_venta = int(os.environ.get("AFIPSDK_PUNTO_VENTA", PUNTO_VENTA_DEFAULT))
        receptor = datos_receptor(cuit_dni, condicion_iva)
        cbte_tipo = CBTE_TIPO_POR_NOMBRE[receptor["tipo_comprobante"]]
        fecha_cbte = datetime.strptime(fecha, "%Y-%m-%d").strftime("%Y%m%d")

        ultimo = afip.ElectronicBilling.getLastVoucher(punto_venta, cbte_tipo)
        numero = ultimo + 1
        total = round(float(total), 2)
        neto = round(total / (1 + ALICUOTA_IVA), 2)
        iva = round(total - neto, 2)

        data = {
            "CantReg": 1,
            "PtoVta": punto_venta,
            "CbteTipo": cbte_tipo,
            "Concepto": 1,  # 1 = productos
            "DocTipo": receptor["DocTipo"],
            "DocNro": receptor["DocNro"],
            "CbteDesde": numero,
            "CbteHasta": numero,
            "CbteFch": fecha_cbte,
            "ImpTotal": total,
            "ImpTotConc": 0,
            "ImpNeto": neto,
            "ImpOpEx": 0,
            "ImpIVA": iva,
            "ImpTrib": 0,
            "MonId": "PES",
            "MonCotiz": 1,
            "CondicionIVAReceptorId": receptor["CondicionIVAReceptorId"],
            "Iva": [{"Id": IVA_ALICUOTA_ID_ARCA, "BaseImp": neto, "Importe": iva}],
        }

        resultado = afip.ElectronicBilling.createVoucher(data)
        return {
            "estado": "emitida",
            "cae": resultado["CAE"],
            "cae_vencimiento": resultado["CAEFchVto"],
            "punto_venta": punto_venta,
            "numero": numero,
            "tipo_comprobante": receptor["tipo_comprobante"],
            "imp_neto": neto,
            "imp_iva": iva,
        }
    except Exception as e:
        return {"estado": "error", "error": str(e)}


def emitir_factura(venta_id):
    """Emite (o reintenta emitir) la Factura A/B electrónica de una venta.

    No lanza excepciones hacia afuera: cualquier error queda guardado en la
    venta (facturacion_estado='error', facturacion_error=<detalle>) para
    nunca interrumpir ni revertir la venta ya registrada en el sistema.
    """
    conn = db.get_connection()
    try:
        venta = conn.execute(
            """SELECT v.*, c.cuit_dni AS cliente_cuit_dni, c.condicion_iva AS cliente_condicion_iva
               FROM ventas v LEFT JOIN clientes c ON c.id = v.cliente_id WHERE v.id=?""",
            (venta_id,),
        ).fetchone()
        if not venta:
            return

        resultado = _emitir_factura_arca(
            venta["cliente_cuit_dni"], venta["cliente_condicion_iva"], venta["total"], venta["fecha"]
        )

        if resultado["estado"] == "emitida":
            conn.execute(
                """UPDATE ventas SET
                     cae=?, cae_vencimiento=?, punto_venta_arca=?, numero_factura_arca=?,
                     imp_neto=?, imp_iva=?, facturacion_estado='emitida', facturacion_error=NULL,
                     tipo_comprobante=?
                   WHERE id=?""",
                (
                    resultado["cae"], resultado["cae_vencimiento"], resultado["punto_venta"], resultado["numero"],
                    resultado["imp_neto"], resultado["imp_iva"], resultado["tipo_comprobante"], venta_id,
                ),
            )
        else:
            conn.execute(
                "UPDATE ventas SET facturacion_estado=?, facturacion_error=? WHERE id=?",
                (resultado["estado"], resultado.get("error"), venta_id),
            )
        conn.commit()
    finally:
        conn.close()


def emitir_factura_movimiento(movimiento_id):
    """Igual que emitir_factura(), pero para un cargo de cuenta corriente
    (core/app.py, /clientes/<id>/cuenta-corriente). El receptor de la
    factura es el cliente/mecánico dueño de la cuenta corriente por
    defecto, salvo que el cargo tenga cargado `tercero_cuit_dni` (el
    comprador real es un tercero identificado, no el mecánico) — en ese
    caso se factura a nombre de ese tercero, con su propia condición frente
    al IVA (`tercero_condicion_iva`)."""
    conn = db.get_connection()
    try:
        mov = conn.execute(
            """SELECT m.*, c.cuit_dni AS cliente_cuit_dni, c.condicion_iva AS cliente_condicion_iva
               FROM cuenta_corriente_movimientos m JOIN clientes c ON c.id = m.cliente_id WHERE m.id=?""",
            (movimiento_id,),
        ).fetchone()
        if not mov:
            return

        if mov["tercero_cuit_dni"]:
            cuit_dni = mov["tercero_cuit_dni"]
            condicion_iva = mov["tercero_condicion_iva"]
        else:
            cuit_dni = mov["cliente_cuit_dni"]
            condicion_iva = mov["cliente_condicion_iva"]

        resultado = _emitir_factura_arca(cuit_dni, condicion_iva, mov["monto"], mov["fecha"][:10])

        if resultado["estado"] == "emitida":
            conn.execute(
                """UPDATE cuenta_corriente_movimientos SET
                     cae=?, cae_vencimiento=?, punto_venta_arca=?, numero_factura_arca=?,
                     imp_neto=?, imp_iva=?, tipo_comprobante=?, facturacion_estado='emitida', facturacion_error=NULL
                   WHERE id=?""",
                (
                    resultado["cae"], resultado["cae_vencimiento"], resultado["punto_venta"], resultado["numero"],
                    resultado["imp_neto"], resultado["imp_iva"], resultado["tipo_comprobante"], movimiento_id,
                ),
            )
        else:
            conn.execute(
                "UPDATE cuenta_corriente_movimientos SET facturacion_estado=?, facturacion_error=? WHERE id=?",
                (resultado["estado"], resultado.get("error"), movimiento_id),
            )
        conn.commit()
    finally:
        conn.close()


def url_qr_venta(venta):
    """Devuelve la URL del QR de ARCA para una venta ya facturada, o None si no tiene CAE.

    `venta` debe incluir las columnas de ventas más `cliente_cuit` y
    `cliente_condicion_iva` (alias usados en la consulta de
    /ventas/<id>/comprobante).
    """
    if not venta["cae"]:
        return None
    claves = venta.keys()
    cliente_cuit_dni = venta["cliente_cuit"] if "cliente_cuit" in claves else None
    cliente_condicion_iva = venta["cliente_condicion_iva"] if "cliente_condicion_iva" in claves else None
    receptor = datos_receptor(cliente_cuit_dni, cliente_condicion_iva)
    fecha_cbte = datetime.strptime(venta["fecha"], "%Y-%m-%d").strftime("%Y%m%d")
    cuit_negocio = os.environ.get("AFIPSDK_CUIT", CUIT_PRUEBA_AFIPSDK)
    cbte_tipo = CBTE_TIPO_POR_NOMBRE.get(venta["tipo_comprobante"], CBTE_TIPO_FACTURA_B)
    return _construir_url_qr(
        cuit_negocio, venta["punto_venta_arca"], cbte_tipo, venta["numero_factura_arca"],
        fecha_cbte, venta["total"], receptor["DocTipo"], receptor["DocNro"], venta["cae"],
    )
