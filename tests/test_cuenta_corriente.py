"""Cuenta corriente, promociones y stock no facturado.

Los primeros 4 tests son los que trae el brief de la Tarea 8: son de esquema
(contra `db_conn` directo) y, como advierte el brief, la mayoría pasa igual
sin el port -- confirman hechos sobre la base migrada (saldo, booleanos,
CURRENT_DATE), no el código portado en core/app.py.

El segundo grupo son tests de RUTA (test_client de Flask, sesión iniciada)
que sí ejercitan core/app.py y fallan contra el código previo al port
(placeholders `?`, que psycopg no entiende -- ver la verificación empírica
en task-8-report.md).

Nota sobre facturacion_afip: el cargo de cuenta corriente llama, al final,
a `facturacion_afip.emitir_factura_movimiento()` -- función de la Tarea 10,
todavía sin portar (sigue con placeholders `?`). Los tests de cargo la
neutralizan con monkeypatch para poder verificar el resto de la ruta
(descuento de stock, inserción del movimiento) sin depender de un módulo
que no es responsabilidad de esta tarea."""
from decimal import Decimal

import psycopg
import pytest

from core import facturacion_afip
from core.app import app as flask_app


def _cliente(conn, nombre="Mecánico"):
    return conn.execute(
        "INSERT INTO clientes (nombre, fecha_alta) VALUES (%s, CURRENT_DATE) RETURNING id",
        (nombre,),
    ).fetchone()["id"]


def test_el_saldo_es_cargos_menos_pagos(db_conn):
    cliente = _cliente(db_conn)
    db_conn.execute(
        """INSERT INTO cuenta_corriente_movimientos (cliente_id, tipo, monto)
           VALUES (%s, 'cargo', %s)""", (cliente, Decimal("1500.00")))
    db_conn.execute(
        """INSERT INTO cuenta_corriente_movimientos (cliente_id, tipo, monto)
           VALUES (%s, 'pago', %s)""", (cliente, Decimal("500.50")))

    saldo = db_conn.execute(
        """SELECT COALESCE(SUM(CASE WHEN tipo='cargo' THEN monto ELSE -monto END), 0) AS saldo
           FROM cuenta_corriente_movimientos WHERE cliente_id = %s""",
        (cliente,),
    ).fetchone()["saldo"]
    assert saldo == Decimal("999.50")


def test_una_promocion_vencida_no_se_aplica(db_conn):
    """fecha_fin en el pasado: date('now') pasó a CURRENT_DATE."""
    cliente = _cliente(db_conn)
    db_conn.execute(
        """INSERT INTO promociones_aplicadas
           (cliente_id, tipo, porcentaje_o_monto, alcance, fecha_inicio, fecha_fin, aprobado_por)
           VALUES (%s, 'porcentaje', 10, 'todo', CURRENT_DATE - 30, CURRENT_DATE - 1, 'test')""",
        (cliente,),
    )
    vigentes = db_conn.execute(
        """SELECT COUNT(*) AS n FROM promociones_aplicadas
           WHERE cliente_id = %s AND fecha_inicio <= CURRENT_DATE
             AND (fecha_fin IS NULL OR fecha_fin >= CURRENT_DATE)""",
        (cliente,),
    ).fetchone()["n"]
    assert vigentes == 0


def test_el_descuento_porcentual_se_calcula_exacto(db_conn):
    """10% sobre 999.99 tiene que dar 899.99, no 899.9910000000001."""
    from core.app import aplicar_promociones
    cliente = _cliente(db_conn, "Con promo")
    prod = db_conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta)
           VALUES ('Caro', 'Frenos', 500, 999.99) RETURNING id"""
    ).fetchone()["id"]
    db_conn.execute(
        """INSERT INTO promociones_aplicadas
           (cliente_id, tipo, porcentaje_o_monto, alcance, fecha_inicio, aprobado_por)
           VALUES (%s, 'porcentaje', 10, 'todo', CURRENT_DATE, 'test')""",
        (cliente,),
    )

    # items = lista de tuplas (producto_id, cantidad, precio_unitario, subtotal)
    items = [(prod, 1, Decimal("999.99"), Decimal("999.99"))]
    resultado = aplicar_promociones(db_conn, cliente, items)

    assert resultado[0][3] == Decimal("899.99")
    assert isinstance(resultado[0][3], Decimal)


def test_conciliado_es_booleano(db_conn):
    """Dejó de ser INTEGER 0/1."""
    prod = db_conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta, stock_actual)
           VALUES ('Suelto', 'Otros', 10, 20, 5) RETURNING id"""
    ).fetchone()["id"]
    db_conn.execute(
        """INSERT INTO movimientos_no_facturados (producto_id, tipo, cantidad, precio, conciliado)
           VALUES (%s, 'compra', 3, %s, false)""",
        (prod, Decimal("10.00")),
    )
    fila = db_conn.execute(
        "SELECT conciliado FROM movimientos_no_facturados WHERE producto_id = %s", (prod,)
    ).fetchone()
    assert fila["conciliado"] is False


