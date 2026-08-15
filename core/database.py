"""
Conexión y helpers de datos para el sistema de gestión de ventas de frenos y
embragues, sobre Postgres.

El esquema (creación de tablas) y sus migraciones ya no viven acá: pasaron a
`supabase/migrations/` (ver Tarea 2 y 4 del plan de migración a Postgres).
Este módulo ya no crea ni migra nada — solo abre conexiones y expone los
helpers de consulta/siembra de datos de ejemplo que usa el resto del
sistema.
"""
import os
import random
import secrets
import string
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

# Cadena de conexión. En desarrollo apunta al Postgres local que levanta
# `npx supabase start`; en producción, al pooler de Supabase.
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@127.0.0.1:54322/postgres",
)

# El negocio está en Ituzaingó, provincia de Buenos Aires. "Hoy" es el día
# ACÁ, no donde corra el servidor.
TZ_NEGOCIO = ZoneInfo("America/Argentina/Buenos_Aires")

# Lo mismo, para usar del lado de Postgres. Sirve para comparar contra
# columnas DATE dentro de una consulta sin tener que pasar la fecha como
# parámetro: así el criterio de "hoy" es uno solo, escrito en un solo lugar.
HOY_SQL = "(now() AT TIME ZONE 'America/Argentina/Buenos_Aires')::date"


def hoy():
    """La fecha de hoy para el negocio, en Argentina.

    Existe porque `datetime.now()` devuelve la hora local del servidor, y eso
    dejó de ser Argentina al desplegar en Vercel, que corre en UTC — tres
    horas adelante. Con `datetime.now()`, a partir de las 21:00 hora argentina
    el sistema empieza a fechar todo con el día siguiente: una venta cargada a
    las 21:30 no aparece en las ventas del día, una promoción creada a esa
    hora no se aplica hasta mañana, y el total del mes cambia de mes tres
    horas antes. Ninguno de esos casos tira un error; simplemente dan números
    equivocados.
    """
    return datetime.now(TZ_NEGOCIO).date()


def get_connection():
    """Conexión a Postgres.

    dict_row: las filas se acceden por nombre (venta["fecha"]), igual que con
    sqlite3.Row — por eso ningún template necesitó cambiar.

    prepare_threshold=None: OBLIGATORIO. En producción esto sale por el pooler
    de Supabase en modo transacción, que NO soporta prepared statements, y
    psycopg los activa solo a partir de la quinta ejecución de una consulta.
    Sin esta línea el sistema funciona al principio y empieza a fallar
    después, que es de los bugs más difíciles de diagnosticar.
    """
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        prepare_threshold=None,
    )


# Categorías del catálogo (local y tienda online). Ya NO es la lista fija:
# viven en la tabla `categorias`, editable desde /categorias. Esta lista es
# el dato de siembra inicial, cargado ahora vía
# supabase/migrations/20260813145208_esquema_inicial.sql (antes lo hacía
# _sembrar_categorias, en Python, eliminada en la Tarea 4 de la migración a
# Postgres porque correr eso en cada arranque en frío no tiene sentido en
# serverless). Se conserva acá como dato de referencia y porque
# scripts/importar_datos.py todavía la usa junto con CATEGORIAS_RENOMBRADAS
# para validar la categoría de cada fila.
CATEGORIAS_INICIALES = [
    "Frenos", "Embragues", "Correas", "Líquidos",
    "Rodamientos y Mazas", "Suspensión y Dirección", "Filtros",
    "Retenes y Juntas", "Transmisión", "Motor", "Ferretería",
    "Otros",
]

