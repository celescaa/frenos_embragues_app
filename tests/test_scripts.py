"""Los scripts se corren a mano de vez en cuando, así que nadie se entera de
que están rotos hasta que se los necesita — justo el día que hay que cargar
los datos reales. Estos tests ejercitan sus funciones de base contra Postgres.

Nota sobre `test_importar_datos_carga_un_producto_con_precio_exacto` y
`test_la_planilla_lista_solo_proveedores_activos`: un round-trip por la base
prueba que Postgres guarda bien un `Decimal`/`BOOLEAN` ya construido, no que
el script arme ese valor correctamente a partir de un Excel. Por eso, además
de esos dos tests (documentan el contrato de la columna), este archivo suma
tests que llaman directo a las funciones de parseo/consulta de cada script
-- son los que de verdad se rompen si el port queda mal hecho."""
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_obtener_o_crear_proveedor_devuelve_id(db_conn):
    """Usaba cur.lastrowid, que en psycopg no existe: tiene que venir de
    RETURNING id."""
    from scripts.cargar_stock_por_proveedor import obtener_o_crear_proveedor

    id_nuevo = obtener_o_crear_proveedor(db_conn, "Proveedor Recién Creado")
    assert isinstance(id_nuevo, int) and id_nuevo > 0

    id_repetido = obtener_o_crear_proveedor(db_conn, "Proveedor Recién Creado")
    assert id_repetido == id_nuevo, "no debe duplicar un proveedor que ya existe"


def test_la_planilla_lista_solo_proveedores_activos(db_conn):
    """activo=1 no funciona contra una columna BOOLEAN de Postgres. Llama a
    la función que usa generar_planilla_stock_proveedores.py de verdad (no
    repite la consulta acá) -- si la query del script sigue en `activo=1`,
    esto revienta con "operator does not exist: boolean = integer" en vez
    de simplemente filtrar mal."""
    from scripts.generar_planilla_stock_proveedores import obtener_proveedores_activos

    db_conn.execute("INSERT INTO proveedores (nombre, activo) VALUES ('Vigente SRL', true)")
    db_conn.execute("INSERT INTO proveedores (nombre, activo) VALUES ('Ya no se usa SA', false)")
    nombres = [f["nombre"] for f in obtener_proveedores_activos(db_conn)]
    assert "Vigente SRL" in nombres
    assert "Ya no se usa SA" not in nombres


