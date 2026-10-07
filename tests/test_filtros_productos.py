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


def test_un_error_de_tipeo_ya_muestra_el_producto(client, catalogo):
    """"pastila" ya no necesita sugerencia: la búsqueda tolerante lo rescata
    sola y muestra la pastilla, avisando que no es literal lo que se escribió.
    Antes esto caía en el "¿Quisiste decir?" y había que hacer un clic más."""
    texto = client.get("/productos?q=pastila").data.decode()
    assert "Pastilla delantera" in texto
    assert "quisiste decir" not in texto.lower()
    assert "lo más parecido" in texto


def test_muestra_sugerencias_cuando_no_hay_resultados(client, catalogo):
    """Con una palabra que no se puede rescatar ("heladera" no se parece a
    nada del catálogo), la búsqueda queda vacía y ahí sí entra la sugerencia
    sobre la palabra que sí se parecía."""
    respuesta = client.get("/productos?q=pastila+heladera")
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
    respuesta = client.get("/productos?q=pastila+heladera")
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


# --- Proveedor y el listado compacto -----------------------------------------

@pytest.fixture
def con_proveedores(db_conn, catalogo):
    """La pastilla es de Zerbini y el kit de embrague de Rodamitre."""
    ids = {}
    for nombre, producto in [("Zerbini", "Pastilla delantera"), ("Rodamitre", "Kit de embrague")]:
        ids[nombre] = db_conn.execute(
            "INSERT INTO proveedores (nombre) VALUES (%s) RETURNING id", (nombre,)
        ).fetchone()["id"]
        db_conn.execute(
            "UPDATE productos SET proveedor_id = %s WHERE nombre = %s", (ids[nombre], producto)
        )
    db_conn.commit()
    return ids


def test_filtra_por_proveedor(client, con_proveedores):
    texto = client.get(f"/productos?proveedor_id={con_proveedores['Zerbini']}").data.decode()
    assert "Pastilla delantera" in texto
    assert "Kit de embrague" not in texto


def test_el_desplegable_de_proveedor_lleva_contador(client, con_proveedores):
    texto = client.get("/productos").data.decode()
    assert re.search(r"Zerbini\s*\(1\)", texto)
    assert re.search(r"Rodamitre\s*\(1\)", texto)


def test_la_x_del_proveedor_saca_solo_ese_filtro(client, con_proveedores):
    pagina = client.get(
        f"/productos?proveedor_id={con_proveedores['Zerbini']}&categoria=Frenos"
    ).data.decode()
    consultas = [_query(h) for h in _hrefs_de_los_x(pagina)]
    assert {"categoria": ["Frenos"]} in consultas, "la X del proveedor conserva el rubro"


def test_un_proveedor_invalido_no_rompe_la_pantalla(client, catalogo):
    assert client.get("/productos?proveedor_id=abc").status_code == 200


def test_buscar_por_nombre_de_proveedor_desde_la_pantalla(client, con_proveedores):
    texto = client.get("/productos?q=zerbini").data.decode()
    assert "Pastilla delantera" in texto
    assert "Kit de embrague" not in texto


def test_la_fila_muestra_el_proveedor(client, con_proveedores):
    """Rodamitre no está filtrado ni elegido: si aparece en una fila es
    porque la fila nombra a su proveedor."""
    texto = client.get("/productos?q=embrague").data.decode()
    assert "Rodamitre" in texto.split('id="productosBody"')[1]


def test_mas_barato_solo_aparece_si_hay_dos_cotizaciones(client, con_proveedores, db_conn):
    pastilla = db_conn.execute("SELECT id FROM productos WHERE nombre = 'Pastilla delantera'").fetchone()["id"]
    db_conn.execute(
        "INSERT INTO producto_proveedor (producto_id, proveedor_id, precio_costo) VALUES (%s, %s, 100)",
        (pastilla, con_proveedores["Zerbini"]),
    )
    db_conn.commit()
    assert "Más barato en" not in client.get("/productos").data.decode()

    db_conn.execute(
        "INSERT INTO producto_proveedor (producto_id, proveedor_id, precio_costo) VALUES (%s, %s, 80)",
        (pastilla, con_proveedores["Rodamitre"]),
    )
    db_conn.commit()
    assert "Más barato en Rodamitre" in client.get("/productos").data.decode()
