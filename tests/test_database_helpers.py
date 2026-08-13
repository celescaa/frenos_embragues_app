from decimal import Decimal
from core import database as db


def _proveedor(conn, nombre, activo=True):
    return conn.execute(
        "INSERT INTO proveedores (nombre, activo) VALUES (%s, %s) RETURNING id",
        (nombre, activo),
    ).fetchone()["id"]


def _producto(conn, nombre="Pastilla X"):
    return conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta)
           VALUES (%s, 'Frenos', 100, 130) RETURNING id""",
        (nombre,),
    ).fetchone()["id"]


def test_obtener_categorias_devuelve_solo_activas(db_conn):
    """Usa nombres propios de este test: las categorías iniciales ya vienen
    sembradas por la migración, así que insertar una de ellas chocaría."""
    db_conn.execute(
        "INSERT INTO categorias (nombre, activo) VALUES ('Rubro de prueba activo', true)"
    )
    db_conn.execute(
        "INSERT INTO categorias (nombre, activo) VALUES ('Rubro de prueba inactivo', false)"
    )
    nombres = db.obtener_categorias(db_conn, solo_activas=True)
    assert "Rubro de prueba activo" in nombres
    assert "Rubro de prueba inactivo" not in nombres


def test_mejor_precio_ignora_proveedores_desactivados(db_conn):
    """Sugerir reponerle a un proveedor que ya no se usa no tiene sentido."""
    barato = _proveedor(db_conn, "Barato pero inactivo", activo=False)
    caro = _proveedor(db_conn, "Caro pero activo", activo=True)
    prod = _producto(db_conn)
    db_conn.execute(
        "INSERT INTO producto_proveedor (producto_id, proveedor_id, precio_costo) VALUES (%s, %s, %s)",
        (prod, barato, Decimal("50.00")),
    )
    db_conn.execute(
        "INSERT INTO producto_proveedor (producto_id, proveedor_id, precio_costo) VALUES (%s, %s, %s)",
        (prod, caro, Decimal("80.00")),
    )
    mejor = db.obtener_mejor_precio_por_producto(db_conn, prod)
    assert mejor["precio_costo"] == Decimal("80.00")


def test_los_datos_de_ejemplo_se_cargan(db_conn):
    db.seed_demo_data(db_conn)
    total = db_conn.execute("SELECT COUNT(*) AS n FROM productos").fetchone()["n"]
    assert total > 0