def test_importar_datos_carga_un_producto_con_precio_exacto(db_conn):
    """No llama al importador (ver nota del módulo más arriba): construye el
    Decimal a mano y lo hace ida y vuelta por un INSERT/SELECT directo. Solo
    prueba que la columna NUMERIC de Postgres devuelve el mismo Decimal
    exacto que se escribió -- no que `scripts/importar_datos.py` arme ese
    valor bien a partir de un Excel. Ese contrato lo cubre
    `test_numero_tolera_formato_argentino_y_devuelve_decimal`, más abajo, que
    sí llama a la función de parseo real del script."""
    db_conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta)
           VALUES ('Importado', 'Frenos', %s, %s)""",
        (Decimal("12500.50"), Decimal("16250.65")),
    )
    fila = db_conn.execute(
        "SELECT precio_costo, precio_venta FROM productos WHERE nombre = 'Importado'"
    ).fetchone()
    assert fila["precio_costo"] == Decimal("12500.50")
    assert fila["precio_venta"] == Decimal("16250.65")


def test_numero_tolera_formato_argentino_y_devuelve_decimal():
    """Guarda de verdad la precisión de plata: prueba la función de parseo
    en Python puro, no a través de la base (un NUMERIC(12,2) de Postgres
    redondea y devuelve Decimal sin importar qué tipo escribió el valor, así
    que un round-trip por la base no puede detectar si esta función todavía
    devuelve float)."""
    from scripts.importar_datos import _numero

    valor = _numero("12.500,50")
    assert valor == Decimal("12500.50")
    assert isinstance(valor, Decimal), f"debe ser Decimal, no {type(valor)}"
    assert not isinstance(valor, float)


def test_numero_entero_sigue_devolviendo_int():
    """La tolerancia de formato no cambia para columnas enteras (stock,
    cantidad) -- solo cambió el tipo de salida para plata."""
    from scripts.importar_datos import _numero

    valor = _numero("14", entero=True)
    assert valor == 14
    assert isinstance(valor, int)


def test_fecha_devuelve_date_no_string():
    """Las columnas de fecha son DATE en Postgres: importar_datos.py tiene
    que entregar un datetime.date, no la cadena "YYYY-MM-DD" de antes."""
    from scripts.importar_datos import _fecha

    valor = _fecha("13/08/2026")
    assert valor == date(2026, 8, 13)
    assert isinstance(valor, date)


def test_fecha_tolera_varios_formatos_de_entrada():
    """Misma tolerancia de siempre (Y-m-d, d/m/Y, d-m-Y, Y/m/d) -- no se
    perdió ningún formato al cambiar el tipo de salida."""
    from scripts.importar_datos import _fecha

    esperado = date(2026, 8, 13)
    assert _fecha("2026-08-13") == esperado
    assert _fecha("13/08/2026") == esperado
    assert _fecha("13-08-2026") == esperado
    assert _fecha("2026/08/13") == esperado


# --------------------------------------------------------------------------
# scripts/seed_datos_prueba.py
# --------------------------------------------------------------------------
def test_el_seed_carga_los_13_proveedores_reales(db_conn):
    """Los proveedores son el dato REAL del negocio: si el seed carga de
    menos, la parte que sí va a producción queda incompleta."""
    from scripts.seed_datos_prueba import PROVEEDORES_REALES, sembrar_proveedores

    ids = sembrar_proveedores(db_conn)
    assert len(ids) == len(PROVEEDORES_REALES) == 13
    cargados = db_conn.execute("SELECT COUNT(*) AS c FROM proveedores").fetchone()["c"]
    assert cargados == 13

    fila = db_conn.execute(
        "SELECT * FROM proveedores WHERE nombre='Icepar'"
    ).fetchone()
    assert fila["cuit"] == "33-51966896-0"
    assert fila["activo"] is True


def test_el_seed_no_duplica_proveedores_al_correrlo_de_nuevo(db_conn):
    """Es la garantía que permite correr la parte de proveedores en
    producción sin miedo: la segunda corrida actualiza, no duplica."""
    from scripts.seed_datos_prueba import sembrar_proveedores

    primeros = sembrar_proveedores(db_conn)
    segundos = sembrar_proveedores(db_conn)

    assert primeros == segundos, "los ids tienen que ser los mismos"
    assert db_conn.execute("SELECT COUNT(*) AS c FROM proveedores").fetchone()["c"] == 13


def test_el_seed_reconoce_por_cuit_un_proveedor_ya_cargado_a_mano(db_conn):
    """El CUIT identifica al proveedor mejor que el nombre: si alguien ya lo
    cargó desde /proveedores con otra grafía, el seed tiene que actualizar esa
    fila en vez de crear un duplicado con el nombre de la planilla."""
    from scripts.seed_datos_prueba import sembrar_proveedores

    db_conn.execute(
        "INSERT INTO proveedores (nombre, cuit) VALUES ('RONCAL REPUESTOS', '30-53361668-9')"
    )
    sembrar_proveedores(db_conn)

    filas = db_conn.execute(
        "SELECT nombre FROM proveedores WHERE cuit='30-53361668-9'"
    ).fetchall()
    assert len(filas) == 1, "no debe duplicar un proveedor que ya estaba por CUIT"
    assert filas[0]["nombre"] == "Roncal Repuestos S.A"


def test_el_seed_de_prueba_deja_las_pantallas_con_datos(db_conn):
    """Un solo test para el conjunto: si alguna parte del seed se rompe, la
    pantalla que dependía de ella queda vacía sin que nadie se entere."""
    from scripts.seed_datos_prueba import sembrar_datos_prueba, sembrar_proveedores

    sembrar_datos_prueba(db_conn, sembrar_proveedores(db_conn))

    def contar(tabla):
        return db_conn.execute(f"SELECT COUNT(*) AS c FROM {tabla}").fetchone()["c"]

    for tabla in [
        "clientes", "productos", "producto_proveedor", "ventas", "venta_items",
        "compras", "compra_items", "cuenta_corriente_movimientos",
        "cuenta_corriente_movimiento_items", "promociones_aplicadas",
        "promocion_productos", "movimientos_no_facturados", "pedidos_web",
        "pedido_web_items",
    ]:
        assert contar(tabla) > 0, f"{tabla} quedó vacía"

    # Al menos un cliente debiendo plata, si no /clientes/top-deudores no
    # muestra nada.
    deudores = db_conn.execute(
        """SELECT SUM(CASE WHEN tipo='cargo' THEN monto ELSE -monto END) AS saldo
           FROM cuenta_corriente_movimientos GROUP BY cliente_id"""
    ).fetchall()
    assert any(f["saldo"] > 0 for f in deudores)

    # Y al menos un producto bajo el mínimo cuyo proveedor más barato NO sea
    # el de la ficha: es el caso que /pedidos marca con "mejor precio".
    assert db_conn.execute(
        """SELECT COUNT(*) AS c FROM productos p
           WHERE p.stock_actual <= p.stock_minimo AND p.stock_minimo > 0
             AND NOT p.pedido_pendiente
             AND EXISTS (SELECT 1 FROM producto_proveedor pp
                         WHERE pp.producto_id = p.id AND pp.proveedor_id <> p.proveedor_id
                           AND pp.precio_costo < (SELECT precio_costo FROM producto_proveedor
                                                  WHERE producto_id = p.id AND proveedor_id = p.proveedor_id))"""
    ).fetchone()["c"] > 0


def test_el_seed_guarda_la_plata_como_decimal(db_conn):
    """Las columnas de plata son NUMERIC: un float en el seed entra igual
    (Postgres lo castea) pero arrastra el error de redondeo del float hasta
    ahí. El seed construye Decimal desde strings, no desde float."""
    from decimal import Decimal as D

    from scripts.seed_datos_prueba import sembrar_datos_prueba, sembrar_proveedores

    sembrar_datos_prueba(db_conn, sembrar_proveedores(db_conn))
    fila = db_conn.execute(
        "SELECT precio_costo, precio_venta FROM productos WHERE codigo='EMB-VOL-001'"
    ).fetchone()
    assert fila["precio_costo"] == D("268000.00")
    assert fila["precio_venta"] == D("429000.00")


# --- Carga de la planilla de stock por proveedor ----------------------------

def _hoja_de_planilla(filas):
    """Arma en memoria una hoja con el encabezado real de la planilla.

    El importador lee cada campo POR POSICIÓN, así que el encabezado tiene
    que estar completo: un test que arme filas sueltas sin él no probaría el
    mismo camino que la planilla de verdad."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append([
        "Cargar (SI/NO)", "Código interno", "Categoría", "Descripción / Nombre (*)",
        "Marca", "Modelo compatible", "Precio costo (*)", "Precio venta (*)",
        "Cantidad en stock (*)", "Stock mínimo", "Código de barras", "Subcategoría",
    ])
    for fila in filas:
        ws.append(fila)
    return ws


