"""
Facturación electrónica AFIP/ARCA vía Afip SDK (https://afipsdk.com).

Regla de negocio (decidida con Celes, ver CLAUDE.md): las ventas en efectivo
generan el remito/recibo interno de siempre (ya implementado). Las ventas con
tarjeta o transferencia generan además una Factura C electrónica autorizada
por ARCA (con CAE).

Nota de cumplimiento ya avisada una vez: como monotributista, ARCA exige
Factura C en TODAS las ventas sin excepción por medio de pago ni monto. Esta
regla (efectivo->remito / tarjeta-transferencia->Factura C) es la que pidió
el negocio igual; falta que lo confirmen con su contador. No es responsabilidad
de este módulo decidir eso.

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

Mientras no haya un AFIPSDK_ACCESS_TOKEN configurado, emitir_factura_c() no
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
CBTE_TIPO_FACTURA_C = 11

# Monto a partir del cual ARCA exige identificar al receptor de la Factura C
# (no alcanza con Consumidor Final, hace falta CUIT/DNI cargado). Este valor
# lo fija AFIP/ARCA por resolución y cambia periódicamente — revisar contra
# la normativa vigente antes de confiar en él en producción. Usado por
# core/app.py al cargar un cargo de cuenta corriente (ver /clientes/<id>/cuenta-corriente).
UMBRAL_IDENTIFICACION_RECEPTOR = 419405

# Tipos de documento del receptor (tabla FEParamGetTiposDoc de ARCA)
DOC_TIPO_CUIT = 80
DOC_TIPO_DNI = 96
DOC_TIPO_CONSUMIDOR_FINAL = 99

# Condición frente al IVA del receptor (obligatorio en comprobantes desde la
# RG 5259/2022). Simplificado: sin CUIT/DNI cargado se asume Consumidor Final.
COND_IVA_RESPONSABLE_INSCRIPTO = 1
COND_IVA_CONSUMIDOR_FINAL = 5


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


def datos_receptor(cliente_cuit_dni):
    """Determina DocTipo/DocNro/condición IVA del receptor para la Factura C.

    Sin CUIT/DNI cargado -> Consumidor Final (DocTipo 99, DocNro 0).
    Con 11 dígitos -> se asume CUIT (Responsable Inscripto/Monotributo).
    Con menos de 11 dígitos -> se asume DNI (Consumidor Final).
    """
    limpio = _limpiar_cuit_dni(cliente_cuit_dni)
    if not limpio:
        return {"DocTipo": DOC_TIPO_CONSUMIDOR_FINAL, "DocNro": 0, "CondicionIVAReceptorId": COND_IVA_CONSUMIDOR_FINAL}
    if len(limpio) == 11:
        return {"DocTipo": DOC_TIPO_CUIT, "DocNro": int(limpio), "CondicionIVAReceptorId": COND_IVA_RESPONSABLE_INSCRIPTO}
    return {"DocTipo": DOC_TIPO_DNI, "DocNro": int(limpio), "CondicionIVAReceptorId": COND_IVA_CONSUMIDOR_FINAL}


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


def _emitir_factura_c_arca(cliente_cuit_dni, total, fecha):
    """Llamada cruda a ARCA vía Afip SDK: no toca ninguna tabla, solo
    devuelve el resultado. Punto único usado tanto por emitir_factura_c()
    (ventas del local/tienda) como por emitir_factura_c_movimiento() (cargos
    de cuenta corriente) — mismo criterio de facturación en los dos casos.

    Devuelve un dict:
      {"estado": "sin_configurar"} si falta AFIPSDK_ACCESS_TOKEN
      {"estado": "error", "error": <detalle>} si falló la llamada a ARCA
      {"estado": "emitida", "cae", "cae_vencimiento", "punto_venta", "numero"}
    """
    if not afip_configurado():
        return {
            "estado": "sin_configurar",
            "error": "Falta configurar AFIPSDK_ACCESS_TOKEN (ver .env.example y README.md).",
        }

    try:
        afip = get_afip_client()
        punto_venta = int(os.environ.get("AFIPSDK_PUNTO_VENTA", PUNTO_VENTA_DEFAULT))
        receptor = datos_receptor(cliente_cuit_dni)
        fecha_cbte = datetime.strptime(fecha, "%Y-%m-%d").strftime("%Y%m%d")

        ultimo = afip.ElectronicBilling.getLastVoucher(punto_venta, CBTE_TIPO_FACTURA_C)
        numero = ultimo + 1
        total = round(float(total), 2)

        data = {
            "CantReg": 1,
            "PtoVta": punto_venta,
            "CbteTipo": CBTE_TIPO_FACTURA_C,
            "Concepto": 1,  # 1 = productos
            "DocTipo": receptor["DocTipo"],
            "DocNro": receptor["DocNro"],
            "CbteDesde": numero,
            "CbteHasta": numero,
            "CbteFch": fecha_cbte,
            "ImpTotal": total,
            "ImpTotConc": 0,
            "ImpNeto": total,
            "ImpOpEx": 0,
            "ImpIVA": 0,
            "ImpTrib": 0,
            "MonId": "PES",
            "MonCotiz": 1,
            "CondicionIVAReceptorId": receptor["CondicionIVAReceptorId"],
        }

        resultado = afip.ElectronicBilling.createVoucher(data)
        return {
            "estado": "emitida",
            "cae": resultado["CAE"],
            "cae_vencimiento": resultado["CAEFchVto"],
            "punto_venta": punto_venta,
            "numero": numero,
        }
    except Exception as e:
        return {"estado": "error", "error": str(e)}


def emitir_factura_c(venta_id):
    """Emite (o reintenta emitir) la Factura C electrónica de una venta.

    No lanza excepciones hacia afuera: cualquier error queda guardado en la
    venta (facturacion_estado='error', facturacion_error=<detalle>) para
    nunca interrumpir ni revertir la venta ya registrada en el sistema.
    """
    conn = db.get_connection()
    try:
        venta = conn.execute(
            """SELECT v.*, c.cuit_dni AS cliente_cuit_dni
               FROM ventas v LEFT JOIN clientes c ON c.id = v.cliente_id WHERE v.id=?""",
            (venta_id,),
        ).fetchone()
        if not venta:
            return

        resultado = _emitir_factura_c_arca(venta["cliente_cuit_dni"], venta["total"], venta["fecha"])

        if resultado["estado"] == "emitida":
            conn.execute(
                """UPDATE ventas SET
                     cae=?, cae_vencimiento=?, punto_venta_arca=?, numero_factura_arca=?,
                     facturacion_estado='emitida', facturacion_error=NULL, tipo_comprobante='Factura C'
                   WHERE id=?""",
                (resultado["cae"], resultado["cae_vencimiento"], resultado["punto_venta"], resultado["numero"], venta_id),
            )
        else:
            conn.execute(
                "UPDATE ventas SET facturacion_estado=?, facturacion_error=? WHERE id=?",
                (resultado["estado"], resultado.get("error"), venta_id),
            )
        conn.commit()
    finally:
        conn.close()


def emitir_factura_c_movimiento(movimiento_id):
    """Igual que emitir_factura_c(), pero para un cargo de cuenta corriente
    (core/app.py, /clientes/<id>/cuenta-corriente). El receptor de la
    factura es el cliente/mecánico dueño de la cuenta corriente por
    defecto, salvo que el cargo tenga cargado `tercero_cuit_dni` (el
    comprador real es un tercero identificado, no el mecánico) — en ese
    caso se factura a nombre de ese tercero. Sigue siendo siempre Factura C
    (nunca A/B): este negocio es monotributista, no puede emitir otra cosa."""
    conn = db.get_connection()
    try:
        mov = conn.execute(
            """SELECT m.*, c.cuit_dni AS cliente_cuit_dni
               FROM cuenta_corriente_movimientos m JOIN clientes c ON c.id = m.cliente_id WHERE m.id=?""",
            (movimiento_id,),
        ).fetchone()
        if not mov:
            return

        receptor_cuit_dni = mov["tercero_cuit_dni"] or mov["cliente_cuit_dni"]
        resultado = _emitir_factura_c_arca(receptor_cuit_dni, mov["monto"], mov["fecha"][:10])

        if resultado["estado"] == "emitida":
            conn.execute(
                """UPDATE cuenta_corriente_movimientos SET
                     cae=?, cae_vencimiento=?, punto_venta_arca=?, numero_factura_arca=?,
                     facturacion_estado='emitida', facturacion_error=NULL
                   WHERE id=?""",
                (resultado["cae"], resultado["cae_vencimiento"], resultado["punto_venta"], resultado["numero"], movimiento_id),
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

    `venta` debe incluir las columnas de ventas más `cliente_cuit` (alias
    usado en la consulta de /ventas/<id>/comprobante).
    """
    if not venta["cae"]:
        return None
    cliente_cuit_dni = venta["cliente_cuit"] if "cliente_cuit" in venta.keys() else None
    receptor = datos_receptor(cliente_cuit_dni)
    fecha_cbte = datetime.strptime(venta["fecha"], "%Y-%m-%d").strftime("%Y%m%d")
    cuit_negocio = os.environ.get("AFIPSDK_CUIT", CUIT_PRUEBA_AFIPSDK)
    return _construir_url_qr(
        cuit_negocio, venta["punto_venta_arca"], CBTE_TIPO_FACTURA_C, venta["numero_factura_arca"],
        fecha_cbte, venta["total"], receptor["DocTipo"], receptor["DocNro"], venta["cae"],
    )
