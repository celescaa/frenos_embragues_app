# Migración a Postgres — Plan de implementación (1 de 2)

> **Para agentes:** SUB-SKILL REQUERIDA: usar superpowers:subagent-driven-development (recomendado) o superpowers:executing-plans para implementar este plan tarea por tarea. Los pasos usan checkboxes (`- [ ]`) para seguimiento.

**Objetivo:** que el sistema completo corra sobre Postgres en vez de SQLite, con un arnés de tests que demuestre que ninguna de las ~193 consultas cambió de comportamiento.

**Arquitectura:** se mantiene el SQL crudo y `core/database.py` como único lugar que abre conexiones; solo cambia el driver (`sqlite3` → `psycopg` v3) y el dialecto. El esquema deja de crearse desde Python (`init_db()`/`_migrar()`) y pasa a migraciones de la CLI de Supabase. Se aprovecha para corregir dos errores de tipos: la plata pasa de flotante a decimal exacto y las fechas de texto a tipos de fecha reales.

**Stack:** Python 3.11, Flask, psycopg 3, Postgres 15 (local vía Supabase CLI + Docker), pytest.

**Spec:** `docs/superpowers/specs/2026-08-13-migracion-vercel-supabase-design.md`

**Fuera de alcance de este plan (van al Plan 2):** Supabase Auth, Supabase Storage para las fotos, `vercel.json`, variables de entorno de producción, `ProxyFix`, `SESSION_COOKIE_SECURE` y el deploy. El login sigue funcionando exactamente como hoy (tabla `usuarios` con `password_hash`) hasta el Plan 2.

## Restricciones globales

Estas reglas aplican a **todas** las tareas de port de consultas. No se repiten en cada tarea.

**Traducción de dialecto obligatoria:**

| SQLite (hoy) | Postgres |
|---|---|
| `?` | `%s` |
| `cursor.lastrowid` | `INSERT ... RETURNING id` + `.fetchone()["id"]` |
| `LIKE` | `ILIKE` |
| `INSERT OR IGNORE` | `INSERT ... ON CONFLICT DO NOTHING` |
| `date('now')` | `CURRENT_DATE` |
| `sqlite3.IntegrityError` | `psycopg.errors.UniqueViolation` / `psycopg.errors.ForeignKeyViolation` |
| `PRAGMA foreign_keys = ON` | se elimina (Postgres siempre aplica las FK) |

**Reglas de trabajo:**

- **Ninguna consulta se reescribe de memoria.** Se parte del SQL existente y se le aplica la traducción. Si una consulta parece mejorable, se deja igual: este plan migra, no refactoriza.
- `LIKE` → `ILIKE` es el cambio más peligroso del plan: es el único que **no falla visiblemente**, solo hace que un buscador deje de encontrar resultados. Cada tarea que toque un buscador tiene un test dedicado de mayúsculas/minúsculas.
- Los montos vienen de la base como `decimal.Decimal`. **Nunca mezclar `Decimal` con `float`** en una operación (lanza `TypeError`). Convertir con `Decimal(str(x))`, nunca `float(x)`.
- Las fechas vienen como `datetime.date` / `datetime.datetime`, ya no como texto. Donde el código hacía `datetime.strptime(fila["fecha"], "%Y-%m-%d")`, ahora la fila ya trae un `date`.
- Commit al final de cada tarea, en español, siguiendo el estilo del repositorio.

**Conexión de desarrollo:** `postgresql://postgres:postgres@127.0.0.1:54322/postgres` (la que expone `npx supabase start`).

## Estructura de archivos

| Archivo | Responsabilidad | Estado |
|---|---|---|
| `supabase/config.toml` | Configuración de la CLI | Crear (Tarea 1) |
| `supabase/migrations/<ts>_esquema_inicial.sql` | Las 18 tablas en Postgres | Crear (Tarea 2) |
| `tests/conftest.py` | Fixtures: conexión, base limpia, cliente Flask logueado | Crear (Tarea 1) |
| `tests/test_esquema.py` | Verifica tipos de columnas (NUMERIC/DATE) | Crear (Tarea 2) |
| `tests/test_<area>.py` | Un archivo por área portada | Crear (Tareas 4-10) |
| `core/database.py` | Conexión + helpers de lectura | Modificar (Tareas 3-4) |
| `core/app.py` | 146 consultas + rutas | Modificar (Tarea 4: quita 2 llamadas a `init_db()`/`seed_admin_user()`; Tareas 5-9, 11: el resto) |
| `scripts/*.py` (4 scripts) | Quitar la llamada a `db.init_db()`, ya innecesaria | Modificar (Tarea 4) |
| `core/facturacion_afip.py` | 6 consultas | Modificar (Tarea 10) |
| `core/tienda_pagos.py` | 3 consultas | Modificar (Tarea 10) |
| `core/importar_factura.py` | 2 consultas | Modificar (Tarea 10) |
| `requirements.txt` | Sumar `psycopg[binary]`, `pytest` | Modificar (Tarea 1) |

---

### Tarea 1: Entorno de pruebas y Postgres local

Sin esto no hay forma de verificar nada de lo que sigue. Es la base del plan.

**Archivos:**
- Crear: `supabase/config.toml` (lo genera la CLI)
- Crear: `tests/conftest.py`
- Crear: `tests/test_conexion.py`
- Modificar: `requirements.txt`
- Modificar: `.gitignore`

**Interfaces:**
- Produce: fixture `db_conn` (conexión psycopg a la base de test, con rollback al final) y fixture `pg_url` (string de conexión). Todas las tareas siguientes las consumen.

- [ ] **Paso 1: Inicializar la CLI de Supabase**

```bash
cd "$(git rev-parse --show-toplevel)"
npx supabase init
```

Responder `N` si pregunta por configuración de VS Code / Deno.

- [ ] **Paso 2: Levantar Postgres local**

```bash
npx supabase start
```

Esperado: imprime `DB URL: postgresql://postgres:postgres@127.0.0.1:54322/postgres`. La primera vez descarga imágenes de Docker y puede tardar varios minutos.

- [ ] **Paso 3: Agregar dependencias**

En `requirements.txt`, sumar al final:

```
psycopg[binary]==3.2.3
pytest==8.3.4
```

Instalar:

```bash
pip install -r requirements.txt
```

- [ ] **Paso 4: Ignorar artefactos de Supabase**

Agregar a `.gitignore`:

```
# Artefactos locales de la CLI de Supabase (la base local vive en Docker)
supabase/.temp/
supabase/.branches/
```

- [ ] **Paso 5: Escribir el conftest**

Crear `tests/conftest.py`:

```python
"""Fixtures compartidas por toda la suite.

La base de pruebas es el Postgres local que levanta `npx supabase start`
(ver README). Cada test corre dentro de una transacción que se revierte al
terminar, así que los tests no se ensucian entre sí.
"""
import os
import pytest
import psycopg
from psycopg.rows import dict_row

PG_URL_TEST = os.environ.get(
    "DATABASE_URL_TEST",
    "postgresql://postgres:postgres@127.0.0.1:54322/postgres",
)


@pytest.fixture(scope="session")
def pg_url():
    return PG_URL_TEST


@pytest.fixture
def db_conn(pg_url):
    """Conexión con rollback automático: nada de lo que escribe un test queda."""
    conn = psycopg.connect(pg_url, row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
```

