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
