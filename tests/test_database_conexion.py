from decimal import Decimal
from core import database as db


def test_get_connection_devuelve_filas_por_nombre():
    conn = db.get_connection()
    try:
        fila = conn.execute("SELECT 'ok' AS estado").fetchone()
        assert fila["estado"] == "ok"
    finally:
        conn.close()


def test_los_montos_llegan_como_decimal_exacto():
    """Si esto devuelve float, volvió el bug de redondeo que la migración
    vino a corregir."""
    conn = db.get_connection()
    try:
        fila = conn.execute("SELECT 0.1::numeric(12,2) + 0.2::numeric(12,2) AS suma").fetchone()
        assert fila["suma"] == Decimal("0.30")
    finally:
        conn.close()


def test_no_quedan_rastros_de_sqlite():
    """INSTANCE_DIR/DB_PATH eran para el archivo local; en serverless no hay
    disco persistente y no deben volver."""
    assert not hasattr(db, "DB_PATH")
    assert not hasattr(db, "INSTANCE_DIR")