- [ ] **Paso 6: Escribir el test que falla**

Crear `tests/test_conexion.py`:

```python
def test_la_base_de_pruebas_responde(db_conn):
    fila = db_conn.execute("SELECT 1 AS uno").fetchone()
    assert fila["uno"] == 1


def test_las_filas_se_acceden_por_nombre(db_conn):
    """El resto del sistema accede a las filas por nombre (venta["fecha"]),
    así que la conexión tiene que devolver diccionarios, no tuplas."""
    fila = db_conn.execute("SELECT 'Frenos' AS categoria").fetchone()
    assert fila["categoria"] == "Frenos"
```

- [ ] **Paso 7: Correr los tests**

```bash
python -m pytest tests/test_conexion.py -v
```

Esperado: **PASAN**. Si fallan con `connection refused`, Postgres local no está levantado — volver al Paso 2.

- [ ] **Paso 8: Commit**

```bash
git add requirements.txt .gitignore supabase/ tests/
git commit -m "Agregar arnés de pruebas con Postgres local

El proyecto no tenía tests. Para migrar ~193 consultas de SQLite a Postgres
hace falta poder verificar que ninguna cambió de comportamiento."
```

---

### Tarea 2: El esquema como migración de Supabase

**Archivos:**
- Crear: `supabase/migrations/<timestamp>_esquema_inicial.sql`
- Crear: `tests/test_esquema.py`
- Referencia (no modificar todavía): `core/database.py:28-256` (la constante `SCHEMA`)

**Interfaces:**
- Produce: las 18 tablas en Postgres. Todas las tareas siguientes consultan contra ellas.

- [ ] **Paso 1: Escribir los tests que fallan**

Crear `tests/test_esquema.py`:

```python
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
```

- [ ] **Paso 2: Verificar que fallan**

```bash
python -m pytest tests/test_esquema.py -v
```

Esperado: FALLAN todos (las tablas todavía no existen en Postgres).

- [ ] **Paso 3: Crear el archivo de migración**

```bash
npx supabase migration new esquema_inicial
```

Esperado: crea `supabase/migrations/<timestamp>_esquema_inicial.sql` vacío.

- [ ] **Paso 4: Traducir el esquema**

Traducir la constante `SCHEMA` de `core/database.py:28-256` al archivo recién creado, aplicando estas reglas:

| SQLite | Postgres |
|---|---|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY` |
| `REAL` en las 21 columnas de plata | `NUMERIC(12,2)` |
| `TEXT DEFAULT CURRENT_TIMESTAMP` (**esta regla gana sobre la siguiente**) | `TIMESTAMPTZ NOT NULL DEFAULT now()` |
| `TEXT` en `fecha`, `fecha_alta`, `fecha_inicio`, `fecha_fin`, `fecha_pedido_pendiente` | `DATE` |
| `TEXT` en `fecha_creacion`, `bloqueado_hasta` | `TIMESTAMPTZ` |
| `INTEGER` usado como booleano (`activo`, `debe_cambiar_password`, `conciliado`, `pedido_pendiente`) | `BOOLEAN` con default `true`/`false` |
| `usuarios.id` | `UUID PRIMARY KEY DEFAULT gen_random_uuid()` |

**Cuidado con las columnas `fecha` que llevan default de marca de tiempo.**
Dos tablas tienen una columna llamada `fecha` que **no** es una fecha simple
sino una marca de tiempo, porque su default es `CURRENT_TIMESTAMP`. Van a
`TIMESTAMPTZ`, no a `DATE`:

- `cuenta_corriente_movimientos.fecha`
- `movimientos_no_facturados.fecha`

En cambio `ventas.fecha`, `compras.fecha` y `pedidos_web.fecha` sí son fechas
simples (`TEXT NOT NULL` sin default) y van a `DATE`.

Las columnas que hoy agrega `_migrar()` (`core/database.py:400-560`) van **directo en el `CREATE TABLE`**: ese mecanismo de migración incremental desaparece. Revisar `_migrar()` completo y confirmar que ninguna columna quede afuera.

Ejemplo de la traducción, para fijar el criterio:

```sql
CREATE TABLE productos (
    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    nombre TEXT NOT NULL,
    categoria TEXT NOT NULL,
    subcategoria TEXT,
    marca TEXT,
    modelo_compatible TEXT,
    codigo TEXT UNIQUE,
    codigo_barras TEXT,
    imagen TEXT,
    precio_costo NUMERIC(12,2) NOT NULL DEFAULT 0,
    precio_venta NUMERIC(12,2) NOT NULL DEFAULT 0,
    stock_actual INTEGER NOT NULL DEFAULT 0,
    stock_minimo INTEGER NOT NULL DEFAULT 0,
    proveedor_id INTEGER REFERENCES proveedores(id),
    pedido_pendiente BOOLEAN NOT NULL DEFAULT false,
    fecha_pedido_pendiente DATE
);

CREATE TABLE usuarios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    nombre TEXT NOT NULL,
    rol TEXT NOT NULL DEFAULT 'empleado',
    activo BOOLEAN NOT NULL DEFAULT true,
    debe_cambiar_password BOOLEAN NOT NULL DEFAULT false,
    intentos_fallidos INTEGER NOT NULL DEFAULT 0,
    bloqueado_hasta TIMESTAMPTZ,
    fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Las tablas se crean en orden de dependencia (`proveedores` antes que `productos`, `ventas` antes que `venta_items`, etc.), porque las FK ahora se aplican de verdad.

- [ ] **Paso 5: Aplicar la migración**

```bash
npx supabase db reset
```

Esperado: aplica sin errores. Si falla por una FK, es un problema de orden de creación de tablas.

- [ ] **Paso 6: Verificar que los tests pasan**

```bash
python -m pytest tests/test_esquema.py -v
```

Esperado: **PASAN** los 40+ tests parametrizados.

- [ ] **Paso 7: Commit**

```bash
git add supabase/migrations/ tests/test_esquema.py
git commit -m "Traducir el esquema a Postgres como migración de Supabase

La plata pasa de flotante a numeric(12,2) y las fechas a date/timestamptz.
usuarios.id pasa a uuid para no cambiarlo de nuevo cuando entre Supabase
Auth en el Plan 2."
```

---

### Tarea 3: Capa de conexión a Postgres

**Archivos:**
- Modificar: `core/database.py:1-27` (cabecera, imports, rutas de archivo) y `core/database.py:259-263` (`get_connection`)
- Crear: `tests/test_database_conexion.py`

**Interfaces:**
- Produce: `db.get_connection()` devolviendo una conexión psycopg con `dict_row`. Todo el resto del sistema la consume sin cambios en su forma de uso.

- [ ] **Paso 1: Escribir los tests que fallan**

Crear `tests/test_database_conexion.py`:

