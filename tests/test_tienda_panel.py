"""Tienda online pública, panel/dashboard, usuarios y login.

Los primeros 3 tests son los que trae el brief de la Tarea 9. El primero
(`test_el_catalogo_de_la_tienda_busca_sin_distinguir_mayusculas`) sí pasa
por la ruta `/tienda` y ejercita el port. Los otros dos
(`test_el_bloqueo_por_intentos_usa_marca_de_tiempo`,
`test_el_panel_agrupa_ventas_por_mes`) son de esquema, contra `db_conn`
directo con SQL Postgres ya escrito a mano en el propio test -- confirman
hechos ciertos sobre la base migrada (bloqueado_hasta es timestamptz,
to_char sirve para agrupar por mes) pero NO ejercitan el código portado en
`core/app.py`: pasarían igual si el port de esta tarea nunca se hubiera
hecho.

Por eso, el segundo grupo de acá abajo son tests de RUTA (test_client de
Flask, con sesión de admin donde hace falta) que sí fallan contra el
`core/app.py` previo al port -- placeholders `?` (psycopg no los entiende,
revienta con `psycopg.ProgrammingError`), `datetime.strptime()` sobre un
valor que psycopg ya devuelve como `datetime` (revienta con `TypeError`), o
un convertidor de ruta `<int:...>` que ni siquiera matchea un id con forma
de UUID (404 antes de llegar al handler). Son la cobertura real del
dashboard, el bloqueo de login, el convertidor uuid de `/usuarios` y la
idempotencia del webhook de Mercado Pago.

Nota sobre facturacion_afip: una venta con método de pago "Mercado Pago"
siempre dispara Factura A/B, y el webhook llama a
`facturacion_afip.emitir_factura()` -- función de la Tarea 10, todavía sin
portar (sigue con `?`). Se neutraliza con monkeypatch en el test que ejerce
el camino de pago aprobado, para no depender de un módulo que no es
responsabilidad de esta tarea (mismo criterio ya usado en la Tarea 8 con
emitir_factura_movimiento)."""
from decimal import Decimal

import pytest

from core import facturacion_afip, tienda_pagos
from core.app import app as flask_app


# ---------------------------------------------------------------------------
# Tests del brief (verbatim)
# ---------------------------------------------------------------------------
def test_el_catalogo_de_la_tienda_busca_sin_distinguir_mayusculas(db_conn):
    """Tercer y último buscador del sistema."""
    from core.app import app as flask_app
    db_conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta, stock_actual)
           VALUES ('Disco Ventilado', 'Frenos', 100, 200, 5)"""
    )
    db_conn.commit()
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        respuesta = c.get("/tienda?q=disco")
        assert b"Disco Ventilado" in respuesta.data


def test_el_bloqueo_por_intentos_usa_marca_de_tiempo(db_conn, crear_usuario):
    """bloqueado_hasta pasó de texto a timestamptz: ya no se parsea a mano."""
    from datetime import datetime, timezone, timedelta
    usuario = crear_usuario("bloqueado", nombre="Test")
    futuro = datetime.now(timezone.utc) + timedelta(minutes=15)
    db_conn.execute(
        "UPDATE usuarios SET bloqueado_hasta=%s WHERE id=%s", (futuro, usuario["id"])
    )
    fila = db_conn.execute(
        "SELECT bloqueado_hasta FROM usuarios WHERE username = 'bloqueado'"
    ).fetchone()
    assert isinstance(fila["bloqueado_hasta"], datetime)


def test_el_panel_agrupa_ventas_por_mes(db_conn):
    cliente = db_conn.execute(
        "INSERT INTO clientes (nombre, fecha_alta) VALUES ('X', CURRENT_DATE) RETURNING id"
    ).fetchone()["id"]
    db_conn.execute(
        """INSERT INTO ventas (fecha, cliente_id, total, metodo_pago)
           VALUES (CURRENT_DATE, %s, %s, 'Efectivo')""",
        (cliente, Decimal("1000.00")),
    )
    fila = db_conn.execute(
        """SELECT to_char(fecha, 'MM/YYYY') AS mes, SUM(total) AS total
           FROM ventas GROUP BY mes"""
    ).fetchone()
    assert fila["total"] == Decimal("1000.00")


# ---------------------------------------------------------------------------
# Tests de ruta: ejercitan core/app.py y fallan contra el código previo al
# port de esta tarea.
# ---------------------------------------------------------------------------
def _cliente(conn, nombre="Cliente"):
    return conn.execute(
        "INSERT INTO clientes (nombre, fecha_alta) VALUES (%s, CURRENT_DATE) RETURNING id",
        (nombre,),
    ).fetchone()["id"]


def _producto(conn, nombre, precio_venta, stock, categoria="Frenos"):
    return conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta, stock_actual)
           VALUES (%s, %s, 1, %s, %s) RETURNING id""",
        (nombre, categoria, precio_venta, stock),
    ).fetchone()["id"]


