"""La lógica de compra NO está extraída en una función: vive dentro de la
ruta compras_nueva() (core/app.py:1667). Este plan migra, no refactoriza, así
que se verifica el comportamiento a nivel de base y de ruta."""
import psycopg
import pytest


def test_no_se_puede_borrar_un_proveedor_con_datos_asociados(db_conn):
    """Postgres aplica las FK siempre; SQLite necesitaba PRAGMA foreign_keys.
    La ruta captura este error y muestra un mensaje claro."""
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