```python
from decimal import Decimal
from core import database as db


def test_get_connection_devuelve_filas_por_nombre():
    conn = db.get_connection()
    try:
        fila = conn.execute("SELECT 'ok' AS estado").fetchone()
        assert fila["estado"] == "ok"
    finally:
        conn.close()


def test_los_montos_llegan_como_decimal_exacto():
    """Si esto devuelve float, volvió el bug de redondeo que la migración
    vino a corregir."""
    conn = db.get_connection()
    try:
        fila = conn.execute("SELECT 0.1::numeric(12,2) + 0.2::numeric(12,2) AS suma").fetchone()
        assert fila["suma"] == Decimal("0.30")
    finally:
        conn.close()


def test_no_quedan_rastros_de_sqlite():
    """INSTANCE_DIR/DB_PATH eran para el archivo local; en serverless no hay
    disco persistente y no deben volver."""
    assert not hasattr(db, "DB_PATH")
    assert not hasattr(db, "INSTANCE_DIR")
```

- [ ] **Paso 2: Verificar que fallan**

```bash
python -m pytest tests/test_database_conexion.py -v
```

Esperado: FALLAN (`get_connection` todavía abre SQLite).

- [ ] **Paso 3: Reemplazar la conexión**

En `core/database.py`, cambiar el import `import sqlite3` por:

```python
import psycopg
from psycopg.rows import dict_row
```

Eliminar las líneas 14-26 (`_RAIZ_PROYECTO`, `INSTANCE_DIR`, `os.makedirs`, `DB_PATH`, `CREDENCIALES_PATH`) y reemplazar `get_connection()` por:

```python
# Cadena de conexión. En desarrollo apunta al Postgres local que levanta
# `npx supabase start`; en producción, al pooler de Supabase.
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@127.0.0.1:54322/postgres",
)


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
```

Actualizar el docstring del módulo (línea 1-4): ya no es SQLite.

- [ ] **Paso 4: Verificar que los tests pasan**

```bash
python -m pytest tests/test_database_conexion.py -v
```

Esperado: **PASAN**.

- [ ] **Paso 5: Commit**

```bash
git add core/database.py tests/test_database_conexion.py
git commit -m "Cambiar el driver de la base a psycopg (Postgres)

prepare_threshold=None es obligatorio: el pooler de Supabase en modo
transacción no soporta prepared statements, y psycopg los activa solos a
partir de la quinta ejecución."
```

---

### Tarea 4: Portar las consultas de `core/database.py`

Son 36 consultas: siembra de categorías y subcategorías, y los helpers de cotizaciones que usan `/pedidos` y `/productos`.

**Archivos:**
- Modificar: `core/database.py` (funciones `init_db`, `_migrar`, `_sembrar_*`, `obtener_categorias`, `obtener_cotizaciones_producto`, `obtener_mejor_precio_por_producto`, `seed_admin_user`, y los datos de ejemplo)
- Crear: `tests/test_database_helpers.py`

**Interfaces:**
- Consume: `db.get_connection()` (Tarea 3).
- Produce (firmas exactas, verificadas contra el código actual):
  - `db.obtener_categorias(conn=None, solo_activas=True) -> list[dict]`
  - `db.obtener_subcategorias(conn=None, categoria_id=None, solo_activas=True) -> list[dict]`
  - `db.obtener_cotizaciones_producto(conn, producto_id) -> list[dict]`
  - `db.obtener_mejor_precio_por_producto(conn, producto_id) -> dict | None` — **recibe un producto puntual**, no devuelve un mapa de todos
  - `db.seed_demo_data(conn)` — hoy es `seed_demo_data()` sin argumentos y abre su propia conexión; pasa a recibirla

- [ ] **Paso 1: Escribir los tests que fallan**

Crear `tests/test_database_helpers.py`:

```python
from decimal import Decimal
from core import database as db


def _proveedor(conn, nombre, activo=True):
    return conn.execute(
        "INSERT INTO proveedores (nombre, activo) VALUES (%s, %s) RETURNING id",
        (nombre, activo),
    ).fetchone()["id"]


def _producto(conn, nombre="Pastilla X"):
    return conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta)
           VALUES (%s, 'Frenos', 100, 130) RETURNING id""",
        (nombre,),
    ).fetchone()["id"]


def test_obtener_categorias_devuelve_solo_activas(db_conn):
    db_conn.execute("INSERT INTO categorias (nombre, activo) VALUES ('Frenos', true)")
    db_conn.execute("INSERT INTO categorias (nombre, activo) VALUES ('Vieja', false)")
    nombres = [c["nombre"] for c in db.obtener_categorias(db_conn, solo_activas=True)]
    assert "Frenos" in nombres
    assert "Vieja" not in nombres


def test_mejor_precio_ignora_proveedores_desactivados(db_conn):
    """Sugerir reponerle a un proveedor que ya no se usa no tiene sentido."""
    barato = _proveedor(db_conn, "Barato pero inactivo", activo=False)
    caro = _proveedor(db_conn, "Caro pero activo", activo=True)
    prod = _producto(db_conn)
    db_conn.execute(
        "INSERT INTO producto_proveedor (producto_id, proveedor_id, precio_costo) VALUES (%s, %s, %s)",
        (prod, barato, Decimal("50.00")),
    )
    db_conn.execute(
        "INSERT INTO producto_proveedor (producto_id, proveedor_id, precio_costo) VALUES (%s, %s, %s)",
        (prod, caro, Decimal("80.00")),
    )
    mejor = db.obtener_mejor_precio_por_producto(db_conn, prod)
    assert mejor["precio_costo"] == Decimal("80.00")


def test_los_datos_de_ejemplo_se_cargan(db_conn):
    db.seed_demo_data(db_conn)
    total = db_conn.execute("SELECT COUNT(*) AS n FROM productos").fetchone()["n"]
    assert total > 0
```

- [ ] **Paso 2: Verificar que fallan**

```bash
python -m pytest tests/test_database_helpers.py -v
```

- [ ] **Paso 3: Portar el módulo**

Aplicando las restricciones globales:

- **Eliminar por completo** `init_db()`, `_migrar()`, `_migrar_subcategorias_taxonomia_v2()` y la constante `SCHEMA`: ese trabajo ahora lo hacen las migraciones de la Tarea 2. Eliminar también `seed_admin_user()` y `CREDENCIALES_PATH` (el primer admin se crea a mano; en el Plan 2 pasa a Supabase Auth).
- Conservar `CATEGORIAS_INICIALES` y `SUBCATEGORIAS_INICIALES` como datos, pero su siembra pasa a un `INSERT ... ON CONFLICT DO NOTHING` dentro del archivo de migración de la Tarea 2, no en Python.
- `seed_demo_data()` (línea 599) pasa a recibir la conexión: `seed_demo_data(conn)`, en vez de abrir la suya.
- Los `INSERT OR IGNORE` (5 lugares) pasan a `ON CONFLICT DO NOTHING`.
- Los montos de los datos de ejemplo se escriben como `Decimal("1234.56")`, no como float.

- [ ] **Paso 4: Actualizar quien llamaba a lo eliminado**

En `core/app.py:88-90`, eliminar las llamadas `db.init_db()` y `db.seed_admin_user()`. En serverless correrían en cada arranque en frío.

**Cuatro scripts también llaman a `db.init_db()`** y quedarían rotos:

