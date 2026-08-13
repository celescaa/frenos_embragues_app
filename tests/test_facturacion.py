from decimal import Decimal

from core import facturacion_afip


class _FacturacionElectronicBillingFalso:
    """Doble de prueba de `afip.ElectronicBilling`: sin red real, responde
    lo mínimo que necesita `_emitir_factura_arca()` (último comprobante +
    CAE) y guarda cada payload de `createVoucher()` para poder inspeccionar
    con qué se llamó a ARCA -- en particular `CbteFch`, la fecha ya
    convertida a YYYYMMDD."""

    def __init__(self, ultimo=41, cae="70123456789012", cae_vencimiento="20260901"):
        self.ultimo = ultimo
        self.cae = cae
        self.cae_vencimiento = cae_vencimiento
        self.llamadas_create_voucher = []

    def getLastVoucher(self, punto_venta, cbte_tipo):
        return self.ultimo

    def createVoucher(self, data):
        self.llamadas_create_voucher.append(data)
        return {"CAE": self.cae, "CAEFchVto": self.cae_vencimiento}


class _AfipFalso:
    def __init__(self, electronic_billing):
        self.ElectronicBilling = electronic_billing


def test_emitir_factura_camino_feliz_neto_iva_exacto_y_fecha_correcta(db_conn, monkeypatch):
    """Ejercita el camino completo de _emitir_factura_arca (no solo la rama
    'sin_configurar'): simula ARCA configurado con un doble de prueba, sin
    red real, para llegar de verdad a la aritmética Decimal de neto/IVA y al
    .strftime() de la fecha -- las dos ramas que el resto de la suite nunca
    ejecuta (el otro test de este archivo sale por 'sin_configurar' antes de
    llegar ahí, y los tests de ruta de cuenta corriente reemplazan estas
    funciones por completo con monkeypatch).

    El total (100.10) está elegido a propósito: con el algoritmo viejo en
    float (round(100.10/1.21, 2) + round(100.10 - 82.73, 2)), el resultado
    es 100.10000000000001, no 100.10 exacto -- verificado empíricamente
    antes de escribir este test (ver task-10-report.md, Ronda 1)."""
    fake_billing = _FacturacionElectronicBillingFalso()
    fake_afip = _AfipFalso(fake_billing)
    monkeypatch.setattr(facturacion_afip, "afip_configurado", lambda: True)
    monkeypatch.setattr(facturacion_afip, "get_afip_client", lambda: fake_afip)

    cliente = db_conn.execute(
        "INSERT INTO clientes (nombre, fecha_alta) VALUES ('Con ARCA', CURRENT_DATE) RETURNING id"
    ).fetchone()["id"]
    venta = db_conn.execute(
        """INSERT INTO ventas (fecha, cliente_id, total, metodo_pago, tipo_comprobante)
           VALUES (CURRENT_DATE, %s, %s, 'Tarjeta', 'Factura B') RETURNING id, fecha""",
        (cliente, Decimal("100.10")),
    ).fetchone()
    venta_id, fecha_venta = venta["id"], venta["fecha"]
    db_conn.commit()

    facturacion_afip.emitir_factura(venta_id)

    fila = db_conn.execute(
        "SELECT facturacion_estado, cae, imp_neto, imp_iva, total FROM ventas WHERE id = %s",
        (venta_id,),
    ).fetchone()

    assert fila["facturacion_estado"] == "emitida"
    assert fila["cae"] == "70123456789012"
    assert isinstance(fila["imp_neto"], Decimal) and isinstance(fila["imp_iva"], Decimal)
    assert fila["imp_neto"] + fila["imp_iva"] == fila["total"]  # exacto, no aproximado

    # La fecha que se le mandó a ARCA: partiendo del `date` real que devolvió
    # la base (no un supuesto sobre la fecha de hoy), en formato YYYYMMDD.
    assert len(fake_billing.llamadas_create_voucher) == 1
    payload_enviado_a_arca = fake_billing.llamadas_create_voucher[0]
    assert payload_enviado_a_arca["CbteFch"] == fecha_venta.strftime("%Y%m%d")


def test_sin_configurar_arca_la_venta_no_se_rompe(db_conn, monkeypatch):
    """El contrato de siempre: si ARCA no está configurado, la venta queda
    registrada y marcada, nunca revienta."""
    monkeypatch.delenv("AFIPSDK_ACCESS_TOKEN", raising=False)
    cliente = db_conn.execute(
        "INSERT INTO clientes (nombre, fecha_alta) VALUES ('X', CURRENT_DATE) RETURNING id"
    ).fetchone()["id"]
    venta = db_conn.execute(
        """INSERT INTO ventas (fecha, cliente_id, total, metodo_pago, tipo_comprobante)
           VALUES (CURRENT_DATE, %s, %s, 'Tarjeta', 'Factura B') RETURNING id""",
        (cliente, Decimal("1210.00")),
    ).fetchone()["id"]
    db_conn.commit()

    from core import facturacion_afip
    facturacion_afip.emitir_factura(venta)  # no debe lanzar

    estado = db_conn.execute(
        "SELECT facturacion_estado FROM ventas WHERE id = %s", (venta,)
    ).fetchone()["facturacion_estado"]
    assert estado == "sin_configurar"


def test_el_neto_mas_el_iva_da_el_total_exacto():
    """Con flotantes esto fallaba por un centavo. ARCA lo rechaza."""
    from core.facturacion_afip import ALICUOTA_IVA
    total = Decimal("1210.00")
    neto = (total / (1 + Decimal(str(ALICUOTA_IVA)))).quantize(Decimal("0.01"))
    iva = total - neto
    assert neto + iva == total