@pytest.fixture
def client_admin(crear_usuario):
    """Sesión de admin ya iniciada.

    Usa el fixture `crear_usuario`, que crea también la cuenta en Supabase
    Auth: desde que `usuarios.id` es clave foránea de `auth.users`, un perfil
    insertado a mano no tiene dónde apoyarse y la base lo rechaza.
    """
    usuario_id = crear_usuario("admin_test", rol="admin", nombre="Admin Test")["id"]
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        with c.session_transaction() as sesion:
            sesion["usuario_id"] = str(usuario_id)
            sesion["usuario_nombre"] = "Admin Test"
            sesion["usuario_rol"] = "admin"
            sesion["debe_cambiar_password"] = False
        yield c, usuario_id


def test_dashboard_carga_con_ventas_y_agrupa_top_por_id(client_admin, db_conn):
    """GET '/': contra el código previo, top_productos/top_clientes agrupan
    por vi.producto_id / v.cliente_id -- Postgres lo rechaza porque
    p.nombre/c.nombre no son funcionalmente dependientes de esas columnas
    (rompe con GroupingError), y el resto de las consultas del panel siguen
    usando `?`. Portado, la pantalla tiene que cargar con 200 y mostrar el
    top de productos/clientes."""
    client, _ = client_admin
    cliente = _cliente(db_conn, "Comprador Frecuente")
    prod = _producto(db_conn, "Disco de freno", Decimal("500.00"), 10)
    venta_id = db_conn.execute(
        """INSERT INTO ventas (fecha, cliente_id, total, metodo_pago)
           VALUES (CURRENT_DATE, %s, %s, 'Efectivo') RETURNING id""",
        (cliente, Decimal("500.00")),
    ).fetchone()["id"]
    db_conn.execute(
        """INSERT INTO venta_items (venta_id, producto_id, cantidad, precio_unitario, subtotal)
           VALUES (%s, %s, 1, %s, %s)""",
        (venta_id, prod, Decimal("500.00"), Decimal("500.00")),
    )
    db_conn.commit()

    respuesta = client.get("/")
    assert respuesta.status_code == 200
    cuerpo = respuesta.data.decode()
    assert "Comprador Frecuente" in cuerpo
    assert "Disco de freno" in cuerpo


def test_login_bloquea_tras_5_intentos_y_no_revienta_al_leer_el_bloqueo(db_conn, crear_usuario):
    """Contra el código previo, ya el primer POST revienta (`?` en el SELECT
    de usuarios). Portado: 5 intentos con contraseña incorrecta bloquean la
    cuenta, y un 6to intento (aunque la contraseña sea correcta) tiene que
    avisar que sigue bloqueada, sin TypeError por mezclar datetime naive/
    tz-aware."""
    crear_usuario("bloqueame", password="correcta123", nombre="Test")

    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        for _ in range(5):
            r = c.post("/login", data={"username": "bloqueame", "password": "incorrecta"})
            assert r.status_code == 200

        respuesta = c.post(
            "/login", data={"username": "bloqueame", "password": "correcta123"}, follow_redirects=True
        )
    assert respuesta.status_code == 200
    assert "intentos fallidos" in respuesta.data.decode().lower()

    fila = db_conn.execute(
        "SELECT intentos_fallidos, bloqueado_hasta FROM usuarios WHERE username = 'bloqueame'"
    ).fetchone()
    assert fila["intentos_fallidos"] == 5
    assert fila["bloqueado_hasta"] is not None


def test_usuarios_editar_usa_convertidor_uuid(client_admin, crear_usuario):
    """La ruta tiene que aceptar un id con forma de UUID en la URL. Contra
    el código previo (`<int:usuario_id>`), Flask ni siquiera matchea la
    ruta con un id así -- 404 antes de llegar al handler."""
    client, _ = client_admin
    otro = crear_usuario("otro_admin", rol="admin")["id"]

    respuesta = client.get(f"/usuarios/{otro}/editar")
    assert respuesta.status_code == 200
    assert b"otro_admin" in respuesta.data