- `scripts/importar_datos.py:302`
- `scripts/cargar_stock_por_proveedor.py:114`
- `scripts/generar_planilla_stock_proveedores.py:91`
- `scripts/matchear_productos_proveedores.py:161`

En los cuatro, eliminar esa línea. Ya no tiene sentido: el esquema lo aplican las migraciones, no el script. Si la base no está migrada, el script debe fallar con un error claro en vez de crear tablas por su cuenta.

- [ ] **Paso 5: Verificar que los scripts siguen arrancando**

```bash
python scripts/generar_planilla_stock_proveedores.py --help 2>&1 | head -5
python scripts/importar_datos.py --help 2>&1 | head -5
```

Esperado: no fallan con `AttributeError: module 'core.database' has no attribute 'init_db'`.

- [ ] **Paso 6: Verificar que los tests pasan**

```bash
python -m pytest tests/ -v
```

Esperado: **PASAN** todos (incluidos los de las tareas anteriores).

- [ ] **Paso 7: Commit**

```bash
git add core/database.py core/app.py scripts/ tests/test_database_helpers.py
git commit -m "Portar core/database.py a Postgres

init_db(), _migrar() y seed_admin_user() se eliminan: el esquema ahora vive
en supabase/migrations/ y en serverless esas funciones correrían en cada
arranque en frío. Los 4 scripts que llamaban a init_db() se actualizan."
```

---

### Tareas 5 a 9: Portar las 146 consultas de `core/app.py`

Se dividen por área para que cada una sea revisable por separado. **Las cinco siguen la misma estructura de pasos**, que se detalla completa en la Tarea 5 y se repite en las demás con su propio contenido.

En todas: aplicar las restricciones globales, no reescribir SQL de memoria, y al terminar correr `python -m pytest tests/ -v` completo antes del commit.

---

### Tarea 5: Portar clientes y productos

Incluye **2 de los 3 buscadores** del sistema — la parte más delicada del plan.

**Archivos:**
- Modificar: `core/app.py` — rutas `/clientes*`, `/productos*`, `/categorias*`, `/subcategorias*`, `/api/clientes-nuevo`, `/api/productos-nuevo`, `/api/producto-por-codigo`
- Puntos de riesgo concretos: `core/app.py:437` (buscador de clientes), `core/app.py:863` (buscador de productos), `core/app.py:1085`, `:1158`, `:1215` (`sqlite3.IntegrityError`)
- Crear: `tests/test_clientes_productos.py`

**Interfaces:**
- Consume: `db.get_connection()`, `db.obtener_categorias()`, `db.obtener_mejor_precio_por_producto()`.
- Produce: nada nuevo; conserva las firmas existentes de `productos_para_buscador()` y `subcategorias_por_categoria_json()`.

- [ ] **Paso 1: Escribir los tests que fallan**

Crear `tests/test_clientes_productos.py`:

```python
"""El buscador es lo más frágil de la migración: en SQLite LIKE no distingue
mayúsculas, en Postgres sí. Si alguien olvida un ILIKE, el buscador deja de
encontrar cosas sin lanzar ningún error."""
import pytest
from core.app import app as flask_app


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


def test_buscar_producto_no_distingue_mayusculas(client, db_conn):
    db_conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta)
           VALUES ('Pastilla Delantera Bosch', 'Frenos', 100, 130)"""
    )
    db_conn.commit()
    for texto in ["pastilla", "PASTILLA", "PaStIlLa"]:
        respuesta = client.get(f"/productos?q={texto}")
        assert b"Pastilla Delantera Bosch" in respuesta.data, f"falló con '{texto}'"


def test_buscar_producto_por_modelo_compatible(client, db_conn):
    """Escribir 'Gol' tiene que encontrar 'VW Gol / Voyage'."""
    db_conn.execute(
        """INSERT INTO productos (nombre, categoria, modelo_compatible, precio_costo, precio_venta)
           VALUES ('Kit embrague', 'Embragues', 'VW Gol / Voyage', 100, 130)"""
    )
    db_conn.commit()
    respuesta = client.get("/productos?q=gol")
    assert b"Kit embrague" in respuesta.data


def test_buscar_cliente_no_distingue_mayusculas(client, db_conn):
    db_conn.execute(
        "INSERT INTO clientes (nombre, fecha_alta) VALUES ('Taller Rodríguez', CURRENT_DATE)"
    )
    db_conn.commit()
    respuesta = client.get("/clientes?q=rodr")
    assert b"Rodr" in respuesta.data


def test_codigo_duplicado_da_mensaje_claro_y_no_rompe(client, db_conn):
    """productos.codigo es UNIQUE: el error se captura y se muestra, no
    revienta con una página de error."""
    db_conn.execute(
        """INSERT INTO productos (nombre, categoria, codigo, precio_costo, precio_venta)
           VALUES ('Existente', 'Frenos', 'ABC123', 100, 130)"""
    )
    db_conn.commit()
    respuesta = client.post("/api/productos-nuevo", data={
        "nombre": "Otro", "categoria": "Frenos", "codigo": "ABC123",
        "precio_costo": "100", "precio_venta": "130",
    })
    assert respuesta.status_code < 500
```

- [ ] **Paso 2: Verificar que fallan**

```bash
python -m pytest tests/test_clientes_productos.py -v
```

- [ ] **Paso 3: Portar las consultas del área**

Recorrer las rutas listadas arriba aplicando las restricciones globales. Prestar atención especial a:

- **`core/app.py:437`** — buscador de clientes: los tres `LIKE` pasan a `ILIKE`.
- **`core/app.py:863`** — buscador de productos: los cuatro `LIKE` pasan a `ILIKE`. El `codigo_barras = ?` **se deja como igualdad exacta** (un código de barras se escanea, no se tipea).
- **`core/app.py:2172`** — el otro buscador (queda para la Tarea 9, no tocar acá).
- **`:1085`, `:1158`, `:1215`** — `except sqlite3.IntegrityError` pasa a `except psycopg.errors.UniqueViolation`. Agregar `import psycopg` en la cabecera de `core/app.py` y quitar `import sqlite3` cuando ya no quede ningún uso.
- Los `INSERT` que después usan `lastrowid` pasan a `RETURNING id`.

- [ ] **Paso 4: Verificar que los tests pasan**

```bash
python -m pytest tests/ -v
```

- [ ] **Paso 5: Commit**

```bash
git add core/app.py tests/test_clientes_productos.py
git commit -m "Portar clientes y productos a Postgres

Los buscadores pasan de LIKE a ILIKE: en SQLite LIKE no distinguía
mayúsculas, en Postgres sí."
```

---

### Tarea 6: Portar ventas y comprobantes

**Archivos:**
- Modificar: `core/app.py` — `/ventas`, `/ventas/nueva`, `/ventas/dia`, `/ventas/<id>/comprobante`, `/ventas/<id>/facturar`, `/ventas/<id>/enviar-mail`, y las funciones `registrar_venta()` y `aplicar_promociones()`
- Puntos de riesgo: `core/app.py:1412` (número de comprobante), `:1418`, `:1500` (inserts con `lastrowid`), `:1282-1290` (filtros de `/ventas/dia`), `:1539` (`IntegrityError`)
- Crear: `tests/test_ventas.py`

