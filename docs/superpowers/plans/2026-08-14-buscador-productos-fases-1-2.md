# Buscador de productos con filtros — Fases 1 y 2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que buscar un repuesto en `/productos` se pueda hacer filtrando por rubro, subrubro, marca y auto compatible, con una búsqueda de texto que no se rompa por mayúsculas, acentos, orden de palabras ni errores de tipeo.

**Architecture:** Tres tablas nuevas (`marcas`, `vehiculos`, `producto_vehiculos`) y **una sola función de búsqueda** en `core/database.py` que las tres pantallas del sistema van a compartir en las fases siguientes. En esta entrega se conecta únicamente a `/productos`. La normalización del texto (minúsculas + sin acentos) vive en una función SQL `texto_busqueda()` marcada `IMMUTABLE`, que es lo que permite indexarla.

**Tech Stack:** Python 3.11, Flask, Postgres vía Supabase (psycopg 3, `dict_row`), extensiones `unaccent` y `pg_trgm`, Bootstrap 5, pytest.

**Spec:** [docs/superpowers/specs/2026-08-14-buscador-productos-filtros-design.md](../specs/2026-08-14-buscador-productos-filtros-design.md)

**Alcance de este plan:** fases 1 y 2 de la spec. Las fases 3 (Nueva venta), 4 (tienda), 5 (detección de autos) y 6 (equivalencias) tienen su propio plan, que se escribe cuando el hermano de Celes haya probado esta entrega.

## Global Constraints

Estas reglas ya rigen en el proyecto (ver `CLAUDE.md`) y valen para **todas** las tareas de este plan:

- **Nunca `float()` en una columna de plata.** Postgres devuelve `Decimal`. Los formularios pasan por `a_decimal()` (en `core/app.py`).
- **Todo id que venga de un formulario o de la URL pasa por `a_entero()`** (en `core/app.py`). Postgres aborta la consulta con un id no numérico; SQLite no lo hacía. Sin esto, `/productos?vehiculo_id=abc` es un error 500.
- **Nunca `datetime.now()` para una fecha de negocio.** Se usa `db.hoy()` (zona `America/Argentina/Buenos_Aires`). En este plan no hay fechas de negocio, pero la regla vale igual.
- **Búsquedas de texto sin distinguir mayúsculas.** En Postgres `LIKE` sí distingue, a diferencia de SQLite. En este plan se resuelve con `texto_busqueda()`, no con `ILIKE` (ver Task 2 para el porqué).
- **Nunca abrir una conexión a mano.** Siempre `db.get_connection()`, que fija `prepare_threshold=None` — sin eso, el pooler de Supabase en producción empieza a fallar recién a partir de la quinta ejecución de cada consulta.
- **Los mensajes al usuario van en español**, tuteando, como el resto del sistema.
- **Correr la suite completa antes de cada commit final de tarea:** `python -m pytest tests/ -v` con `npx supabase start` levantado.

---

### Task 1: Migración — tablas, normalización de texto e índice

**Files:**
- Create: `supabase/migrations/<timestamp>_buscador_marcas_vehiculos.sql`
- Modify: `tests/conftest.py:31-37` (lista `TABLAS`)
- Modify: `tests/test_esquema.py:29-37` (lista `TABLAS_ESPERADAS`)
- Test: `tests/test_buscador_esquema.py`

**Interfaces:**
- Consumes: nada (primera tarea).
- Produces:
  - Tablas `marcas(id, nombre)`, `vehiculos(id, marca_auto, modelo, motor, anio_desde, anio_hasta, activo)`, `producto_vehiculos(id, producto_id, vehiculo_id)`.
  - Función SQL `texto_busqueda(text) RETURNS text` — minúsculas, sin acentos, sin espacios de más. `IMMUTABLE`.
  - Función SQL `sembrar_marcas_desde_productos() RETURNS integer` — agrega a `marcas` las que falten mirando `productos.marca`, devuelve cuántas agregó. Idempotente.

- [ ] **Step 1: Averiguar en qué esquema instala las extensiones esta instancia**

Supabase suele crear las extensiones en el esquema `extensions`, no en `public`. La migración tiene que referenciar `unaccent` con el esquema correcto o va a fallar al aplicarse.

Con `npx supabase start` levantado, correr:

```bash
psql postgresql://postgres:postgres@127.0.0.1:54322/postgres -c "SELECT nspname FROM pg_namespace WHERE nspname IN ('extensions','public') ORDER BY nspname"
```

Si aparece `extensions`, usar `WITH SCHEMA extensions` y `extensions.unaccent(...)` en el paso 3. Si no aparece, usar `public` en ambos lugares. **No adivinar: el resto del plan asume `extensions`.**

- [ ] **Step 2: Crear el archivo de migración vacío**

```bash
npx supabase migration new buscador_marcas_vehiculos
```

Genera `supabase/migrations/<timestamp>_buscador_marcas_vehiculos.sql`. El timestamp lo pone la CLI, así que el nombre real va a diferir del que figura arriba.

- [ ] **Step 3: Escribir la migración**

Contenido completo del archivo:

```sql
-- Buscador de productos con filtros (fase 1).
-- Ver docs/superpowers/specs/2026-08-14-buscador-productos-filtros-design.md

CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS pg_trgm  WITH SCHEMA extensions;

-- Normalización única para TODA búsqueda de texto del sistema: minúsculas,
-- sin acentos, sin espacios de más.
--
-- Tiene que ser IMMUTABLE para poder indexarla, y unaccent() por sí sola NO
-- lo es (depende del diccionario activo, que se puede cambiar en caliente).
-- Pasarle el diccionario explícito como primer argumento la vuelve
-- determinística, y por eso este wrapper se puede marcar IMMUTABLE sin
-- mentir. Sin esto, el índice del final falla al crearse.
CREATE OR REPLACE FUNCTION texto_busqueda(t TEXT) RETURNS TEXT
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT btrim(regexp_replace(
        lower(extensions.unaccent('extensions.unaccent'::regdictionary, coalesce(t, ''))),
        '\s+', ' ', 'g'))
$$;

CREATE TABLE marcas (
    id     INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE
);

-- Sin columna `activo` a propósito: las marcas no tienen pantalla de
-- administración, se mantienen solas desde la ficha del producto.
CREATE UNIQUE INDEX marcas_nombre_normalizado ON marcas (texto_busqueda(nombre));

CREATE TABLE vehiculos (
    id         INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    marca_auto TEXT NOT NULL,
    modelo     TEXT NOT NULL,
    -- Obligatorio. Para el repuesto que sirve para cualquier motor de ese
    -- auto existe el valor explícito 'Todos los motores': dejarlo vacío
    -- obligaría a decidir en cada consulta si vacío es "no sé" o "cualquiera".
    motor      TEXT NOT NULL,
    anio_desde INTEGER,
    anio_hasta INTEGER,
    activo     BOOLEAN NOT NULL DEFAULT true,
    UNIQUE (marca_auto, modelo, motor)
);

CREATE TABLE producto_vehiculos (
    id          INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    producto_id INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    -- Sin CASCADE a propósito: borrar un vehículo que algún producto usa
    -- tiene que fallar, igual que hoy falla borrar un proveedor con
    -- productos. Se desactiva con `activo`, no se borra.
    vehiculo_id INTEGER NOT NULL REFERENCES vehiculos(id),
    UNIQUE (producto_id, vehiculo_id)
);

CREATE INDEX producto_vehiculos_vehiculo ON producto_vehiculos (vehiculo_id);

-- Índice para la búsqueda de texto. Sin esto, cada ILIKE '%algo%' recorre la
-- tabla entera: invisible con 29 productos de prueba, un problema real con
-- los ~6.000 del catálogo verdadero.
CREATE INDEX productos_texto_trgm ON productos USING gin (
    texto_busqueda(
        coalesce(nombre, '') || ' ' || coalesce(codigo, '') || ' ' ||
        coalesce(marca, '') || ' ' || coalesce(modelo_compatible, '')
    ) extensions.gin_trgm_ops
);

-- Agrega a `marcas` las que falten mirando productos.marca. Idempotente:
-- se puede volver a correr cuando se importe el catálogo real.
--
-- DISTINCT ON sobre el nombre normalizado es lo que hace que 'COBREQ',
-- 'Cobreq' y 'cobreq ' entren como UNA sola marca. Sin eso el desplegable
-- prolijo termina siendo tres veces la misma marca, peor que el texto libre
-- que vino a reemplazar.
CREATE OR REPLACE FUNCTION sembrar_marcas_desde_productos() RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE
    agregadas INTEGER;
BEGIN
    WITH candidatas AS (
        SELECT DISTINCT ON (texto_busqueda(marca)) btrim(marca) AS nombre
        FROM productos
        WHERE marca IS NOT NULL AND texto_busqueda(marca) <> ''
        ORDER BY texto_busqueda(marca), btrim(marca)
    ), insertadas AS (
        INSERT INTO marcas (nombre)
        SELECT c.nombre FROM candidatas c
        WHERE NOT EXISTS (
            SELECT 1 FROM marcas m WHERE texto_busqueda(m.nombre) = texto_busqueda(c.nombre)
        )
        RETURNING 1
    )
    SELECT count(*) INTO agregadas FROM insertadas;
    RETURN agregadas;
END;
$$;

SELECT sembrar_marcas_desde_productos();
```

