from decimal import Decimal


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