**Interfaces:**
- Consume: `db.get_connection()`.
- Produce (firmas exactas, **no cambian** — las consume la Tarea 8 y el webhook de la tienda):
  - `registrar_venta(conn, cliente_id, metodo_pago, items, tipo_comprobante_solicitado="Remito", id_operacion=None) -> (venta_id, tipo_comprobante)`
  - `aplicar_promociones(conn, cliente_id, items) -> list[tuple]` — vive 6 líneas antes de `registrar_venta()` en el mismo bloque (`core/app.py:1335`); se porta acá, no en la Tarea 8. La Tarea 8 solo la **consume** para verificarla con datos reales de promoción.
  - En ambas, `items` es una lista de **tuplas** `(producto_id, cantidad, precio_unitario, subtotal)`, no de diccionarios.

- [ ] **Paso 1: Escribir los tests que fallan**

Crear `tests/test_ventas.py`:

```python
from decimal import Decimal
from core.app import registrar_venta


def _cliente(conn, nombre="Juan"):
    return conn.execute(
        "INSERT INTO clientes (nombre, fecha_alta) VALUES (%s, CURRENT_DATE) RETURNING id",
        (nombre,),
    ).fetchone()["id"]


def _producto(conn, nombre, precio_venta, stock):
    return conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta, stock_actual)
           VALUES (%s, 'Frenos', 1, %s, %s) RETURNING id""",
        (nombre, precio_venta, stock),
    ).fetchone()["id"]


def test_una_venta_descuenta_stock(db_conn):
    prod = _producto(db_conn, "Pastilla", Decimal("150.00"), 10)
    cliente = _cliente(db_conn)

    # items = lista de tuplas (producto_id, cantidad, precio_unitario, subtotal)
    items = [(prod, 3, Decimal("150.00"), Decimal("450.00"))]
    registrar_venta(db_conn, cliente, "Efectivo", items)

    stock = db_conn.execute(
        "SELECT stock_actual FROM productos WHERE id = %s", (prod,)
    ).fetchone()["stock_actual"]
    assert stock == 7


def test_el_total_es_decimal_exacto(db_conn):
    """Tres unidades de 0.10 tienen que dar 0.30 clavado, no 0.30000000000004."""
    prod = _producto(db_conn, "Centavo", Decimal("0.10"), 100)
    cliente = _cliente(db_conn, "Ana")

    items = [(prod, 3, Decimal("0.10"), Decimal("0.30"))]
    venta_id, _ = registrar_venta(db_conn, cliente, "Efectivo", items)

    total = db_conn.execute(
        "SELECT total FROM ventas WHERE id = %s", (venta_id,)
    ).fetchone()["total"]
    assert total == Decimal("0.30")


def test_registrar_venta_devuelve_id_y_tipo(db_conn):
    """Devuelve la tupla (venta_id, tipo_comprobante). El id ahora sale de
    RETURNING id, ya no de cursor.lastrowid."""
    prod = _producto(db_conn, "X", Decimal("2.00"), 5)
    cliente = _cliente(db_conn, "Luis")

    items = [(prod, 1, Decimal("2.00"), Decimal("2.00"))]
    venta_id, tipo = registrar_venta(db_conn, cliente, "Efectivo", items)

    assert isinstance(venta_id, int) and venta_id > 0
    assert tipo == "Remito"
```

- [ ] **Paso 2: Verificar que fallan**

```bash
python -m pytest tests/test_ventas.py -v
```

- [ ] **Paso 3: Portar el área**

Aplicando las restricciones globales. Atención a:

- `core/app.py:1412` — `numero_comprobante` se calcula con `f"{1000 + ultimo + 1:06d}"`: verificar que la consulta que obtiene `ultimo` siga devolviendo un entero y no `None` con la base vacía.
- Los tres `INSERT` que usaban `lastrowid` pasan a `RETURNING id`.
- `/ventas/dia`: el `COUNT(DISTINCT COALESCE(id_operacion, 'v'||id))` funciona igual en Postgres, pero `id` ahora se concatena a texto explícitamente: `'v' || id::text`.
- `aplicar_promociones()`: toda la aritmética pasa a `Decimal`. El prorrateo de descuentos de monto fijo debe cuadrar exacto contra el total.

- [ ] **Paso 4: Verificar que los tests pasan**

```bash
python -m pytest tests/ -v
```

- [ ] **Paso 5: Commit**

```bash
git add core/app.py tests/test_ventas.py
git commit -m "Portar ventas y comprobantes a Postgres"
```

---

### Tarea 7: Portar compras, proveedores y pedidos

**Archivos:**
- Modificar: `core/app.py` — `/compras`, `/compras/nueva`, `/compras/importar-factura`, `/proveedores*`, `/pedidos*`
- Puntos de riesgo: `core/app.py:1716` (insert de compra con `lastrowid`), el `IntegrityError` al eliminar un proveedor con datos asociados
- Crear: `tests/test_compras_pedidos.py`

**Interfaces:**
- Consume: `db.get_connection()`, `db.obtener_mejor_precio_por_producto()`.
- Produce: `compras_nueva()` conserva su comportamiento de limpiar `pedido_pendiente` al registrar la compra.

- [ ] **Paso 1: Escribir los tests que fallan**

Crear `tests/test_compras_pedidos.py`:

```python
"""La lógica de compra NO está extraída en una función: vive dentro de la
ruta compras_nueva() (core/app.py:1667). Este plan migra, no refactoriza, así
que se verifica el comportamiento a nivel de base y de ruta."""
import psycopg
import pytest


def test_no_se_puede_borrar_un_proveedor_con_datos_asociados(db_conn):
    """Postgres aplica las FK siempre; SQLite necesitaba PRAGMA foreign_keys.
    La ruta captura este error y muestra un mensaje claro."""
    prov = db_conn.execute(
        "INSERT INTO proveedores (nombre, activo) VALUES ('Con productos', true) RETURNING id"
    ).fetchone()["id"]
    db_conn.execute(
        """INSERT INTO productos (nombre, categoria, proveedor_id, precio_costo, precio_venta)
           VALUES ('Atado', 'Frenos', %s, 1, 2)""",
        (prov,),
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db_conn.execute("DELETE FROM proveedores WHERE id = %s", (prov,))


def test_activo_es_booleano_de_verdad(db_conn):
    """Dejó de ser INTEGER 0/1: en Python se compara contra True, no contra 1."""
    prov = db_conn.execute(
        "INSERT INTO proveedores (nombre, activo) VALUES ('P', true) RETURNING id"
    ).fetchone()["id"]
    fila = db_conn.execute("SELECT activo FROM proveedores WHERE id = %s", (prov,)).fetchone()
    assert fila["activo"] is True


def test_solo_los_proveedores_activos_se_ofrecen(db_conn):
    db_conn.execute("INSERT INTO proveedores (nombre, activo) VALUES ('Vigente', true)")
    db_conn.execute("INSERT INTO proveedores (nombre, activo) VALUES ('Dado de baja', false)")
    nombres = [
        f["nombre"]
        for f in db_conn.execute(
            "SELECT nombre FROM proveedores WHERE activo IS TRUE"
        ).fetchall()
    ]
    assert "Vigente" in nombres
    assert "Dado de baja" not in nombres


def test_pedidos_ignora_productos_sin_control_de_reposicion(db_conn):
    """stock_minimo = 0 significa 'no controlar reposición todavía'."""
    db_conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta,
                                  stock_actual, stock_minimo)
           VALUES ('En revisión', 'Frenos', 1, 2, 0, 0)"""
    )
    faltantes = db_conn.execute(
        """SELECT COUNT(*) AS n FROM productos
           WHERE stock_minimo > 0 AND stock_actual <= stock_minimo"""
    ).fetchone()["n"]
    assert faltantes == 0
```