def test_la_planilla_solo_carga_las_filas_con_cantidad(db_conn):
    """La planilla trae el catálogo COMPLETO de cada proveedor (~200.000
    filas) y el local trabaja una fracción. La cantidad escrita a mano es lo
    único que distingue "esto lo tenemos" de "esto el proveedor lo vende":
    sin este filtro, la primera carga llenaría el sistema de productos
    fantasma en stock 0."""
    from scripts.cargar_stock_por_proveedor import _procesar_hoja, obtener_o_crear_proveedor

    proveedor_id = obtener_o_crear_proveedor(db_conn, "Proveedor De Prueba")
    ws = _hoja_de_planilla([
        ["SI", "CON-CANT", "Frenos", "PASTILLA QUE SI TENEMOS", "Cobreq", "Fiat Palio",
         1000, 1300, 4, 2, None, "Pastillas de freno"],
        ["SI", "SIN-CANT", "Frenos", "PASTILLA QUE NO TENEMOS", "Cobreq", "VW Gol",
         1000, 1300, None, 2, None, "Pastillas de freno"],
    ])
    resumen = {"proveedores_nuevos": 0, "productos_nuevos": 0, "productos_actualizados": 0,
               "sin_cantidad": 0, "avisos": []}
    _procesar_hoja(ws, proveedor_id, "Proveedor De Prueba", db_conn, resumen)

    codigos = [f["codigo"] for f in db_conn.execute(
        "SELECT codigo FROM productos WHERE proveedor_id = %s", (proveedor_id,)
    ).fetchall()]
    assert codigos == ["CON-CANT"]
    assert resumen["sin_cantidad"] == 1


