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
    """El importador escribe plata: tiene que llegar como Decimal exacto."""
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