- [ ] **Step 4: Aplicar la migración y verificar que no falla**

```bash
npx supabase db reset
```

Expected: termina sin error y lista la migración nueva entre las aplicadas. Si falla en el `CREATE INDEX ... gin_trgm_ops` con "functions in index expression must be marked IMMUTABLE", el esquema de `unaccent` del Step 1 está mal — corregirlo y repetir.

- [ ] **Step 5: Sumar las tablas nuevas a las dos listas de tests**

En `tests/conftest.py`, agregar a la lista `TABLAS` (el comentario de arriba dice "Las 18 tablas", pasa a 21):

```python
    "marcas", "vehiculos", "producto_vehiculos",
```

En `tests/test_esquema.py`, agregar a `TABLAS_ESPERADAS`:

```python
    "marcas", "vehiculos", "producto_vehiculos",
```

- [ ] **Step 6: Escribir los tests de la migración**

Crear `tests/test_buscador_esquema.py`:

```python
"""Lo que la migración del buscador deja en la base: la normalización de
texto y la siembra de marcas sin duplicados.

La normalización se prueba acá y no junto a buscar_productos() porque es una
función de la base: si deja de sacar acentos, TODA búsqueda del sistema
empeora sin lanzar ningún error."""
import psycopg
import pytest


def texto(conn, valor):
    return conn.execute("SELECT texto_busqueda(%s) AS t", (valor,)).fetchone()["t"]


def test_normaliza_mayusculas_acentos_y_espacios(db_conn):
    assert texto(db_conn, "HIDRÁULICO") == "hidraulico"
    assert texto(db_conn, "  Bujía   Precalentamiento ") == "bujia precalentamiento"
    assert texto(db_conn, None) == ""


def test_sembrar_marcas_junta_las_que_solo_cambian_en_mayusculas_o_acentos(db_conn):
    for marca in ["COBREQ", "Cobreq", "cobreq ", "Fric-Rot"]:
        db_conn.execute(
            """INSERT INTO productos (nombre, categoria, marca, precio_costo, precio_venta)
               VALUES (%s, 'Frenos', %s, 100, 130)""",
            (f"Pastilla {marca}", marca),
        )
    agregadas = db_conn.execute("SELECT sembrar_marcas_desde_productos() AS n").fetchone()["n"]
    assert agregadas == 2, "COBREQ/Cobreq/'cobreq ' son la misma marca"
    # Se compara normalizado a propósito: cuál de las tres grafías queda
    # guardada depende del collation de la base, y eso no es lo que este test
    # viene a fijar — lo que importa es que quede UNA sola.
    nombres = sorted(
        r["nombre"].strip().lower()
        for r in db_conn.execute("SELECT nombre FROM marcas")
    )
    assert nombres == ["cobreq", "fric-rot"]


def test_sembrar_marcas_es_idempotente(db_conn):
    db_conn.execute(
        """INSERT INTO productos (nombre, categoria, marca, precio_costo, precio_venta)
           VALUES ('Pastilla', 'Frenos', 'Cobreq', 100, 130)"""
    )
    db_conn.execute("SELECT sembrar_marcas_desde_productos()")
    agregadas = db_conn.execute("SELECT sembrar_marcas_desde_productos() AS n").fetchone()["n"]
    assert agregadas == 0


def test_no_se_puede_borrar_un_vehiculo_en_uso(db_conn):
    producto_id = db_conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta)
           VALUES ('Buje', 'Suspensión y Dirección', 100, 130) RETURNING id"""
    ).fetchone()["id"]
    vehiculo_id = db_conn.execute(
        """INSERT INTO vehiculos (marca_auto, modelo, motor)
           VALUES ('FIAT', 'Palio', '1.4') RETURNING id"""
    ).fetchone()["id"]
    db_conn.execute(
        "INSERT INTO producto_vehiculos (producto_id, vehiculo_id) VALUES (%s, %s)",
        (producto_id, vehiculo_id),
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db_conn.execute("DELETE FROM vehiculos WHERE id = %s", (vehiculo_id,))


def test_borrar_un_producto_se_lleva_sus_vehiculos(db_conn):
    producto_id = db_conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta)
           VALUES ('Buje', 'Suspensión y Dirección', 100, 130) RETURNING id"""
    ).fetchone()["id"]
    vehiculo_id = db_conn.execute(
        """INSERT INTO vehiculos (marca_auto, modelo, motor)
           VALUES ('FIAT', 'Palio', '1.4') RETURNING id"""
    ).fetchone()["id"]
    db_conn.execute(
        "INSERT INTO producto_vehiculos (producto_id, vehiculo_id) VALUES (%s, %s)",
        (producto_id, vehiculo_id),
    )
    db_conn.execute("DELETE FROM productos WHERE id = %s", (producto_id,))
    quedan = db_conn.execute("SELECT count(*) AS n FROM producto_vehiculos").fetchone()["n"]
    assert quedan == 0
```

- [ ] **Step 7: Correr los tests**

Run: `python -m pytest tests/test_buscador_esquema.py tests/test_esquema.py -v`
Expected: PASS todos.

- [ ] **Step 8: Correr la suite completa**

Run: `python -m pytest tests/ -v`
Expected: PASS. Si algo falla, es la lista `TABLAS` de `conftest.py` mal editada.

- [ ] **Step 9: Commit**

```bash
git add supabase/migrations/ tests/conftest.py tests/test_esquema.py tests/test_buscador_esquema.py
git commit -m "Crear las tablas de marcas y vehículos para el buscador con filtros

texto_busqueda() normaliza minúsculas, acentos y espacios en un solo lugar,
y va marcada IMMUTABLE para poder indexarla: unaccent() sola no lo es
porque depende del diccionario activo.

sembrar_marcas_desde_productos() junta las marcas que solo difieren en
mayúsculas o acentos — si no, el desplegable termina con la misma marca
tres veces y es peor que el texto libre que reemplaza."
```

---

### Task 2: `db.buscar_productos()`

**Files:**
- Modify: `core/database.py` (agregar después de `obtener_subcategorias()`, cerca de la línea 168)
- Test: `tests/test_buscar_productos.py`

**Interfaces:**
- Consumes: `texto_busqueda()` de Task 1; tablas `vehiculos` y `producto_vehiculos`.
- Produces:
  - `db.buscar_productos(conn, q=None, categoria=None, subcategoria=None, marca=None, vehiculo_id=None, solo_con_stock=False, limite=None) -> list[dict]` — filas completas de `productos`, ordenadas por `categoria, nombre`.
  - `db._condiciones_busqueda(q, categoria, subcategoria, marca, vehiculo_id, solo_con_stock, excluir=()) -> (list[str], list)` — privada, la reutiliza Task 4.

- [ ] **Step 1: Escribir los tests**

Crear `tests/test_buscar_productos.py`:

```python
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
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_buscar_productos.py -v`
Expected: FAIL con `AttributeError: module 'core.database' has no attribute 'buscar_productos'`.

- [ ] **Step 3: Implementar**

En `core/database.py`, después de `obtener_subcategorias()`:

