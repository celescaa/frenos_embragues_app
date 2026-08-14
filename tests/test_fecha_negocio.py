"""La fecha del negocio no puede depender del reloj del servidor.

Hasta ahora el sistema usaba `datetime.now()` a secas, o sea la hora local de
la máquina donde corre. Eso funcionaba porque corría en la compu del local, en
Argentina. **En Vercel el servidor está en UTC**, tres horas adelante: a partir
de las 21:00 hora argentina, `datetime.now()` ya devuelve el día siguiente.

Las consecuencias son concretas y silenciosas:

- Una venta cargada a las 21:30 quedaría fechada al día siguiente, y no
  aparecería en "Ventas del día" de esa jornada.
- Una promoción creada a las 21:30 quedaría con fecha de inicio de mañana, así
  que no se aplicaría a las ventas de esa misma noche.
- El total del mes cambiaría de mes tres horas antes de tiempo.

Nada de eso tira un error: da números equivocados. Por eso "hoy" pasa a
resolverse siempre contra el huso de Argentina, sin importar dónde corra.
"""
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from core import database as db


def test_hoy_devuelve_una_fecha():
    assert isinstance(db.hoy(), date)


def test_hoy_es_el_dia_en_argentina_no_el_del_servidor(monkeypatch):
    """El caso que rompe en Vercel: el proceso corre con el reloj en UTC."""
    monkeypatch.setenv("TZ", "UTC")
    if hasattr(os, "tzset"):
        import time
        time.tzset()
    try:
        esperado = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date()
        assert db.hoy() == esperado
    finally:
        monkeypatch.delenv("TZ", raising=False)
        if hasattr(os, "tzset"):
            import time
            time.tzset()


def test_una_promocion_creada_hoy_se_aplica_hoy(db_conn):
    """El síntoma real: entre las 21:00 y la medianoche, una promoción recién
    cargada no descontaba nada porque su fecha de inicio quedaba en el futuro
    según el reloj con el que se la consultaba."""
    from core.app import aplicar_promociones
    from decimal import Decimal

    cliente = db_conn.execute(
        "INSERT INTO clientes (nombre, fecha_alta) VALUES ('Cliente con promo', CURRENT_DATE) RETURNING id"
    ).fetchone()["id"]
    producto = db_conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta, stock_actual)
           VALUES ('Producto', 'Frenos', 50, 100, 10) RETURNING id"""
    ).fetchone()["id"]
    db_conn.execute(
        """INSERT INTO promociones_aplicadas
           (cliente_id, porcentaje_o_monto, tipo, alcance, fecha_inicio, fecha_fin, aprobado_por)
           VALUES (%s, 10, 'porcentaje', 'todo', %s, NULL, 'test')""",
        (cliente, db.hoy()),
    )

    resultado = aplicar_promociones(
        db_conn, cliente, [(producto, 1, Decimal("100.00"), Decimal("100.00"))]
    )
    assert resultado[0][2] == Decimal("90.00"), (
        "la promoción creada hoy no se aplicó: 'hoy' no coincide entre quien la "
        "guarda y quien la consulta"
    )
