"""La pantalla de Stock con la barra de filtros. Lo que se prueba acá es que
la ruta pase los filtros a db.buscar_productos() y muestre lo que hay que
mostrar; el criterio de búsqueda en sí tiene sus propios tests."""
import html
import re
from urllib.parse import parse_qs, urlparse

import pytest
from core.app import app as flask_app


def _hrefs_de_los_x(pagina):
    """Los links de la X de cada etiqueta de filtro activo, en el orden en
    que aparecen en la pantalla (q, categoría, subcategoría, marca, auto,
    sólo con stock -- se omite el que no esté activo). El HTML autoescapa
    el '&' del query string como '&amp;', así que hay que desescaparlo
    antes de parsear la URL -- si no, "&amp;marca=Cobreq" no matchea como
    parámetro "marca"."""
    return [
        html.unescape(href)
        for href in re.findall(
            r'<a href="([^"]+)"\s+class="text-white text-decoration-none ms-1">&times;</a>',
            pagina,
        )
    ]


def _query(href):
    return parse_qs(urlparse(href).query)


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


@pytest.fixture
def catalogo(db_conn):
    filas = [
        ("Pastilla delantera", "Frenos", "Pastillas", "Cobreq", 5),
        ("Disco de freno", "Frenos", "Discos", "Fric-Rot", 0),
        ("Kit de embrague", "Embragues", "Kits de embrague", "Sachs", 3),
    ]
    for nombre, categoria, subcategoria, marca, stock in filas:
        db_conn.execute(
            """INSERT INTO productos
               (nombre, categoria, subcategoria, marca, stock_actual, precio_costo, precio_venta)
               VALUES (%s, %s, %s, %s, %s, 100, 130)""",
            (nombre, categoria, subcategoria, marca, stock),
        )
    db_conn.commit()


def test_filtra_por_marca(client, catalogo):
    respuesta = client.get("/productos?marca=Cobreq")
    assert b"Pastilla delantera" in respuesta.data
    assert b"Kit de embrague" not in respuesta.data


def test_filtra_solo_con_stock(client, catalogo):
    respuesta = client.get("/productos?solo_con_stock=1")
    assert b"Disco de freno" not in respuesta.data
    assert b"Pastilla delantera" in respuesta.data


def test_filtra_por_auto(client, catalogo, db_conn):
    vehiculo_id = db_conn.execute(
        "INSERT INTO vehiculos (marca_auto, modelo, motor) VALUES ('FIAT','Palio','1.4') RETURNING id"
    ).fetchone()["id"]
    producto_id = db_conn.execute(
        "SELECT id FROM productos WHERE nombre = 'Pastilla delantera'"
    ).fetchone()["id"]
    db_conn.execute(
        "INSERT INTO producto_vehiculos (producto_id, vehiculo_id) VALUES (%s, %s)",
        (producto_id, vehiculo_id),
    )
    db_conn.commit()
    respuesta = client.get(f"/productos?vehiculo_id={vehiculo_id}")
    assert b"Pastilla delantera" in respuesta.data
    assert b"Kit de embrague" not in respuesta.data


def test_un_auto_invalido_no_rompe_la_pantalla(client, catalogo):
    """Postgres aborta la consulta con un id no numérico; sin a_entero() esto
    es un error 500."""
    respuesta = client.get("/productos?vehiculo_id=abc")
    assert respuesta.status_code == 200


def test_muestra_sugerencias_cuando_no_hay_resultados(client, catalogo):
    respuesta = client.get("/productos?q=pastila")
    assert "quisiste decir" in respuesta.data.decode().lower()
    assert b"Pastilla delantera" in respuesta.data


def test_avisa_cuando_recorta_los_resultados(client, db_conn):
    """Con el catálogo real dibujar la tabla entera cuelga el navegador. El
    aviso dice la verdad en vez de aparentar que hay 200 nomás."""
    from core import app as core_app

    for i in range(core_app.LIMITE_RESULTADOS + 5):
        db_conn.execute(
            """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta)
               VALUES (%s, 'Frenos', 100, 130)""",
            (f"Producto {i:04d}",),
        )
    db_conn.commit()
    respuesta = client.get("/productos")
    assert b"Mostrando" in respuesta.data
    assert str(core_app.LIMITE_RESULTADOS + 5).encode() in respuesta.data


