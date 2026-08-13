from decimal import Decimal
from core.app import registrar_venta


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
    """Tres unidades de 0.10 tienen que dar 0.30 clavado, no 0.30000000000004."""
    prod = _producto(db_conn, "Centavo", Decimal("0.10"), 100)
    cliente = _cliente(db_conn, "Ana")

    items = [(prod, 3, Decimal("0.10"), Decimal("0.30"))]
    venta_id, _ = registrar_venta(db_conn, cliente, "Efectivo", items)

    total = db_conn.execute(
        "SELECT total FROM ventas WHERE id = %s", (venta_id,)
    ).fetchone()["total"]
    assert total == Decimal("0.30")


def test_registrar_venta_devuelve_id_y_tipo(db_conn):
    """Devuelve la tupla (venta_id, tipo_comprobante). El id ahora sale de
    RETURNING id, ya no de cursor.lastrowid."""
    prod = _producto(db_conn, "X", Decimal("2.00"), 5)
    cliente = _cliente(db_conn, "Luis")

    items = [(prod, 1, Decimal("2.00"), Decimal("2.00"))]
    venta_id, tipo = registrar_venta(db_conn, cliente, "Efectivo", items)

    assert isinstance(venta_id, int) and venta_id > 0
    assert tipo == "Remito"