```python
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
      AND texto_busqueda(v.marca_auto || ' ' || v.modelo) LIKE %s
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
    # la columna cruda no podría usar el índice trigram.
    for palabra in (q or "").split():
        condiciones.append(
            f"({TEXTO_PRODUCTO_SQL} LIKE %s OR p.codigo_barras = %s OR {TEXTO_VEHICULOS_SQL})"
        )
        patron = f"%{palabra.lower()}%"
        # El código de barras matchea EXACTO, nunca por parecido: es lo que
        # dispara la pistola y un match aproximado sería cargar el producto
        # equivocado en la venta.
        params += [patron, palabra, patron]

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
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_buscar_productos.py -v`
Expected: PASS los 14.

- [ ] **Step 5: Verificar que el índice se está usando de verdad**

El índice no sirve de nada si la expresión de la consulta no coincide con la del índice, y eso no lo detecta ningún test.

```bash
psql postgresql://postgres:postgres@127.0.0.1:54322/postgres -c "EXPLAIN SELECT p.* FROM productos p WHERE texto_busqueda(coalesce(p.nombre,'') || ' ' || coalesce(p.codigo,'') || ' ' || coalesce(p.marca,'') || ' ' || coalesce(p.modelo_compatible,'')) LIKE '%pastilla%'"
```

Expected: aparece `productos_texto_trgm` en el plan. Con la tabla casi vacía Postgres puede elegir igual un `Seq Scan` por ser más barato — en ese caso, forzar con `SET enable_seqscan = off;` antes del EXPLAIN y confirmar que **puede** usarlo. Si ni así aparece, la expresión del índice y la de `TEXTO_PRODUCTO_SQL` difieren: compararlas carácter por carácter.

- [ ] **Step 6: Correr la suite completa y commitear**

```bash
python -m pytest tests/ -v
git add core/database.py tests/test_buscar_productos.py
git commit -m "Unificar la búsqueda de productos en db.buscar_productos()

Una sola función para las tres pantallas que buscan productos, que antes
tenían tres criterios distintos ya divergidos.

Busca palabra por palabra en cualquier orden sobre texto normalizado, así
'palio pastilla' encuentra 'PASTILLA DE FRENO FIAT PALIO'. El código de
barras sigue matcheando exacto: es lo que dispara la pistola y un match
aproximado sería cargar el producto equivocado en la venta."
```

---

### Task 3: Sugerencias cuando no hay resultados

**Files:**
- Modify: `core/database.py` (agregar debajo de `buscar_productos()`)
- Test: `tests/test_buscar_productos.py` (agregar al final)

**Interfaces:**
- Consumes: `texto_busqueda()` y la extensión `pg_trgm` de Task 1.
- Produces: `db.sugerencias_busqueda(conn, q, limite=5) -> list[str]` — nombres de productos parecidos a lo que se escribió, de mayor a menor parecido. Lista vacía si `q` está vacío o si nada supera el umbral.

- [ ] **Step 1: Escribir los tests**

Agregar al final de `tests/test_buscar_productos.py`:

```python
def test_sugiere_cuando_hay_un_error_de_tipeo(db_conn, catalogo):
    """'pastila' no devuelve nada; en vez de dejar al usuario en la nada, se
    le ofrece lo parecido."""
    assert db.buscar_productos(db_conn, q="pastila") == []
    sugerencias = db.sugerencias_busqueda(db_conn, "pastila")
    assert "Pastilla de freno delantera" in sugerencias


def test_no_sugiere_cualquier_cosa(db_conn, catalogo):
    """Una sugerencia sin parecido real es peor que ninguna."""
    assert db.sugerencias_busqueda(db_conn, "zzzzzzzz") == []


def test_no_sugiere_sin_texto(db_conn, catalogo):
    assert db.sugerencias_busqueda(db_conn, "") == []
    assert db.sugerencias_busqueda(db_conn, None) == []
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_buscar_productos.py -k sugiere -v`
Expected: FAIL con `AttributeError: ... has no attribute 'sugerencias_busqueda'`.

- [ ] **Step 3: Implementar**

En `core/database.py`, debajo de `buscar_productos()`:

```python
# Parecido mínimo (0 a 1) para ofrecer una sugerencia. 0.3 es el default
# histórico de pg_trgm y tolera un par de letras cambiadas ("pastila" ->
# "pastilla") sin ofrecer cualquier cosa. Subirlo deja sin sugerencia
# errores reales; bajarlo sugiere productos que no tienen nada que ver.
UMBRAL_SUGERENCIA = 0.3


def sugerencias_busqueda(conn, q, limite=5):
    """Nombres parecidos a lo que se escribió, para cuando la búsqueda no
    devuelve nada. Es una sugerencia que se le muestra al usuario, NO un
    reemplazo automático: no se le cambia a alguien lo que buscó sin avisarle.
    """
    texto = (q or "").strip()
    if not texto:
        return []
    filas = conn.execute(
        """SELECT p.nombre,
                  similarity(texto_busqueda(p.nombre), texto_busqueda(%s)) AS parecido
           FROM productos p
           WHERE similarity(texto_busqueda(p.nombre), texto_busqueda(%s)) >= %s
           ORDER BY parecido DESC, p.nombre
           LIMIT %s""",
        (texto, texto, UMBRAL_SUGERENCIA, limite),
    ).fetchall()
    return [f["nombre"] for f in filas]
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_buscar_productos.py -v`
Expected: PASS los 17.

Si `similarity()` da "function does not exist", es que `pg_trgm` quedó en el esquema `extensions` y no está en el `search_path`. Calificarla: `extensions.similarity(...)`.

- [ ] **Step 5: Commit**

```bash
python -m pytest tests/ -v
git add core/database.py tests/test_buscar_productos.py
git commit -m "Sugerir productos parecidos cuando la búsqueda no devuelve nada

Sugiere, no reemplaza: no se le cambia a alguien lo que buscó sin avisarle."
```

---

### Task 4: `db.facetas_productos()` — los contadores

**Files:**
- Modify: `core/database.py` (agregar debajo de `sugerencias_busqueda()`)
- Test: `tests/test_facetas_productos.py`

**Interfaces:**
- Consumes: `_condiciones_busqueda()` de Task 2.
- Produces: `db.facetas_productos(conn, q=None, categoria=None, subcategoria=None, marca=None, vehiculo_id=None, solo_con_stock=False) -> dict` con la forma:
  ```python
  {"total": 12,
   "categoria":    {"Frenos": 8, "Embragues": 4},
   "subcategoria": {"Pastillas": 5, ...},
   "marca":        {"Cobreq": 3, ...}}
  ```

- [ ] **Step 1: Escribir los tests**

Crear `tests/test_facetas_productos.py`:

```python
"""Los contadores al lado de cada filtro. Lo que hace que 'se achique solo'
se sienta bien es que nunca manden a un rubro vacío."""
import pytest
from core import database as db


@pytest.fixture
def catalogo(db_conn):
    filas = [
        ("Pastilla delantera", "Frenos", "Pastillas", "Cobreq", 5),
        ("Pastilla trasera", "Frenos", "Pastillas", "Fric-Rot", 0),
        ("Disco de freno", "Frenos", "Discos", "Cobreq", 2),
        ("Kit de embrague", "Embragues", "Kits de embrague", "Sachs", 1),
    ]
    for nombre, categoria, subcategoria, marca, stock in filas:
        db_conn.execute(
            """INSERT INTO productos
               (nombre, categoria, subcategoria, marca, stock_actual, precio_costo, precio_venta)
               VALUES (%s, %s, %s, %s, %s, 100, 130)""",
            (nombre, categoria, subcategoria, marca, stock),
        )


def test_cuenta_por_categoria_sin_filtros(db_conn, catalogo):
    facetas = db.facetas_productos(db_conn)
    assert facetas["total"] == 4
    assert facetas["categoria"] == {"Frenos": 3, "Embragues": 1}


def test_una_categoria_elegida_no_se_filtra_a_si_misma(db_conn, catalogo):
    """Si al elegir Frenos el contador de Embragues cayera a 0, el usuario no
    podría ver que existe otra opción con productos. El contador de cada
    filtro se calcula SIN aplicarse a sí mismo."""
    facetas = db.facetas_productos(db_conn, categoria="Frenos")
    assert facetas["categoria"] == {"Frenos": 3, "Embragues": 1}
    assert facetas["total"] == 3, "el total sí respeta el filtro elegido"


def test_los_demas_filtros_si_achican_los_contadores(db_conn, catalogo):
    """Elegida la categoría Frenos, el contador de marcas solo cuenta frenos."""
    facetas = db.facetas_productos(db_conn, categoria="Frenos")
    assert facetas["marca"] == {"Cobreq": 2, "Fric-Rot": 1}
    assert "Sachs" not in facetas["marca"]


def test_solo_con_stock_se_refleja_en_los_contadores(db_conn, catalogo):
    facetas = db.facetas_productos(db_conn, solo_con_stock=True)
    assert facetas["total"] == 3
    assert facetas["categoria"] == {"Frenos": 2, "Embragues": 1}


def test_el_texto_buscado_achica_los_contadores(db_conn, catalogo):
    facetas = db.facetas_productos(db_conn, q="pastilla")
    assert facetas["total"] == 2
    assert facetas["categoria"] == {"Frenos": 2}


def test_los_productos_sin_subcategoria_no_rompen(db_conn, catalogo):
    db_conn.execute(
        """INSERT INTO productos (nombre, categoria, marca, precio_costo, precio_venta)
           VALUES ('Suelto', 'Otros', 'Sin marca', 100, 130)"""
    )
    facetas = db.facetas_productos(db_conn)
    assert facetas["total"] == 5
    assert None not in facetas["subcategoria"]
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_facetas_productos.py -v`
Expected: FAIL con `AttributeError: ... has no attribute 'facetas_productos'`.

