"""La búsqueda tiene que aguantar cómo escribe alguien que no usa programas:
mayúsculas, acentos, palabras en otro orden. Cada uno de estos tests es un
caso real de mostrador, no una variante teórica."""
import pytest
from core import database as db


@pytest.fixture
def catalogo(db_conn):
    """Cuatro productos que cubren los casos de los tests de abajo."""
    ids = {}
    filas = [
        ("Pastilla de freno delantera", "Frenos", "Pastillas", "Cobreq", "FIAT Palio", 5),
        ("Kit de embrague", "Embragues", "Kits de embrague", "Sachs", "VW Gol", 0),
        ("Líquido de freno hidráulico", "Frenos", "Líquidos de freno", "Wagner", "", 3),
        ("Buje de parrilla", "Suspensión y Dirección", None, "VTH", "FIAT Palio", 2),
    ]
    for nombre, categoria, subcategoria, marca, modelo, stock in filas:
        ids[nombre] = db_conn.execute(
            """INSERT INTO productos
               (nombre, categoria, subcategoria, marca, modelo_compatible,
                stock_actual, precio_costo, precio_venta)
               VALUES (%s, %s, %s, %s, %s, %s, 100, 130) RETURNING id""",
            (nombre, categoria, subcategoria, marca, modelo, stock),
        ).fetchone()["id"]
    return ids


def nombres(filas):
    return sorted(f["nombre"] for f in filas)


def test_no_distingue_mayusculas(db_conn, catalogo):
    for texto in ["pastilla", "PASTILLA", "PaStIlLa"]:
        assert "Pastilla de freno delantera" in nombres(
            db.buscar_productos(db_conn, q=texto)
        ), f"falló con '{texto}'"


def test_no_distingue_acentos(db_conn, catalogo):
    """Nadie escribe los acentos en un buscador."""
    assert "Líquido de freno hidráulico" in nombres(
        db.buscar_productos(db_conn, q="hidraulico")
    )
    assert "Líquido de freno hidráulico" in nombres(
        db.buscar_productos(db_conn, q="liquido")
    )


def test_no_importa_el_orden_de_las_palabras(db_conn, catalogo):
    """El caso del mostrador: el cliente dice el auto primero."""
    assert nombres(db.buscar_productos(db_conn, q="palio pastilla")) == [
        "Pastilla de freno delantera"
    ]


def test_cada_palabra_tiene_que_estar(db_conn, catalogo):
    """No alcanza con que matchee una: 'pastilla gol' no existe."""
    assert db.buscar_productos(db_conn, q="pastilla gol") == []


def test_los_espacios_de_mas_no_molestan(db_conn, catalogo):
    assert nombres(db.buscar_productos(db_conn, q="  palio    pastilla ")) == [
        "Pastilla de freno delantera"
    ]


def test_filtra_por_categoria_y_subcategoria(db_conn, catalogo):
    assert len(db.buscar_productos(db_conn, categoria="Frenos")) == 2
    assert nombres(db.buscar_productos(db_conn, categoria="Frenos", subcategoria="Pastillas")) == [
        "Pastilla de freno delantera"
    ]


def test_filtra_por_marca(db_conn, catalogo):
    assert nombres(db.buscar_productos(db_conn, marca="Cobreq")) == [
        "Pastilla de freno delantera"
    ]


def test_solo_con_stock_deja_afuera_los_que_estan_en_cero(db_conn, catalogo):
    resultado = nombres(db.buscar_productos(db_conn, solo_con_stock=True))
    assert "Kit de embrague" not in resultado
    assert len(resultado) == 3


def test_filtra_por_vehiculo_vinculado(db_conn, catalogo):
    """El filtro de auto mira los autos VINCULADOS, no el texto libre: el buje
    y la pastilla dicen 'FIAT Palio' en modelo_compatible, pero solo la
    pastilla está vinculada de verdad."""
    vehiculo_id = db_conn.execute(
        """INSERT INTO vehiculos (marca_auto, modelo, motor)
           VALUES ('FIAT', 'Palio', '1.4') RETURNING id"""
    ).fetchone()["id"]
    db_conn.execute(
        "INSERT INTO producto_vehiculos (producto_id, vehiculo_id) VALUES (%s, %s)",
        (catalogo["Pastilla de freno delantera"], vehiculo_id),
    )
    assert nombres(db.buscar_productos(db_conn, vehiculo_id=vehiculo_id)) == [
        "Pastilla de freno delantera"
    ]


def test_encuentra_por_el_auto_vinculado_escribiendolo(db_conn, catalogo):
    """Escribir 'palio' también tiene que traer lo vinculado a un Palio,
    aunque el producto no diga 'Palio' en ningún campo suyo."""
    vehiculo_id = db_conn.execute(
        """INSERT INTO vehiculos (marca_auto, modelo, motor)
           VALUES ('FIAT', 'Palio', '1.4') RETURNING id"""
    ).fetchone()["id"]
    db_conn.execute(
        "INSERT INTO producto_vehiculos (producto_id, vehiculo_id) VALUES (%s, %s)",
        (catalogo["Kit de embrague"], vehiculo_id),
    )
    assert "Kit de embrague" in nombres(db.buscar_productos(db_conn, q="palio embrague"))


def test_el_codigo_de_barras_matchea_exacto_y_no_por_parecido(db_conn, catalogo):
    """Es lo que dispara la pistola: un match aproximado ahí sería cargar el
    producto equivocado en la venta."""
    db_conn.execute(
        "UPDATE productos SET codigo_barras = '7791234567890' WHERE id = %s",
        (catalogo["Kit de embrague"],),
    )
    assert nombres(db.buscar_productos(db_conn, q="7791234567890")) == ["Kit de embrague"]
    assert db.buscar_productos(db_conn, q="779123456789") == []


def test_los_filtros_se_combinan(db_conn, catalogo):
    assert db.buscar_productos(db_conn, q="pastilla", categoria="Embragues") == []


def test_el_limite_recorta(db_conn, catalogo):
    assert len(db.buscar_productos(db_conn, limite=2)) == 2


def test_sin_filtros_devuelve_todo(db_conn, catalogo):
    assert len(db.buscar_productos(db_conn)) == 4
