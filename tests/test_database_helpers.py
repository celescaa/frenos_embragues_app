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


def test_precio_mas_barato_solo_cuando_hay_con_que_comparar(db_conn):
    """Con una sola cotización no hay 'mejor precio': es el único. La pantalla
    de Stock lo mostraba al lado de cada producto, repitiendo el proveedor."""
    prov = [
        db_conn.execute("INSERT INTO proveedores (nombre) VALUES (%s) RETURNING id", (n,)).fetchone()["id"]
        for n in ("Caro", "Barato", "Desactivado")
    ]
    db_conn.execute("UPDATE proveedores SET activo = false WHERE id = %s", (prov[2],))
    prods = [
        db_conn.execute(
            "INSERT INTO productos (nombre, categoria, precio_costo, precio_venta) VALUES (%s, 'Frenos', 1, 2) RETURNING id",
            (n,),
        ).fetchone()["id"]
        for n in ("Con dos", "Con una", "Con una activa")
    ]
    for producto, proveedor, precio in [
        (prods[0], prov[0], "150.00"), (prods[0], prov[1], "120.00"),
        (prods[1], prov[0], "90.00"),
        # la segunda cotización es de un proveedor desactivado: no cuenta
        (prods[2], prov[0], "90.00"), (prods[2], prov[2], "10.00"),
    ]:
        db_conn.execute(
            "INSERT INTO producto_proveedor (producto_id, proveedor_id, precio_costo) VALUES (%s, %s, %s)",
            (producto, proveedor, precio),
        )
    baratos = db.obtener_precios_mas_baratos(db_conn, prods)
    assert list(baratos) == [prods[0]]
    assert baratos[prods[0]]["proveedor_nombre"] == "Barato"
    assert baratos[prods[0]]["precio_costo"] == Decimal("120.00")
    assert db.obtener_precios_mas_baratos(db_conn, []) == {}
