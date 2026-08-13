"""La lógica de compra NO está extraída en una función: vive dentro de la
ruta compras_nueva() (core/app.py:1667). Este plan migra, no refactoriza.

Los primeros 4 tests son de esquema (contra `db_conn` directo, sin pasar por
ninguna ruta): confirman hechos ciertos sobre la base migrada en la Tarea 2
(las FK se aplican siempre, `activo`/`pedido_pendiente` son booleanos de
verdad) pero NO ejercitan el código portado en `core/app.py` -- pasarían
igual si el port de esta tarea nunca se hubiera hecho. Por eso, más abajo,
hay un segundo grupo de tests de RUTA (con el `test_client` de Flask, sesión
iniciada) que sí falla contra el `core/app.py` previo al port (ver
`task-7-report.md`, sección "Ronda de correcciones 1" para la comprobación
empírica) y es la cobertura real de compras_nueva(), proveedores_eliminar()
y pedidos_lista()."""
from decimal import Decimal

import psycopg
import pytest

from core.app import app as flask_app


# ---------------------------------------------------------------------------
# Tests de esquema (no ejercitan el port de esta tarea, ver docstring de
# arriba) -- se mantienen porque verifican hechos ciertos sobre la base.
# ---------------------------------------------------------------------------
def test_no_se_puede_borrar_un_proveedor_con_datos_asociados(db_conn):
    """Postgres aplica las FK siempre; SQLite necesitaba PRAGMA foreign_keys.
    Esto es lo que hace que, sin el `except psycopg.errors.ForeignKeyViolation`
    de la ruta (ver test_borrar_proveedor_con_productos_no_rompe_la_ruta más
    abajo), un DELETE así reviente."""
    prov = db_conn.execute(
        "INSERT INTO proveedores (nombre, activo) VALUES ('Con productos', true) RETURNING id"
    ).fetchone()["id"]
    db_conn.execute(
        """INSERT INTO productos (nombre, categoria, proveedor_id, precio_costo, precio_venta)
           VALUES ('Atado', 'Frenos', %s, 1, 2)""",
        (prov,),
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db_conn.execute("DELETE FROM proveedores WHERE id = %s", (prov,))


def test_activo_es_booleano_de_verdad(db_conn):
    """Dejó de ser INTEGER 0/1: en Python se compara contra True, no contra 1."""
    prov = db_conn.execute(
        "INSERT INTO proveedores (nombre, activo) VALUES ('P', true) RETURNING id"
    ).fetchone()["id"]
    fila = db_conn.execute("SELECT activo FROM proveedores WHERE id = %s", (prov,)).fetchone()
    assert fila["activo"] is True


def test_solo_los_proveedores_activos_se_ofrecen(db_conn):
    db_conn.execute("INSERT INTO proveedores (nombre, activo) VALUES ('Vigente', true)")
    db_conn.execute("INSERT INTO proveedores (nombre, activo) VALUES ('Dado de baja', false)")
    nombres = [
        f["nombre"]
        for f in db_conn.execute(
            "SELECT nombre FROM proveedores WHERE activo IS TRUE"
        ).fetchall()
    ]
    assert "Vigente" in nombres
    assert "Dado de baja" not in nombres


def test_pedidos_ignora_productos_sin_control_de_reposicion(db_conn):
    """stock_minimo = 0 significa 'no controlar reposición todavía'."""
    db_conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta,
                                  stock_actual, stock_minimo)
           VALUES ('En revisión', 'Frenos', 1, 2, 0, 0)"""
    )
    faltantes = db_conn.execute(
        """SELECT COUNT(*) AS n FROM productos
           WHERE stock_minimo > 0 AND stock_actual <= stock_minimo"""
    ).fetchone()["n"]
    assert faltantes == 0


# ---------------------------------------------------------------------------
# Tests de ruta: estos sí ejercitan el código portado en core/app.py y
# fallan contra el core/app.py previo al port de la Tarea 7.
# ---------------------------------------------------------------------------
@pytest.fixture
def client(db_conn):
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        with c.session_transaction() as sesion:
            sesion["usuario_id"] = "00000000-0000-0000-0000-000000000001"
            sesion["usuario_nombre"] = "Test"
            sesion["usuario_rol"] = "admin"
            sesion["debe_cambiar_password"] = False
        yield c


def test_borrar_proveedor_con_productos_no_rompe_la_ruta(client, db_conn):
    """Contra el código viejo, esto revienta: capturaba sqlite3.IntegrityError,
    que con psycopg nunca se dispara (la excepción real es
    psycopg.errors.ForeignKeyViolation), así que subía sin manejar. La ruta
    portada tiene que responder con el mensaje amistoso de siempre, nunca
    con un error sin manejar, y el proveedor tiene que seguir existiendo."""
    prov = db_conn.execute(
        "INSERT INTO proveedores (nombre, activo) VALUES ('Con productos', true) RETURNING id"
    ).fetchone()["id"]
    db_conn.execute(
        """INSERT INTO productos (nombre, categoria, proveedor_id, precio_costo, precio_venta)
           VALUES ('Atado', 'Frenos', %s, 1, 2)""",
        (prov,),
    )
    db_conn.commit()

    respuesta = client.post(f"/proveedores/{prov}/eliminar", follow_redirects=True)

    assert respuesta.status_code < 500
    assert "No se puede eliminar".encode() in respuesta.data

    fila = db_conn.execute("SELECT id FROM proveedores WHERE id = %s", (prov,)).fetchone()
    assert fila is not None, "el proveedor no debería haberse borrado"


def test_compras_nueva_registra_de_punta_a_punta(client, db_conn):
    """Cubre lo que compras_nueva() promete: sube el stock, actualiza el
    costo, limpia 'pedido pendiente', y -clave para el RETURNING id que
    reemplazó a cursor.lastrowid- cada compra queda con SUS PROPIOS
    compra_items y no con los de otra. Contra el código viejo esto falla de
    entrada: los placeholders `?` no son válidos para psycopg (usa `%s`),
    así que el POST ni siquiera llega a ejecutar el INSERT."""
    prov = db_conn.execute(
        "INSERT INTO proveedores (nombre, activo) VALUES ('Proveedor compra', true) RETURNING id"
    ).fetchone()["id"]
    prod_a = db_conn.execute(
        """INSERT INTO productos (nombre, categoria, proveedor_id, precio_costo, precio_venta,
                                  stock_actual, stock_minimo, pedido_pendiente, fecha_pedido_pendiente)
           VALUES ('Producto A', 'Frenos', %s, 5, 10, 2, 5, true, CURRENT_DATE) RETURNING id""",
        (prov,),
    ).fetchone()["id"]
    prod_b = db_conn.execute(
        """INSERT INTO productos (nombre, categoria, proveedor_id, precio_costo, precio_venta,
                                  stock_actual, stock_minimo)
           VALUES ('Producto B', 'Frenos', %s, 3, 6, 1, 5) RETURNING id""",
        (prov,),
    ).fetchone()["id"]
    db_conn.commit()

    r1 = client.post("/compras/nueva", data={
        "proveedor_id": str(prov),
        "numero_factura_proveedor": "FAC-A",
        "producto_id": [str(prod_a)],
        "cantidad": ["5"],
        "precio_unitario": ["12.50"],
    }, follow_redirects=True)
    assert r1.status_code < 400

    r2 = client.post("/compras/nueva", data={
        "proveedor_id": str(prov),
        "numero_factura_proveedor": "FAC-B",
        "producto_id": [str(prod_b)],
        "cantidad": ["2"],
        "precio_unitario": ["4.00"],
    }, follow_redirects=True)
    assert r2.status_code < 400

    # producto A: stock repuesto, costo actualizado, pedido_pendiente limpio
    fila_a = db_conn.execute(
        """SELECT stock_actual, precio_costo, pedido_pendiente, fecha_pedido_pendiente
           FROM productos WHERE id = %s""",
        (prod_a,),
    ).fetchone()
    assert fila_a["stock_actual"] == 7
    assert fila_a["precio_costo"] == Decimal("12.50")
    assert fila_a["pedido_pendiente"] is False
    assert fila_a["fecha_pedido_pendiente"] is None

    fila_b = db_conn.execute(
        "SELECT stock_actual, precio_costo FROM productos WHERE id = %s", (prod_b,)
    ).fetchone()
    assert fila_b["stock_actual"] == 3
    assert fila_b["precio_costo"] == Decimal("4.00")

    # cada compra quedó con SUS PROPIOS items -- el chequeo real del
    # RETURNING id: si compra_id se hubiera resuelto mal, los items de FAC-B
    # podrían haber quedado colgados de la compra de FAC-A (o viceversa).
    compra_a = db_conn.execute(
        "SELECT id FROM compras WHERE numero_factura_proveedor = 'FAC-A'"
    ).fetchone()
    compra_b = db_conn.execute(
        "SELECT id FROM compras WHERE numero_factura_proveedor = 'FAC-B'"
    ).fetchone()
    assert compra_a["id"] != compra_b["id"]

    items_a = db_conn.execute(
        "SELECT producto_id, cantidad, subtotal FROM compra_items WHERE compra_id = %s", (compra_a["id"],)
    ).fetchall()
    items_b = db_conn.execute(
        "SELECT producto_id, cantidad, subtotal FROM compra_items WHERE compra_id = %s", (compra_b["id"],)
    ).fetchall()
    assert len(items_a) == 1
    assert items_a[0]["producto_id"] == prod_a
    assert items_a[0]["cantidad"] == 5
    assert items_a[0]["subtotal"] == Decimal("62.50")

    assert len(items_b) == 1
    assert items_b[0]["producto_id"] == prod_b
    assert items_b[0]["cantidad"] == 2
    assert items_b[0]["subtotal"] == Decimal("8.00")


def test_pedidos_lista_responde_con_faltante_y_proveedor_activo(client, db_conn):
    """/pedidos arma la agrupación por proveedor más conveniente. Contra el
    código viejo también falla por los mismos placeholders `?`."""
    prov = db_conn.execute(
        "INSERT INTO proveedores (nombre, activo, email, telefono) VALUES ('Repone Bien', true, 'a@b.com', '111') RETURNING id"
    ).fetchone()["id"]
    db_conn.execute(
        """INSERT INTO productos (nombre, categoria, proveedor_id, precio_costo, precio_venta,
                                  stock_actual, stock_minimo)
           VALUES ('Bajo mínimo', 'Frenos', %s, 8, 15, 1, 5)""",
        (prov,),
    )
    db_conn.commit()

    respuesta = client.get("/pedidos")

    assert respuesta.status_code == 200
    assert "Bajo mínimo".encode() in respuesta.data
    assert "Repone Bien".encode() in respuesta.data