# Subcategorías iniciales por categoría (taxonomía granular armada en otro
# chat a partir de clasificar de punta a punta las listas de precios reales
# de 5 proveedores — ~107.000 filas). Mismo criterio que CATEGORIAS_INICIALES
# de arriba: el dato de siembra en sí ahora vive en la migración de
# Supabase, esto queda como referencia/documentación del dato.
SUBCATEGORIAS_INICIALES = {
    "Correas": ["Correas", "Tensores y poleas"],
    "Embragues": [
        "Bombas y cilindros", "Crapodinas y collarines", "Discos y platos",
        "Otros de embrague", "Volantes bimasa",
    ],
    "Frenos": [
        "Pastillas", "Discos", "Campanas", "Zapatas", "Seguros antirruido",
        "Válvulas y actuadores", "Cables y sensores de desgaste",
        "Mangueras y flexibles", "Cables y cintas", "Bombas y cilindros",
        "Otros de frenos",
    ],
    "Rodamientos y Mazas": ["Mazas de rueda", "Rodamientos y rulemanes"],
    "Suspensión y Dirección": [
        "Amortiguadores", "Parrillas y bujes", "Rótulas y extremos", "Bieletas",
        "Cremalleras y bombas de dirección", "Otros de suspensión/dirección",
    ],
    "Filtros": ["Filtro de aire", "Filtro de aceite", "Filtro de combustible"],
    "Retenes y Juntas": ["Retenes", "Juntas", "Diafragmas"],
    "Transmisión": [
        "Homocinéticas", "Semiejes y palieres", "Crucetas",
        "Coronas y diferencial", "Otros de transmisión",
    ],
    "Motor": ["Comando", "Encendido", "Refrigeración", "Vacío y servofreno", "Otros de motor"],
    "Ferretería": ["Tuercas", "Arandelas", "Bulones", "Tornillos"],
}

# Categorías viejas (antes de sumar Correas/Líquidos) -> nuevas equivalentes.
# Se usa tanto para actualizar productos ya cargados como en el importador,
# por si la planilla de carga todavía tiene el desplegable viejo.
CATEGORIAS_RENOMBRADAS = {"Freno": "Frenos", "Embrague": "Embragues", "Otro": "Otros"}


def obtener_categorias(conn=None, solo_activas=True):
    """Nombres de categorías cargadas en la tabla `categorias`, para
    dropdowns y validación. Si no se pasa una conexión abierta, abre y
    cierra una propia."""
    conn_propia = conn is None
    if conn_propia:
        conn = get_connection()
    consulta = "SELECT nombre FROM categorias"
    if solo_activas:
        consulta += " WHERE activo = true"
    consulta += " ORDER BY nombre"
    nombres = [r["nombre"] for r in conn.execute(consulta)]
    if conn_propia:
        conn.close()
    return nombres


def obtener_subcategorias(conn=None, categoria_id=None, solo_activas=True):
    """Subcategorías cargadas, opcionalmente filtradas a una categoría
    puntual. Devuelve filas completas (id, nombre, categoria_id, activo,
    categoria_nombre) para poder armar tanto dropdowns como el JSON de
    cascada categoría->subcategoría."""
    conn_propia = conn is None
    if conn_propia:
        conn = get_connection()
    consulta = """SELECT s.*, c.nombre AS categoria_nombre FROM subcategorias s
                  JOIN categorias c ON c.id = s.categoria_id"""
    condiciones, params = [], []
    if categoria_id:
        condiciones.append("s.categoria_id = %s")
        params.append(categoria_id)
    if solo_activas:
        condiciones.append("s.activo = true")
    if condiciones:
        consulta += " WHERE " + " AND ".join(condiciones)
    consulta += " ORDER BY c.nombre, s.nombre"
    filas = conn.execute(consulta, params).fetchall()
    if conn_propia:
        conn.close()
    return filas


# Campos de `productos` sobre los que busca el texto libre, concatenados y
# normalizados. Tiene que coincidir EXACTAMENTE con la expresión del índice
# `productos_texto_trgm` de la migración: si difieren, el índice deja de
# usarse y la búsqueda se vuelve lenta sin que nada avise.
TEXTO_PRODUCTO_SQL = """texto_busqueda(
    coalesce(p.nombre, '') || ' ' || coalesce(p.codigo, '') || ' ' ||
    coalesce(p.marca, '') || ' ' || coalesce(p.modelo_compatible, '')
)"""