- [ ] **Paso 2: Verificar que fallan**

```bash
python -m pytest tests/test_compras_pedidos.py -v
```

- [ ] **Paso 3: Portar el área**

Aplicando las restricciones globales. Atención a:

- `pedido_pendiente` y `activo` ahora son `BOOLEAN`: las comparaciones `= 1` / `= 0` pasan a `IS TRUE` / `IS FALSE`, y en Python se comparan contra `True`/`False`, no contra `1`/`0`.
- La consulta de `/pedidos` que excluye `stock_minimo = 0` y proveedores desactivados no cambia de lógica, solo de dialecto.
- El `except sqlite3.IntegrityError` al eliminar un proveedor pasa a `except psycopg.errors.ForeignKeyViolation`.

- [ ] **Paso 4: Verificar que los tests pasan**

```bash
python -m pytest tests/ -v
```

- [ ] **Paso 5: Commit**

```bash
git add core/app.py tests/test_compras_pedidos.py
git commit -m "Portar compras, proveedores y pedidos a Postgres"
```

---

### Tarea 8: Portar cuenta corriente, promociones y stock no facturado

**Archivos:**
- Modificar: `core/app.py` — `/clientes/<id>/cuenta-corriente*`, `/clientes/top`, `/clientes/top-deudores`, `/clientes/<id>/promocion/nueva`, `/promociones/<id>/finalizar`, `/stock/no-facturado*`
- Puntos de riesgo: `core/app.py:751` (`date('now')` en promociones vigentes), `:814`, el cálculo de saldo `SUM(cargos) - SUM(pagos)`
- Crear: `tests/test_cuenta_corriente.py`

**Interfaces:**
- Consume: `db.get_connection()`, `aplicar_promociones(conn, cliente_id, items) -> list[tuple]` (Tarea 6 — **ya portada, no se vuelve a tocar acá**; esta tarea solo la ejercita con datos reales de promoción para confirmar el comportamiento de punta a punta).

- [ ] **Paso 1: Escribir los tests que fallan**

Crear `tests/test_cuenta_corriente.py`:

```python
from decimal import Decimal


def _cliente(conn, nombre="Mecánico"):
    return conn.execute(
        "INSERT INTO clientes (nombre, fecha_alta) VALUES (%s, CURRENT_DATE) RETURNING id",
        (nombre,),
    ).fetchone()["id"]


def test_el_saldo_es_cargos_menos_pagos(db_conn):
    cliente = _cliente(db_conn)
    db_conn.execute(
        """INSERT INTO cuenta_corriente_movimientos (cliente_id, tipo, monto)
           VALUES (%s, 'cargo', %s)""", (cliente, Decimal("1500.00")))
    db_conn.execute(
        """INSERT INTO cuenta_corriente_movimientos (cliente_id, tipo, monto)
           VALUES (%s, 'pago', %s)""", (cliente, Decimal("500.50")))

    saldo = db_conn.execute(
        """SELECT COALESCE(SUM(CASE WHEN tipo='cargo' THEN monto ELSE -monto END), 0) AS saldo
           FROM cuenta_corriente_movimientos WHERE cliente_id = %s""",
        (cliente,),
    ).fetchone()["saldo"]
    assert saldo == Decimal("999.50")


def test_una_promocion_vencida_no_se_aplica(db_conn):
    """fecha_fin en el pasado: date('now') pasó a CURRENT_DATE."""
    cliente = _cliente(db_conn)
    db_conn.execute(
        """INSERT INTO promociones_aplicadas
           (cliente_id, tipo, porcentaje_o_monto, alcance, fecha_inicio, fecha_fin, aprobado_por)
           VALUES (%s, 'porcentaje', 10, 'todo', CURRENT_DATE - 30, CURRENT_DATE - 1, 'test')""",
        (cliente,),
    )
    vigentes = db_conn.execute(
        """SELECT COUNT(*) AS n FROM promociones_aplicadas
           WHERE cliente_id = %s AND fecha_inicio <= CURRENT_DATE
             AND (fecha_fin IS NULL OR fecha_fin >= CURRENT_DATE)""",
        (cliente,),
    ).fetchone()["n"]
    assert vigentes == 0


def test_el_descuento_porcentual_se_calcula_exacto(db_conn):
    """10% sobre 999.99 tiene que dar 899.99, no 899.9910000000001."""
    from core.app import aplicar_promociones
    cliente = _cliente(db_conn, "Con promo")
    prod = db_conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta)
           VALUES ('Caro', 'Frenos', 500, 999.99) RETURNING id"""
    ).fetchone()["id"]
    db_conn.execute(
        """INSERT INTO promociones_aplicadas
           (cliente_id, tipo, porcentaje_o_monto, alcance, fecha_inicio, aprobado_por)
           VALUES (%s, 'porcentaje', 10, 'todo', CURRENT_DATE, 'test')""",
        (cliente,),
    )

    # items = lista de tuplas (producto_id, cantidad, precio_unitario, subtotal)
    items = [(prod, 1, Decimal("999.99"), Decimal("999.99"))]
    resultado = aplicar_promociones(db_conn, cliente, items)

    assert resultado[0][3] == Decimal("899.99")
    assert isinstance(resultado[0][3], Decimal)


def test_conciliado_es_booleano(db_conn):
    """Dejó de ser INTEGER 0/1."""
    prod = db_conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta, stock_actual)
           VALUES ('Suelto', 'Otros', 10, 20, 5) RETURNING id"""
    ).fetchone()["id"]
    db_conn.execute(
        """INSERT INTO movimientos_no_facturados (producto_id, tipo, cantidad, precio, conciliado)
           VALUES (%s, 'compra', 3, %s, false)""",
        (prod, Decimal("10.00")),
    )
    fila = db_conn.execute(
        "SELECT conciliado FROM movimientos_no_facturados WHERE producto_id = %s", (prod,)
    ).fetchone()
    assert fila["conciliado"] is False
```

- [ ] **Paso 2: Verificar que fallan**

```bash
python -m pytest tests/test_cuenta_corriente.py -v
```

- [ ] **Paso 3: Portar el área**

Aplicando las restricciones globales. Atención a:

