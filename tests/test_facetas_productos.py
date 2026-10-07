"""Los contadores al lado de cada filtro. Lo que hace que 'se achique solo'
se sienta bien es que nunca manden a un rubro vacío."""
import pytest
from core import database as db


@pytest.fixture
def catalogo(db_conn):
    filas = [
        ("Pastilla delantera", "Frenos", "Pastillas", "Cobreq", 5),
        ("Pastilla trasera", "Frenos", "Pastillas", "Fric-Rot", 0),
        ("Disco de freno", "Frenos", "Discos", "Cobreq", 2),
        ("Kit de embrague", "Embragues", "Kits de embrague", "Sachs", 1),
    ]
    for nombre, categoria, subcategoria, marca, stock in filas:
        db_conn.execute(
            """INSERT INTO productos
               (nombre, categoria, subcategoria, marca, stock_actual, precio_costo, precio_venta)
               VALUES (%s, %s, %s, %s, %s, 100, 130)""",
            (nombre, categoria, subcategoria, marca, stock),
        )


def test_cuenta_por_categoria_sin_filtros(db_conn, catalogo):
    facetas = db.facetas_productos(db_conn)
    assert facetas["total"] == 4
    assert facetas["categoria"] == {"Frenos": 3, "Embragues": 1}


def test_una_categoria_elegida_no_se_filtra_a_si_misma(db_conn, catalogo):
    """Si al elegir Frenos el contador de Embragues cayera a 0, el usuario no
    podría ver que existe otra opción con productos. El contador de cada
    filtro se calcula SIN aplicarse a sí mismo."""
    facetas = db.facetas_productos(db_conn, categoria="Frenos")
    assert facetas["categoria"] == {"Frenos": 3, "Embragues": 1}
    assert facetas["total"] == 3, "el total sí respeta el filtro elegido"


def test_los_demas_filtros_si_achican_los_contadores(db_conn, catalogo):
    """Elegida la categoría Frenos, el contador de marcas solo cuenta frenos."""
    facetas = db.facetas_productos(db_conn, categoria="Frenos")
    assert facetas["marca"] == {"Cobreq": 2, "Fric-Rot": 1}
    assert "Sachs" not in facetas["marca"]


def test_solo_con_stock_se_refleja_en_los_contadores(db_conn, catalogo):
    facetas = db.facetas_productos(db_conn, solo_con_stock=True)
    assert facetas["total"] == 3
    assert facetas["categoria"] == {"Frenos": 2, "Embragues": 1}


def test_el_texto_buscado_achica_los_contadores(db_conn, catalogo):
    facetas = db.facetas_productos(db_conn, q="pastilla")
    assert facetas["total"] == 2
    assert facetas["categoria"] == {"Frenos": 2}


def test_los_productos_sin_subcategoria_no_rompen(db_conn, catalogo):
    db_conn.execute(
        """INSERT INTO productos (nombre, categoria, marca, precio_costo, precio_venta)
           VALUES ('Suelto', 'Otros', 'Sin marca', 100, 130)"""
    )
    facetas = db.facetas_productos(db_conn)
    assert facetas["total"] == 5
    assert None not in facetas["subcategoria"]


def test_marca_en_distinta_capitalizacion_da_una_sola_opcion_de_faceta(db_conn):
    """El catálogo real sale de listas de precios de proveedores con la
    marca escrita distinto (COBREQ / Cobreq / cobreq). Agrupar por la
    columna p.marca cruda mostraba esa marca tres veces en el desplegable
    de /productos, cada una con su propio contador de 1 -- aunque el
    filtro de marca (que sí compara normalizado) ya devolvía los tres
    productos al elegir cualquiera de las tres opciones."""
    for nombre, marca in [("Pastilla A", "Cobreq"), ("Pastilla B", "COBREQ")]:
        db_conn.execute(
            """INSERT INTO productos (nombre, categoria, marca, precio_costo, precio_venta)
               VALUES (%s, 'Frenos', %s, 100, 130)""",
            (nombre, marca),
        )
    facetas = db.facetas_productos(db_conn)
    assert len(facetas["marca"]) == 1, facetas["marca"]
    (nombre_faceta, cantidad), = facetas["marca"].items()
    assert cantidad == 2
    # Y filtrar usando esa misma opción devuelve los dos productos.
    assert len(db.buscar_productos(db_conn, marca=nombre_faceta)) == 2


def test_cuenta_por_proveedor_y_no_se_filtra_a_si_mismo(db_conn):
    ids = [
        db_conn.execute("INSERT INTO proveedores (nombre) VALUES (%s) RETURNING id", (n,)).fetchone()["id"]
        for n in ("Zerbini", "Rodamitre")
    ]
    for nombre, proveedor_id in [("Parrilla", ids[0]), ("Rodamiento", ids[0]), ("Rotula", ids[1])]:
        db_conn.execute(
            """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta, proveedor_id)
               VALUES (%s, 'Suspensión', 100, 130, %s)""",
            (nombre, proveedor_id),
        )
    facetas = db.facetas_productos(db_conn, proveedor_id=ids[0])
    assert facetas["proveedor_id"] == {ids[0]: 2, ids[1]: 1}
    assert facetas["total"] == 2