# ---------------------------------------------------------------------------
# Tests de ruta: ejercitan core/app.py y fallan contra el código previo al
# port de esta tarea (placeholders `?`, no válidos para psycopg).
# ---------------------------------------------------------------------------
@pytest.fixture
def client(db_conn, monkeypatch):
    # facturacion_afip.emitir_factura_movimiento() es de la Tarea 10 (todavía
    # sin portar, sigue con `?`). Se neutraliza acá para que estos tests
    # verifiquen la ruta de cuenta corriente en sí -- no un módulo que no es
    # responsabilidad de esta tarea.
    monkeypatch.setattr(facturacion_afip, "emitir_factura_movimiento", lambda movimiento_id: None)
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        with c.session_transaction() as sesion:
            sesion["usuario_id"] = "00000000-0000-0000-0000-000000000001"
            sesion["usuario_nombre"] = "Test"
            sesion["usuario_rol"] = "admin"
            sesion["debe_cambiar_password"] = False
        yield c


def _producto(conn, nombre, precio_venta, stock):
    return conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta, stock_actual)
           VALUES (%s, 'Frenos', 1, %s, %s) RETURNING id""",
        (nombre, precio_venta, stock),
    ).fetchone()["id"]


def test_cargo_descuenta_stock_y_guarda_movimiento(client, db_conn):
    """POST tipo=cargo: contra el código previo al port, la primera consulta
    de la ruta (SELECT cliente WHERE id=?) ya revienta -- psycopg no entiende
    `?`. Portado, tiene que: crear el movimiento con RETURNING id (ya no
    cursor.lastrowid), crear sus renglones y descontar stock, igual que una
    venta al contado."""
    cliente = _cliente(db_conn, "Taller Ruta 8")
    prod = _producto(db_conn, "Pastilla delantera", Decimal("300.00"), 10)
    db_conn.commit()

    respuesta = client.post(
        f"/clientes/{cliente}/cuenta-corriente/nueva",
        data={"tipo": "cargo", "producto_id": [str(prod)], "cantidad": ["4"]},
        follow_redirects=True,
    )
    assert respuesta.status_code < 400

    stock = db_conn.execute(
        "SELECT stock_actual FROM productos WHERE id = %s", (prod,)
    ).fetchone()["stock_actual"]
    assert stock == 6

    mov = db_conn.execute(
        "SELECT tipo, monto FROM cuenta_corriente_movimientos WHERE cliente_id = %s", (cliente,)
    ).fetchone()
    assert mov["tipo"] == "cargo"
    assert mov["monto"] == Decimal("1200.00")
    assert isinstance(mov["monto"], Decimal)

    renglon = db_conn.execute(
        """SELECT cantidad, precio_unitario, subtotal FROM cuenta_corriente_movimiento_items i
           JOIN cuenta_corriente_movimientos m ON m.id = i.movimiento_id WHERE m.cliente_id = %s""",
        (cliente,),
    ).fetchone()
    assert renglon["cantidad"] == 4
    assert renglon["subtotal"] == Decimal("1200.00")


def test_pago_registra_movimiento_sin_tocar_stock(client, db_conn):
    """POST tipo=pago: no toca stock ni factura, pero sí pasa por el mismo
    INSERT con placeholders que el resto de la ruta."""
    cliente = _cliente(db_conn, "Cliente que paga")
    db_conn.commit()

    respuesta = client.post(
        f"/clientes/{cliente}/cuenta-corriente/nueva",
        data={"tipo": "pago", "monto": "500.50"},
        follow_redirects=True,
    )
    assert respuesta.status_code < 400

    mov = db_conn.execute(
        "SELECT tipo, monto FROM cuenta_corriente_movimientos WHERE cliente_id = %s", (cliente,)
    ).fetchone()
    assert mov["tipo"] == "pago"
    assert mov["monto"] == Decimal("500.50")
    assert isinstance(mov["monto"], Decimal)


def test_cargo_por_encima_del_umbral_sin_cuit_no_se_registra(client, db_conn):
    """El monto (ahora Decimal) se compara contra
    facturacion_afip.UMBRAL_IDENTIFICACION_RECEPTOR (int) -- si esa
    comparación mezclara Decimal con float mal convertido, lanzaría
    TypeError en vez de simplemente rechazar el cargo con un mensaje. Cliente
    sin CUIT/DNI cargado, producto carísimo para superar el umbral."""
    cliente = _cliente(db_conn, "Sin CUIT")
    umbral = facturacion_afip.UMBRAL_IDENTIFICACION_RECEPTOR
    prod = _producto(db_conn, "Kit de embrague premium", Decimal(umbral + 1000), 5)
    db_conn.commit()

    respuesta = client.post(
        f"/clientes/{cliente}/cuenta-corriente/nueva",
        data={"tipo": "cargo", "producto_id": [str(prod)], "cantidad": ["1"]},
        follow_redirects=True,
    )
    assert respuesta.status_code < 500

    mov = db_conn.execute(
        "SELECT id FROM cuenta_corriente_movimientos WHERE cliente_id = %s", (cliente,)
    ).fetchone()
    assert mov is None, "no debería haberse registrado el cargo sin CUIT/DNI por encima del umbral"

    stock = db_conn.execute(
        "SELECT stock_actual FROM productos WHERE id = %s", (prod,)
    ).fetchone()["stock_actual"]
    assert stock == 5, "el stock no debería haberse tocado si el cargo se rechazó"


def test_top_deudores_calcula_saldo_correctamente(client, db_conn):
    """GET /clientes/top-deudores: SUM(cargos) - SUM(pagos), solo saldo > 0.
    Contra el código previo, /clientes/<id>/cuenta-corriente/nueva nunca
    llega a insertar nada (revienta con `?`), así que esta ruta no tendría
    ningún deudor que mostrar."""
    deudor = _cliente(db_conn, "Debe Mucho")
    saldado = _cliente(db_conn, "Ya Pagó Todo")
    db_conn.execute(
        """INSERT INTO cuenta_corriente_movimientos (cliente_id, tipo, monto)
           VALUES (%s, 'cargo', %s)""", (deudor, Decimal("2000.00")))
    db_conn.execute(
        """INSERT INTO cuenta_corriente_movimientos (cliente_id, tipo, monto)
           VALUES (%s, 'cargo', %s)""", (saldado, Decimal("300.00")))
    db_conn.execute(
        """INSERT INTO cuenta_corriente_movimientos (cliente_id, tipo, monto)
           VALUES (%s, 'pago', %s)""", (saldado, Decimal("300.00")))
    db_conn.commit()

    respuesta = client.get("/clientes/top-deudores")
    assert respuesta.status_code == 200
    cuerpo = respuesta.data.decode()
    assert "Debe Mucho" in cuerpo
    assert "Ya Pagó Todo" not in cuerpo


def test_clientes_top_muestra_solo_promociones_vigentes(client, db_conn):
    """GET /clientes/top: la consulta de promociones vigentes pasó de
    `date('now')` a CURRENT_DATE. Contra el código previo (SQLite), esa
    misma consulta ni siquiera es válida en Postgres -- date('now') no
    existe -- así que la ruta entera revienta con 500."""
    vencida = _cliente(db_conn, "Promo Vencida SA")
    vigente = _cliente(db_conn, "Promo Vigente SA")
    db_conn.execute(
        """INSERT INTO promociones_aplicadas
           (cliente_id, tipo, porcentaje_o_monto, alcance, fecha_inicio, fecha_fin, aprobado_por)
           VALUES (%s, 'porcentaje', 15, 'todo', CURRENT_DATE - 30, CURRENT_DATE - 1, 'test')""",
        (vencida,),
    )
    db_conn.execute(
        """INSERT INTO promociones_aplicadas
           (cliente_id, tipo, porcentaje_o_monto, alcance, fecha_inicio, fecha_fin, aprobado_por)
           VALUES (%s, 'porcentaje', 20, 'todo', CURRENT_DATE - 5, NULL, 'test')""",
        (vigente,),
    )
    db_conn.commit()

    respuesta = client.get("/clientes/top?periodo=todo")
    assert respuesta.status_code == 200
    cuerpo = respuesta.data.decode()
    assert "Promo Vigente SA" in cuerpo
    assert "Promo Vencida SA" not in cuerpo


def test_promocion_nueva_crea_promocion_con_decimal(client, db_conn):
    """POST /clientes/<id>/promocion/nueva: porcentaje_o_monto pasó de
    float() a a_decimal(), y el id de la promoción de cursor.lastrowid a
    RETURNING id."""
    cliente = _cliente(db_conn, "Nueva Promo")
    db_conn.commit()

    respuesta = client.post(
        f"/clientes/{cliente}/promocion/nueva",
        data={"tipo": "porcentaje", "porcentaje_o_monto": "12.5", "alcance": "todo"},
        follow_redirects=True,
    )
    assert respuesta.status_code < 400

    promo = db_conn.execute(
        "SELECT porcentaje_o_monto FROM promociones_aplicadas WHERE cliente_id = %s", (cliente,)
    ).fetchone()
    assert promo["porcentaje_o_monto"] == Decimal("12.5")
    assert isinstance(promo["porcentaje_o_monto"], Decimal)


def test_promocion_finalizar_marca_fecha_fin(client, db_conn):
    """POST /promociones/<id>/finalizar: contra el código previo revienta
    por el placeholder `?` en el UPDATE."""
    cliente = _cliente(db_conn, "Con promo activa")
    promo_id = db_conn.execute(
        """INSERT INTO promociones_aplicadas
           (cliente_id, tipo, porcentaje_o_monto, alcance, fecha_inicio, aprobado_por)
           VALUES (%s, 'porcentaje', 10, 'todo', CURRENT_DATE, 'test') RETURNING id""",
        (cliente,),
    ).fetchone()["id"]
    db_conn.commit()

    respuesta = client.post(f"/promociones/{promo_id}/finalizar", follow_redirects=True)
    assert respuesta.status_code < 400

    fecha_fin = db_conn.execute(
        "SELECT fecha_fin FROM promociones_aplicadas WHERE id = %s", (promo_id,)
    ).fetchone()["fecha_fin"]
    assert fecha_fin is not None


def test_stock_no_facturado_registra_movimiento_y_actualiza_stock(client, db_conn):
    """POST /stock/no-facturado: precio pasó de float() a a_decimal()."""
    prod = _producto(db_conn, "Suelto sin factura", Decimal("50.00"), 10)
    db_conn.commit()

    respuesta = client.post(
        "/stock/no-facturado",
        data={"tipo": "compra", "producto_id": str(prod), "cantidad": "3", "precio": "45.90"},
        follow_redirects=True,
    )
    assert respuesta.status_code < 400

    fila = db_conn.execute(
        "SELECT stock_actual FROM productos WHERE id = %s", (prod,)
    ).fetchone()
    assert fila["stock_actual"] == 13

    mov = db_conn.execute(
        "SELECT cantidad, precio, conciliado FROM movimientos_no_facturados WHERE producto_id = %s", (prod,)
    ).fetchone()
    assert mov["cantidad"] == 3
    assert mov["precio"] == Decimal("45.90")
    assert isinstance(mov["precio"], Decimal)
    assert mov["conciliado"] is False


def test_stock_no_facturado_conciliar_es_booleano_de_verdad(client, db_conn):
    """POST .../conciliar: conciliado=1 pasó a conciliado=true (BOOLEAN)."""
    prod = _producto(db_conn, "Para conciliar", Decimal("20.00"), 5)
    mov_id = db_conn.execute(
        """INSERT INTO movimientos_no_facturados (tipo, producto_id, cantidad, precio, conciliado)
           VALUES ('compra', %s, 1, 20.00, false) RETURNING id""",
        (prod,),
    ).fetchone()["id"]
    db_conn.commit()

    respuesta = client.post(f"/stock/no-facturado/{mov_id}/conciliar", follow_redirects=True)
    assert respuesta.status_code < 400

    conciliado = db_conn.execute(
        "SELECT conciliado FROM movimientos_no_facturados WHERE id = %s", (mov_id,)
    ).fetchone()["conciliado"]
    assert conciliado is True