def test_una_cantidad_en_cero_si_se_carga(db_conn):
    """Cero es un dato: significa "lo trabajamos pero se acabó", y el
    producto tiene que existir para que aparezca en la lista de pedidos.
    Es distinto de la celda vacía, que significa "no lo trabajamos"."""
    from scripts.cargar_stock_por_proveedor import _procesar_hoja, obtener_o_crear_proveedor

    proveedor_id = obtener_o_crear_proveedor(db_conn, "Proveedor Con Cero")
    ws = _hoja_de_planilla([
        ["SI", "AGOTADO", "Frenos", "PASTILLA AGOTADA", "Cobreq", "Fiat Palio",
         1000, 1300, 0, 2, None, "Pastillas de freno"],
    ])
    resumen = {"proveedores_nuevos": 0, "productos_nuevos": 0, "productos_actualizados": 0,
               "sin_cantidad": 0, "avisos": []}
    _procesar_hoja(ws, proveedor_id, "Proveedor Con Cero", db_conn, resumen)

    fila = db_conn.execute("SELECT stock_actual FROM productos WHERE codigo='AGOTADO'").fetchone()
    assert fila is not None, "una cantidad en 0 no se puede confundir con una celda vacía"
    assert fila["stock_actual"] == 0


def test_la_planilla_guarda_la_subcategoria(db_conn):
    """La columna existe en la planilla desde que se sumaron las
    subcategorías (06/08/2026), pero este importador nunca la leía: los
    productos entraban con el rubro cargado y el subrubro vacío, sin que
    nada avisara."""
    from scripts.cargar_stock_por_proveedor import _procesar_hoja, obtener_o_crear_proveedor

    proveedor_id = obtener_o_crear_proveedor(db_conn, "Proveedor Con Subrubro")
    ws = _hoja_de_planilla([
        ["SI", "SUB-001", "Embrague", "KIT DE EMBRAGUE FIAT PALIO", "Valeo", "Fiat Palio",
         1000, 1300, 3, 2, None, "Kits de embrague (disco + plato + collarín)"],
    ])
    resumen = {"proveedores_nuevos": 0, "productos_nuevos": 0, "productos_actualizados": 0,
               "sin_cantidad": 0, "avisos": []}
    _procesar_hoja(ws, proveedor_id, "Proveedor Con Subrubro", db_conn, resumen)

    fila = db_conn.execute(
        "SELECT categoria, subcategoria FROM productos WHERE codigo='SUB-001'"
    ).fetchone()
    assert fila["categoria"] == "Embrague"
    assert fila["subcategoria"] == "Kits de embrague (disco + plato + collarín)"


