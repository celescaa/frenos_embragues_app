# Deploy en Vercel + Supabase Auth y Storage — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dejar el sistema desplegado y funcionando en Vercel, con las
credenciales en Supabase Auth y las fotos de producto en Supabase Storage —
lo único que falta para que deje de correr solo en la compu del local.

**Architecture:** Flask sigue siendo Flask y sigue manejando la sesión con su
cookie firmada; Supabase Auth pasa a ser únicamente el **almacén de
credenciales**. Como `verificar_sesion()` solo lee `usuario_id`, `usuario_rol`
y `debe_cambiar_password` de la sesión, mientras esas tres claves se sigan
poblando el resto del sistema (protección global de rutas, `es_admin()`,
`inject_usuario()`, los 30+ templates) no se entera del cambio. El alcance real
son 4 pantallas. Las fotos dejan el disco y pasan a un bucket público, con las
dos funciones existentes conservando su firma.

**Tech Stack:** Flask, psycopg 3, Postgres/Supabase, `supabase` 2.31 (cliente
Python), Werkzeug `ProxyFix`, Vercel (plan Hobby).

**Spec:** `docs/superpowers/specs/2026-08-13-migracion-vercel-supabase-design.md`
— secciones 1 (Infraestructura), 3 (Autenticación) y 4 (Fotos, scripts y
verificación). El Plan 1 (`2026-08-13-migracion-postgres.md`) ya está ejecutado
y mergeado; este plan arranca sobre esa base.

## Global Constraints

Copiadas del spec y del estado real del código. **Todas las tareas están
sujetas a esta sección.**

- **La sesión de Flask no cambia de forma.** `verificar_sesion()`
  (`core/app.py:114`) lee `session["usuario_id"]`, `session["usuario_rol"]` y
  `session["debe_cambiar_password"]`. Ninguna tarea puede cambiar esos nombres
  ni sus tipos: `usuario_id` es el UUID **como string**, `usuario_rol` es
  `"admin"` o `"empleado"`, `debe_cambiar_password` es un bool.
- **Supabase Auth guarda email y contraseña. Todo lo demás sigue en la tabla
  `usuarios`**: `username`, `nombre`, `rol`, `activo`,
  `debe_cambiar_password`, `intentos_fallidos`, `bloqueado_hasta`.
- **`usuarios.id` es UUID y pasa a ser el mismo id que `auth.users.id`.** Ya es
  `UUID PRIMARY KEY DEFAULT gen_random_uuid()` desde el Plan 1
  (`supabase/migrations/20260813145208_esquema_inicial.sql:218`); lo que se
  agrega es la clave foránea a `auth.users(id)`.
- **El mensaje de error del login tiene que ser idéntico** cuando el usuario no
  existe y cuando la contraseña está mal: `"Usuario o contraseña incorrectos."`
  Cualquier diferencia permite enumerar qué usuarios existen. Esto **ya está
  así** en `core/app.py:183` y `:186` — no romperlo.
- **Se conservan las tres cosas que Supabase no trae**: bloqueo por 5 intentos
  fallidos durante 15 minutos (`LOCKOUT_INTENTOS` / `LOCKOUT_MINUTOS`), cambio
  de contraseña obligatorio (`debe_cambiar_password`), y los roles
  `admin`/`empleado`.
- **`SUPABASE_SERVICE_ROLE_KEY` es solo del servidor.** Saltea todas las
  políticas de la base. Nunca se manda a un template, nunca se loguea, nunca se
  commitea. Solo la usan las operaciones de `/usuarios`.
- **La plata sigue siendo `Decimal`.** Vale todo lo del Plan 1: nunca `float()`
  en una columna NUMERIC, siempre `a_decimal()`. Un id que viene de un
  formulario pasa por `a_entero()`.
- **`prepare_threshold=None` sigue siendo obligatorio** en cualquier conexión
  psycopg (`core/database.py:get_connection`). El pooler de Supabase en modo
  transacción no soporta prepared statements.
- **API real del cliente `supabase` 2.31**, verificada contra el Supabase local
  el 13/08/2026 (no copiar de la documentación, que muestra TypeScript):
  - `create_client(url, key) -> Client`
  - `client.auth.sign_in_with_password({"email": ..., "password": ...})` →
    objeto con `.user.id` (str UUID). Con credenciales inválidas **lanza**
    `supabase_auth.errors.AuthApiError` (mensaje `"Invalid login credentials"`,
    `code="invalid_credentials"`).
  - `admin.auth.admin.create_user({"email":..., "password":..., "email_confirm": True})`
    → objeto con `.user.id`. Sin `email_confirm: True` el usuario queda sin
    confirmar y no puede entrar.
  - `admin.auth.admin.update_user_by_id(uid: str, attributes: dict)`
  - `admin.auth.admin.delete_user(id: str, should_soft_delete: bool = False)`
  - `admin.auth.admin.list_users(page=None, per_page=None) -> List[User]`
  - La excepción se importa así: `from supabase_auth.errors import AuthApiError`
- **Toda migración de esquema es un archivo nuevo en `supabase/migrations/`**,
  nunca una edición del archivo existente: la migración inicial ya está
  aplicada en la nube (`pjjorgruhvamqbluanen`) y editarla la dejaría fuera de
  sincronía. Nombre: `<timestamp>_<descripcion>.sql`.
- **La suite se corre con `python -m pytest tests/ -v`** contra el Postgres
  local (`npx supabase start`). `tests/conftest.py` corta con un mensaje claro
  si la base del puerto no es la de este proyecto. Al terminar cada tarea la
  suite tiene que estar **entera en verde**, no solo los tests nuevos.
- **Los tests de autenticación corren contra el Supabase Auth local** (el que
  levanta `npx supabase start` en `http://127.0.0.1:54321`), no contra mocks:
  un mock del cliente de Supabase no probaría nada de lo que esta migración
  cambia.

---

## File Structure

| Archivo | Responsabilidad | Tarea |
|---|---|---|
| `vercel.json` (crear) | Región `gru1`, `maxDuration`, exclusiones del bundle | 1 |
| `core/app.py` (modificar) | `SECRET_KEY` de entorno, `ProxyFix`, cookies seguras | 1 |
| `core/supabase_auth.py` (crear) | Único punto de contacto con Supabase Auth | 3 |
| `supabase/migrations/*_auth.sql` (crear) | `email`, FK a `auth.users`, `password_hash` nullable | 2 |
| `supabase/migrations/*_drop_password_hash.sql` (crear) | Borra `password_hash` | 6 |
| `core/app.py` — `/login`, `/logout` | Login por usuario o email | 3 |
| `core/app.py` — `/cambiar-password` | Cambio de contraseña vía Supabase | 4 |
| `core/app.py` — `/usuarios/*` | Alta, edición, reseteo y baja vía admin API | 5 |
| `core/almacenamiento.py` (crear) | Subida/borrado/URL pública en Storage | 7 |
| `core/app.py` — funciones de imagen | Delegan en `almacenamiento.py` | 7 |
| `templates/{productos,tienda_catalogo,producto_form,compra_importar_factura}.html` | Línea del `src` de la imagen | 7 |
| `tests/conftest.py` | Fixtures de usuario contra Supabase Auth local | 2 |
| `tests/test_auth_supabase.py` (crear) | Login, bloqueo, cambio de contraseña, /usuarios | 3-5 |
| `tests/test_almacenamiento.py` (crear) | Fotos contra Storage local | 7 |
| `.env.example`, `README.md`, `CLAUDE.md`, `docs/DOCUMENTACION_TECNICA.md` | Documentación | 8 |

**Por qué `core/supabase_auth.py` y `core/almacenamiento.py` son archivos
propios y no código suelto en `core/app.py`:** `core/app.py` ya tiene ~2500
líneas. Además son los dos únicos puntos donde el sistema habla con un servicio
externo por red, y el resto del código no debería enterarse de eso — mismo
criterio que ya siguen `facturacion_afip.py` y `tienda_pagos.py`.

---

## Task 1: Configuración para Vercel

Infraestructura de despliegue. No toca ninguna lógica de negocio.

**Files:**
- Create: `vercel.json`
- Modify: `core/app.py:42-70` (bloque de `secret_key` y config de cookies)
- Test: `tests/test_configuracion.py` (crear)

**Interfaces:**
- Consumes: nada de tareas anteriores.
- Produces: `app` con `ProxyFix` aplicado y `SECRET_KEY` leída del entorno.
  Las tareas siguientes no dependen de esto.