# Lo mismo para los autos vinculados, para que escribir "palio" encuentre un
# producto que no dice "Palio" en ninguno de sus campos pero está vinculado
# a un Palio.
TEXTO_VEHICULOS_SQL = """EXISTS (
    SELECT 1 FROM producto_vehiculos pv JOIN vehiculos v ON v.id = pv.vehiculo_id
    WHERE pv.producto_id = p.id
      AND texto_busqueda(v.marca_auto || ' ' || v.modelo) LIKE '%%' || texto_busqueda(%s) || '%%'
)"""


def _condiciones_busqueda(q=None, categoria=None, subcategoria=None, marca=None,
                          vehiculo_id=None, solo_con_stock=False, excluir=()):
    """Arma el WHERE compartido por buscar_productos() y facetas_productos().

    `excluir` nombra filtros a NO aplicar: los contadores de cada filtro se
    calculan sin aplicarse a sí mismos, para que digan cuántos productos
    habría si el usuario cambiara de opción (si no, el filtro elegido siempre
    mostraría su propio total y el resto en cero).
    """
    condiciones, params = [], []

    # Cada palabra por separado, en cualquier orden: alguien que busca
    # "palio pastilla" tiene que encontrar "PASTILLA DE FRENO FIAT PALIO".
    # Se compara sobre texto ya normalizado con LIKE (no ILIKE): ILIKE sobre
    # la columna cruda no podría usar el índice trigram. El patrón se arma
    # en SQL con texto_busqueda(%s), no en Python: normalizar la palabra con
    # .lower() de este lado saca las mayúsculas pero no los acentos, y
    # texto_busqueda() sí los saca, así que los dos lados quedaban
    # normalizados distinto y buscar escribiendo el acento no encontraba
    # nada.
    for palabra in (q or "").split():
        condiciones.append(
            f"({TEXTO_PRODUCTO_SQL} LIKE '%%' || texto_busqueda(%s) || '%%' "
            f"OR p.codigo_barras = %s OR {TEXTO_VEHICULOS_SQL})"
        )
        # El código de barras matchea EXACTO, nunca por parecido: es lo que
        # dispara la pistola y un match aproximado sería cargar el producto
        # equivocado en la venta.
        params += [palabra, palabra, palabra]

    if categoria and "categoria" not in excluir:
        condiciones.append("p.categoria = %s")
        params.append(categoria)
    if subcategoria and "subcategoria" not in excluir:
        condiciones.append("p.subcategoria = %s")
        params.append(subcategoria)
    if marca and "marca" not in excluir:
        condiciones.append("texto_busqueda(p.marca) = texto_busqueda(%s)")
        params.append(marca)
    if vehiculo_id and "vehiculo_id" not in excluir:
        condiciones.append(
            "EXISTS (SELECT 1 FROM producto_vehiculos pv "
            "WHERE pv.producto_id = p.id AND pv.vehiculo_id = %s)"
        )
        params.append(vehiculo_id)
    if solo_con_stock:
        condiciones.append("p.stock_actual > 0")

    return condiciones, params


def buscar_productos(conn, q=None, categoria=None, subcategoria=None, marca=None,
                     vehiculo_id=None, solo_con_stock=False, limite=None):
    """Punto único de búsqueda de productos del sistema.

    Antes este criterio estaba escrito tres veces (la pantalla de Stock, el
    JSON del buscador tipo autocompletar y el catálogo de la tienda) y ya
    habían divergido entre sí. Cualquier pantalla que busque productos llama
    acá: si no, vuelve a haber una pantalla que busca mejor que otra.
    """
    condiciones, params = _condiciones_busqueda(
        q, categoria, subcategoria, marca, vehiculo_id, solo_con_stock
    )
    consulta = "SELECT p.* FROM productos p"
    if condiciones:
        consulta += " WHERE " + " AND ".join(condiciones)
    consulta += " ORDER BY p.categoria, p.nombre"
    if limite:
        consulta += " LIMIT %s"
        params = params + [limite]
    return conn.execute(consulta, params).fetchall()


# Parecido mínimo (0 a 1) para ofrecer una sugerencia. 0.3 es el default
# histórico de pg_trgm y tolera un par de letras cambiadas ("pastila" ->
# "pastilla") sin ofrecer cualquier cosa. Subirlo deja sin sugerencia
# errores reales; bajarlo sugiere productos que no tienen nada que ver.
UMBRAL_SUGERENCIA = 0.3


