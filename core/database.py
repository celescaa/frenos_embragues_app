"""
Esquema e inicialización de la base de datos SQLite para el sistema de
gestión de ventas de frenos y embragues.
"""
import sqlite3
import os
import secrets
import string
from datetime import datetime, timedelta
import random
from werkzeug.security import generate_password_hash

# Carpeta donde viven los datos que tienen que sobrevivir a un redeploy
# (base de datos, credenciales iniciales, clave de sesión). Por defecto es la
# raíz del proyecto (un nivel arriba de core/, donde vivía data.db antes de
# que este archivo se mudara a core/ — comportamiento de siempre corriendo
# local). En Docker se pisa con SI_INSTANCE_DIR apuntando a un volumen
# montado, para no perder nada cuando se recrea el contenedor (ver
# Dockerfile/docker-compose.yml).
_RAIZ_PROYECTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTANCE_DIR = os.environ.get("SI_INSTANCE_DIR") or _RAIZ_PROYECTO
os.makedirs(INSTANCE_DIR, exist_ok=True)

DB_PATH = os.path.join(INSTANCE_DIR, "data.db")
CREDENCIALES_PATH = os.path.join(INSTANCE_DIR, "credenciales_iniciales.txt")

SCHEMA = """
CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    telefono TEXT,
    email TEXT,
    direccion TEXT,
    cuit_dni TEXT,
    fecha_alta TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proveedores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    telefono TEXT,
    email TEXT,
    direccion TEXT,
    cuit TEXT,
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS productos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT UNIQUE,
    nombre TEXT NOT NULL,
    categoria TEXT NOT NULL DEFAULT 'Otros',
    marca TEXT,
    modelo_compatible TEXT,
    precio_costo REAL NOT NULL DEFAULT 0,
    precio_venta REAL NOT NULL DEFAULT 0,
    stock_actual INTEGER NOT NULL DEFAULT 0,
    stock_minimo INTEGER NOT NULL DEFAULT 2,
    proveedor_id INTEGER,
    codigo_barras TEXT,
    pedido_pendiente INTEGER NOT NULL DEFAULT 0,
    fecha_pedido_pendiente TEXT,
    FOREIGN KEY (proveedor_id) REFERENCES proveedores(id)
);

CREATE TABLE IF NOT EXISTS ventas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    cliente_id INTEGER,
    total REAL NOT NULL DEFAULT 0,
    metodo_pago TEXT DEFAULT 'Efectivo',
    tipo_comprobante TEXT DEFAULT 'Remito',
    numero_comprobante TEXT,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS venta_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venta_id INTEGER NOT NULL,
    producto_id INTEGER NOT NULL,
    cantidad INTEGER NOT NULL,
    precio_unitario REAL NOT NULL,
    subtotal REAL NOT NULL,
    FOREIGN KEY (venta_id) REFERENCES ventas(id),
    FOREIGN KEY (producto_id) REFERENCES productos(id)
);

CREATE TABLE IF NOT EXISTS compras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    proveedor_id INTEGER,
    total REAL NOT NULL DEFAULT 0,
    numero_factura_proveedor TEXT,
    FOREIGN KEY (proveedor_id) REFERENCES proveedores(id)
);

CREATE TABLE IF NOT EXISTS compra_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    compra_id INTEGER NOT NULL,
    producto_id INTEGER NOT NULL,
    cantidad INTEGER NOT NULL,
    precio_unitario REAL NOT NULL,
    subtotal REAL NOT NULL,
    FOREIGN KEY (compra_id) REFERENCES compras(id),
    FOREIGN KEY (producto_id) REFERENCES productos(id)
);

CREATE TABLE IF NOT EXISTS producto_proveedor (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL,
    proveedor_id INTEGER NOT NULL,
    precio_costo REAL NOT NULL DEFAULT 0,
    codigo_proveedor TEXT,
    FOREIGN KEY (producto_id) REFERENCES productos(id),
    FOREIGN KEY (proveedor_id) REFERENCES proveedores(id),
    UNIQUE (producto_id, proveedor_id)
);

CREATE TABLE IF NOT EXISTS pedidos_web (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    nombre_cliente TEXT NOT NULL,
    telefono TEXT,
    email TEXT,
    direccion TEXT,
    cuit_dni TEXT,
    total REAL NOT NULL DEFAULT 0,
    estado TEXT NOT NULL DEFAULT 'pendiente_pago',
    mp_preference_id TEXT,
    mp_payment_id TEXT,
    venta_id INTEGER,
    FOREIGN KEY (venta_id) REFERENCES ventas(id)
);

CREATE TABLE IF NOT EXISTS pedido_web_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_id INTEGER NOT NULL,
    producto_id INTEGER NOT NULL,
    cantidad INTEGER NOT NULL,
    precio_unitario REAL NOT NULL,
    subtotal REAL NOT NULL,
    FOREIGN KEY (pedido_id) REFERENCES pedidos_web(id),
    FOREIGN KEY (producto_id) REFERENCES productos(id)
);

CREATE TABLE IF NOT EXISTS categorias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS subcategorias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    categoria_id INTEGER NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (categoria_id) REFERENCES categorias(id),
    UNIQUE (categoria_id, nombre)
);

CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    nombre TEXT NOT NULL,
    rol TEXT NOT NULL DEFAULT 'empleado',
    activo INTEGER NOT NULL DEFAULT 1,
    debe_cambiar_password INTEGER NOT NULL DEFAULT 0,
    intentos_fallidos INTEGER NOT NULL DEFAULT 0,
    bloqueado_hasta TEXT,
    fecha_creacion TEXT NOT NULL
);

-- Cuenta corriente de clientes (típicamente mecánicos que compran a crédito
-- para un tercero). Un cargo puede tener varios productos (ver
-- cuenta_corriente_movimiento_items, análoga a venta_items) y, cuando el
-- comprador real es un tercero identificado con su propio CUIT/DNI
-- (tercero_cuit_dni), la Factura C se emite a nombre de ese tercero en vez
-- del cliente/mecánico dueño de la cuenta — cliente_tercero_nombre queda
-- como el nombre de referencia en los dos casos (facturado o no).
-- producto_id quedó de una versión anterior (un cargo = un solo producto),
-- ya no se usa para cargos nuevos.
CREATE TABLE IF NOT EXISTS cuenta_corriente_movimientos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL,
    cliente_tercero_nombre TEXT,
    tercero_cuit_dni TEXT,
    producto_id INTEGER,
    monto REAL NOT NULL,
    tipo TEXT NOT NULL,
    fecha TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    venta_id INTEGER,
    observaciones TEXT,
    cae TEXT,
    cae_vencimiento TEXT,
    punto_venta_arca INTEGER,
    numero_factura_arca INTEGER,
    facturacion_estado TEXT,
    facturacion_error TEXT,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id),
    FOREIGN KEY (producto_id) REFERENCES productos(id),
    FOREIGN KEY (venta_id) REFERENCES ventas(id)
);

-- Productos de un cargo de cuenta corriente (un cargo = varios productos que
-- el mecánico se lleva a crédito, mismo patrón que venta_items). El stock se
-- descuenta al confirmar el cargo, igual que en una venta: el producto ya
-- salió del local, solo falta que se pague.
CREATE TABLE IF NOT EXISTS cuenta_corriente_movimiento_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    movimiento_id INTEGER NOT NULL,
    producto_id INTEGER NOT NULL,
    cantidad INTEGER NOT NULL,
    precio_unitario REAL NOT NULL,
    subtotal REAL NOT NULL,
    FOREIGN KEY (movimiento_id) REFERENCES cuenta_corriente_movimientos(id),
    FOREIGN KEY (producto_id) REFERENCES productos(id)
);

-- Compras/ventas sin factura (no pasan por compras/ventas ni por AFIP), pero
-- sí impactan el mismo stock_actual que todo lo demás.
CREATE TABLE IF NOT EXISTS movimientos_no_facturados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    tipo TEXT NOT NULL,
    producto_id INTEGER NOT NULL,
    cantidad INTEGER NOT NULL,
    precio REAL NOT NULL DEFAULT 0,
    contraparte TEXT,
    observaciones TEXT,
    conciliado INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (producto_id) REFERENCES productos(id)
);

-- Descuentos aprobados manualmente para un cliente puntual (ver /clientes/top).
CREATE TABLE IF NOT EXISTS promociones_aplicadas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL,
    porcentaje_o_monto REAL NOT NULL,
    tipo TEXT NOT NULL,
    alcance TEXT NOT NULL,
    fecha_inicio TEXT NOT NULL,
    fecha_fin TEXT,
    aprobado_por TEXT,
    fecha_aprobacion TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS promocion_productos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    promocion_id INTEGER NOT NULL,
    producto_id INTEGER NOT NULL,
    FOREIGN KEY (promocion_id) REFERENCES promociones_aplicadas(id),
    FOREIGN KEY (producto_id) REFERENCES productos(id)
);
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Categorías del catálogo (local y tienda online). Ya NO es la lista fija:
# viven en la tabla `categorias`, editable desde /categorias. Esto es solo
# la carga inicial para bases nuevas (ver _sembrar_categorias).
CATEGORIAS_INICIALES = [
    "Frenos", "Embragues", "Correas", "Líquidos",
    "Rodamientos y Mazas", "Suspensión y Dirección", "Filtros",
    "Retenes y Juntas", "Transmisión", "Motor", "Ferretería",
    "Otros",
]

# Subcategorías iniciales por categoría. Reemplazadas el 06/08/2026 por una
# taxonomía más granular armada en otro chat a partir de clasificar de punta
# a punta las listas de precios reales de 5 proveedores (Distrisuper, Eine,
# Miguel Angel Sen-Sei, Rio, Roncal — ~107.000 filas). Filtros, Retenes y
# Juntas y Ferretería no estaban cubiertas por ese trabajo, así que
# mantienen la taxonomía más simple armada antes. Ver
# `_migrar_subcategorias_taxonomia_v2` para cómo se reconcilia esto en una
# base que ya tenía sembrada la taxonomía vieja (más simple) de estas mismas
# categorías.
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

# Categorías cubiertas por la taxonomía granular de arriba (06/08/2026) —
# en una base que ya tenía la taxonomía vieja sembrada para estas mismas
# categorías, `_migrar_subcategorias_taxonomia_v2` reemplaza las
# subcategorías viejas por las nuevas de SUBCATEGORIAS_INICIALES.
CATEGORIAS_CON_TAXONOMIA_V2 = [
    "Correas", "Embragues", "Frenos", "Rodamientos y Mazas",
    "Suspensión y Dirección", "Transmisión", "Motor",
]

# "Rodamientos" y "Amortiguadores" se habían agregado como categorías
# provisorias (05/08/2026, antes de tener esta taxonomía con subcategorías)
# al limpiar una lista de precios sin identificar. Se reemplazan por su
# categoría/subcategoría definitiva (ver _migrar_categorias_reemplazadas).
CATEGORIAS_REEMPLAZADAS_POR_SUBCATEGORIA = {
    "Rodamientos": ("Rodamientos y Mazas", "Rodamientos"),
    "Amortiguadores": ("Suspensión y Dirección", "Amortiguadores"),
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
        consulta += " WHERE activo = 1"
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
        condiciones.append("s.categoria_id = ?")
        params.append(categoria_id)
    if solo_activas:
        condiciones.append("s.activo = 1")
    if condiciones:
        consulta += " WHERE " + " AND ".join(condiciones)
    consulta += " ORDER BY c.nombre, s.nombre"
    filas = conn.execute(consulta, params).fetchall()
    if conn_propia:
        conn.close()
    return filas


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
           WHERE pp.producto_id = ? AND pr.activo = 1 ORDER BY pp.precio_costo ASC""",
        (producto_id,),
    ).fetchall()