def test_usuarios_nuevo_crea_usuario_activo_con_booleanos_reales(client_admin, db_conn):
    """activo/debe_cambiar_password son BOOLEAN de verdad ahora, no 0/1.
    Contra el código previo, ya el chequeo de username duplicado (`?`)
    revienta."""
    client, _ = client_admin
    respuesta = client.post(
        "/usuarios/nuevo",
        data={"username": "nuevo_empleado", "nombre": "Nuevo Empleado", "rol": "empleado"},
        follow_redirects=True,
    )
    assert respuesta.status_code == 200

    fila = db_conn.execute(
        "SELECT activo, debe_cambiar_password, rol FROM usuarios WHERE username='nuevo_empleado'"
    ).fetchone()
    assert fila["activo"] is True
    assert fila["debe_cambiar_password"] is True
    assert fila["rol"] == "empleado"


def test_webhook_mercadopago_es_idempotente(db_conn, monkeypatch):
    """Un pedido ya 'pagado' no tiene que generar una segunda venta si
    Mercado Pago reintenta la notificación. Contra el código previo, la
    primera consulta de la ruta (SELECT pedidos_web WHERE id=?) ya revienta
    con psycopg.ProgrammingError."""
    pedido_id = db_conn.execute(
        """INSERT INTO pedidos_web (fecha, nombre_cliente, telefono, total, estado)
           VALUES (CURRENT_DATE, 'Comprador Web', '111', %s, 'pagado')
           RETURNING id""",
        (Decimal("100.00"),),
    ).fetchone()["id"]
    db_conn.commit()

    monkeypatch.setattr(
        tienda_pagos, "obtener_pago",
        lambda payment_id: {"external_reference": str(pedido_id), "status": "approved"},
    )
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        respuesta = c.post("/webhooks/mercadopago?data.id=123&type=payment")
    assert respuesta.status_code == 200

    cantidad_ventas = db_conn.execute("SELECT COUNT(*) AS c FROM ventas").fetchone()["c"]
    assert cantidad_ventas == 0


def test_webhook_mercadopago_aprobado_genera_venta_crea_cliente_y_descuenta_stock(db_conn, monkeypatch):
    """Pago aprobado sobre un pedido pendiente: tiene que crear el cliente
    (no existía por email/teléfono), generar la venta real con RETURNING id
    (ya no cursor.lastrowid) y descontar stock -- mismo criterio que una
    venta del local. facturacion_afip.emitir_factura() es de la Tarea 10
    (todavía con `?`); se neutraliza para no depender de un módulo que no
    es responsabilidad de esta tarea."""
    monkeypatch.setattr(facturacion_afip, "emitir_factura", lambda venta_id: None)
    prod = _producto(db_conn, "Kit de embrague", Decimal("1000.00"), 5)
    pedido_id = db_conn.execute(
        """INSERT INTO pedidos_web (fecha, nombre_cliente, telefono, email, total, estado)
           VALUES (CURRENT_DATE, 'Nuevo Comprador', '222333', 'nuevo@correo.com', %s, 'pendiente_pago')
           RETURNING id""",
        (Decimal("1000.00"),),
    ).fetchone()["id"]
    db_conn.execute(
        """INSERT INTO pedido_web_items (pedido_id, producto_id, cantidad, precio_unitario, subtotal)
           VALUES (%s, %s, 1, %s, %s)""",
        (pedido_id, prod, Decimal("1000.00"), Decimal("1000.00")),
    )
    db_conn.commit()

    monkeypatch.setattr(
        tienda_pagos, "obtener_pago",
        lambda payment_id: {"external_reference": str(pedido_id), "status": "approved"},
    )
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        respuesta = c.post("/webhooks/mercadopago?data.id=999&type=payment")
    assert respuesta.status_code == 200

    venta = db_conn.execute(
        """SELECT v.total, v.metodo_pago FROM ventas v
           JOIN clientes c ON c.id = v.cliente_id WHERE c.email = 'nuevo@correo.com'"""
    ).fetchone()
    assert venta is not None
    assert venta["total"] == Decimal("1000.00")
    assert venta["metodo_pago"] == "Mercado Pago"

    stock = db_conn.execute("SELECT stock_actual FROM productos WHERE id=%s", (prod,)).fetchone()["stock_actual"]
    assert stock == 4