**Contexto que el implementador necesita:**

Hoy `core/app.py:45-52` genera la clave de sesión y la guarda en un archivo
`.secret_key` en la raíz del proyecto. En Vercel no hay disco persistente: cada
invocación arrancaría con una clave nueva y **todas las sesiones se caerían en
cada cold start**. Tiene que venir de la variable de entorno `SECRET_KEY`.

Para desarrollo local se conserva el comportamiento de archivo, para no obligar
a Celes a definir la variable a mano cada vez que corre `python app.py`.

- [ ] **Step 1: Escribir el test que falla**

`tests/test_configuracion.py`:

```python
"""Configuración de despliegue: clave de sesión, proxy y cookies.

En Vercel no hay disco persistente ni conexión directa del navegador: la app
corre detrás de un proxy y se reinicia seguido. Estos tests fijan las tres
consecuencias de eso.
"""
import importlib
import os

import pytest


def test_la_clave_de_sesion_sale_del_entorno_si_esta_definida(monkeypatch):
    """En producción la clave NO puede salir de un archivo: cada cold start
    generaría una distinta y tiraría abajo todas las sesiones abiertas."""
    monkeypatch.setenv("SECRET_KEY", "clave-de-prueba-no-secreta")
    import core.app
    modulo = importlib.reload(core.app)
    assert modulo.app.secret_key == "clave-de-prueba-no-secreta"


def test_la_app_confia_en_los_headers_del_proxy():
    """Vercel termina el HTTPS en su proxy y reenvía por HTTP. Sin ProxyFix,
    `request.host` sale del header Host crudo (falsificable) y url_for arma
    URLs http:// en un sitio https://."""
    from core.app import app
    assert not isinstance(app.wsgi_app, type(app.__class__.wsgi_app)), \
        "wsgi_app sigue siendo el original: falta envolverlo con ProxyFix"
    assert app.wsgi_app.__class__.__name__ == "ProxyFix"


def test_la_cookie_de_sesion_es_segura_cuando_hay_https(monkeypatch):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "1")
    import core.app
    modulo = importlib.reload(core.app)
    assert modulo.app.config["SESSION_COOKIE_SECURE"] is True
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_configuracion.py -v`
Expected: FAIL — `SECRET_KEY` se ignora, `wsgi_app` no es `ProxyFix`, y
`SESSION_COOKIE_SECURE` no existe en la config.

- [ ] **Step 3: Implementar en `core/app.py`**

Reemplazar el bloque de `core/app.py:42-52` por:

```python
# La clave de sesión sale de la variable de entorno SECRET_KEY. En Vercel eso
# no es opcional: no hay disco persistente, así que un archivo se regeneraría
# en cada cold start y tiraría abajo todas las sesiones abiertas.
#
# Corriendo local se conserva el archivo de siempre, para no tener que definir
# la variable a mano en cada `python app.py`.
_SECRET_KEY_ENV = os.environ.get("SECRET_KEY")
if _SECRET_KEY_ENV:
    app.secret_key = _SECRET_KEY_ENV
else:
    _SECRET_KEY_PATH = os.path.join(PROJECT_ROOT, ".secret_key")
    if os.path.exists(_SECRET_KEY_PATH):
        with open(_SECRET_KEY_PATH) as _f:
            app.secret_key = _f.read().strip()
    else:
        app.secret_key = secrets.token_hex(32)
        with open(_SECRET_KEY_PATH, "w") as _f:
            _f.write(app.secret_key)
```

Reemplazar la línea comentada de `core/app.py:68-69` por:

```python
# HTTPS lo provee Vercel. Se activa por variable de entorno en vez de estar
# fijo, porque corriendo local (http://127.0.0.1:5050) una cookie "secure"
# no viajaría nunca y no se podría iniciar sesión.
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE") == "1"
```

Y al final del bloque de configuración, después de `csrf = CSRFProtect(app)`:

```python
# Vercel pone la aplicación detrás de un proxy que termina el HTTPS y reenvía
# por HTTP. Sin esto, `request.host` sale del header Host crudo -- que el
# cliente puede falsificar, y que `manejar_csrf_error` usa para su chequeo de
# mismo origen -- y `url_for(_external=True)` arma URLs http:// en un sitio
# https://. Un solo proxy de confianza: el de Vercel.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
```

Con el import correspondiente arriba: `from werkzeug.middleware.proxy_fix import ProxyFix`

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/test_configuracion.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Sacar la siembra de datos de ejemplo del arranque**

`core/app.py:95-100` llama a `db.seed_demo_data()` **al importar el módulo**,
o sea en cada arranque en frío de una función serverless. Son dos problemas
distintos y el segundo es grave:

1. Una conexión y unas consultas de más en cada cold start, justo en la
   petición que ya es la más lenta.
2. `seed_demo_data()` es idempotente respecto de "ya hay productos", pero una
   base de **producción recién creada está vacía** — que es exactamente su
   condición de disparo. El primer visitante del sistema real le sembraría a
   la base del negocio 5 clientes, 14 productos y 45 ventas de mentira.

Se mueve al bloque `__main__`, que solo corre con `python app.py` y nunca bajo
Vercel ni gunicorn. Local sigue funcionando igual que siempre.

Borrar las líneas 88-100 y agregar al bloque `if __name__ == "__main__":` del
final del archivo, antes de `app.run(...)`:

```python
    # Los datos de ejemplo se siembran solo al correr `python app.py` a mano.
    # NO puede ir a nivel de módulo: ahí se ejecutaría en cada arranque en
    # frío de Vercel, y como su condición es "la base está vacía" -- que es
    # justo el estado de una base de producción recién creada -- le sembraría
    # productos y ventas de mentira a la base del negocio.
    _conn_seed = db.get_connection()
    try:
        db.seed_demo_data(_conn_seed)
        _conn_seed.commit()
    finally:
        _conn_seed.close()
```

Test, en `tests/test_configuracion.py`:

```python
def test_importar_la_app_no_siembra_datos_de_ejemplo(db_conn):
    """En serverless el módulo se importa en cada arranque en frío, y una base
    de producción recién creada está vacía: sembrar ahí le metería productos y
    ventas de mentira al negocio."""
    db_conn.execute("TRUNCATE TABLE venta_items, ventas, productos CASCADE")
    db_conn.commit()

    import core.app
    importlib.reload(core.app)

    cuantos = db_conn.execute("SELECT COUNT(*) AS c FROM productos").fetchone()["c"]
    assert cuantos == 0, "importar core.app sembró datos de ejemplo"
```

- [ ] **Step 6: Crear `vercel.json`**

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "regions": ["gru1"],
  "functions": {
    "app.py": {
      "runtime": "python3.12",
      "maxDuration": 300,
      "excludeFiles": "{scripts,docs,plantillas,listas_proveedores,tests,supabase}/**"
    }
  }
}
```

`"regions": ["gru1"]` es São Paulo, la misma región donde está la base. **No es
un detalle de estilo**: Vercel corre las funciones en Washington por defecto, y
lo que determina la latencia es la distancia entre la función y la base, no
entre el usuario y la base. Cada pantalla del sistema hace varias consultas.
El plan Hobby permite una sola región, que es justo lo que hace falta.

`static/` **no** se excluye: Flask lo sigue sirviendo (CSS y logo).

- [ ] **Step 7: Correr la suite entera**

Run: `python -m pytest tests/ -v`
Expected: PASS — 144 de antes + 4 nuevos = 148.

- [ ] **Step 8: Commit**

```bash
git add vercel.json core/app.py tests/test_configuracion.py
git commit -m "Configurar la app para correr detrás del proxy de Vercel"
```

---

## Task 2: Migración de esquema para Supabase Auth

Migración **aditiva a propósito**: agrega lo que hace falta pero todavía no
borra `password_hash`, así el login viejo sigue funcionando hasta que la
Tarea 3 lo reemplace. Cada tarea tiene que dejar el sistema andando.

**Files:**
- Create: `supabase/migrations/<timestamp>_usuarios_supabase_auth.sql`
- Modify: `tests/conftest.py`
- Test: `tests/test_esquema.py` (agregar casos)

**Interfaces:**
- Produces:
  - Columna `usuarios.email TEXT UNIQUE` (nullable por ahora: los usuarios
    que ya existan no tienen email).
  - FK `usuarios.id → auth.users(id) ON DELETE CASCADE`.
  - `usuarios.password_hash` pasa a **nullable** (los usuarios nuevos creados
    vía Supabase Auth no van a tener uno).
  - Fixture `usuario_supabase` en `conftest.py`, que crea un usuario en
    Supabase Auth **y** su fila en `usuarios`, y lo limpia al terminar.

**Contexto que el implementador necesita:**

`auth.users` es un esquema que administra Supabase, ya existe en la base local
(lo crea `npx supabase start`) y en la nube. La FK garantiza que no queden
perfiles huérfanos: si se borra la cuenta en Supabase Auth, se borra el perfil.

**Ojo con el orden de la FK:** `usuarios.id` hoy tiene
`DEFAULT gen_random_uuid()`. Ese default se **saca** en esta migración: a
partir de ahora el id siempre lo provee `auth.users`, nunca se inventa. Si se
dejara, alguien podría insertar un perfil con un id que no existe en
`auth.users` y la FK lo rechazaría con un error confuso.

- [ ] **Step 1: Escribir la migración**

`supabase/migrations/<timestamp>_usuarios_supabase_auth.sql` (usar el timestamp
real: `date -u +%Y%m%d%H%M%S`):

```sql
-- Supabase Auth pasa a ser el almacén de credenciales. La tabla usuarios
-- queda como el "perfil": username, nombre, rol, activo y las tres cosas que
-- Supabase no trae (cambio obligatorio de contraseña, intentos fallidos,
-- bloqueo temporal).
--
-- Migración aditiva a propósito: password_hash se hace nullable pero NO se
-- borra todavía, así el login actual sigue funcionando hasta que el código
-- pase a Supabase Auth. Lo borra una migración posterior.

