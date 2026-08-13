from decimal import Decimal
from core.app import aplicar_promociones, registrar_venta


def _cliente(conn, nombre="Juan"):
    return conn.execute(
        "INSERT INTO clientes (nombre, fecha_alta) VALUES (%s, CURRENT_DATE) RETURNING id",
        (nombre,),
    ).fetchone()["id"]


def _producto(conn, nombre, precio_venta, stock):
    return conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta, stock_actual)
           VALUES (%s, 'Frenos', 1, %s, %s) RETURNING id""",
        (nombre, precio_venta, stock),
    ).fetchone()["id"]


def test_una_venta_descuenta_stock(db_conn):
    prod = _producto(db_conn, "Pastilla", Decimal("150.00"), 10)
    cliente = _cliente(db_conn)

    # items = lista de tuplas (producto_id, cantidad, precio_unitario, subtotal)
    items = [(prod, 3, Decimal("150.00"), Decimal("450.00"))]
    registrar_venta(db_conn, cliente, "Efectivo", items)

    stock = db_conn.execute(
        "SELECT stock_actual FROM productos WHERE id = %s", (prod,)
    ).fetchone()["stock_actual"]
    assert stock == 7


def test_el_total_es_decimal_exacto(db_conn):
    """No custodia precisión decimal: el subtotal ya viene calculado en el
    tuple de `items` (registrar_venta() solo lo suma, nunca multiplica
    precio_unitario x cantidad), y una columna NUMERIC(12,2) redondea
    cualquier valor al guardarlo -- así que esto pasaría igual si toda la
    aritmética usara float. Lo que sí prueba: que una venta persiste su
    total de punta a punta y que el id que devuelve `registrar_venta()`
    (ahora vía RETURNING id, no cursor.lastrowid) sirve para leer la fila
    recién insertada. El guardián real de precisión decimal es
    `test_aplicar_promociones_porcentual_usa_decimal_exacto` más abajo, que
    verifica la aritmética en Python antes de que toque la base."""
    prod = _producto(db_conn, "Centavo", Decimal("0.10"), 100)
    cliente = _cliente(db_conn, "Ana")

    items = [(prod, 3, Decimal("0.10"), Decimal("0.30"))]
    venta_id, _ = registrar_venta(db_conn, cliente, "Efectivo", items)

    total = db_conn.execute(
        "SELECT total FROM ventas WHERE id = %s", (venta_id,)
    ).fetchone()["total"]
    assert total == Decimal("0.30")


def test_aplicar_promociones_porcentual_usa_decimal_exacto(db_conn):
    """Guardián real de precisión decimal: llama a aplicar_promociones()
    directo (no a través de registrar_venta() ni de una columna NUMERIC que
    redondearía y taparía el error), con un caso elegido para que difieran
    el cálculo en Decimal y el cálculo en float.

    2.75 con 2% de descuento: en Decimal, 2.75 * 0.98 = 2.695 exacto, que
    redondea (half-even) a 2.70. En float, 0.98 no es representable exacto
    en binario, así que 2.75 * 0.98 da un valor apenas menor a 2.695 (nunca
    llega al empate) y redondea a 2.69 -- un resultado distinto, no solo un
    error de última cifra. Confirmado empíricamente (no por inspección) con
    Python antes de escribir este test."""
    cliente = _cliente(db_conn, "Mecánico con descuento")
    db_conn.execute(
        """INSERT INTO promociones_aplicadas
           (cliente_id, porcentaje_o_monto, tipo, alcance, fecha_inicio, fecha_fin, aprobado_por)
           VALUES (%s, %s, 'porcentaje', 'todo', CURRENT_DATE, NULL, 'test')""",
        (cliente, Decimal("2.00")),
    )
    prod = _producto(db_conn, "Producto con promo", Decimal("2.75"), 10)

    items = [(prod, 1, Decimal("2.75"), Decimal("2.75"))]
    resultado = aplicar_promociones(db_conn, cliente, items)

    precio_final = resultado[0][2]
    subtotal_final = resultado[0][3]
    assert isinstance(precio_final, Decimal)
    assert isinstance(subtotal_final, Decimal)
    assert precio_final == Decimal("2.70")
    assert subtotal_final == Decimal("2.70")


def test_registrar_venta_devuelve_id_y_tipo(db_conn):
    """Devuelve la tupla (venta_id, tipo_comprobante). El id ahora sale de
    RETURNING id, ya no de cursor.lastrowid."""
    prod = _producto(db_conn, "X", Decimal("2.00"), 5)
    cliente = _cliente(db_conn, "Luis")

    items = [(prod, 1, Decimal("2.00"), Decimal("2.00"))]
    venta_id, tipo = registrar_venta(db_conn, cliente, "Efectivo", items)

    assert isinstance(venta_id, int) and venta_id > 0
    assert tipo == "Remito"