def obtener_mejor_precio_por_producto(conn, producto_id):
    """La cotización más barata de un producto (ver obtener_cotizaciones_producto
    de arriba), o None si no hay ninguna cargada."""
    cotizaciones = obtener_cotizaciones_producto(conn, producto_id)
    return cotizaciones[0] if cotizaciones else None


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    _migrar(conn)
    conn.commit()
    conn.close()


def _migrar(conn):
    """Agrega columnas nuevas a bases creadas con versiones anteriores."""
    columnas_nuevas = {
        "productos": [
            ("codigo_barras", "TEXT"), ("imagen", "TEXT"),
            ("pedido_pendiente", "INTEGER NOT NULL DEFAULT 0"),
            ("fecha_pedido_pendiente", "TEXT"),
            ("subcategoria", "TEXT"),
        ],
        "proveedores": [("activo", "INTEGER NOT NULL DEFAULT 1")],
        "clientes": [("tipo_cliente", "TEXT NOT NULL DEFAULT 'particular'")],
        "ventas": [
            ("cae", "TEXT"),
            ("cae_vencimiento", "TEXT"),
            ("punto_venta_arca", "INTEGER"),
            ("numero_factura_arca", "INTEGER"),
            ("facturacion_estado", "TEXT"),
            ("facturacion_error", "TEXT"),
            # vincula dos ventas que son en realidad un mismo pago mixto
            # (ej. mitad efectivo, mitad tarjeta) para no contarlas dos veces
            # en "cantidad de ventas" — ver /ventas/dia.
            ("id_operacion", "TEXT"),
        ],
        # CUIT/DNI del tercero real a nombre de quien se factura un cargo de
        # cuenta corriente (si no se carga, se factura al cliente/mecánico
        # dueño de la cuenta, comportamiento de siempre).
        "cuenta_corriente_movimientos": [("tercero_cuit_dni", "TEXT")],
    }
    for tabla, columnas in columnas_nuevas.items():
        existentes = {r["name"] for r in conn.execute(f"PRAGMA table_info({tabla})")}
        for nombre, tipo in columnas:
            if nombre not in existentes:
                conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {tipo}")

    # Productos cargados con la taxonomía vieja (Freno/Embrague/Otro) pasan
    # a la nueva (Frenos/Embragues/Otros) — Correas y Líquidos son nuevas,
    # no requieren migrar nada.
    for vieja, nueva in CATEGORIAS_RENOMBRADAS.items():
        conn.execute("UPDATE productos SET categoria=? WHERE categoria=?", (nueva, vieja))

    _sembrar_categorias(conn)
    _sembrar_subcategorias(conn)
    _migrar_categorias_reemplazadas(conn)
    _migrar_subcategorias_taxonomia_v2(conn)