def test_el_mismo_codigo_en_otro_proveedor_no_pisa_el_producto(db_conn):
    """Dos distribuidores venden la misma pieza con el mismo código de
    fábrica (el extremo LT10006 está en Distrisuper y en Zerbini). Como
    `productos.codigo` es UNIQUE, el importador le cambiaba al producto ya
    cargado el nombre, el precio, el stock y hasta el proveedor, en silencio.
    Ahora el segundo proveedor entra como una cotización, que es lo que el
    comparador de precios de /pedidos necesita para elegir a quién comprarle."""
    from scripts.cargar_stock_por_proveedor import _procesar_hoja, obtener_o_crear_proveedor

    uno = obtener_o_crear_proveedor(db_conn, "Distribuidor Uno")
    dos = obtener_o_crear_proveedor(db_conn, "Distribuidor Dos")
    resumen = {"proveedores_nuevos": 0, "productos_nuevos": 0, "productos_actualizados": 0,
               "sin_cantidad": 0, "sin_identificar": 0, "cotizaciones": 0, "avisos": []}

    _procesar_hoja(_hoja_de_planilla([
        ["SI", "LT10006", "Dirección", "EXTREMO PEUGEOT 205 306 504 PARTNER", "TRW",
         "Peugeot 205", 1000, 1300, 5, 2, None, "Terminales / rótulas"],
    ]), uno, "Distribuidor Uno", db_conn, resumen)
    _procesar_hoja(_hoja_de_planilla([
        ["SI", "LT10006", "Dirección", "EXTREMO DE DIRECCION", "TRW", "", 900, 1170, 7, 2,
         None, "Terminales / rótulas"],
    ]), dos, "Distribuidor Dos", db_conn, resumen)

    productos = db_conn.execute(
        "SELECT nombre, proveedor_id, stock_actual FROM productos WHERE codigo='LT10006'"
    ).fetchall()
    assert len(productos) == 1
    assert productos[0]["nombre"] == "EXTREMO PEUGEOT 205 306 504 PARTNER", "no lo tiene que pisar"
    assert productos[0]["proveedor_id"] == uno
    assert productos[0]["stock_actual"] == 5

    cotizaciones = {f["proveedor_id"]: f["precio_costo"] for f in db_conn.execute(
        """SELECT pp.proveedor_id, pp.precio_costo FROM producto_proveedor pp
           JOIN productos p ON p.id = pp.producto_id WHERE p.codigo='LT10006'"""
    ).fetchall()}
    assert cotizaciones == {uno: Decimal("1000.00"), dos: Decimal("900.00")}
    assert resumen["cotizaciones"] == 1


def test_dos_productos_distintos_que_se_llaman_igual_no_se_pisan(db_conn):
    """Zerbini lista 12 rodamientos distintos con la descripción idéntica
    "RODAMIENTO DE RODILLOS (CON JAULA) CONO Y CUBETA" y códigos diferentes.
    El importador los buscaba por nombre cuando el código no estaba en la
    base, los colapsaba en un solo producto y le dejaba el código del último:
    11 piezas desaparecían sin que nada avisara."""
    from scripts.cargar_stock_por_proveedor import _procesar_hoja, obtener_o_crear_proveedor

    proveedor_id = obtener_o_crear_proveedor(db_conn, "Zerbini De Prueba")
    resumen = {"proveedores_nuevos": 0, "productos_nuevos": 0, "productos_actualizados": 0,
               "sin_cantidad": 0, "sin_identificar": 0, "cotizaciones": 0, "avisos": []}
    _procesar_hoja(_hoja_de_planilla([
        ["SI", codigo, "Suspensión", "RODAMIENTO DE RODILLOS (CON JAULA) CONO Y CUBETA",
         "SKF", "", 1000, 1300, 2, 2, None, "Rodamientos y rulemanes"]
        for codigo in ("30203", "30205", "30208")
    ]), proveedor_id, "Zerbini De Prueba", db_conn, resumen)

    codigos = sorted(f["codigo"] for f in db_conn.execute(
        "SELECT codigo FROM productos WHERE proveedor_id = %s", (proveedor_id,)
    ).fetchall())
    assert codigos == ["30203", "30205", "30208"]
    assert resumen["productos_nuevos"] == 3