- `core/app.py:751` — `date('now')` pasa a `CURRENT_DATE` en la consulta de promociones vigentes.
- `aplicar_promociones()` **ya está portada por la Tarea 6** — acá no se toca su código, solo se verifica con datos reales (una promoción cargada + una venta) que el descuento calculado en `Decimal` cuadra exacto.
- `conciliado` pasa a `BOOLEAN`.
- El umbral `UMBRAL_IDENTIFICACION_RECEPTOR` de `facturacion_afip` se compara contra un `Decimal`.

- [ ] **Paso 4: Verificar que los tests pasan**

```bash
python -m pytest tests/ -v
```

- [ ] **Paso 5: Commit**

```bash
git add core/app.py tests/test_cuenta_corriente.py
git commit -m "Portar cuenta corriente, promociones y stock no facturado a Postgres"
```

---

### Tarea 9: Portar tienda online, panel y usuarios

**Archivos:**
- Modificar: `core/app.py` — `/` (dashboard), `/tienda*`, `/webhooks/mercadopago`, `/usuarios*`, `/login`, `/cambiar-password`
- Puntos de riesgo: `core/app.py:2172` (**el tercer buscador**), `:354`, `:381` (agrupamiento por mes del panel), `:161` (`bloqueado_hasta`), `:2303`, `:2426` (alta de cliente desde el webhook)
- Crear: `tests/test_tienda_panel.py`

**Interfaces:**
- Consume: `registrar_venta()` (Tarea 6), `db.get_connection()`.
- Produce: nada nuevo.

- [ ] **Paso 1: Escribir los tests que fallan**

Crear `tests/test_tienda_panel.py`:

```python
from decimal import Decimal


def test_el_catalogo_de_la_tienda_busca_sin_distinguir_mayusculas(db_conn):
    """Tercer y último buscador del sistema."""
    from core.app import app as flask_app
    db_conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta, stock_actual)
           VALUES ('Disco Ventilado', 'Frenos', 100, 200, 5)"""
    )
    db_conn.commit()
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        respuesta = c.get("/tienda?q=disco")
        assert b"Disco Ventilado" in respuesta.data


def test_el_bloqueo_por_intentos_usa_marca_de_tiempo(db_conn):
    """bloqueado_hasta pasó de texto a timestamptz: ya no se parsea a mano."""
    from datetime import datetime, timezone, timedelta
    futuro = datetime.now(timezone.utc) + timedelta(minutes=15)
    db_conn.execute(
        """INSERT INTO usuarios (username, password_hash, nombre, bloqueado_hasta)
           VALUES ('bloqueado', 'x', 'Test', %s)""",
        (futuro,),
    )
    fila = db_conn.execute(
        "SELECT bloqueado_hasta FROM usuarios WHERE username = 'bloqueado'"
    ).fetchone()
    assert isinstance(fila["bloqueado_hasta"], datetime)


def test_el_panel_agrupa_ventas_por_mes(db_conn):
    cliente = db_conn.execute(
        "INSERT INTO clientes (nombre, fecha_alta) VALUES ('X', CURRENT_DATE) RETURNING id"
    ).fetchone()["id"]
    db_conn.execute(
        """INSERT INTO ventas (fecha, cliente_id, total, metodo_pago)
           VALUES (CURRENT_DATE, %s, %s, 'Efectivo')""",
        (cliente, Decimal("1000.00")),
    )
    fila = db_conn.execute(
        """SELECT to_char(fecha, 'MM/YYYY') AS mes, SUM(total) AS total
           FROM ventas GROUP BY mes"""
    ).fetchone()
    assert fila["total"] == Decimal("1000.00")
```

- [ ] **Paso 2: Verificar que fallan**

```bash
python -m pytest tests/test_tienda_panel.py -v
```

- [ ] **Paso 3: Portar el área**

Aplicando las restricciones globales. Atención a:

- **`core/app.py:2172`** — el tercer buscador: los tres `LIKE` pasan a `ILIKE`. Con este quedan cubiertos los tres del sistema.
- **`core/app.py:161`** — al bloquear una cuenta ya no se formatea la fecha a texto: se pasa el `datetime` directo. Y al leerla, `usuario["bloqueado_hasta"]` ya es un `datetime`, así que **se elimina el `datetime.strptime(...)` del login** (`core/app.py:143`).
- **`core/app.py:354`, `:381`** — el agrupamiento por mes pasa de `strftime` de SQLite a `to_char(fecha, 'MM/YYYY')`.
- **`usuarios.id` ahora es `uuid`:** las rutas `/usuarios/<int:usuario_id>/editar`, `/eliminar` y `/resetear-password` tienen que cambiar el convertidor de `<int:...>` a `<uuid:...>`, y los templates que arman esas URLs seguirán funcionando sin cambios.
- El webhook de Mercado Pago sigue siendo idempotente: verificar que la consulta que chequea si el pago ya se procesó siga funcionando.

- [ ] **Paso 4: Verificar que los tests pasan**

```bash
python -m pytest tests/ -v
```

- [ ] **Paso 5: Commit**

```bash
git add core/app.py tests/test_tienda_panel.py
git commit -m "Portar tienda, panel y usuarios a Postgres

usuarios.id pasó a uuid, así que las rutas de /usuarios cambian el
convertidor de <int:...> a <uuid:...>."
```

---

### Tarea 10: Portar los módulos auxiliares

Son 11 consultas repartidas en tres módulos que por lo demás no se tocan.

**Archivos:**
- Modificar: `core/facturacion_afip.py` (6 consultas), `core/tienda_pagos.py` (3), `core/importar_factura.py` (2)
- Crear: `tests/test_facturacion.py`

**Interfaces:**
- Consume: `db.get_connection()`.
- Produce: `facturacion_afip.emitir_factura(venta_id)` y `emitir_factura_movimiento(movimiento_id)` conservan su contrato: **nunca lanzan excepción hacia afuera**, dejan el estado en `facturacion_estado`.

- [ ] **Paso 1: Escribir los tests que fallan**

Crear `tests/test_facturacion.py`:

```python
from decimal import Decimal


def test_sin_configurar_arca_la_venta_no_se_rompe(db_conn, monkeypatch):
    """El contrato de siempre: si ARCA no está configurado, la venta queda
    registrada y marcada, nunca revienta."""
    monkeypatch.delenv("AFIPSDK_ACCESS_TOKEN", raising=False)
    cliente = db_conn.execute(
        "INSERT INTO clientes (nombre, fecha_alta) VALUES ('X', CURRENT_DATE) RETURNING id"
    ).fetchone()["id"]
    venta = db_conn.execute(
        """INSERT INTO ventas (fecha, cliente_id, total, metodo_pago, tipo_comprobante)
           VALUES (CURRENT_DATE, %s, %s, 'Tarjeta', 'Factura B') RETURNING id""",
        (cliente, Decimal("1210.00")),
    ).fetchone()["id"]
    db_conn.commit()

    from core import facturacion_afip
    facturacion_afip.emitir_factura(venta)  # no debe lanzar

    estado = db_conn.execute(
        "SELECT facturacion_estado FROM ventas WHERE id = %s", (venta,)
    ).fetchone()["facturacion_estado"]
    assert estado == "sin_configurar"


def test_el_neto_mas_el_iva_da_el_total_exacto():
    """Con flotantes esto fallaba por un centavo. ARCA lo rechaza."""
    from core.facturacion_afip import ALICUOTA_IVA
    total = Decimal("1210.00")
    neto = (total / (1 + Decimal(str(ALICUOTA_IVA)))).quantize(Decimal("0.01"))
    iva = total - neto
    assert neto + iva == total
```

