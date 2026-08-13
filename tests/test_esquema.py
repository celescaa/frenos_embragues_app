"""Verifica que el esquema migrado tenga los tipos correctos.

Las dos correcciones del diseño (plata a decimal exacto, fechas a tipos de
fecha) se verifican acá porque un error silencioso en un tipo es de los más
caros de descubrir tarde.
"""
import pytest

# Las 21 columnas de plata que dejan de ser flotantes (ver el spec).
COLUMNAS_DE_PLATA = [
    ("productos", "precio_costo"), ("productos", "precio_venta"),
    ("ventas", "total"), ("ventas", "imp_neto"), ("ventas", "imp_iva"),
    ("venta_items", "precio_unitario"), ("venta_items", "subtotal"),
    ("compras", "total"),
    ("compra_items", "precio_unitario"), ("compra_items", "subtotal"),
    ("producto_proveedor", "precio_costo"),
    ("pedidos_web", "total"),
    ("pedido_web_items", "precio_unitario"), ("pedido_web_items", "subtotal"),
    ("cuenta_corriente_movimientos", "monto"),
    ("cuenta_corriente_movimientos", "imp_neto"),
    ("cuenta_corriente_movimientos", "imp_iva"),
    ("cuenta_corriente_movimiento_items", "precio_unitario"),
    ("cuenta_corriente_movimiento_items", "subtotal"),
    ("movimientos_no_facturados", "precio"),
    ("promociones_aplicadas", "porcentaje_o_monto"),
]

TABLAS_ESPERADAS = [
    "clientes", "proveedores", "productos", "ventas", "venta_items",
    "compras", "compra_items", "producto_proveedor", "pedidos_web",
    "pedido_web_items", "usuarios", "cuenta_corriente_movimientos",
    "cuenta_corriente_movimiento_items", "movimientos_no_facturados",
    "categorias", "subcategorias", "promociones_aplicadas",
    "promocion_productos",
]


def tipo_de(conn, tabla, columna):
    fila = conn.execute(
        """SELECT data_type FROM information_schema.columns
           WHERE table_name = %s AND column_name = %s""",
        (tabla, columna),
    ).fetchone()
    assert fila is not None, f"no existe {tabla}.{columna}"
    return fila["data_type"]


@pytest.mark.parametrize("tabla", TABLAS_ESPERADAS)
def test_la_tabla_existe(db_conn, tabla):
    fila = db_conn.execute(
        "SELECT to_regclass(%s) AS t", (f"public.{tabla}",)
    ).fetchone()
    assert fila["t"] is not None


@pytest.mark.parametrize("tabla,columna", COLUMNAS_DE_PLATA)
def test_la_plata_es_decimal_exacto(db_conn, tabla, columna):
    """Un flotante acumula error de redondeo. ARCA exige neto + IVA = total
    exacto, así que la plata tiene que ser numeric."""
    assert tipo_de(db_conn, tabla, columna) == "numeric"


def test_las_fechas_son_tipo_fecha(db_conn):
    assert tipo_de(db_conn, "ventas", "fecha") == "date"
    assert tipo_de(db_conn, "clientes", "fecha_alta") == "date"


def test_las_marcas_de_tiempo_llevan_zona_horaria(db_conn):
    assert tipo_de(db_conn, "usuarios", "fecha_creacion") == "timestamp with time zone"


def test_usuarios_usa_uuid(db_conn):
    """En el Plan 2 este id se liga a auth.users de Supabase Auth. Se define
    como uuid desde ahora para no cambiar el tipo dos veces."""
    assert tipo_de(db_conn, "usuarios", "id") == "uuid"