def _sembrar_categorias(conn):
    """Carga la tabla `categorias` con las iniciales (solo si están vacías,
    para no revivir una que alguien desactivó/borró a propósito) y suma
    cualquier categoría que ya tengan productos cargados pero que todavía
    no esté en la tabla (por ejemplo, bases viejas migradas)."""
    if conn.execute("SELECT COUNT(*) AS c FROM categorias").fetchone()["c"] == 0:
        for nombre in CATEGORIAS_INICIALES:
            conn.execute("INSERT OR IGNORE INTO categorias (nombre) VALUES (?)", (nombre,))

    faltantes = conn.execute(
        """SELECT DISTINCT categoria FROM productos
           WHERE categoria IS NOT NULL AND TRIM(categoria) != ''
           AND categoria NOT IN (SELECT nombre FROM categorias)"""
    ).fetchall()
    for f in faltantes:
        conn.execute("INSERT OR IGNORE INTO categorias (nombre) VALUES (?)", (f["categoria"],))


def _sembrar_subcategorias(conn):
    """Carga SUBCATEGORIAS_INICIALES la primera vez que corre (tabla
    subcategorias vacía) — de ahí en más no revive nada que se haya
    desactivado/borrado a propósito desde /categorias."""
    if conn.execute("SELECT COUNT(*) AS c FROM subcategorias").fetchone()["c"] > 0:
        return
    for categoria_nombre, subcategorias in SUBCATEGORIAS_INICIALES.items():
        cat = conn.execute("SELECT id FROM categorias WHERE nombre=?", (categoria_nombre,)).fetchone()
        if not cat:
            conn.execute("INSERT OR IGNORE INTO categorias (nombre) VALUES (?)", (categoria_nombre,))
            cat = conn.execute("SELECT id FROM categorias WHERE nombre=?", (categoria_nombre,)).fetchone()
        for nombre in subcategorias:
            conn.execute(
                "INSERT OR IGNORE INTO subcategorias (nombre, categoria_id) VALUES (?, ?)",
                (nombre, cat["id"]),
            )