- [ ] **Paso 2: Verificar que fallan**

```bash
python -m pytest tests/test_facturacion.py -v
```

- [ ] **Paso 3: Portar los tres módulos**

Aplicando las restricciones globales. Atención a:

- `facturacion_afip.py:220` y `:369` — hoy hacen `datetime.strptime(venta["fecha"], "%Y-%m-%d").strftime("%Y%m%d")`. Como `venta["fecha"]` ya es un `date`, pasa a `venta["fecha"].strftime("%Y%m%d")`.
- `ALICUOTA_IVA` y el cálculo de neto/IVA pasan a `Decimal`.
- `_emitir_factura_arca()` recibe el `total` como `Decimal` y lo convierte a `float` **solo al armar el payload que se manda a ARCA** (la API externa espera números, no `Decimal`).
- `tienda_pagos.py`: los importes que se mandan a Mercado Pago se convierten a `float` en el borde, por el mismo motivo.

- [ ] **Paso 4: Verificar que los tests pasan**

```bash
python -m pytest tests/ -v
```

- [ ] **Paso 5: Commit**

```bash
git add core/facturacion_afip.py core/tienda_pagos.py core/importar_factura.py tests/test_facturacion.py
git commit -m "Portar los módulos de facturación, pagos e importación a Postgres

Los Decimal se convierten a float solo en el borde, al armar los payloads
de ARCA y Mercado Pago."
```

---

### Tarea 11: Verificación integral y limpieza

La última red de seguridad: recorrer las 67 rutas y confirmar que ninguna quedó rota.

**Archivos:**
- Crear: `tests/test_rutas.py`
- Modificar: `README.md`, `CLAUDE.md`
- Modificar: `core/app.py` (eliminar imports muertos)

**Interfaces:**
- Consume: todo lo anterior.

- [ ] **Paso 1: Escribir el test de humo de todas las rutas**

Crear `tests/test_rutas.py`:

```python
"""Recorre todas las rutas GET sin parámetros y verifica que ninguna
devuelva un error de servidor. Es la red que atrapa una consulta mal
portada que ningún test específico haya tocado."""
import pytest
from core.app import app as flask_app

RUTAS_PRIVADAS = [
    "/", "/clientes", "/clientes/top", "/clientes/top-deudores",
    "/productos", "/categorias", "/proveedores", "/compras",
    "/compras/importar-factura", "/pedidos", "/ventas", "/ventas/dia",
    "/ventas/nueva", "/compras/nueva", "/stock/no-facturado",
    "/usuarios", "/clientes/nuevo", "/productos/nuevo", "/proveedores/nuevo",
]

RUTAS_PUBLICAS = ["/login", "/tienda", "/tienda/carrito"]


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def client_logueado(client):
    with client.session_transaction() as sesion:
        sesion["usuario_id"] = "00000000-0000-0000-0000-000000000001"
        sesion["usuario_nombre"] = "Test"
        sesion["usuario_rol"] = "admin"
        sesion["debe_cambiar_password"] = False
    return client


@pytest.mark.parametrize("ruta", RUTAS_PRIVADAS)
def test_las_rutas_privadas_responden(client_logueado, ruta):
    respuesta = client_logueado.get(ruta)
    assert respuesta.status_code < 500, f"{ruta} devolvió {respuesta.status_code}"


@pytest.mark.parametrize("ruta", RUTAS_PUBLICAS)
def test_las_rutas_publicas_responden_sin_login(client, ruta):
    respuesta = client.get(ruta)
    assert respuesta.status_code < 500, f"{ruta} devolvió {respuesta.status_code}"


@pytest.mark.parametrize("ruta", RUTAS_PRIVADAS)
def test_sin_sesion_redirige_al_login(client, ruta):
    respuesta = client.get(ruta)
    assert respuesta.status_code in (301, 302), f"{ruta} no pidió login"
```

- [ ] **Paso 2: Correr y arreglar lo que falle**

```bash
python -m pytest tests/test_rutas.py -v
```

Cada fallo es una consulta mal portada. Arreglarla y volver a correr hasta que pasen todas.

- [ ] **Paso 3: Limpiar restos de SQLite**

```bash
grep -rn "sqlite3\|lastrowid\|INSERT OR IGNORE\|PRAGMA\|date('now')" core/ | grep -v "^core/.*#"
```

Esperado: **sin resultados**. Si aparece alguno, portarlo. Eliminar de `core/app.py` el `import sqlite3` si ya no se usa.

- [ ] **Paso 4: Verificar que no quedaron `LIKE` sin migrar**

```bash
grep -rn "LIKE" core/
```

Esperado: solo `ILIKE`. Un `LIKE` suelto es un buscador roto en silencio.

- [ ] **Paso 5: Correr la suite completa**

```bash
python -m pytest tests/ -v
```

Esperado: **PASAN todos**.

- [ ] **Paso 6: Probar la app a mano**

```bash
DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:54322/postgres" python app.py
```

Abrir http://127.0.0.1:5050, entrar, y recorrer: cargar un producto, hacer una venta, ver el comprobante, registrar una compra. Confirmar que el stock se mueve y los totales cierran.

- [ ] **Paso 7: Actualizar la documentación**

En `README.md`: reemplazar las instrucciones de instalación que asumen SQLite por el flujo nuevo (`npx supabase start`, `npx supabase db reset`, variable `DATABASE_URL`), y documentar cómo correr los tests.

En `CLAUDE.md`: actualizar la sección de arquitectura (ya no es "Flask + SQLite (`data.db`), corre local"), anotar que el esquema vive en `supabase/migrations/`, que la plata es `NUMERIC` y las fechas son tipos de fecha, y que existe una suite de tests. Dejar anotado el gotcha de `prepare_threshold=None`.

- [ ] **Paso 8: Commit**

```bash
git add tests/test_rutas.py README.md CLAUDE.md core/app.py
git commit -m "Verificar las 67 rutas contra Postgres y actualizar la documentación

Cierra la migración de SQLite a Postgres. Queda pendiente el Plan 2:
Supabase Auth, Storage para las fotos y el deploy en Vercel."
```

---

## Al terminar este plan

El sistema corre completo sobre Postgres, con tests que lo respaldan, y sigue funcionando local con `python app.py`. **Todavía no está en Vercel** y el login sigue siendo el propio con `password_hash`.

El Plan 2 (`docs/superpowers/plans/`, a escribir después de ejecutar este) cubre: migrar el login a Supabase Auth, mover las fotos a Supabase Storage, `vercel.json`, `ProxyFix`, `SESSION_COOKIE_SECURE`, las variables de entorno de producción y el deploy.

**Precondiciones humanas del Plan 2** (no hacen falta para este):
1. Crear el proyecto en Supabase.
2. Crear el proyecto en Vercel y conectarlo al repositorio.
3. Cargar las variables de entorno en Vercel.
4. Crear el primer usuario admin desde el panel de Supabase.
