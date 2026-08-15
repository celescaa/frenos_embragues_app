"""Lo que la migración del buscador deja en la base: la normalización de
texto y la siembra de marcas sin duplicados.

La normalización se prueba acá y no junto a buscar_productos() porque es una
función de la base: si deja de sacar acentos, TODA búsqueda del sistema
empeora sin lanzar ningún error."""
import psycopg
import pytest


def texto(conn, valor):
    return conn.execute("SELECT texto_busqueda(%s) AS t", (valor,)).fetchone()["t"]


def test_normaliza_mayusculas_acentos_y_espacios(db_conn):
    assert texto(db_conn, "HIDRÁULICO") == "hidraulico"
    assert texto(db_conn, "  Bujía   Precalentamiento ") == "bujia precalentamiento"
    assert texto(db_conn, None) == ""


def test_sembrar_marcas_junta_las_que_solo_cambian_en_mayusculas_o_acentos(db_conn):
    for marca in ["COBREQ", "Cobreq", "cobreq ", "Fric-Rot"]:
        db_conn.execute(
            """INSERT INTO productos (nombre, categoria, marca, precio_costo, precio_venta)
               VALUES (%s, 'Frenos', %s, 100, 130)""",
            (f"Pastilla {marca}", marca),
        )
    agregadas = db_conn.execute("SELECT sembrar_marcas_desde_productos() AS n").fetchone()["n"]
    assert agregadas == 2, "COBREQ/Cobreq/'cobreq ' son la misma marca"
    # Se compara normalizado a propósito: cuál de las tres grafías queda
    # guardada depende del collation de la base, y eso no es lo que este test
    # viene a fijar — lo que importa es que quede UNA sola.
    nombres = sorted(
        r["nombre"].strip().lower()
        for r in db_conn.execute("SELECT nombre FROM marcas")
    )
    assert nombres == ["cobreq", "fric-rot"]


def test_sembrar_marcas_es_idempotente(db_conn):
    db_conn.execute(
        """INSERT INTO productos (nombre, categoria, marca, precio_costo, precio_venta)
           VALUES ('Pastilla', 'Frenos', 'Cobreq', 100, 130)"""
    )
    db_conn.execute("SELECT sembrar_marcas_desde_productos()")
    agregadas = db_conn.execute("SELECT sembrar_marcas_desde_productos() AS n").fetchone()["n"]
    assert agregadas == 0


def test_no_se_puede_borrar_un_vehiculo_en_uso(db_conn):
    producto_id = db_conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta)
           VALUES ('Buje', 'Suspensión y Dirección', 100, 130) RETURNING id"""
    ).fetchone()["id"]
    vehiculo_id = db_conn.execute(
        """INSERT INTO vehiculos (marca_auto, modelo, motor)
           VALUES ('FIAT', 'Palio', '1.4') RETURNING id"""
    ).fetchone()["id"]
    db_conn.execute(
        "INSERT INTO producto_vehiculos (producto_id, vehiculo_id) VALUES (%s, %s)",
        (producto_id, vehiculo_id),
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db_conn.execute("DELETE FROM vehiculos WHERE id = %s", (vehiculo_id,))


def test_borrar_un_producto_se_lleva_sus_vehiculos(db_conn):
    producto_id = db_conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta)
           VALUES ('Buje', 'Suspensión y Dirección', 100, 130) RETURNING id"""
    ).fetchone()["id"]
    vehiculo_id = db_conn.execute(
        """INSERT INTO vehiculos (marca_auto, modelo, motor)
           VALUES ('FIAT', 'Palio', '1.4') RETURNING id"""
    ).fetchone()["id"]
    db_conn.execute(
        "INSERT INTO producto_vehiculos (producto_id, vehiculo_id) VALUES (%s, %s)",
        (producto_id, vehiculo_id),
    )
    db_conn.execute("DELETE FROM productos WHERE id = %s", (producto_id,))
    quedan = db_conn.execute("SELECT count(*) AS n FROM producto_vehiculos").fetchone()["n"]
    assert quedan == 0