-- El email vive en auth.users, pero se copia acá para poder resolver
-- "usuario o email" en el login con una sola consulta a nuestra base, sin
-- pedirle a Supabase que liste usuarios en cada intento.
ALTER TABLE usuarios ADD COLUMN email TEXT;
ALTER TABLE usuarios ADD CONSTRAINT usuarios_email_key UNIQUE (email);

-- El id ya era UUID; ahora es el MISMO id que auth.users. Se saca el default:
-- un perfil sin cuenta detrás no tiene sentido, y dejar el default invitaría
-- a crear uno con un id inventado que la FK rechazaría con un error confuso.
ALTER TABLE usuarios ALTER COLUMN id DROP DEFAULT;
ALTER TABLE usuarios
    ADD CONSTRAINT usuarios_id_fkey
    FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE;

-- Los usuarios creados vía Supabase Auth no tienen hash propio.
ALTER TABLE usuarios ALTER COLUMN password_hash DROP NOT NULL;
```

- [ ] **Step 2: Aplicar y verificar que corre limpia**

Run: `npx supabase db reset`
Expected: aplica las dos migraciones sin error.

- [ ] **Step 3: Escribir el fixture en `tests/conftest.py`**

Agregar al final del archivo:

```python
SUPABASE_URL_TEST = os.environ.get("SUPABASE_URL_TEST", "http://127.0.0.1:54321")
SUPABASE_SERVICE_KEY_TEST = os.environ.get(
    "SUPABASE_SERVICE_ROLE_KEY_TEST", "sb_secret_N7UND0UgjKTVK-Uodkm0Hg_xSvEMPvz"
)