def sugerencias_busqueda(conn, q, limite=5):
    """Nombres parecidos a lo que se escribió, para cuando la búsqueda no
    devuelve nada. Es una sugerencia que se le muestra al usuario, NO un
    reemplazo automático: no se le cambia a alguien lo que buscó sin avisarle.

    Usa word_similarity() en vez de similarity(): similarity() compara las
    dos cadenas completas, así que un nombre de producto largo ("Pastilla de
    freno delantera") diluye el parecido de una palabra sola tipeada con
    error ("pastila") muy por debajo de 0.3 aunque la palabra que importa
    matchee casi perfecto. word_similarity() busca el mejor tramo delimitado
    por palabra dentro del nombre completo, que es el caso real de mostrador
    (el cliente escribe una palabra, no el nombre entero del producto).
    """
    texto = (q or "").strip()
    if not texto:
        return []
    filas = conn.execute(
        """SELECT p.nombre,
                  word_similarity(texto_busqueda(%s), texto_busqueda(p.nombre)) AS parecido
           FROM productos p
           WHERE word_similarity(texto_busqueda(%s), texto_busqueda(p.nombre)) >= %s
           ORDER BY parecido DESC, p.nombre
           LIMIT %s""",
        (texto, texto, UMBRAL_SUGERENCIA, limite),
    ).fetchall()
    return [f["nombre"] for f in filas]


def obtener_cotizaciones_producto(conn, producto_id):
    """Cotizaciones de proveedores activos para un producto, de menor a
    mayor precio_costo. Es la fuente única del criterio de "mejor precio"
    que usan tanto /pedidos (agrupa por el proveedor más conveniente) como
    la columna "Mejor precio" de /productos — no duplicar esta consulta en
    los dos lugares."""
    return conn.execute(
        """SELECT pp.precio_costo, pp.codigo_proveedor, pr.id AS proveedor_id, pr.nombre AS proveedor_nombre,
                  pr.email AS proveedor_email, pr.telefono AS proveedor_telefono
           FROM producto_proveedor pp JOIN proveedores pr ON pr.id = pp.proveedor_id
           WHERE pp.producto_id = %s AND pr.activo = true ORDER BY pp.precio_costo ASC""",
        (producto_id,),
    ).fetchall()


def obtener_mejor_precio_por_producto(conn, producto_id):
    """La cotización más barata de un producto (ver obtener_cotizaciones_producto
    de arriba), o None si no hay ninguna cargada."""
    cotizaciones = obtener_cotizaciones_producto(conn, producto_id)
    return cotizaciones[0] if cotizaciones else None


def _generar_password_temporal(largo=10):
    alfabeto = string.ascii_letters + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(largo))