def _migrar_categorias_reemplazadas(conn):
    """Pasa los productos de una categoría provisoria vieja a su
    categoría/subcategoría definitiva (CATEGORIAS_REEMPLAZADAS_POR_SUBCATEGORIA)
    y borra la categoría vieja si ya no le quedan productos. Idempotente: la
    segunda vez que corre, la categoría vieja ya no existe y no hace nada."""
    for vieja, (categoria_nueva, subcategoria_nueva) in CATEGORIAS_REEMPLAZADAS_POR_SUBCATEGORIA.items():
        vieja_row = conn.execute("SELECT id FROM categorias WHERE nombre=?", (vieja,)).fetchone()
        if not vieja_row:
            continue
        conn.execute(
            "UPDATE productos SET categoria=?, subcategoria=? WHERE categoria=?",
            (categoria_nueva, subcategoria_nueva, vieja),
        )
        en_uso = conn.execute("SELECT COUNT(*) AS c FROM productos WHERE categoria=?", (vieja,)).fetchone()["c"]
        if en_uso == 0:
            conn.execute("DELETE FROM categorias WHERE id=?", (vieja_row["id"],))


def _migrar_subcategorias_taxonomia_v2(conn):
    """Reconcilia una base que ya tenía sembrada la taxonomía de
    subcategorías vieja (más simple) con la nueva, más granular
    (SUBCATEGORIAS_INICIALES, CATEGORIAS_CON_TAXONOMIA_V2 — ver el
    comentario ahí). Por cada categoría cubierta por la taxonomía nueva:
    borra las subcategorías viejas que ya no están en la lista nueva (solo
    si ningún producto las tiene asignadas, para no perder datos reales) y
    agrega las que falten. Idempotente: si ya se aplicó, no encuentra nada
    para borrar ni para agregar."""
    for categoria_nombre in CATEGORIAS_CON_TAXONOMIA_V2:
        cat = conn.execute("SELECT id FROM categorias WHERE nombre=?", (categoria_nombre,)).fetchone()
        if not cat:
            continue
        nuevas = set(SUBCATEGORIAS_INICIALES.get(categoria_nombre, []))
        existentes = conn.execute(
            "SELECT id, nombre FROM subcategorias WHERE categoria_id=?", (cat["id"],)
        ).fetchall()
        for s in existentes:
            if s["nombre"] in nuevas:
                continue
            en_uso = conn.execute(
                "SELECT COUNT(*) AS c FROM productos WHERE subcategoria=?", (s["nombre"],)
            ).fetchone()["c"]
            if en_uso == 0:
                conn.execute("DELETE FROM subcategorias WHERE id=?", (s["id"],))
        for nombre in nuevas:
            conn.execute(
                "INSERT OR IGNORE INTO subcategorias (nombre, categoria_id) VALUES (?, ?)",
                (nombre, cat["id"]),
            )