- [ ] **Step 3: Implementar**

En `core/database.py`, debajo de `sugerencias_busqueda()`:

```python
# Las tres dimensiones que llevan contador al lado de cada opción. El auto no
# lleva contador: la lista de vehículos puede ser larga y el contador exigiría
# una consulta por vehículo cargado.
DIMENSIONES_FACETAS = ["categoria", "subcategoria", "marca"]


def facetas_productos(conn, q=None, categoria=None, subcategoria=None, marca=None,
                      vehiculo_id=None, solo_con_stock=False):
    """Cuántos productos hay en cada opción de cada filtro, para mostrarlo al
    lado (`Frenos (128)`), más el total que cumple TODOS los filtros.

    Cada dimensión se cuenta SIN aplicar su propio filtro: si al elegir Frenos
    el contador de Embragues cayera a cero, el usuario no podría ver que hay
    otra opción con productos y quedaría encerrado en su propia elección.
    """
    filtros = dict(q=q, categoria=categoria, subcategoria=subcategoria,
                   marca=marca, vehiculo_id=vehiculo_id, solo_con_stock=solo_con_stock)

    condiciones, params = _condiciones_busqueda(**filtros)
    consulta = "SELECT count(*) AS n FROM productos p"
    if condiciones:
        consulta += " WHERE " + " AND ".join(condiciones)
    resultado = {"total": conn.execute(consulta, params).fetchone()["n"]}

    for dimension in DIMENSIONES_FACETAS:
        condiciones, params = _condiciones_busqueda(**filtros, excluir=(dimension,))
        consulta = f"SELECT p.{dimension} AS valor, count(*) AS n FROM productos p"
        if condiciones:
            consulta += " WHERE " + " AND ".join(condiciones)
        consulta += f" GROUP BY p.{dimension}"
        resultado[dimension] = {
            fila["valor"]: fila["n"]
            for fila in conn.execute(consulta, params).fetchall()
            if fila["valor"]  # los productos sin subcategoría no son una opción
        }
    return resultado
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_facetas_productos.py -v`
Expected: PASS los 6.

- [ ] **Step 5: Commit**

```bash
python -m pytest tests/ -v
git add core/database.py tests/test_facetas_productos.py
git commit -m "Contar cuántos productos hay en cada opción de cada filtro

Cada dimensión se cuenta sin aplicar su propio filtro: si al elegir Frenos
el contador de Embragues cayera a cero, el usuario quedaría encerrado en su
propia elección sin ver que hay otra opción con productos."
```

---

### Task 5: Pantalla `/vehiculos`

**Files:**
- Modify: `core/database.py` (agregar `obtener_vehiculos()` debajo de `obtener_subcategorias()`)
- Modify: `core/app.py` (rutas nuevas, al lado de las de `/categorias`)
- Create: `templates/vehiculos.html`
- Modify: `templates/base.html` (link en el menú Stock)
- Modify: `tests/test_rutas.py:7-13` (agregar `/vehiculos` a `RUTAS_PRIVADAS`)
- Test: `tests/test_vehiculos.py`

**Interfaces:**
- Consumes: tabla `vehiculos` de Task 1.
- Produces:
  - `db.obtener_vehiculos(conn=None, solo_activos=True) -> list[dict]` — filas de `vehiculos` ordenadas por `marca_auto, modelo, motor`.
  - Rutas `GET /vehiculos`, `POST /vehiculos/nuevo`, `POST /vehiculos/<id>/activar`, `POST /vehiculos/<id>/eliminar`.

- [ ] **Step 1: Escribir los tests**

Crear `tests/test_vehiculos.py`:

```python
"""El ABM de autos. Sigue el mismo patrón activo/inactivo que proveedores y
categorías: no se borra lo que está en uso, se desactiva."""
import pytest
from core.app import app as flask_app
from core import database as db


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


def test_crear_un_vehiculo(client, db_conn):
    respuesta = client.post("/vehiculos/nuevo", data={
        "marca_auto": "FIAT", "modelo": "Palio", "motor": "1.4",
        "anio_desde": "2008", "anio_hasta": "2012",
    }, follow_redirects=True)
    assert respuesta.status_code == 200
    fila = db_conn.execute("SELECT * FROM vehiculos").fetchone()
    assert (fila["marca_auto"], fila["modelo"], fila["motor"]) == ("FIAT", "Palio", "1.4")
    assert fila["anio_desde"] == 2008


def test_el_anio_es_opcional(client, db_conn):
    """Celes fue explícita: el motor sí o sí, el año no importa si no se llena."""
    client.post("/vehiculos/nuevo", data={
        "marca_auto": "VW", "modelo": "Gol", "motor": "1.6",
        "anio_desde": "", "anio_hasta": "",
    }, follow_redirects=True)
    fila = db_conn.execute("SELECT * FROM vehiculos").fetchone()
    assert fila["anio_desde"] is None and fila["anio_hasta"] is None


def test_no_deja_repetir_el_mismo_auto(client, db_conn):
    datos = {"marca_auto": "FIAT", "modelo": "Palio", "motor": "1.4",
             "anio_desde": "", "anio_hasta": ""}
    client.post("/vehiculos/nuevo", data=datos, follow_redirects=True)
    respuesta = client.post("/vehiculos/nuevo", data=datos, follow_redirects=True)
    assert respuesta.status_code == 200, "avisa, no revienta"
    total = db_conn.execute("SELECT count(*) AS n FROM vehiculos").fetchone()["n"]
    assert total == 1


def test_no_se_puede_borrar_uno_en_uso(client, db_conn):
    """Mismo criterio que un proveedor con compras: se avisa y se ofrece
    desactivarlo, no se rompe con un error de base de datos."""
    producto_id = db_conn.execute(
        """INSERT INTO productos (nombre, categoria, precio_costo, precio_venta)
           VALUES ('Buje', 'Otros', 100, 130) RETURNING id"""
    ).fetchone()["id"]
    vehiculo_id = db_conn.execute(
        """INSERT INTO vehiculos (marca_auto, modelo, motor)
           VALUES ('FIAT', 'Palio', '1.4') RETURNING id"""
    ).fetchone()["id"]
    db_conn.execute(
        "INSERT INTO producto_vehiculos (producto_id, vehiculo_id) VALUES (%s, %s)",
        (producto_id, vehiculo_id),
    )
    db_conn.commit()
    respuesta = client.post(f"/vehiculos/{vehiculo_id}/eliminar", follow_redirects=True)
    assert respuesta.status_code == 200
    queda = db_conn.execute(
        "SELECT count(*) AS n FROM vehiculos WHERE id = %s", (vehiculo_id,)
    ).fetchone()["n"]
    assert queda == 1


def test_obtener_vehiculos_omite_los_desactivados(db_conn):
    db_conn.execute(
        """INSERT INTO vehiculos (marca_auto, modelo, motor, activo)
           VALUES ('FIAT', 'Palio', '1.4', true), ('VW', 'Gol', '1.6', false)"""
    )
    activos = [v["modelo"] for v in db.obtener_vehiculos(db_conn, solo_activos=True)]
    assert activos == ["Palio"]
    todos = [v["modelo"] for v in db.obtener_vehiculos(db_conn, solo_activos=False)]
    assert sorted(todos) == ["Gol", "Palio"]
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_vehiculos.py -v`
Expected: FAIL — las rutas devuelven 404 y `obtener_vehiculos` no existe.