@pytest.fixture
def crear_usuario(db_conn):
    """Crea un usuario completo: la cuenta en Supabase Auth (donde viven email
    y contraseña) más su fila en `usuarios` (el perfil).

    Contra el Supabase Auth LOCAL, no contra un mock: lo que esta migración
    cambia es justamente el diálogo con ese servicio, así que un mock no
    probaría nada. `email_confirm=True` es obligatorio -- sin eso la cuenta
    queda sin confirmar y no puede iniciar sesión.
    """
    from supabase import create_client

    admin = create_client(SUPABASE_URL_TEST, SUPABASE_SERVICE_KEY_TEST)
    creados = []

    def _crear(username, password="clave-de-prueba-123", rol="empleado",
               nombre="Usuario Test", activo=True, debe_cambiar_password=False,
               email=None):
        email = email or f"{username}@ejemplo.test"
        cuenta = admin.auth.admin.create_user(
            {"email": email, "password": password, "email_confirm": True}
        )
        usuario_id = cuenta.user.id
        creados.append(usuario_id)
        db_conn.execute(
            """INSERT INTO usuarios (id, username, email, nombre, rol, activo,
                                     debe_cambiar_password)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (usuario_id, username, email, nombre, rol, activo, debe_cambiar_password),
        )
        db_conn.commit()
        return {"id": usuario_id, "username": username, "email": email,
                "password": password, "rol": rol}

    yield _crear

    for usuario_id in creados:
        try:
            admin.auth.admin.delete_user(usuario_id)
        except Exception:
            pass  # el test pudo haberlo borrado ya
```

**Importante:** el fixture `_limpiar_base_de_pruebas` que ya existe hace
TRUNCATE de `usuarios`, pero eso **no borra la cuenta en Supabase Auth** — por
eso este fixture lleva su propia limpieza. Sin ella, la segunda corrida de la
suite fallaría con "email ya registrado".

- [ ] **Step 4: Escribir el test de esquema**

Agregar a `tests/test_esquema.py`:

```python
def test_usuarios_cuelga_de_auth_users(db_conn):
    """Un perfil sin cuenta detrás no debe poder existir."""
    import psycopg
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db_conn.execute(
            """INSERT INTO usuarios (id, username, nombre, rol)
               VALUES (gen_random_uuid(), 'huerfano', 'Sin cuenta', 'empleado')"""
        )


def test_el_perfil_se_borra_junto_con_la_cuenta(db_conn, crear_usuario):
    """ON DELETE CASCADE: borrar la cuenta en Supabase Auth no puede dejar un
    perfil colgado apuntando a un id que ya no existe."""
    from supabase import create_client
    from tests.conftest import SUPABASE_URL_TEST, SUPABASE_SERVICE_KEY_TEST

    usuario = crear_usuario("para_borrar")
    admin = create_client(SUPABASE_URL_TEST, SUPABASE_SERVICE_KEY_TEST)
    admin.auth.admin.delete_user(usuario["id"])

    fila = db_conn.execute(
        "SELECT id FROM usuarios WHERE id=%s", (usuario["id"],)
    ).fetchone()
    assert fila is None
```

- [ ] **Step 5: Agregar `supabase` a `requirements.txt`**

```
supabase>=2.31,<3
```

- [ ] **Step 6: Correr la suite entera**

Run: `python -m pytest tests/ -v`
Expected: PASS — todo lo anterior sigue verde (el login viejo no se tocó) más
los 2 tests nuevos.

- [ ] **Step 7: Commit**

```bash
git add supabase/migrations tests/conftest.py tests/test_esquema.py requirements.txt
git commit -m "Ligar la tabla usuarios a las cuentas de Supabase Auth"
```

---

## Task 3: Login con Supabase Auth, por usuario o email

El corazón del cambio.

**Files:**
- Create: `core/supabase_auth.py`
- Modify: `core/app.py:140-215` (`login()` y `logout()`)
- Test: `tests/test_auth_supabase.py` (crear)

**Interfaces:**
- Consumes: la columna `usuarios.email` y el fixture `crear_usuario` (Tarea 2).
- Produces, en `core/supabase_auth.py`:
  - `cliente_publico() -> Client`
  - `cliente_admin() -> Client`
  - `verificar_credenciales(email: str, password: str) -> str | None` —
    devuelve el id (UUID string) si son válidas, `None` si no. **Nunca lanza.**
  - `configurado() -> bool`

**Contexto que el implementador necesita:**

El flujo del login queda así, y el orden importa:

1. Se recibe un solo campo (`username` en el formulario, que puede tener un
   nombre de usuario o un email).
2. Si contiene `@`, es un email; si no, se busca en `usuarios` la fila con ese
   `username` para obtener su email.
3. **Se chequea el bloqueo por intentos fallidos ANTES de llamar a Supabase.**
   Si no, una cuenta bloqueada seguiría consumiendo intentos contra el servicio
   externo, que además tiene su propio rate limiting y podría bloquearnos a
   nosotros.
4. Se llama a Supabase Auth con el email real.
5. Se actualizan `intentos_fallidos` / `bloqueado_hasta` en **nuestra** tabla.

**El mensaje de error es el mismo en todos los casos de fallo**, incluido
"ese username no existe". Ver Global Constraints.

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_auth_supabase.py`:

```python
"""Login contra Supabase Auth, entrando por nombre de usuario o por email.

Contra el Supabase Auth local que levanta `npx supabase start`, no contra
mocks: lo que cambia acá es justamente el diálogo con ese servicio.
"""
import pytest

from core.app import app as flask_app


@pytest.fixture
def cliente():
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as c:
        yield c


def test_se_puede_entrar_con_el_nombre_de_usuario(cliente, crear_usuario):
    usuario = crear_usuario("matias", password="clave-correcta-123")
    respuesta = cliente.post(
        "/login", data={"username": "matias", "password": "clave-correcta-123"},
        follow_redirects=False,
    )
    assert respuesta.status_code == 302
    with cliente.session_transaction() as sesion:
        assert sesion["usuario_id"] == usuario["id"]
        assert sesion["usuario_rol"] == "empleado"


def test_se_puede_entrar_con_el_email(cliente, crear_usuario):
    """Supabase Auth se basa en email; el sistema tiene que aceptar los dos."""
    usuario = crear_usuario("matias", password="clave-correcta-123")
    respuesta = cliente.post(
        "/login", data={"username": usuario["email"], "password": "clave-correcta-123"},
    )
    assert respuesta.status_code == 302
    with cliente.session_transaction() as sesion:
        assert sesion["usuario_id"] == usuario["id"]


def test_la_contrasena_incorrecta_no_inicia_sesion(cliente, crear_usuario):
    crear_usuario("matias", password="clave-correcta-123")
    respuesta = cliente.post(
        "/login", data={"username": "matias", "password": "clave-equivocada"},
    )
    assert respuesta.status_code == 200
    with cliente.session_transaction() as sesion:
        assert "usuario_id" not in sesion


def test_el_error_no_revela_si_el_usuario_existe(cliente, crear_usuario):
    """Mensajes distintos permitirían averiguar qué usuarios hay cargados
    probando nombres, que es el paso previo a atacar sus contraseñas."""
    crear_usuario("matias", password="clave-correcta-123")
    con_usuario_real = cliente.post(
        "/login", data={"username": "matias", "password": "mal"}
    ).data
    con_usuario_inventado = cliente.post(
        "/login", data={"username": "no_existe_nadie_asi", "password": "mal"}
    ).data
    assert b"Usuario o contra" in con_usuario_real
    assert con_usuario_real == con_usuario_inventado


def test_el_usuario_inactivo_no_puede_entrar(cliente, crear_usuario):
    crear_usuario("baja", password="clave-correcta-123", activo=False)
    cliente.post("/login", data={"username": "baja", "password": "clave-correcta-123"})
    with cliente.session_transaction() as sesion:
        assert "usuario_id" not in sesion


def test_se_bloquea_tras_cinco_intentos_fallidos(cliente, crear_usuario, db_conn):
    """El bloqueo es nuestro, no de Supabase: se conserva tal cual estaba."""
    usuario = crear_usuario("matias", password="clave-correcta-123")
    for _ in range(5):
        cliente.post("/login", data={"username": "matias", "password": "mal"})

    fila = db_conn.execute(
        "SELECT intentos_fallidos, bloqueado_hasta FROM usuarios WHERE id=%s",
        (usuario["id"],),
    ).fetchone()
    assert fila["intentos_fallidos"] >= 5
    assert fila["bloqueado_hasta"] is not None

    # Y con la contraseña BUENA tampoco entra mientras dure el bloqueo.
    cliente.post("/login", data={"username": "matias", "password": "clave-correcta-123"})
    with cliente.session_transaction() as sesion:
        assert "usuario_id" not in sesion


def test_un_login_exitoso_limpia_los_intentos_fallidos(cliente, crear_usuario, db_conn):
    usuario = crear_usuario("matias", password="clave-correcta-123")
    cliente.post("/login", data={"username": "matias", "password": "mal"})
    cliente.post("/login", data={"username": "matias", "password": "clave-correcta-123"})
    fila = db_conn.execute(
        "SELECT intentos_fallidos FROM usuarios WHERE id=%s", (usuario["id"],)
    ).fetchone()
    assert fila["intentos_fallidos"] == 0
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_auth_supabase.py -v`
Expected: FAIL — el login actual valida contra `password_hash`, y el fixture
`crear_usuario` no escribe esa columna, así que ningún login prospera.

- [ ] **Step 3: Escribir `core/supabase_auth.py`**

```python
"""Único punto de contacto con Supabase Auth.

Supabase Auth guarda email y contraseña; todo lo demás (username, nombre, rol,
bloqueo por intentos, cambio obligatorio de contraseña) sigue en la tabla
`usuarios` de este sistema. Flask sigue manejando la sesión con su cookie
firmada, así que la protección CSRF queda intacta.

Mismo criterio defensivo que `facturacion_afip.py` y `tienda_pagos.py`: las
funciones de acá no dejan escapar excepciones de red o de configuración. Un
login que falla tiene que mostrar "usuario o contraseña incorrectos", no una
página de error.
"""
import os

from supabase import Client, create_client
from supabase_auth.errors import AuthApiError

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def configurado():
    return bool(SUPABASE_URL and SUPABASE_ANON_KEY)


def cliente_publico() -> Client:
    """Cliente con la clave pública: solo sirve para iniciar sesión."""
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def cliente_admin() -> Client:
    """Cliente con la clave de servicio, que SALTEA todas las políticas de la
    base. Solo para las operaciones de /usuarios (alta, reseteo, baja), nunca
    en un camino que toque el navegador."""
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def verificar_credenciales(email, password):
    """Devuelve el id (UUID como string) si el email y la contraseña son
    correctos, o None en cualquier otro caso.

    Nunca lanza: quien llama solo necesita saber si entró o no, y cualquier
    distinción entre "contraseña mal" y "Supabase no responde" filtrada al
    usuario sería información de más.
    """
    if not configurado():
        return None
    try:
        respuesta = cliente_publico().auth.sign_in_with_password(
            {"email": email, "password": password}
        )
    except AuthApiError:
        return None
    except Exception:
        return None
    return respuesta.user.id if respuesta and respuesta.user else None
```

- [ ] **Step 4: Reescribir `login()` en `core/app.py`**

Reemplazar el cuerpo del `if request.method == "POST":` de `login()`
(`core/app.py:145-205`) por:

```python
    if request.method == "POST":
        identificador = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = db.get_connection()

        # Se admite entrar con el nombre de usuario o con el email. Supabase
        # Auth solo entiende de emails, así que un username se traduce contra
        # nuestra propia tabla antes de preguntarle a Supabase.
        if "@" in identificador:
            usuario = conn.execute(
                "SELECT * FROM usuarios WHERE email = %s", (identificador,)
            ).fetchone()
        else:
            usuario = conn.execute(
                "SELECT * FROM usuarios WHERE username = %s", (identificador,)
            ).fetchone()

        # El bloqueo se chequea ANTES de hablar con Supabase: una cuenta
        # bloqueada no tiene que seguir gastando intentos contra un servicio
        # externo que además tiene su propio rate limiting.
        if usuario and usuario["bloqueado_hasta"]:
            bloqueado_hasta = usuario["bloqueado_hasta"]
            ahora = datetime.now(timezone.utc)
            if ahora < bloqueado_hasta:
                minutos = int((bloqueado_hasta - ahora).total_seconds() // 60) + 1
                flash(f"Demasiados intentos fallidos. Probá de nuevo en {minutos} minuto(s).", "danger")
                conn.close()
                return render_template("login.html")
            conn.execute("UPDATE usuarios SET intentos_fallidos=0, bloqueado_hasta=NULL WHERE id=%s", (usuario["id"],))
            conn.commit()
            usuario = conn.execute("SELECT * FROM usuarios WHERE id=%s", (usuario["id"],)).fetchone()

        # Solo se le pregunta a Supabase si el perfil existe y está activo.
        id_verificado = None
        if usuario and usuario["activo"] and usuario["email"]:
            id_verificado = supabase_auth.verificar_credenciales(usuario["email"], password)

        if not id_verificado or str(id_verificado) != str(usuario["id"]):
            # Mismo mensaje exista o no el usuario: cualquier diferencia
            # permitiría averiguar qué cuentas hay probando nombres.
            if usuario and usuario["activo"]:
                intentos = usuario["intentos_fallidos"] + 1
                if intentos >= LOCKOUT_INTENTOS:
                    bloqueado_hasta = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTOS)
                    conn.execute(
                        "UPDATE usuarios SET intentos_fallidos=%s, bloqueado_hasta=%s WHERE id=%s",
                        (intentos, bloqueado_hasta, usuario["id"]),
                    )
                    flash(f"Demasiados intentos fallidos. La cuenta queda bloqueada {LOCKOUT_MINUTOS} minutos.", "danger")
                else:
                    conn.execute("UPDATE usuarios SET intentos_fallidos=%s WHERE id=%s", (intentos, usuario["id"]))
                    flash("Usuario o contraseña incorrectos.", "danger")
                conn.commit()
            else:
                flash("Usuario o contraseña incorrectos.", "danger")
            conn.close()
            return render_template("login.html")

        conn.execute("UPDATE usuarios SET intentos_fallidos=0, bloqueado_hasta=NULL WHERE id=%s", (usuario["id"],))
        conn.commit()
        conn.close()

        session.clear()
        session.permanent = True
        session["usuario_id"] = str(usuario["id"])
        session["usuario_nombre"] = usuario["nombre"]
        session["usuario_rol"] = usuario["rol"]
        session["debe_cambiar_password"] = bool(usuario["debe_cambiar_password"])

        if usuario["debe_cambiar_password"]:
            return redirect(url_for("cambiar_password"))
        flash(f"Bienvenido, {usuario['nombre']}.", "success")
        siguiente = request.args.get("next")
        return redirect(siguiente or url_for("dashboard"))
```

Agregar el import: `from . import supabase_auth`

**`logout()` no cambia**: la sesión es de Flask, así que `session.clear()`
sigue siendo todo lo que hace falta. No se llama a `sign_out()` de Supabase
porque este sistema nunca guarda el token de Supabase — usa el servicio solo
para verificar la contraseña en el momento del login.

- [ ] **Step 5: Actualizar la etiqueta del formulario**

En `templates/login.html`, cambiar la etiqueta del campo por
`Usuario o email` (el `name="username"` **no cambia**, para no tocar nada más).

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/test_auth_supabase.py -v`
Expected: PASS (7 tests)

- [ ] **Step 7: Correr la suite entera**

Run: `python -m pytest tests/ -v`
Expected: los tests viejos que creaban usuarios con `password_hash` y esperaban
poder loguearse **van a fallar**. Hay que migrarlos al fixture `crear_usuario`.
El más probable es `test_login_bloquea_tras_5_intentos_y_no_revienta_al_leer_el_bloqueo`
en `tests/test_tienda_panel.py`, que ahora queda cubierto por
`test_se_bloquea_tras_cinco_intentos_fallidos`: **borrarlo en vez de
duplicarlo.** Los fixtures `client_admin` que solo inyectan la sesión a mano
(sin pasar por `/login`) siguen funcionando sin cambios.

- [ ] **Step 8: Commit**

```bash
git add core/supabase_auth.py core/app.py templates/login.html tests/
git commit -m "Validar las contraseñas contra Supabase Auth"
```

---

## Task 4: Cambio de contraseña con Supabase Auth

**Files:**
- Modify: `core/app.py:217-250` (`cambiar_password()`), `core/supabase_auth.py`
- Test: `tests/test_auth_supabase.py` (agregar)

**Interfaces:**
- Consumes: `verificar_credenciales()`, `cliente_admin()` (Tarea 3).
- Produces: `supabase_auth.cambiar_password(usuario_id, nueva) -> bool`

**Contexto que el implementador necesita:**

Hoy la contraseña actual se verifica con `check_password_hash`. Ahora se
verifica llamando a `verificar_credenciales()` con el email del usuario: si
entra, la contraseña actual es correcta.

Se usa `update_user_by_id` (la admin API) y no `update_user`, porque este
sistema **no guarda la sesión de Supabase** del usuario — solo verifica
credenciales en el login. Sin sesión activa no hay contra quién aplicar
`update_user`.

- [ ] **Step 1: Escribir los tests que fallan**

```python
def test_cambiar_la_contrasena_permite_entrar_con_la_nueva(cliente, crear_usuario):
    usuario = crear_usuario("matias", password="clave-vieja-123")
    cliente.post("/login", data={"username": "matias", "password": "clave-vieja-123"})
    cliente.post("/cambiar-password", data={
        "actual": "clave-vieja-123", "nueva": "clave-nueva-456", "confirmar": "clave-nueva-456",
    })
    cliente.get("/logout")

    cliente.post("/login", data={"username": "matias", "password": "clave-nueva-456"})
    with cliente.session_transaction() as sesion:
        assert sesion["usuario_id"] == usuario["id"]


def test_no_se_puede_cambiar_sin_saber_la_contrasena_actual(cliente, crear_usuario):
    crear_usuario("matias", password="clave-vieja-123")
    cliente.post("/login", data={"username": "matias", "password": "clave-vieja-123"})
    respuesta = cliente.post("/cambiar-password", data={
        "actual": "no-es-la-actual", "nueva": "clave-nueva-456", "confirmar": "clave-nueva-456",
    })
    assert b"actual no es correcta" in respuesta.data
    cliente.get("/logout")
    cliente.post("/login", data={"username": "matias", "password": "clave-nueva-456"})
    with cliente.session_transaction() as sesion:
        assert "usuario_id" not in sesion, "la contraseña se cambió sin validar la actual"


def test_el_cambio_obligatorio_no_pide_la_contrasena_actual(cliente, crear_usuario):
    """Tras un reseteo el usuario entra con una temporal y tiene que cambiarla;
    exigirle la 'actual' ahí sería redundante (acaba de escribirla al entrar)."""
    crear_usuario("nuevo", password="temporal-123", debe_cambiar_password=True)
    cliente.post("/login", data={"username": "nuevo", "password": "temporal-123"})
    cliente.post("/cambiar-password", data={
        "actual": "", "nueva": "elegida-por-mi-456", "confirmar": "elegida-por-mi-456",
    })
    cliente.get("/logout")
    cliente.post("/login", data={"username": "nuevo", "password": "elegida-por-mi-456"})
    with cliente.session_transaction() as sesion:
        assert "usuario_id" in sesion
        assert sesion["debe_cambiar_password"] is False
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_auth_supabase.py -k contrasena -v`
Expected: FAIL — `cambiar_password()` todavía escribe `password_hash`, que
Supabase Auth no mira.

- [ ] **Step 3: Agregar a `core/supabase_auth.py`**

```python
def cambiar_password(usuario_id, nueva):
    """Cambia la contraseña de una cuenta. Devuelve True si salió bien.

    Usa la admin API y no `update_user` porque este sistema no guarda la
    sesión de Supabase del usuario: solo le pregunta por sus credenciales en
    el momento del login.
    """
    if not SUPABASE_SERVICE_ROLE_KEY:
        return False
    try:
        cliente_admin().auth.admin.update_user_by_id(str(usuario_id), {"password": nueva})
    except Exception:
        return False
    return True
```

- [ ] **Step 4: Modificar `cambiar_password()` en `core/app.py`**

Reemplazar la verificación de la contraseña actual y el UPDATE:

```python
        # La contraseña actual se verifica pidiéndole a Supabase que inicie
        # sesión con ella: si entra, era la correcta.
        actual_valida = obligatorio or bool(
            supabase_auth.verificar_credenciales(usuario["email"], actual)
        )

        if not actual_valida:
            flash("La contraseña actual no es correcta.", "danger")
        elif len(nueva) < 8:
            flash("La contraseña nueva tiene que tener al menos 8 caracteres.", "danger")
        elif nueva != confirmar:
            flash("Las contraseñas nuevas no coinciden.", "danger")
        elif not supabase_auth.cambiar_password(usuario["id"], nueva):
            flash("No se pudo cambiar la contraseña. Probá de nuevo en un momento.", "danger")
        else:
            conn.execute(
                "UPDATE usuarios SET debe_cambiar_password=false WHERE id=%s",
                (usuario["id"],),
            )
```

**Ojo:** el orden de las ramas importa. `cambiar_password()` va **última**,
después de validar largo y coincidencia — si no, una contraseña de 3 letras se
guardaría en Supabase antes de que el sistema la rechace.

El resto del cuerpo (commit, `session["debe_cambiar_password"] = False`,
redirect) no cambia.

- [ ] **Step 5: Correr los tests**

Run: `python -m pytest tests/test_auth_supabase.py -v`
Expected: PASS (10 tests)

- [ ] **Step 6: Suite entera y commit**

```bash
python -m pytest tests/ -v
git add core/app.py core/supabase_auth.py tests/test_auth_supabase.py
git commit -m "Cambiar la contraseña contra Supabase Auth"
```

---

## Task 5: Gestión de usuarios (`/usuarios`)

**Files:**
- Modify: `core/app.py:2081-2173` (`usuarios_nuevo`, `usuarios_resetear_password`,
  `usuarios_eliminar`), `core/supabase_auth.py`, `templates/usuario_form.html`
- Test: `tests/test_auth_supabase.py` (agregar)

**Interfaces:**
- Consumes: `cliente_admin()` (Tarea 3).
- Produces:
  - `supabase_auth.crear_cuenta(email, password) -> str | None` (devuelve el id)
  - `supabase_auth.borrar_cuenta(usuario_id) -> bool`

**Contexto que el implementador necesita:**

El alta de usuario ahora necesita un **email**, que antes no se pedía. Se
agrega el campo al formulario. El id de la fila en `usuarios` ya no lo genera
Postgres: lo devuelve Supabase al crear la cuenta, y se inserta explícitamente.

`usuarios_editar` **no cambia**: solo toca nombre, rol y activo, que viven en
nuestra tabla.

`usuarios_eliminar` pasa a borrar la cuenta en Supabase; el `ON DELETE CASCADE`
de la Tarea 2 se lleva la fila de `usuarios` sola. **No hay que hacer las dos
cosas**: borrar el perfil a mano además de la cuenta es redundante y, si la
llamada a Supabase falla después del DELETE local, deja una cuenta activa sin
perfil — alguien que puede autenticarse pero no tiene rol.

- [ ] **Step 1: Escribir los tests que fallan**

```python
def test_un_admin_crea_un_usuario_que_puede_entrar(cliente, crear_usuario, db_conn):
    """El alta tiene que dejar la cuenta lista de punta a punta: si crea el
    perfil pero no la cuenta, el usuario nuevo no puede iniciar sesión."""
    admin = crear_usuario("jefe", rol="admin", password="clave-admin-123")
    cliente.post("/login", data={"username": "jefe", "password": "clave-admin-123"})

    respuesta = cliente.post("/usuarios/nuevo", data={
        "username": "empleado_nuevo", "email": "empleado_nuevo@ejemplo.test",
        "nombre": "Empleado Nuevo", "rol": "empleado",
    }, follow_redirects=True)

    # La contraseña temporal se muestra una sola vez, en el mensaje.
    import re
    temporal = re.search(rb"Contrase&#241;a temporal: (\S+)", respuesta.data) \
        or re.search(rb"Contraseña temporal: (\S+)", respuesta.data)
    assert temporal, "no se mostró la contraseña temporal"

    fila = db_conn.execute(
        "SELECT id, email, debe_cambiar_password FROM usuarios WHERE username=%s",
        ("empleado_nuevo",),
    ).fetchone()
    assert fila["email"] == "empleado_nuevo@ejemplo.test"
    assert fila["debe_cambiar_password"] is True

    cliente.get("/logout")
    cliente.post("/login", data={
        "username": "empleado_nuevo", "password": temporal.group(1).decode(),
    })
    with cliente.session_transaction() as sesion:
        assert sesion["usuario_id"] == str(fila["id"])
        assert sesion["debe_cambiar_password"] is True


def test_borrar_un_usuario_borra_tambien_su_cuenta(cliente, crear_usuario, db_conn):
    """Si quedara la cuenta viva sin perfil, esa persona seguiría pudiendo
    autenticarse contra Supabase."""
    admin = crear_usuario("jefe", rol="admin", password="clave-admin-123")
    victima = crear_usuario("se_va", password="clave-123")
    cliente.post("/login", data={"username": "jefe", "password": "clave-admin-123"})

    cliente.post(f"/usuarios/{victima['id']}/eliminar")

    assert db_conn.execute(
        "SELECT id FROM usuarios WHERE id=%s", (victima["id"],)
    ).fetchone() is None

    from core import supabase_auth
    cuentas = supabase_auth.cliente_admin().auth.admin.list_users()
    assert victima["id"] not in [c.id for c in cuentas]


def test_resetear_la_contrasena_da_una_temporal_que_funciona(cliente, crear_usuario, db_conn):
    admin = crear_usuario("jefe", rol="admin", password="clave-admin-123")
    olvidadizo = crear_usuario("olvidadizo", password="la-que-olvido-123")
    cliente.post("/login", data={"username": "jefe", "password": "clave-admin-123"})

    respuesta = cliente.post(
        f"/usuarios/{olvidadizo['id']}/resetear-password", follow_redirects=True
    )
    import re
    temporal = re.search(rb"temporal: (\S+)", respuesta.data)
    assert temporal

    cliente.get("/logout")
    cliente.post("/login", data={
        "username": "olvidadizo", "password": temporal.group(1).decode(),
    })
    with cliente.session_transaction() as sesion:
        assert sesion["usuario_id"] == olvidadizo["id"]
        assert sesion["debe_cambiar_password"] is True
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_auth_supabase.py -k "usuario or borrar or resetear" -v`
Expected: FAIL — el alta todavía inserta `password_hash` y no crea la cuenta.

- [ ] **Step 3: Agregar a `core/supabase_auth.py`**

```python
def crear_cuenta(email, password):
    """Crea la cuenta en Supabase Auth y devuelve su id, o None si falló.

    `email_confirm=True` no es opcional: sin eso la cuenta queda pendiente de
    confirmación y el usuario no puede iniciar sesión. Acá el alta la hace un
    administrador del negocio en persona, así que no hay nada que confirmar
    por mail.
    """
    if not SUPABASE_SERVICE_ROLE_KEY:
        return None
    try:
        respuesta = cliente_admin().auth.admin.create_user(
            {"email": email, "password": password, "email_confirm": True}
        )
    except Exception:
        return None
    return respuesta.user.id if respuesta and respuesta.user else None


def borrar_cuenta(usuario_id):
    """Borra la cuenta. La fila de `usuarios` se va sola por ON DELETE CASCADE."""
    if not SUPABASE_SERVICE_ROLE_KEY:
        return False
    try:
        cliente_admin().auth.admin.delete_user(str(usuario_id))
    except Exception:
        return False
    return True
```

- [ ] **Step 4: Modificar las tres rutas en `core/app.py`**

`usuarios_nuevo()` — el cuerpo del POST:

```python
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        nombre = request.form.get("nombre", "").strip()
        rol = request.form.get("rol", "empleado")
        conn = db.get_connection()
        existente = conn.execute(
            "SELECT id FROM usuarios WHERE username=%s OR email=%s", (username, email)
        ).fetchone()
        if existente:
            flash(f"Ya existe un usuario con ese nombre de usuario o ese email.", "danger")
            conn.close()
            return redirect(url_for("usuarios_nuevo"))

        password_temporal = db._generar_password_temporal()
        # Primero la cuenta: su id es el que va a llevar el perfil. Si esto
        # falla no se escribe nada en nuestra tabla, así que no queda un
        # perfil sin cuenta detrás (que además la FK rechazaría).
        usuario_id = supabase_auth.crear_cuenta(email, password_temporal)
        if not usuario_id:
            flash("No se pudo crear la cuenta. Revisá que el email sea válido y no esté en uso.", "danger")
            conn.close()
            return redirect(url_for("usuarios_nuevo"))

        conn.execute(
            """INSERT INTO usuarios (id, username, email, nombre, rol, activo, debe_cambiar_password)
               VALUES (%s, %s, %s, %s, %s, TRUE, TRUE)""",
            (usuario_id, username, email, nombre, rol),
        )
        conn.commit()
        conn.close()
```

El `flash` con la contraseña temporal no cambia.

`usuarios_resetear_password()`:

```python
    conn = db.get_connection()
    password_temporal = db._generar_password_temporal()
    if not supabase_auth.cambiar_password(usuario_id, password_temporal):
        flash("No se pudo resetear la contraseña. Probá de nuevo en un momento.", "danger")
        conn.close()
        return redirect(url_for("usuarios_lista"))
    conn.execute(
        "UPDATE usuarios SET debe_cambiar_password=true, intentos_fallidos=0, bloqueado_hasta=NULL WHERE id=%s",
        (usuario_id,),
    )
    conn.commit()
    conn.close()
```

`usuarios_eliminar()` — reemplazar el `DELETE FROM usuarios` por:

```python
    # Se borra la cuenta y el perfil se va solo (ON DELETE CASCADE). Hacer las
    # dos cosas por separado abre la puerta a que el DELETE local salga bien y
    # el borrado de la cuenta falle: quedaría alguien que puede autenticarse
    # pero no tiene rol ni perfil.
    if not supabase_auth.borrar_cuenta(usuario_id):
        flash("No se pudo eliminar el usuario. Probá de nuevo en un momento.", "danger")
        return redirect(url_for("usuarios_lista"))
    flash("Usuario eliminado.", "info")
    return redirect(url_for("usuarios_lista"))
```

- [ ] **Step 5: Agregar el campo email a `templates/usuario_form.html`**

Campo `email`, `type="email"`, `required`, **solo al crear** (al editar se
muestra como texto no editable: cambiar el email es cambiar la credencial, y
eso no está en el alcance de esta pantalla).

- [ ] **Step 6: Correr los tests y la suite**

Run: `python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add core/app.py core/supabase_auth.py templates/usuario_form.html tests/
git commit -m "Gestionar altas, reseteos y bajas contra Supabase Auth"
```

---

## Task 6: Borrar `password_hash`

Ya no queda código que lea ni escriba esa columna. Se borra para que no quede
un rastro de credenciales viejas en la base.

**Files:**
- Create: `supabase/migrations/<timestamp>_borrar_password_hash.sql`
- Modify: `core/database.py` (`seed_demo_data` si siembra usuarios)
- Test: `tests/test_esquema.py`

- [ ] **Step 1: Verificar que no queda ningún uso**

Run: `grep -rn "password_hash" core/ scripts/ tests/ templates/`
Expected: sin resultados en `core/`, `templates/` ni `scripts/`. Si aparece
alguno, esa es una tarea anterior incompleta — **parar y reportarlo**, no
borrar la columna igual.

- [ ] **Step 2: Escribir la migración**

```sql
-- Supabase Auth es el único almacén de credenciales desde las migraciones
-- anteriores. Esta columna ya no la lee ni la escribe nadie; se borra para no
-- dejar hashes de contraseñas viejos dando vueltas en la base.
ALTER TABLE usuarios DROP COLUMN password_hash;
```

- [ ] **Step 3: Escribir el test**

```python
def test_ya_no_se_guardan_hashes_de_contrasena(db_conn):
    """Las credenciales viven solo en Supabase Auth."""
    columnas = [
        f["column_name"] for f in db_conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='usuarios'"
        )
    ]
    assert "password_hash" not in columnas
    assert "email" in columnas
```

- [ ] **Step 4: Aplicar, correr la suite y commitear**

```bash
npx supabase db reset
python -m pytest tests/ -v
git add supabase/migrations tests/test_esquema.py core/database.py
git commit -m "Borrar la columna password_hash, ya sin uso"
```

---

## Task 7: Fotos de producto a Supabase Storage

**Files:**
- Create: `core/almacenamiento.py`
- Modify: `core/app.py:304-305` (constantes) y `:337-356` (las dos funciones)
- Modify: `templates/productos.html`, `templates/tienda_catalogo.html`,
  `templates/producto_form.html`, `templates/compra_importar_factura.html`
- Test: `tests/test_almacenamiento.py` (crear)

**Interfaces:**
- Produces:
  - `almacenamiento.subir_imagen(nombre_archivo, contenido: bytes, content_type) -> bool`
  - `almacenamiento.borrar_imagen(nombre_archivo) -> bool`
  - `almacenamiento.url_publica(nombre_archivo) -> str`
- `guardar_imagen_producto(producto_id, file_storage)` y
  `eliminar_imagen_producto(nombre_archivo)` **conservan su firma exacta** —
  quien las llama (`productos_nuevo`, `productos_editar`) no cambia.

**Contexto que el implementador necesita:**

`productos.imagen` sigue guardando **solo el nombre del archivo**, igual que
hoy. Lo que cambia es de dónde lo sirve el navegador: en vez de
`url_for('static', filename='img/productos/' + p.imagen)`, la URL pública del
bucket.

El helper `url_publica` se registra como filtro de Jinja para que los templates
queden legibles y para no repetir el armado de la URL en 4 lugares.

El bucket `productos` es **público** (las fotos se muestran en la tienda
online, que no tiene login). Hay que crearlo — se hace en la Tarea 9 como paso
manual, y en local lo crea el propio test si falta.

- [ ] **Step 1: Escribir los tests que fallan**

```python
"""Fotos de producto en Supabase Storage.

Contra el Storage local que levanta `npx supabase start`. En Vercel no hay
disco: una foto guardada en el sistema de archivos desaparece en el siguiente
cold start, y en el medio otras invocaciones ni siquiera la ven.
"""
import io

import pytest
from werkzeug.datastructures import FileStorage

from core import almacenamiento
from core.app import eliminar_imagen_producto, guardar_imagen_producto


PNG_MINIMO = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6300010000050001".ljust(120, "0")
)


def test_guardar_una_foto_la_deja_disponible_en_una_url_publica():
    archivo = FileStorage(
        stream=io.BytesIO(PNG_MINIMO), filename="foto.png", content_type="image/png"
    )
    nombre = guardar_imagen_producto(4242, archivo)
    assert nombre == "producto_4242.png"

    url = almacenamiento.url_publica(nombre)
    assert nombre in url
    assert url.startswith("http")

    eliminar_imagen_producto(nombre)


def test_solo_se_aceptan_las_extensiones_permitidas():
    archivo = FileStorage(
        stream=io.BytesIO(b"no soy una imagen"), filename="virus.exe",
        content_type="application/octet-stream",
    )
    assert guardar_imagen_producto(1, archivo) is None


def test_borrar_una_foto_que_no_existe_no_rompe():
    """El borrado corre cuando se reemplaza una foto; que la anterior ya no
    esté no puede tumbar el guardado del producto."""
    eliminar_imagen_producto("producto_inexistente_99999.png")
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_almacenamiento.py -v`
Expected: FAIL — `core.almacenamiento` no existe.

- [ ] **Step 3: Escribir `core/almacenamiento.py`**

```python
"""Fotos de producto en Supabase Storage.

En Vercel no hay disco persistente: una foto guardada en el sistema de
archivos desaparece en el siguiente cold start, y mientras tanto las otras
invocaciones ni siquiera la ven. El bucket es público porque las fotos se
muestran en la tienda online, que no tiene login.

Mismo criterio defensivo que el resto de los módulos que hablan con servicios
externos: nada de acá lanza excepciones hacia afuera. Que falle la subida de
una foto no puede impedir guardar el producto.
"""
import os

from supabase import create_client

BUCKET = "productos"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _bucket():
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY).storage.from_(BUCKET)


def subir_imagen(nombre_archivo, contenido, content_type):
    """Sube (o reemplaza) una imagen. Devuelve True si salió bien."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return False
    try:
        _bucket().upload(
            nombre_archivo, contenido,
            {"content-type": content_type, "upsert": "true"},
        )
    except Exception:
        return False
    return True


def borrar_imagen(nombre_archivo):
    if not nombre_archivo or not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return False
    try:
        _bucket().remove([nombre_archivo])
    except Exception:
        return False
    return True


def url_publica(nombre_archivo):
    """URL pública de una foto, o cadena vacía si no hay foto cargada."""
    if not nombre_archivo:
        return ""
    return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{nombre_archivo}"
```

**`upsert: "true"` es necesario**: el nombre del archivo se deriva del id del
producto (`producto_42.png`), así que al reemplazar la foto de un producto se
sube el mismo nombre. Sin `upsert`, Storage lo rechaza por duplicado y la foto
nueva se pierde en silencio.

- [ ] **Step 4: Modificar `core/app.py`**

Borrar `CARPETA_IMAGENES_PRODUCTOS` y el `os.makedirs` (líneas 304-305), y
reescribir las dos funciones conservando su firma:

```python
def guardar_imagen_producto(producto_id, file_storage):
    """Guarda la foto subida para un producto y devuelve el nombre de archivo
    a guardar en productos.imagen, o None si no se subió nada válido."""
    if not file_storage or not file_storage.filename:
        return None
    extension = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    if extension not in EXTENSIONES_IMAGEN_PERMITIDAS:
        return None
    nombre_archivo = secure_filename(f"producto_{producto_id}.{extension}")
    contenido = file_storage.read()
    if not almacenamiento.subir_imagen(nombre_archivo, contenido, file_storage.content_type):
        return None
    return nombre_archivo


def eliminar_imagen_producto(nombre_archivo):
    almacenamiento.borrar_imagen(nombre_archivo)
```

Y registrar el filtro de Jinja junto a los que ya existen (cerca de
`app.jinja_env.filters["money"] = money`, `core/app.py:300`):

```python
app.jinja_env.filters["url_imagen"] = almacenamiento.url_publica
```

- [ ] **Step 5: Modificar los 4 templates**

En cada uno, reemplazar el armado de la URL de la imagen por
`{{ producto.imagen|url_imagen }}` (ajustando el nombre de la variable según el
template). **Solo esa línea** — no tocar clases, tamaños ni el `alt`.

- [ ] **Step 6: Correr los tests y la suite**

Run: `python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add core/almacenamiento.py core/app.py templates/ tests/test_almacenamiento.py
git commit -m "Guardar las fotos de producto en Supabase Storage"
```

---

## Task 8: Scripts, variables de entorno y documentación

**Files:**
- Modify: `.env.example`, `README.md`, `CLAUDE.md`,
  `docs/DOCUMENTACION_TECNICA.md`
- Modify: `core/database.py` (comentario sobre el pooler)

**Contexto que el implementador necesita:**

Los 6 scripts de `scripts/` se siguen corriendo desde la Mac de Celes, pero
ahora contra Supabase por internet. **Usan un pooler distinto que la app**: son
procesos largos con cargas masivas, así que van por el pooler en **modo sesión
(puerto 5432)**, no por el de transacción (6543) que usa la app. No hay que
cambiar código: es la `DATABASE_URL` que se les pasa.

- [ ] **Step 1: Actualizar `.env.example`**

Agregar, con un comentario por variable:

```bash
# --- Base de datos ---
# App (Vercel): pooler en modo TRANSACCIÓN, puerto 6543.
DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-0-sa-east-1.pooler.supabase.com:6543/postgres
# Scripts de scripts/ (cargas masivas desde la compu): pooler en modo SESIÓN,
# puerto 5432. Correrlos por el de transacción puede cortar a mitad de camino.
# DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-0-sa-east-1.pooler.supabase.com:5432/postgres

# --- Sesión ---
# Obligatoria en producción: sin esto, cada cold start invalida las sesiones.
# Generar con: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=
# Poner en 1 solo donde haya HTTPS (Vercel). Local va vacía.
SESSION_COOKIE_SECURE=

# --- Supabase ---
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_ANON_KEY=
# SOLO del servidor: saltea todas las políticas de la base. Nunca en el
# navegador, nunca en el repositorio.
SUPABASE_SERVICE_ROLE_KEY=
```

- [ ] **Step 2: Actualizar `README.md`**

Sección nueva de despliegue: variables a cargar en Vercel, cómo crear el primer
admin, cómo correr los scripts contra la nube.

- [ ] **Step 3: Actualizar `CLAUDE.md`**

En la sección "Migración a Postgres", reemplazar el bloque "Plan 1 de 2" por el
estado real: qué quedó desplegado, dónde viven las credenciales ahora, y los
tres archivos que dejaron de existir (`.secret_key`, `credenciales_iniciales.txt`,
`static/img/productos/`).

- [ ] **Step 4: Actualizar `docs/DOCUMENTACION_TECNICA.md`**

Los dos módulos nuevos (`core/supabase_auth.py`, `core/almacenamiento.py`) en
el árbol de archivos y en la sección de módulos. La tabla de tablas: `usuarios`
ya no guarda hash de contraseña.

- [ ] **Step 5: Commit**

```bash
git add .env.example README.md CLAUDE.md docs/ core/database.py
git commit -m "Documentar el despliegue y las variables de entorno"
```

---

## Task 9: Verificación integral y deploy

**Files:** ninguno (o correcciones puntuales de lo que aparezca).

**Pasos manuales de Celes** (marcados con 👤 — el implementador **no** puede
hacerlos y tiene que pedirlos):

- [ ] **Step 1: Barrido de restos**

```bash
grep -rn "password_hash\|CARPETA_IMAGENES_PRODUCTOS\|SI_INSTANCE_DIR\|credenciales_iniciales" core/ scripts/ templates/
grep -rn "float(" core/ | grep -v "facturacion_afip\|tienda_pagos\|importar_factura"
```
Expected: sin resultados. Cualquier hallazgo es una tarea anterior incompleta.

- [ ] **Step 2: Suite entera, dos veces seguidas**

Run: `python -m pytest tests/ -v && python -m pytest tests/ -v`
Expected: PASS las dos. La segunda corrida verifica que la limpieza de
usuarios de Supabase Auth funciona — si el fixture no borra las cuentas, la
segunda falla con "email ya registrado".

- [ ] **Step 3: 👤 Crear el bucket `productos` en Supabase**

Panel → Storage → New bucket → nombre `productos`, marcado **público**.

- [ ] **Step 4: 👤 Aplicar las migraciones nuevas a la nube**

```bash
npx supabase db push
```

- [ ] **Step 5: 👤 Crear el proyecto en Vercel y conectarlo al repositorio**

- [ ] **Step 6: 👤 Cargar las variables de entorno en Vercel**

Todas las de `.env.example`, más las que ya existían (`AFIPSDK_*`,
`MERCADOPAGO_*`, `SMTP_*`). `STORE_BASE_URL` pasa a ser la URL pública real de
Vercel — eso **destraba el webhook de Mercado Pago**, que hasta ahora no podía
funcionar por no tener una URL alcanzable desde internet.

- [ ] **Step 7: 👤 Crear el primer admin**

Panel de Supabase → Authentication → Users → Add user (con "Auto Confirm User"
activado). Después, una sola vez, desde el SQL Editor:

```sql
INSERT INTO usuarios (id, username, email, nombre, rol, activo, debe_cambiar_password)
VALUES ('<el uuid que muestra el panel>', 'matias', '<el mismo email>',
        'Matías', 'admin', true, false);
```

- [ ] **Step 8: Verificación en el deploy real**

Con la URL de Vercel ya andando, verificar a mano y **reportar el resultado de
cada punto** (no darlos por buenos):

1. `/login` entra con el admin recién creado.
2. Se puede entrar con el username **y** con el email.
3. Cargar un producto con foto: la foto se ve en `/productos` y en `/tienda`.
4. Registrar una venta de punta a punta.
5. **El gotcha de CSRF con HTTPS**: `WTF_CSRF_SSL_STRICT` (default `True`)
   exige un header `Referer` del mismo origen en cada POST. Probar un POST
   real (guardar un cliente) y confirmar que no aparece el error de "página
   desactualizada". Si aparece, es este el motivo.
6. `/tienda` carga sin sesión iniciada.
7. Que el proxy quedó bien: en una pantalla cualquiera, que los links sean
   `https://` y no `http://`.

- [ ] **Step 9: Commit final si hubo correcciones**

---

## Riesgos conocidos

- **La suite depende de que el Supabase local esté levantado.** Ya no alcanza
  con Postgres: los tests de autenticación y de fotos necesitan también los
  servicios Auth y Storage (`npx supabase start` los levanta todos). El
  chequeo de `pytest_configure` cubre la base pero **no** estos dos servicios;
  si fallan, el mensaje va a ser de conexión rechazada.
- **Las claves locales de Supabase están escritas en `conftest.py`.** Son los
  valores por defecto de la CLI, idénticos en cualquier máquina y sin acceso a
  nada real. Aun así, quedan overrideables por variable de entorno.
- **`update_user_by_id` cambia la contraseña sin invalidar sesiones activas.**
  Si alguien tenía la sesión abierta en otro navegador, sigue abierta después
  del cambio. Es el comportamiento que ya había con el hash propio, así que no
  es una regresión — pero si alguna vez se quiere cerrar todo al cambiar la
  contraseña, hay que hacerlo explícitamente.
- **El primer deploy es donde aparecen los problemas de proxy y CSRF.** Por eso
  el Step 8 de la Tarea 9 es verificación manual con resultado reportado punto
  por punto, y no un "probar que anda".

## Fuera de alcance

- **2FA / TOTP.** La base queda lista (Supabase lo ofrece gratis), pero se suma
  después de que el sistema esté andando en producción.
- **RLS (Row Level Security).** Todo el acceso a la base pasa por Flask con la
  cadena de conexión de servidor; no hay clientes hablando directo con
  Postgres, así que RLS no tendría nada que hacer cumplir.
- **Recuperación de contraseña por email.** Supabase la habilita, pero requiere
  configurar el envío de mails del proyecto y una pantalla nueva.
- **Migrar los usuarios existentes.** Los que hay son de prueba: se crean de
  nuevo a mano.