def seed_demo_data(conn):
    """Carga datos de ejemplo solo si la base está vacía. Antes abría su
    propia conexión (`seed_demo_data()`); ahora la recibe, para poder
    correr dentro de la transacción de un test o de un script que ya tenga
    una abierta."""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM productos")
    if cur.fetchone()["c"] > 0:
        return  # ya hay datos, no pisar nada

    hoy = datetime.now()

    proveedores = [
        ("Frenos del Sur SA", "0341-4550022", "ventas@frenosdelsur.com", "Rosario, Santa Fe", "30-71234567-8"),
        ("Embragues Rosario SRL", "0341-4551133", "info@embraguesrosario.com", "Rosario, Santa Fe", "30-70987654-3"),
        ("Distribuidora Autopartes Litoral", "0341-4559900", "contacto@dal.com.ar", "Rosario, Santa Fe", "30-69876543-2"),
    ]
    # Uno por uno (no executemany) para capturar el id real que les asigna
    # Postgres: a diferencia del rowid de SQLite, la secuencia de un
    # IDENTITY no es transaccional, así que no se puede asumir que van a
    # quedar en 1/2/3 acá (por ejemplo, si este mismo seed ya corrió antes
    # en una transacción que se revirtió, la secuencia ya avanzó).
    # id_proveedor[i] es el id real del proveedor que antes se
    # referenciaba como el entero i+1 en `productos` de abajo.
    id_proveedor = [
        cur.execute(
            "INSERT INTO proveedores (nombre, telefono, email, direccion, cuit) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            p,
        ).fetchone()["id"]
        for p in proveedores
    ]

    clientes = [
        ("Juan Pérez", "341-5551234", "juanperez@gmail.com", "Av. Pellegrini 1200", "20-30111222-3"),
        ("Transporte Cargas del Litoral", "341-5559876", "administracion@cargaslitoral.com", "Ruta 9 Km 12", "30-65432198-7"),
        ("María Gómez", "341-5556655", "mariagomez@hotmail.com", "Bv. Oroño 850", "27-28999123-4"),
        ("Taller Mecánico El Rápido", "341-5552211", "elrapido.taller@gmail.com", "San Martín 2300", "30-71122334-5"),
        ("Carlos Fernández", "341-5558877", "", "Córdoba 3400", ""),
    ]
    cur.executemany(
        "INSERT INTO clientes (nombre, telefono, email, direccion, cuit_dni, fecha_alta) VALUES (%s, %s, %s, %s, %s, %s)",
        [(n, t, e, d, c, hoy.strftime("%Y-%m-%d")) for n, t, e, d, c in clientes],
    )

    productos = [
        ("FR-001", "Juego de pastillas de freno delanteras", "Frenos", "Bosch", "VW Gol / Voyage", Decimal("8500.00"), Decimal("14900.00"), 18, 5, id_proveedor[0]),
        ("FR-002", "Juego de pastillas de freno traseras", "Frenos", "Bosch", "VW Gol / Voyage", Decimal("7200.00"), Decimal("12500.00"), 14, 5, id_proveedor[0]),
        ("FR-003", "Disco de freno delantero ventilado", "Frenos", "Fremax", "Fiat Cronos", Decimal("12500.00"), Decimal("21900.00"), 10, 4, id_proveedor[0]),
        ("FR-004", "Disco de freno trasero macizo", "Frenos", "Fremax", "Fiat Cronos", Decimal("9800.00"), Decimal("16900.00"), 3, 4, id_proveedor[0]),
        ("FR-005", "Cilindro maestro de freno", "Frenos", "TRW", "Chevrolet Onix", Decimal("15400.00"), Decimal("26900.00"), 6, 2, id_proveedor[0]),
        ("FR-006", "Cañería de freno flexible", "Frenos", "TRW", "Universal", Decimal("3200.00"), Decimal("6200.00"), 25, 6, id_proveedor[0]),
        ("FR-007", "Líquido de frenos DOT 4 (500ml)", "Líquidos", "Bosch", "Universal", Decimal("2100.00"), Decimal("4200.00"), 40, 10, id_proveedor[0]),
        ("EMB-001", "Kit de embrague completo (disco+plato+collarín)", "Embragues", "Luk", "VW Gol / Voyage", Decimal("42000.00"), Decimal("68900.00"), 8, 3, id_proveedor[1]),
        ("EMB-002", "Kit de embrague completo", "Embragues", "Sachs", "Fiat Cronos / Argo", Decimal("45500.00"), Decimal("74900.00"), 5, 3, id_proveedor[1]),
        ("EMB-003", "Collarín hidráulico", "Embragues", "Luk", "Chevrolet Onix / Prisma", Decimal("18700.00"), Decimal("31900.00"), 2, 3, id_proveedor[1]),
        ("EMB-004", "Cable de embrague", "Embragues", "Fremax", "Renault Kangoo", Decimal("5600.00"), Decimal("9900.00"), 12, 5, id_proveedor[1]),
        ("EMB-005", "Bomba de embrague hidráulica", "Embragues", "Sachs", "Ford Ka", Decimal("21300.00"), Decimal("35900.00"), 4, 3, id_proveedor[1]),
        ("COR-001", "Correa de distribución", "Correas", "Gates", "VW Gol / Voyage", Decimal("6800.00"), Decimal("11900.00"), 15, 5, id_proveedor[2]),
        ("COR-002", "Correa poly-V (accesorios)", "Correas", "Gates", "Fiat Cronos / Argo", Decimal("4200.00"), Decimal("7900.00"), 20, 5, id_proveedor[2]),
        ("OTR-001", "Kit de fijación de disco de freno", "Otros", "Genérico", "Universal", Decimal("900.00"), Decimal("1900.00"), 30, 10, id_proveedor[2]),
        ("OTR-002", "Grasa para embrague/frenos (pomo)", "Otros", "Genérico", "Universal", Decimal("1500.00"), Decimal("2900.00"), 20, 8, id_proveedor[2]),
    ]
    cur.executemany(
        """INSERT INTO productos
           (codigo, nombre, categoria, marca, modelo_compatible, precio_costo, precio_venta, stock_actual, stock_minimo, proveedor_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        productos,
    )

    # Algunos productos con cotizaciones de más de un proveedor, para mostrar
    # el comparador de precios (a quién le conviene comprarle cada producto).
    cotizaciones = [
        ("FR-001", "Frenos del Sur SA", Decimal("8500.00"), "BOS-4501"),
        ("FR-001", "Distribuidora Autopartes Litoral", Decimal("8100.00"), "DAL-9012"),
        ("FR-003", "Frenos del Sur SA", Decimal("12500.00"), "FRX-2201"),
        ("FR-003", "Distribuidora Autopartes Litoral", Decimal("12900.00"), "DAL-2202"),
        ("EMB-001", "Embragues Rosario SRL", Decimal("42000.00"), "LUK-7701"),
        ("EMB-001", "Distribuidora Autopartes Litoral", Decimal("43500.00"), "DAL-7701"),
    ]
    for codigo, proveedor_nombre, precio, codigo_prov in cotizaciones:
        producto = cur.execute("SELECT id FROM productos WHERE codigo=%s", (codigo,)).fetchone()
        proveedor = cur.execute("SELECT id FROM proveedores WHERE nombre=%s", (proveedor_nombre,)).fetchone()
        if producto and proveedor:
            cur.execute(
                """INSERT INTO producto_proveedor (producto_id, proveedor_id, precio_costo, codigo_proveedor)
                   VALUES (%s, %s, %s, %s)""",
                (producto["id"], proveedor["id"], precio, codigo_prov),
            )

    # Ventas de ejemplo de los últimos ~4 meses, para que el dashboard tenga datos
    cur.execute("SELECT id, precio_venta FROM productos")
    productos_db = cur.fetchall()
    cur.execute("SELECT id FROM clientes")
    clientes_ids = [r["id"] for r in cur.fetchall()]

    random.seed(7)
    for i in range(45):
        dias_atras = random.randint(0, 120)
        fecha = (hoy - timedelta(days=dias_atras)).strftime("%Y-%m-%d")
        cliente_id = random.choice(clientes_ids)
        metodo = random.choice(["Efectivo", "Transferencia", "Tarjeta"])
        tipo = random.choice(["Remito", "Recibo"])
        n_items = random.randint(1, 3)
        elegidos = random.sample(productos_db, n_items)
        total = Decimal("0")
        venta_id = cur.execute(
            "INSERT INTO ventas (fecha, cliente_id, total, metodo_pago, tipo_comprobante, numero_comprobante) VALUES (%s, %s, 0, %s, %s, %s) RETURNING id",
            (fecha, cliente_id, metodo, tipo, f"{1000+i:06d}"),
        ).fetchone()["id"]
        for prod in elegidos:
            cantidad = random.randint(1, 4)
            subtotal = cantidad * prod["precio_venta"]
            total += subtotal
            cur.execute(
                "INSERT INTO venta_items (venta_id, producto_id, cantidad, precio_unitario, subtotal) VALUES (%s, %s, %s, %s, %s)",
                (venta_id, prod["id"], cantidad, prod["precio_venta"], subtotal),
            )
        cur.execute("UPDATE ventas SET total = %s WHERE id = %s", (total, venta_id))


if __name__ == "__main__":
    _conn = get_connection()
    try:
        seed_demo_data(_conn)
        _conn.commit()
    finally:
        _conn.close()
    print("Datos de ejemplo cargados en:", DATABASE_URL)