- [ ] **Step 3: Agregar `obtener_vehiculos()` a `core/database.py`**

Debajo de `obtener_subcategorias()`:

```python
def obtener_vehiculos(conn=None, solo_activos=True):
    """Autos cargados, para el desplegable del filtro y para vincularlos a un
    producto. Mismo patrón que obtener_categorias(): si no se pasa una
    conexión abierta, abre y cierra una propia."""
    conn_propia = conn is None
    if conn_propia:
        conn = get_connection()
    consulta = "SELECT * FROM vehiculos"
    if solo_activos:
        consulta += " WHERE activo = true"
    consulta += " ORDER BY marca_auto, modelo, motor"
    filas = conn.execute(consulta).fetchall()
    if conn_propia:
        conn.close()
    return filas
```

- [ ] **Step 4: Agregar las rutas a `core/app.py`**

Al lado de las rutas de `/categorias`:

```python
@app.route("/vehiculos")
def vehiculos_lista():
    conn = db.get_connection()
    vehiculos = db.obtener_vehiculos(conn, solo_activos=False)
    usos = {
        fila["vehiculo_id"]: fila["n"]
        for fila in conn.execute(
            "SELECT vehiculo_id, count(*) AS n FROM producto_vehiculos GROUP BY vehiculo_id"
        ).fetchall()
    }
    conn.close()
    return render_template("vehiculos.html", vehiculos=vehiculos, usos=usos)


@app.route("/vehiculos/nuevo", methods=["POST"])
def vehiculos_nuevo():
    marca_auto = request.form.get("marca_auto", "").strip()
    modelo = request.form.get("modelo", "").strip()
    motor = request.form.get("motor", "").strip()
    if not (marca_auto and modelo and motor):
        flash("Marca, modelo y motor son obligatorios.", "warning")
        return redirect(url_for("vehiculos_lista"))
    conn = db.get_connection()
    try:
        conn.execute(
            """INSERT INTO vehiculos (marca_auto, modelo, motor, anio_desde, anio_hasta)
               VALUES (%s, %s, %s, %s, %s)""",
            (marca_auto, modelo, motor,
             a_entero(request.form.get("anio_desde")),
             a_entero(request.form.get("anio_hasta"))),
        )
        conn.commit()
        flash(f"Se agregó {marca_auto} {modelo} {motor}.", "success")
    except psycopg.errors.UniqueViolation:
        conn.rollback()
        flash(f"{marca_auto} {modelo} {motor} ya estaba cargado.", "warning")
    conn.close()
    return redirect(url_for("vehiculos_lista"))


@app.route("/vehiculos/<int:vehiculo_id>/activar", methods=["POST"])
def vehiculos_activar(vehiculo_id):
    conn = db.get_connection()
    conn.execute("UPDATE vehiculos SET activo = NOT activo WHERE id = %s", (vehiculo_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("vehiculos_lista"))


@app.route("/vehiculos/<int:vehiculo_id>/eliminar", methods=["POST"])
def vehiculos_eliminar(vehiculo_id):
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM vehiculos WHERE id = %s", (vehiculo_id,))
        conn.commit()
        flash("Auto eliminado.", "success")
    except psycopg.errors.ForeignKeyViolation:
        # Mismo criterio que un proveedor con compras cargadas: se avisa con
        # un mensaje claro y se ofrece desactivarlo, en vez de dejar escapar
        # el error de la base.
        conn.rollback()
        flash("No se puede eliminar: hay productos vinculados a este auto. "
              "Desactivalo si no querés que aparezca más.", "warning")
    conn.close()
    return redirect(url_for("vehiculos_lista"))
```

Verificar que `import psycopg` esté al principio de `core/app.py`; si no está, agregarlo.

- [ ] **Step 5: Crear `templates/vehiculos.html`**

```html
{% extends "base.html" %}
{% block title %}Autos | Frenos & Embragues{% endblock %}
{% block content %}
<h4 class="mb-3"><i class="bi bi-car-front"></i> Autos compatibles</h4>

<div class="card p-3 mb-3">
  <form method="post" action="{{ url_for('vehiculos_nuevo') }}" class="row g-2 align-items-end">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <div class="col-md-2">
      <label class="form-label small">Marca del auto</label>
      <input name="marca_auto" class="form-control" required placeholder="FIAT">
    </div>
    <div class="col-md-2">
      <label class="form-label small">Modelo</label>
      <input name="modelo" class="form-control" required placeholder="Palio">
    </div>
    <div class="col-md-2">
      <label class="form-label small">Motor</label>
      <input name="motor" class="form-control" required placeholder="1.4"
             list="motoresSugeridos">
      <datalist id="motoresSugeridos"><option value="Todos los motores"></datalist>
      <div class="form-text">Si el repuesto sirve para cualquier motor, poné "Todos los motores".</div>
    </div>
    <div class="col-md-2">
      <label class="form-label small">Año desde <span class="text-muted">(opcional)</span></label>
      <input name="anio_desde" type="number" class="form-control" placeholder="2008">
    </div>
    <div class="col-md-2">
      <label class="form-label small">Año hasta <span class="text-muted">(opcional)</span></label>
      <input name="anio_hasta" type="number" class="form-control" placeholder="2012">
    </div>
    <div class="col-md-2">
      <button class="btn btn-primary w-100"><i class="bi bi-plus-lg"></i> Agregar</button>
    </div>
  </form>
</div>

<div class="card p-3">
  <table class="table table-hover align-middle mb-0">
    <thead><tr><th>Auto</th><th>Años</th><th class="text-end">Productos</th><th></th><th></th></tr></thead>
    <tbody>
    {% for v in vehiculos %}
      <tr class="{{ '' if v.activo else 'text-muted' }}">
        <td>{{ v.marca_auto }} {{ v.modelo }} <span class="text-muted">{{ v.motor }}</span>
          {% if not v.activo %}<span class="badge bg-secondary ms-1">desactivado</span>{% endif %}
        </td>
        <td>{% if v.anio_desde or v.anio_hasta %}{{ v.anio_desde or '?' }} - {{ v.anio_hasta or '?' }}{% else %}<span class="text-muted">—</span>{% endif %}</td>
        <td class="text-end">{{ usos.get(v.id, 0) }}</td>
        <td class="text-end">
          <form method="post" action="{{ url_for('vehiculos_activar', vehiculo_id=v.id) }}" class="d-inline">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <button class="btn btn-sm btn-outline-secondary">{{ 'Desactivar' if v.activo else 'Activar' }}</button>
          </form>
        </td>
        <td class="text-end">
          <form method="post" action="{{ url_for('vehiculos_eliminar', vehiculo_id=v.id) }}" class="d-inline"
                onsubmit="return confirm('¿Eliminar este auto?');">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <button class="btn btn-sm btn-outline-danger"><i class="bi bi-trash"></i></button>
          </form>
        </td>
      </tr>
    {% else %}
      <tr><td colspan="5" class="text-center text-muted py-4">
        Todavía no hay autos cargados. Agregá el primero con el formulario de arriba.
      </td></tr>
    {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

- [ ] **Step 6: Agregar el link al menú Stock de `templates/base.html`**

Dentro del `<ul class="dropdown-menu">` del menú Stock, después del link a Categorías:

```html
<li><a class="dropdown-item" href="{{ url_for('vehiculos_lista') }}">Autos</a></li>
```

- [ ] **Step 7: Sumar `/vehiculos` a la red de seguridad de rutas**

En `tests/test_rutas.py`, agregar `"/vehiculos"` a `RUTAS_PRIVADAS`.

- [ ] **Step 8: Correr los tests**

Run: `python -m pytest tests/test_vehiculos.py tests/test_rutas.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
python -m pytest tests/ -v
git add core/database.py core/app.py templates/vehiculos.html templates/base.html tests/test_vehiculos.py tests/test_rutas.py
git commit -m "Sumar la pantalla de autos compatibles

El motor es obligatorio, con 'Todos los motores' para el repuesto que sirve
para cualquier motor del mismo auto; el año es opcional.