def test_los_filtros_se_combinan(client, catalogo):
    respuesta = client.get("/productos?categoria=Frenos&marca=Sachs")
    assert b"Kit de embrague" not in respuesta.data
    assert b"Pastilla delantera" not in respuesta.data


def test_mensaje_vacio_sin_filtros_dice_que_no_hay_productos_cargados(client, db_conn):
    """Con la base vacía y sin filtros, el mensaje tiene que decir eso -- no
    'ningún producto coincide con los filtros', que no aplica acá."""
    respuesta = client.get("/productos")
    assert "No hay productos cargados todavía." in respuesta.data.decode()


def test_mensaje_vacio_con_filtro_dice_que_no_coincide_nada(client, catalogo):
    """Con productos cargados pero un filtro que no cruza con ninguno, decir
    'no hay productos cargados' sería mentira (hay 3) y confunde a quien no
    usa programas: el mensaje tiene que hablar del filtro, no de la base."""
    respuesta = client.get("/productos?categoria=Frenos&marca=Sachs")
    texto = respuesta.data.decode()
    assert "Ningún producto coincide con los filtros aplicados." in texto
    assert "No hay productos cargados todavía." not in texto


def test_mensaje_vacio_no_aparece_junto_a_las_sugerencias(client, catalogo):
    """Cuando hay sugerencias ('¿Quisiste decir?'), ese alert ya explica por
    qué no hay resultados -- mostrar además el mensaje de la tabla vacía es
    contradictorio (las dos cosas dicen algo distinto a la vez)."""
    respuesta = client.get("/productos?q=pastila")
    texto = respuesta.data.decode()
    assert "quisiste decir" in texto.lower()
    assert "Ningún producto coincide" not in texto
    assert "No hay productos cargados todavía." not in texto


def test_la_x_de_una_etiqueta_conserva_los_demas_filtros(client, catalogo):
    """La X de cada etiqueta tiene que sacar SOLO su propio filtro. Es
    server-side, barato de probar, y no depende de JS -- y no es teórico:
    buscando este mecanismo se encontró que la X del rubro no sacaba el
    subrubro (ver el test de abajo)."""
    respuesta = client.get("/productos?q=pastilla&categoria=Frenos&marca=Cobreq")
    hrefs = _hrefs_de_los_x(respuesta.data.decode())
    assert len(hrefs) == 3, hrefs
    q_href, categoria_href, marca_href = hrefs

    q_qs = _query(q_href)
    assert "q" not in q_qs
    assert q_qs.get("categoria") == ["Frenos"]
    assert q_qs.get("marca") == ["Cobreq"]

    categoria_qs = _query(categoria_href)
    assert "categoria" not in categoria_qs
    assert categoria_qs.get("q") == ["pastilla"]
    assert categoria_qs.get("marca") == ["Cobreq"]

    marca_qs = _query(marca_href)
    assert "marca" not in marca_qs
    assert marca_qs.get("q") == ["pastilla"]
    assert marca_qs.get("categoria") == ["Frenos"]


def test_la_x_del_rubro_saca_tambien_el_subrubro(client, catalogo):
    """Secuencia real: filtrás Frenos + Pastillas, tocás la X de Frenos. Un
    subrubro sin su rubro no es un estado que tenga sentido -- si quedara
    "?subcategoria=Pastillas" solo, el JS repuebla el desplegable de
    subrubro vacío (sin rubro elegido) y el próximo envío del formulario lo
    borra en silencio."""
    respuesta = client.get("/productos?categoria=Frenos&subcategoria=Pastillas")
    hrefs = _hrefs_de_los_x(respuesta.data.decode())
    assert len(hrefs) == 2, hrefs
    categoria_href, subcategoria_href = hrefs

    categoria_qs = _query(categoria_href)
    assert "categoria" not in categoria_qs
    assert "subcategoria" not in categoria_qs

    subcategoria_qs = _query(subcategoria_href)
    assert "subcategoria" not in subcategoria_qs
    assert subcategoria_qs.get("categoria") == ["Frenos"]