def _generar_password_temporal(largo=10):
    alfabeto = string.ascii_letters + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(largo))


def seed_admin_user():
    """Crea el primer usuario (admin) si todavía no hay ninguno cargado.

    La contraseña se genera al azar y se guarda en un archivo de texto local
    (nunca en el código ni en el repositorio) para que el dueño la vea una
    sola vez. En el primer login el sistema obliga a cambiarla.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM usuarios")
    if cur.fetchone()["c"] > 0:
        conn.close()
        return

    password_temporal = _generar_password_temporal()
    cur.execute(
        """INSERT INTO usuarios (username, password_hash, nombre, rol, activo, debe_cambiar_password, fecha_creacion)
           VALUES (?, ?, ?, 'admin', 1, 1, ?)""",
        ("admin", generate_password_hash(password_temporal), "Administrador", datetime.now().strftime("%Y-%m-%d")),
    )
    conn.commit()
    conn.close()

    with open(CREDENCIALES_PATH, "w") as f:
        f.write(
            "Usuario y contraseña iniciales del sistema\n"
            "===========================================\n\n"
            "Usuario:     admin\n"
            f"Contraseña:  {password_temporal}\n\n"
            "El sistema va a pedir que la cambies apenas inicies sesión por primera vez.\n"
            "Después de cambiarla, podés borrar este archivo con confianza.\n"
        )


def seed_demo_data():
    """Carga datos de ejemplo solo si la base está vacía."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM productos")
    if cur.fetchone()["c"] > 0:
        conn.close()
        return  # ya hay datos, no pisar nada

    hoy = datetime.now()

    proveedores = [
        ("Frenos del Sur SA", "0341-4550022", "ventas@frenosdelsur.com", "Rosario, Santa Fe", "30-71234567-8"),
        ("Embragues Rosario SRL", "0341-4551133", "info@embraguesrosario.com", "Rosario, Santa Fe", "30-70987654-3"),
        ("Distribuidora Autopartes Litoral", "0341-4559900", "contacto@dal.com.ar", "Rosario, Santa Fe", "30-69876543-2"),
    ]
    cur.executemany(
        "INSERT INTO proveedores (nombre, telefono, email, direccion, cuit) VALUES (?, ?, ?, ?, ?)",
        proveedores,
    )

    clientes = [
        ("Juan Pérez", "341-5551234", "juanperez@gmail.com", "Av. Pellegrini 1200", "20-30111222-3"),
        ("Transporte Cargas del Litoral", "341-5559876", "administracion@cargaslitoral.com", "Ruta 9 Km 12", "30-65432198-7"),
        ("María Gómez", "341-5556655", "mariagomez@hotmail.com", "Bv. Oroño 850", "27-28999123-4"),
        ("Taller Mecánico El Rápido", "341-5552211", "elrapido.taller@gmail.com", "San Martín 2300", "30-71122334-5"),
        ("Carlos Fernández", "341-5558877", "", "Córdoba 3400", ""),
    ]
    cur.executemany(
        "INSERT INTO clientes (nombre, telefono, email, direccion, cuit_dni, fecha_alta) VALUES (?, ?, ?, ?, ?, ?)",
        [(n, t, e, d, c, hoy.strftime("%Y-%m-%d")) for n, t, e, d, c in clientes],
    )

    productos = [
        ("FR-001", "Juego de pastillas de freno delanteras", "Frenos", "Bosch", "VW Gol / Voyage", 8500, 14900, 18, 5, 1),
        ("FR-002", "Juego de pastillas de freno traseras", "Frenos", "Bosch", "VW Gol / Voyage", 7200, 12500, 14, 5, 1),
        ("FR-003", "Disco de freno delantero ventilado", "Frenos", "Fremax", "Fiat Cronos", 12500, 21900, 10, 4, 1),
        ("FR-004", "Disco de freno trasero macizo", "Frenos", "Fremax", "Fiat Cronos", 9800, 16900, 3, 4, 1),
        ("FR-005", "Cilindro maestro de freno", "Frenos", "TRW", "Chevrolet Onix", 15400, 26900, 6, 2, 1),
        ("FR-006", "Cañería de freno flexible", "Frenos", "TRW", "Universal", 3200, 6200, 25, 6, 1),
        ("FR-007", "Líquido de frenos DOT 4 (500ml)", "Líquidos", "Bosch", "Universal", 2100, 4200, 40, 10, 1),
        ("EMB-001", "Kit de embrague completo (disco+plato+collarín)", "Embragues", "Luk", "VW Gol / Voyage", 42000, 68900, 8, 3, 2),
        ("EMB-002", "Kit de embrague completo", "Embragues", "Sachs", "Fiat Cronos / Argo", 45500, 74900, 5, 3, 2),
        ("EMB-003", "Collarín hidráulico", "Embragues", "Luk", "Chevrolet Onix / Prisma", 18700, 31900, 2, 3, 2),
        ("EMB-004", "Cable de embrague", "Embragues", "Fremax", "Renault Kangoo", 5600, 9900, 12, 5, 2),
        ("EMB-005", "Bomba de embrague hidráulica", "Embragues", "Sachs", "Ford Ka", 21300, 35900, 4, 3, 2),
        ("COR-001", "Correa de distribución", "Correas", "Gates", "VW Gol / Voyage", 6800, 11900, 15, 5, 3),
        ("COR-002", "Correa poly-V (accesorios)", "Correas", "Gates", "Fiat Cronos / Argo", 4200, 7900, 20, 5, 3),
        ("OTR-001", "Kit de fijación de disco de freno", "Otros", "Genérico", "Universal", 900, 1900, 30, 10, 3),
        ("OTR-002", "Grasa para embrague/frenos (pomo)", "Otros", "Genérico", "Universal", 1500, 2900, 20, 8, 3),
    ]
    cur.executemany(
        """INSERT INTO productos
           (codigo, nombre, categoria, marca, modelo_compatible, precio_costo, precio_venta, stock_actual, stock_minimo, proveedor_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        productos,
    )
    conn.commit()

    # Algunos productos con cotizaciones de más de un proveedor, para mostrar
    # el comparador de precios (a quién le conviene comprarle cada producto).
    cotizaciones = [
        ("FR-001", "Frenos del Sur SA", 8500, "BOS-4501"),
        ("FR-001", "Distribuidora Autopartes Litoral", 8100, "DAL-9012"),
        ("FR-003", "Frenos del Sur SA", 12500, "FRX-2201"),
        ("FR-003", "Distribuidora Autopartes Litoral", 12900, "DAL-2202"),
        ("EMB-001", "Embragues Rosario SRL", 42000, "LUK-7701"),
        ("EMB-001", "Distribuidora Autopartes Litoral", 43500, "DAL-7701"),
    ]
    for codigo, proveedor_nombre, precio, codigo_prov in cotizaciones:
        producto = cur.execute("SELECT id FROM productos WHERE codigo=?", (codigo,)).fetchone()
        proveedor = cur.execute("SELECT id FROM proveedores WHERE nombre=?", (proveedor_nombre,)).fetchone()
        if producto and proveedor:
            cur.execute(
                """INSERT INTO producto_proveedor (producto_id, proveedor_id, precio_costo, codigo_proveedor)
                   VALUES (?, ?, ?, ?)""",
                (producto["id"], proveedor["id"], precio, codigo_prov),
            )
    conn.commit()

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
        total = 0
        cur.execute(
            "INSERT INTO ventas (fecha, cliente_id, total, metodo_pago, tipo_comprobante, numero_comprobante) VALUES (?, ?, 0, ?, ?, ?)",
            (fecha, cliente_id, metodo, tipo, f"{1000+i:06d}"),
        )
        venta_id = cur.lastrowid
        for prod in elegidos:
            cantidad = random.randint(1, 4)
            subtotal = cantidad * prod["precio_venta"]
            total += subtotal
            cur.execute(
                "INSERT INTO venta_items (venta_id, producto_id, cantidad, precio_unitario, subtotal) VALUES (?, ?, ?, ?, ?)",
                (venta_id, prod["id"], cantidad, prod["precio_venta"], subtotal),
            )
        cur.execute("UPDATE ventas SET total = ? WHERE id = ?", (total, venta_id))

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    seed_demo_data()
    print("Base de datos inicializada en:", DB_PATH)