Un auto con productos vinculados no se puede borrar: se avisa y se ofrece
desactivarlo, mismo criterio que un proveedor con compras cargadas."
```

---

### Task 6: Vincular autos y marca desde la ficha del producto

**Files:**
- Modify: `core/app.py` — `productos_nuevo()` (línea ~1018) y `productos_editar()`
- Create: función `guardar_vehiculos_producto(conn, producto_id, form)` en `core/app.py`, al lado de `guardar_cotizaciones_proveedor()`
- Modify: `templates/producto_form.html`
- Test: `tests/test_producto_vehiculos.py`

**Interfaces:**
- Consumes: `db.obtener_vehiculos()` de Task 5; `sembrar_marcas_desde_productos()` de Task 1.
- Produces:
  - `guardar_vehiculos_producto(conn, producto_id, form)` — reemplaza los vínculos del producto por los `vehiculo_id` tildados en el formulario.
  - El campo `marca` de la ficha pasa a tener sugerencias (`<datalist>`) y su valor se agrega solo a `marcas` al guardar.

- [ ] **Step 1: Escribir los tests**

Crear `tests/test_producto_vehiculos.py`:

```python
"""Vincular autos a un producto desde su ficha, y que la marca escrita quede
disponible para el filtro sin pantalla de administración de por medio."""
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


@pytest.fixture
def autos(db_conn):
    palio = db_conn.execute(
        "INSERT INTO vehiculos (marca_auto, modelo, motor) VALUES ('FIAT','Palio','1.4') RETURNING id"
    ).fetchone()["id"]
    gol = db_conn.execute(
        "INSERT INTO vehiculos (marca_auto, modelo, motor) VALUES ('VW','Gol','1.6') RETURNING id"
    ).fetchone()["id"]
    db_conn.commit()
    return {"palio": palio, "gol": gol}


DATOS_BASE = {
    "nombre": "Pastilla de freno", "categoria": "Frenos", "marca": "Cobreq",
    "precio_costo": "100", "precio_venta": "130",
    "stock_actual": "5", "stock_minimo": "2",
}


def test_crear_un_producto_vinculando_dos_autos(client, db_conn, autos):
    client.post("/productos/nuevo", data={
        **DATOS_BASE, "vehiculo_id": [str(autos["palio"]), str(autos["gol"])],
    }, follow_redirects=True)
    vinculados = db_conn.execute(
        """SELECT v.modelo FROM producto_vehiculos pv
           JOIN vehiculos v ON v.id = pv.vehiculo_id ORDER BY v.modelo"""
    ).fetchall()
    assert [f["modelo"] for f in vinculados] == ["Gol", "Palio"]


def test_un_producto_sin_autos_se_guarda_igual(client, db_conn, autos):
    """Vincular autos es opcional: el sistema no puede empeorar para quien
    todavía no los cargó."""
    respuesta = client.post("/productos/nuevo", data=DATOS_BASE, follow_redirects=True)
    assert respuesta.status_code == 200
    total = db_conn.execute("SELECT count(*) AS n FROM productos").fetchone()["n"]
    assert total == 1
    assert db_conn.execute("SELECT count(*) AS n FROM producto_vehiculos").fetchone()["n"] == 0


def test_editar_reemplaza_los_autos_vinculados(client, db_conn, autos):
    client.post("/productos/nuevo", data={
        **DATOS_BASE, "vehiculo_id": [str(autos["palio"]), str(autos["gol"])],
    }, follow_redirects=True)
    producto_id = db_conn.execute("SELECT id FROM productos").fetchone()["id"]
    client.post(f"/productos/{producto_id}/editar", data={
        **DATOS_BASE, "vehiculo_id": [str(autos["gol"])],
    }, follow_redirects=True)
    vinculados = db_conn.execute(
        """SELECT v.modelo FROM producto_vehiculos pv
           JOIN vehiculos v ON v.id = pv.vehiculo_id"""
    ).fetchall()
    assert [f["modelo"] for f in vinculados] == ["Gol"]


def test_la_marca_escrita_queda_disponible_para_el_filtro(client, db_conn, autos):
    """No hay pantalla de marcas: la lista se mantiene sola al guardar."""
    client.post("/productos/nuevo", data={**DATOS_BASE, "marca": "Fric-Rot"},
                follow_redirects=True)
    marcas = [m["nombre"] for m in db_conn.execute("SELECT nombre FROM marcas")]
    assert "Fric-Rot" in marcas


def test_la_marca_no_se_duplica_por_mayusculas(client, db_conn, autos):
    client.post("/productos/nuevo", data={**DATOS_BASE, "marca": "Cobreq"},
                follow_redirects=True)
    client.post("/productos/nuevo", data={
        **DATOS_BASE, "nombre": "Otra pastilla", "marca": "COBREQ",
    }, follow_redirects=True)
    total = db_conn.execute("SELECT count(*) AS n FROM marcas").fetchone()["n"]
    assert total == 1
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_producto_vehiculos.py -v`
Expected: FAIL — los vínculos no se guardan y `marcas` queda vacía.

- [ ] **Step 3: Implementar el helper en `core/app.py`**

Al lado de `guardar_cotizaciones_proveedor()`:

```python
def guardar_vehiculos_producto(conn, producto_id, form):
    """Reemplaza los autos vinculados a un producto por los tildados en el
    formulario. Borrar y reinsertar (en vez de calcular la diferencia) es más
    simple y no tiene efectos visibles: la tabla no guarda ningún dato propio
    del vínculo más allá de qué producto va con qué auto.

    Los ids pasan por a_entero() como cualquier id que venga de un formulario:
    Postgres aborta la consulta con un id no numérico, a diferencia de SQLite.
    """
    conn.execute("DELETE FROM producto_vehiculos WHERE producto_id = %s", (producto_id,))
    vistos = set()
    for valor in form.getlist("vehiculo_id"):
        vehiculo_id = a_entero(valor)
        if vehiculo_id and vehiculo_id not in vistos:
            vistos.add(vehiculo_id)
            conn.execute(
                "INSERT INTO producto_vehiculos (producto_id, vehiculo_id) VALUES (%s, %s)",
                (producto_id, vehiculo_id),
            )
```

- [ ] **Step 4: Llamarlo desde las dos rutas de producto**

En `productos_nuevo()`, justo después de `guardar_cotizaciones_proveedor(conn, producto_id, request.form)`:

```python
        guardar_vehiculos_producto(conn, producto_id, request.form)
        # La lista de marcas se mantiene sola desde acá: no hay pantalla de
        # administración de marcas, así que si esto no corre el filtro de
        # marca queda desactualizado respecto de los productos.
        conn.execute("SELECT sembrar_marcas_desde_productos()")
```

Agregar las mismas dos líneas en `productos_editar()`, después de su llamada a `guardar_cotizaciones_proveedor()`.

En las dos rutas, pasar los autos al template. En el `render_template("producto_form.html", ...)` de `productos_nuevo()`:

```python
        vehiculos=db.obtener_vehiculos(conn),
        vehiculos_del_producto=[],
        marcas=[m["nombre"] for m in conn.execute("SELECT nombre FROM marcas ORDER BY nombre")],
```

Y en el de `productos_editar()`, lo mismo pero con los del producto:

```python
        vehiculos=db.obtener_vehiculos(conn),
        vehiculos_del_producto=[
            f["vehiculo_id"] for f in conn.execute(
                "SELECT vehiculo_id FROM producto_vehiculos WHERE producto_id = %s",
                (producto_id,),
            ).fetchall()
        ],
        marcas=[m["nombre"] for m in conn.execute("SELECT nombre FROM marcas ORDER BY nombre")],
```

**Ojo con el orden**: las consultas al template tienen que ir ANTES de `conn.close()`.

- [ ] **Step 5: Agregar la sección al template**

En `templates/producto_form.html`, antes de la sección "Precios por proveedor", agregar:

```html
<div class="card p-3 mb-3">
  <h6 class="mb-2">Autos compatibles <span class="text-muted fw-normal">(opcional)</span></h6>
  {% if vehiculos %}
    <input type="text" id="filtroAutos" class="form-control form-control-sm mb-2"
           placeholder="Filtrar la lista de autos..." autocomplete="off">
    <div style="max-height:220px; overflow-y:auto;">
      {% for v in vehiculos %}
        <div class="form-check fila-auto" data-texto="{{ (v.marca_auto ~ ' ' ~ v.modelo ~ ' ' ~ v.motor)|lower }}">
          <input class="form-check-input" type="checkbox" name="vehiculo_id" value="{{ v.id }}"
                 id="auto{{ v.id }}" {{ 'checked' if v.id in vehiculos_del_producto }}>
          <label class="form-check-label" for="auto{{ v.id }}">
            {{ v.marca_auto }} {{ v.modelo }} <span class="text-muted">{{ v.motor }}</span>
          </label>
        </div>
      {% endfor %}
    </div>
  {% else %}
    <p class="text-muted mb-0 small">
      Todavía no hay autos cargados. Cargalos en <a href="{{ url_for('vehiculos_lista') }}">Stock → Autos</a>
      y después volvé a vincularlos acá.
    </p>
  {% endif %}
</div>
```

Y cambiar el campo `marca` que ya existe para que sugiera las cargadas (sin dejar de aceptar una nueva):

```html
<input name="marca" class="form-control" list="marcasCargadas"
       value="{{ producto.marca if producto else '' }}">
<datalist id="marcasCargadas">
  {% for m in marcas %}<option value="{{ m }}"></option>{% endfor %}
</datalist>
```

En el bloque `{% block scripts %}`, agregar el filtro de la lista:

```javascript
// Filtrar la lista de autos a medida que se escribe. Con muchos autos
// cargados, buscar el correcto scrolleando no es viable.
const filtroAutos = document.getElementById('filtroAutos');
if (filtroAutos) {
  filtroAutos.addEventListener('input', function() {
    const texto = filtroAutos.value.trim().toLowerCase();
    document.querySelectorAll('.fila-auto').forEach(function(fila) {
      fila.style.display = (!texto || fila.dataset.texto.includes(texto)) ? '' : 'none';
    });
  });
}
```

**No agregar `required` a ninguno de estos campos.** La sección es opcional, y un `required` en una sección opcional es exactamente el bug ya documentado en `CLAUDE.md` que dejó esta misma pantalla sin poder guardarse: la validación nativa de HTML5 corre antes del evento `submit`, así que ningún listener puede rescatarlo.

- [ ] **Step 6: Correr los tests**

Run: `python -m pytest tests/test_producto_vehiculos.py -v`
Expected: PASS los 5.

- [ ] **Step 7: Probar en el navegador**

pytest no ve el JavaScript. Con `python app.py` levantado:

1. Ir a `/vehiculos` y cargar `FIAT / Palio / 1.4` y `VW / Gol / 1.6`.
2. Ir a `/productos/nuevo`, verificar que aparecen los dos autos con checkbox.
3. Escribir `gol` en "Filtrar la lista de autos" y verificar que queda solo el Gol.
4. Guardar el producto **sin tildar ningún auto** y sin tocar los precios por proveedor: tiene que guardar. (Si no guarda, hay un `required` de más — ver el paso anterior.)
5. Editarlo, tildar el Palio, guardar, volver a entrar: el Palio tiene que seguir tildado.

- [ ] **Step 8: Commit**

```bash
python -m pytest tests/ -v
git add core/app.py templates/producto_form.html tests/test_producto_vehiculos.py
git commit -m "Vincular autos compatibles desde la ficha del producto

La marca sigue siendo texto libre pero con las ya usadas sugeridas, y se
agrega sola a la tabla de marcas al guardar: sin pantalla de administración,
la lista del filtro no puede quedar desactualizada respecto de los productos.

La sección de autos es opcional y ningún campo lleva required — es el bug
ya documentado que dejó esta misma pantalla sin poder guardarse."
```

---

### Task 7: La barra de filtros en `/productos`

**Files:**
- Modify: `core/app.py` — `productos_lista()` (líneas 979-1015)
- Modify: `templates/productos.html`
- Test: `tests/test_filtros_productos.py`

**Interfaces:**
- Consumes: `db.buscar_productos()`, `db.facetas_productos()`, `db.sugerencias_busqueda()`, `db.obtener_vehiculos()`.
- Produces: `/productos` acepta `q`, `categoria`, `subcategoria`, `marca`, `vehiculo_id`, `solo_con_stock`.

- [ ] **Step 1: Escribir los tests**

Crear `tests/test_filtros_productos.py`:

```python
"""La pantalla de Stock con la barra de filtros. Lo que se prueba acá es que
la ruta pase los filtros a db.buscar_productos() y muestre lo que hay que
mostrar; el criterio de búsqueda en sí tiene sus propios tests."""
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
    assert "quisiste decir".encode() in respuesta.data
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
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_filtros_productos.py -v`
Expected: FAIL — los filtros nuevos se ignoran.

- [ ] **Step 3: Reescribir `productos_lista()` en `core/app.py`**

Reemplazar el cuerpo actual (líneas 979-1015) por:

```python
# Tope de filas dibujadas en Stock. Con los ~6.000 productos del catálogo
# real, dibujar la tabla entera cuelga el navegador. La pantalla avisa
# cuántos quedaron afuera en vez de aparentar que no hay más.
LIMITE_RESULTADOS = 200


@app.route("/productos")
def productos_lista():
    conn = db.get_connection()
    filtros = dict(
        q=request.args.get("q", "").strip() or None,
        categoria=request.args.get("categoria", "").strip() or None,
        subcategoria=request.args.get("subcategoria", "").strip() or None,
        marca=request.args.get("marca", "").strip() or None,
        vehiculo_id=a_entero(request.args.get("vehiculo_id")),
        solo_con_stock=request.args.get("solo_con_stock") == "1",
    )

    productos = db.buscar_productos(conn, limite=LIMITE_RESULTADOS, **filtros)
    facetas = db.facetas_productos(conn, **filtros)
    sugerencias = db.sugerencias_busqueda(conn, filtros["q"]) if not productos else []

    mejores_precios = {p["id"]: db.obtener_mejor_precio_por_producto(conn, p["id"]) for p in productos}
    contexto = dict(
        productos=productos,
        facetas=facetas,
        sugerencias=sugerencias,
        total=facetas["total"],
        limite=LIMITE_RESULTADOS,
        categorias=db.obtener_categorias(conn),
        subcategorias_json=subcategorias_por_categoria_json(conn),
        marcas=[m["nombre"] for m in conn.execute("SELECT nombre FROM marcas ORDER BY nombre")],
        vehiculos=db.obtener_vehiculos(conn),
        mejores_precios=mejores_precios,
        **filtros,
    )
    conn.close()
    return render_template("productos.html", **contexto)
```

- [ ] **Step 4: Reescribir la barra de filtros en `templates/productos.html`**

Reemplazar el `<form>` actual (líneas 9-34) por:

```html
<form class="row g-2 mb-2" method="get" id="filtroForm">
  <div class="col-md-3">
    <input type="text" name="q" id="qFiltro" value="{{ q or '' }}" class="form-control" autocomplete="off"
           placeholder="Buscar: pastilla palio, código, marca...">
  </div>
  <div class="col-md-2">
    <select name="categoria" id="categoriaFiltro" class="form-select">
      <option value="">Todos los rubros</option>
      {% for cat in categorias %}
        <option value="{{ cat }}" {{ 'selected' if categoria == cat }}>
          {{ cat }}{% if facetas.categoria.get(cat) %} ({{ facetas.categoria[cat] }}){% endif %}
        </option>
      {% endfor %}
    </select>
  </div>
  <div class="col-md-2">
    <select name="subcategoria" id="subcategoriaFiltro" class="form-select">
      <option value="">Todos los subrubros</option>
    </select>
  </div>
  <div class="col-md-2">
    <select name="marca" class="form-select" onchange="this.form.submit()">
      <option value="">Todas las marcas</option>
      {% for m in marcas %}
        <option value="{{ m }}" {{ 'selected' if marca == m }}>
          {{ m }}{% if facetas.marca.get(m) %} ({{ facetas.marca[m] }}){% endif %}
        </option>
      {% endfor %}
    </select>
  </div>
  <div class="col-md-2">
    <select name="vehiculo_id" class="form-select" onchange="this.form.submit()">
      <option value="">Todos los autos</option>
      {% for v in vehiculos %}
        <option value="{{ v.id }}" {{ 'selected' if vehiculo_id == v.id }}>
          {{ v.marca_auto }} {{ v.modelo }} {{ v.motor }}
        </option>
      {% endfor %}
    </select>
  </div>
  <div class="col-md-1 d-flex align-items-center">
    <div class="form-check">
      <input class="form-check-input" type="checkbox" name="solo_con_stock" value="1"
             id="soloConStock" {{ 'checked' if solo_con_stock }} onchange="this.form.submit()">
      <label class="form-check-label small" for="soloConStock">Con stock</label>
    </div>
  </div>
</form>

{% if q or categoria or subcategoria or marca or vehiculo_id or solo_con_stock %}
  <div class="mb-3 small">
    <span class="text-muted me-1">Filtrando por:</span>
    {% for etiqueta, parametro in [(q, 'q'), (categoria, 'categoria'), (subcategoria, 'subcategoria'), (marca, 'marca')] %}
      {% if etiqueta %}
        <span class="badge bg-secondary me-1">{{ etiqueta }}
          <a href="{{ url_for('productos_lista', **(request.args.to_dict() | reject_key(parametro))) }}"
             class="text-white text-decoration-none ms-1">&times;</a></span>
      {% endif %}
    {% endfor %}
    {% if vehiculo_id %}
      {% for v in vehiculos if v.id == vehiculo_id %}
        <span class="badge bg-secondary me-1">{{ v.marca_auto }} {{ v.modelo }} {{ v.motor }}
          <a href="{{ url_for('productos_lista', **(request.args.to_dict() | reject_key('vehiculo_id'))) }}"
             class="text-white text-decoration-none ms-1">&times;</a></span>
      {% endfor %}
    {% endif %}
    {% if solo_con_stock %}
      <span class="badge bg-secondary me-1">Sólo con stock
        <a href="{{ url_for('productos_lista', **(request.args.to_dict() | reject_key('solo_con_stock'))) }}"
           class="text-white text-decoration-none ms-1">&times;</a></span>
    {% endif %}
    <a href="{{ url_for('productos_lista') }}" class="ms-2">Limpiar todo</a>
  </div>
{% endif %}

{% if productos %}
  <p class="text-muted small">
    {% if total > limite %}
      Mostrando {{ limite }} de {{ total }} — afiná el filtro para verlos todos.
    {% else %}
      {{ total }} producto{{ 's' if total != 1 }}.
    {% endif %}
  </p>
{% elif sugerencias %}
  <div class="alert alert-warning">
    No hay resultados para "<strong>{{ q }}</strong>". ¿Quisiste decir?
    {% for s in sugerencias %}
      <a href="{{ url_for('productos_lista', q=s) }}" class="ms-1">{{ s }}</a>{{ "," if not loop.last }}
    {% endfor %}
  </div>
{% endif %}
```

Y borrar del `{% block scripts %}` el bloque de "Coincidencias en vivo" (líneas 109-136 del archivo actual): ese filtrado por JavaScript sobre las filas ya dibujadas deja de tener sentido cuando el servidor sólo manda 200 de 1.340 — filtraría sobre un subconjunto y mostraría "0 productos" habiendo resultados.

Reemplazarlo por el auto-envío del buscador de texto:

```javascript
// El buscador de texto espera a que deje de tipear antes de recargar, para
// no disparar una consulta por cada tecla.
let temporizador;
document.getElementById('qFiltro').addEventListener('input', function() {
  clearTimeout(temporizador);
  temporizador = setTimeout(function() { document.getElementById('filtroForm').submit(); }, 400);
});
document.getElementById('categoriaFiltro').addEventListener('change', function() {
  document.getElementById('subcategoriaFiltro').value = '';
  document.getElementById('filtroForm').submit();
});
document.getElementById('subcategoriaFiltro').addEventListener('change', function() {
  document.getElementById('filtroForm').submit();
});
```

Dejar el bloque de `actualizarSubcategoriasFiltro()` que ya existe (líneas 88-107): sigue haciendo falta para la cascada.

- [ ] **Step 5: Agregar el filtro `reject_key` de Jinja en `core/app.py`**

Al lado de los otros filtros de template (`money`, `url_imagen`):

```python
@app.template_filter("reject_key")
def reject_key(diccionario, clave):
    """Los mismos parámetros de la URL menos uno, para armar el link de la X
    de cada etiqueta de filtro sin perder los demás filtros puestos."""
    return {k: v for k, v in diccionario.items() if k != clave}
```

- [ ] **Step 6: Correr los tests**

Run: `python -m pytest tests/test_filtros_productos.py -v`
Expected: PASS los 7.

- [ ] **Step 7: Probar en el navegador**

pytest no ve el JavaScript. Con `python app.py`:

1. Cargar dos autos en `/vehiculos` y vincular uno a un producto.
2. En `/productos`, elegir un rubro: la pantalla tiene que recargarse sola, sin apretar nada.
3. Verificar que los rubros muestran el número al lado, y que al elegir uno los otros **siguen mostrando su número** (no caen a cero).
4. Verificar que el subrubro se repuebla al cambiar de rubro, y que cambiar de rubro no deja pegado el subrubro anterior.
5. Escribir `pastilla` y esperar: recarga sola después de dejar de tipear.
6. Verificar que la dirección de la página tiene los filtros (`?categoria=Frenos&...`) y que el botón "atrás" funciona.
7. Tocar la X de una etiqueta: saca ese filtro y **conserva los demás**.
8. Escribir `pastila` y verificar que aparece "¿Quisiste decir?" con el link.

- [ ] **Step 8: Commit**

```bash
python -m pytest tests/ -v
git add core/app.py templates/productos.html tests/test_filtros_productos.py
git commit -m "Filtrar el stock por rubro, subrubro, marca, auto y stock

Los filtros aplican solos y quedan en la URL, así el botón atrás funciona.
Cada opción muestra cuántos productos hay con los demás filtros aplicados,
para no mandar a un rubro vacío.

Se saca el filtrado por JavaScript sobre las filas ya dibujadas: con el
tope de 200 filas filtraría sobre un subconjunto y diría '0 productos'
habiendo resultados."
```

---

## Verificación final

- [ ] **Correr la suite completa**

Run: `python -m pytest tests/ -v`
Expected: PASS. Antes de este plan eran 183 tests; deberían ser ~222.

- [ ] **Probar el flujo completo en el navegador, de punta a punta**

Con `python app.py` y la base sembrada (`python scripts/seed_datos_prueba.py`):

1. `/vehiculos`: cargar `FIAT / Palio / 1.4`, `FIAT / Palio / Todos los motores` y `VW / Gol / 1.6`.
2. Verificar que cargar `FIAT / Palio / 1.4` de nuevo avisa que ya estaba, sin romperse.
3. `/productos/nuevo`: crear un producto con marca `Cobreq` y los dos Palio vinculados.
4. `/productos`: filtrar por auto `FIAT Palio 1.4` y verificar que aparece.
5. Verificar que `Cobreq` ya está en el desplegable de marcas sin haber tocado ninguna pantalla de marcas.
6. Buscar `palio pastilla` y `PALIO PASTILLA` y `pastila`: los tres tienen que servir de algo.
7. `/vehiculos`: intentar borrar el Palio 1.4 (está en uso) y verificar que avisa en vez de romperse; desactivarlo y verificar que desaparece del filtro de `/productos`.

- [ ] **Verificar que no se rompió el escaneo con la pistola**

Es la función que más usa el mostrador y toca los mismos productos.

1. En cualquier pantalla, escanear (o tipear muy rápido + Enter) un código de barras cargado: tiene que abrir el popup con el precio.
2. En `/ventas/nueva`, escanear: tiene que agregar el producto a la venta, no abrir el popup.

---

## Qué queda para el próximo plan

Las fases 3 a 6 de la spec, que se planifican cuando el hermano de Celes haya usado esta entrega:

- **Fase 3** — los mismos filtros en Nueva venta, vía `/api/buscar-productos`. Reemplaza el JSON con todos los productos embebido en el HTML, que con el catálogo real vuelve pesada esa pantalla.
- **Fase 4** — los mismos filtros en la tienda online.
- **Fase 5** — `scripts/detectar_vehiculos.py`: propone los autos leyendo la descripción del proveedor, con planilla de revisión.
- **Fase 6** — grupos de equivalencia entre marcas del mismo repuesto, con `scripts/proponer_equivalencias.py`.
