# Migración a Vercel + Supabase

**Fecha:** 2026-08-13
**Estado:** diseño aprobado, pendiente de plan de implementación

## Contexto

El sistema corre hoy en la computadora del local: Flask + SQLite (`data.db`),
empaquetado en Docker para poder mudarlo a un hosting con volumen persistente
(Railway, Fly.io o un VPS). Esa decisión está documentada en `CLAUDE.md`.

Celes pidió desplegarlo en **Vercel**, donde ya tiene el otro sistema que
mantiene (*hogar-gestión*, Next.js + Supabase). El motivo es de operación, no
técnico: tener los dos proyectos en la misma plataforma en vez de sumar un
tablero más.

Dos restricciones firmes:

- **Tiene que ser gratis.** Railway ya no tiene plan gratuito permanente y
  Fly.io en la práctica termina siendo pago. Vercel Hobby y Supabase Free sí
  lo son.
- **El sistema todavía no está en producción.** No hay datos reales cargados
  (los 5 clientes, 14 productos y 45 ventas actuales son de ejemplo). Eso
  elimina el riesgo de pérdida de datos y habilita corregir decisiones de
  esquema que con datos reales serían caras.

### Por qué SQLite no servía

No es un problema de configuración sino de arquitectura. SQLite es un archivo
en disco, atado a la máquina donde corre el proceso. Vercel ejecuta funciones
serverless sin disco persistente (solo `/tmp`, efímero), así que el archivo se
perdería en cada deploy. Lo mismo aplica a los otros tres archivos que el
sistema escribe hoy en disco: `.secret_key`, `credenciales_iniciales.txt` y las
fotos de producto en `static/img/productos/`.

Además, SQLite impide un objetivo del negocio: que el sistema sea accesible
desde varias computadoras a la vez. Eso requiere una base que corra como
servidor en red, no un archivo local.

## Decisiones tomadas

| Decisión | Elegido | Motivo |
|---|---|---|
| Hosting | Vercel Hobby | Gratis, y consolida con hogar-gestión |
| Base de datos | Supabase (Postgres) | Ya es el proveedor que Celes usa y conoce |
| Fotos de producto | Supabase Storage | 1 GB gratis, mismo proveedor |
| Capa de acceso a datos | SQL crudo portado (opción A) | Menor superficie de cambio, cada consulta verificable contra la original |
| Autenticación | Supabase Auth | Elección explícita de Celes priorizando seguridad |
| Login | Usuario **o** email | Conserva la experiencia actual y suma recuperación por mail |
| 2FA (TOTP) | Fuera de alcance, para producción | Agrega fricción durante las pruebas sin ganancia |
| Entorno de desarrollo | Postgres local con Docker | Solo queda 1 lugar gratis en Supabase; se reserva para el proyecto real |
| Proyectos Supabase | 1 (arranca como test, luego pasa a prod) | Decisión de Celes ante la cuota disponible |
| Plata en la base | `REAL` → `NUMERIC(12,2)` | Corrige un bug latente aprovechando que no hay datos reales |

### Alternativas descartadas para la capa de datos

- **SQLAlchemy (ORM):** implicaba reescribir las ~193 consultas desde cero.
  Las analíticas del panel (top clientes, mejor precio por proveedor, saldos
  de cuenta corriente) son `GROUP BY` con `JOIN`s que en ORM quedan más
  enredados que en SQL. Más trabajo y más riesgo de cambiar comportamiento sin
  advertirlo.
- **API REST de Supabase / PostgREST (como hogar-gestión):** es el único
  camino donde Row Level Security aplicaría de verdad, pero **no aporta
  seguridad en esta arquitectura y probablemente la reduzca**:
  1. El sistema ya es inmune a inyección SQL — se verificó que las 279
     consultas usan parámetros y que no hay SQL armado con datos del usuario.
     Los dos únicos `execute(f"...")` (`core/database.py:457` y `:460`) usan
     nombres de tabla que son constantes del código, y desaparecen con esta
     migración.
  2. PostgREST **expone la base a internet**: el navegador habla directo con
     Supabase y las políticas RLS son lo único que separa los datos del
     mundo. Con la opción A la base es inalcanzable desde internet — solo el
     servidor Flask, con una credencial secreta, la alcanza.
  3. RLS casi no tendría nada que hacer: en este sistema todo el personal ve
     los mismos datos del negocio, no hay partición por usuario (a diferencia
     de hogar-gestión, donde auxiliar, enfermería, médico y dirección ven
     cosas distintas).

  Además exigiría mover las consultas con `JOIN`s y agregaciones a funciones
  SQL dentro de la base: reescribir la aplicación casi entera.

## Sección 1 — Infraestructura y despliegue

### Vercel

Vercel detecta Flask automáticamente al leer `requirements.txt` y toma como
entrypoint el `app.py` de la raíz, que ya expone una variable `app` de nivel
superior. **El shim de una línea creado en su momento para Docker/gunicorn ya
cumple la convención de Vercel** — no hace falta reestructurar nada.

Se agrega `vercel.json` con:

- `maxDuration` explícito de **300 s** (el máximo del plan Hobby con Fluid
  compute, habilitado por defecto).
- Python **3.12**.
- Exclusión del bundle de `scripts/`, `docs/`, `plantillas/` y
  `listas_proveedores/`, que no se usan en runtime, para no acercarse al
  límite de tamaño.

`static/` **no** se excluye: Flask lo sigue sirviendo, y una vez que las fotos
de producto se muden a Storage queda reducido a CSS y el logo.

### Supabase

Un proyecto en la organización actual de Celes, que tiene 1 lugar libre de los
2 del plan gratuito. Arranca como entorno de prueba y ese mismo proyecto pasa
a producción cuando la migración esté verificada (limpiando antes los datos de
prueba). No se crea una organización nueva: la cuota de proyectos gratuitos se
cuenta por persona entre todas las organizaciones donde es Owner o Admin, así
que separar no aportaría cuota.

El desarrollo se hace contra un **Postgres local** levantado con
`npx supabase start` (Docker y la CLI de Supabase ya están instalados y
funcionando en la Mac de Celes: Docker 29.7.2, CLI 2.114.0). Las migraciones se
prueban ahí antes de tocar la nube — el mismo flujo ya documentado en el README
de hogar-gestión.

### Configuración y secretos

Los tres archivos que hoy se escriben en disco dejan de existir:

| Hoy (archivo en disco) | Pasa a ser |
|---|---|
| `.secret_key` | Variable de entorno `SECRET_KEY` |
| `credenciales_iniciales.txt` | Primer admin creado desde el panel de Supabase |
| `data.db` | Postgres en Supabase |

`SI_INSTANCE_DIR` (en `core/database.py`) pierde sentido y se elimina, junto con
la lógica de `INSTANCE_DIR`, `DB_PATH` y `CREDENCIALES_PATH`.

Variables de entorno nuevas: `SECRET_KEY`, `DATABASE_URL`, `SUPABASE_URL`,
`SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`. Las ya existentes
(`AFIPSDK_*`, `MERCADOPAGO_*`, `SMTP_*`, `STORE_BASE_URL`) se cargan en el panel
de Vercel, nunca en el repositorio. `.env.example` se actualiza con todas.

### Seguridad que se activa con el deploy

- `SESSION_COOKIE_SECURE = True` (hoy comentada en `core/app.py:70`), porque
  Vercel provee HTTPS.
- `STORE_BASE_URL` pasa a ser la URL pública real, lo que **destraba el webhook
  de Mercado Pago** — un pendiente del roadmap que se resuelve como efecto
  secundario del deploy.
- Queda vigente el gotcha ya anotado en `CLAUDE.md`: con HTTPS activo,
  `WTF_CSRF_SSL_STRICT` (default `True`) exige un header `Referer` del mismo
  origen en cada POST. Hay que verificarlo en el primer deploy.
- El otro gotcha de `CLAUDE.md` sobre `request.host` en `manejar_csrf_error`
  **sí aplica ahora**: Vercel pone la aplicación detrás de un proxy. Hay que
  configurar `ProxyFix` de Werkzeug o validar contra una lista de hosts de
  confianza.

### Otros efectos

- `init_db()` deja de ejecutarse al arrancar la app (`core/app.py:88`). Hoy
  corre en cada arranque; en serverless correría en cada cold start. El esquema
  pasa a aplicarse con migraciones.
- `Dockerfile`, `docker-compose.yml` y `.dockerignore` **se conservan** como
  salida hacia un VPS si algún día se quiere dejar Vercel. Además Docker pasa a
  usarse para el Postgres de desarrollo.
- Los proyectos gratuitos de Supabase se pausan tras **1 semana sin
  actividad**; se despiertan a mano en segundos. Con uso diario del negocio no
  debería ocurrir en producción.

## Sección 2 — Base de datos y capa de acceso

### Esquema y migraciones

Las 18 tablas pasan a `supabase/migrations/`, gestionadas con la CLI de
Supabase, igual que hogar-gestión. Toda la maquinaria de `init_db()` y
`_migrar()` (`core/database.py:400-560`) —los `PRAGMA table_info` y `ALTER
TABLE` idempotentes— **desaparece**: era la forma de migrar una base local sin
herramientas. El estado final del esquema actual se convierte en la migración
inicial.

`INTEGER PRIMARY KEY AUTOINCREMENT` pasa a `GENERATED BY DEFAULT AS IDENTITY`.

### Corrección de tipos

**Plata: `REAL` → `NUMERIC(12,2)` en 21 columnas.** Los flotantes no
representan decimales exactos (`0.1 + 0.2 ≠ 0.3`). En este sistema el error se
acumula en tres lugares sensibles: el cálculo de IVA al 21%, el prorrateo de
descuentos de monto fijo sobre los ítems de una venta
(`aplicar_promociones()`), y los saldos de cuenta corriente. Y hay un caso
donde importa de verdad: **ARCA exige que neto + IVA = total exacto** en la
factura electrónica.

Las 21 columnas afectadas, verificadas contra el esquema:

| Tabla | Columnas |
|---|---|
| `productos` | `precio_costo`, `precio_venta` |
| `ventas` | `total`, `imp_neto`, `imp_iva` |
| `venta_items` | `precio_unitario`, `subtotal` |
| `compras` | `total` |
| `compra_items` | `precio_unitario`, `subtotal` |
| `producto_proveedor` | `precio_costo` |
| `pedidos_web` | `total` |
| `pedido_web_items` | `precio_unitario`, `subtotal` |
| `cuenta_corriente_movimientos` | `monto`, `imp_neto`, `imp_iva` |
| `cuenta_corriente_movimiento_items` | `precio_unitario`, `subtotal` |
| `movimientos_no_facturados` | `precio` |
| `promociones_aplicadas` | `porcentaje_o_monto` |

Consecuencia a manejar: Python pasa a recibir `Decimal` en vez de `float`.
Mezclar `Decimal` con `float` en una operación lanza `TypeError`, así que hay
que revisar toda la aritmética de montos. Es trabajo acotado y el error es
ruidoso (falla, no calcula mal), lo que lo hace verificable.

**Fechas: `TEXT` → `DATE` / `TIMESTAMPTZ`.** `fecha`, `fecha_alta`,
`fecha_inicio`, `fecha_fin` y `fecha_pedido_pendiente` pasan a `DATE`;
`fecha_creacion`, `bloqueado_hasta` y `fecha_aprobacion` (que hoy usan
`CURRENT_TIMESTAMP`) pasan a `TIMESTAMPTZ`. Hoy las comparaciones y
agrupamientos por fecha funcionan solo porque el formato `YYYY-MM-DD` ordena
bien alfabéticamente.

### Capa de acceso

`core/database.py` sigue siendo **el único lugar que abre conexiones**. Cambia
el driver: `sqlite3` → `psycopg` (v3). Tres detalles críticos:

1. **Pooler en modo transacción (puerto 6543).** En serverless, conectarse
   directo al 5432 agota las conexiones de Postgres.
2. **Prepared statements desactivados** (`prepare_threshold=None`). El modo
   transacción no los soporta, pero psycopg3 los activa solo a partir de la
   quinta ejecución de una consulta. Sin esto la app funciona al principio y
   **empieza a fallar después** — un bug difícil de diagnosticar.
3. **`row_factory = dict_row`**, para que las filas se sigan accediendo por
   nombre (`venta["fecha"]`) y ningún template deba cambiar por este motivo.

La conexión se abre y cierra por request, no se mantiene global.

### Traducción de dialecto

| SQLite (hoy) | Postgres | Alcance |
|---|---|---|
| `?` | `%s` | ~279 lugares |
| `cursor.lastrowid` | `INSERT ... RETURNING id` | 11 lugares |
| `LIKE` *(no distingue mayúsculas)* | `ILIKE` | 3 buscadores |
| `INSERT OR IGNORE` | `ON CONFLICT DO NOTHING` | 5 lugares |
| `date('now')` | `CURRENT_DATE` | promociones vigentes |
| `sqlite3.IntegrityError` | `psycopg.errors.UniqueViolation` / `ForeignKeyViolation` | 4 lugares |
| `PRAGMA foreign_keys = ON` | innecesario | — |

`LIKE` → `ILIKE` es el más peligroso: es el único que **no rompe nada
visiblemente**. Si se omite, los buscadores de productos y clientes
simplemente dejan de encontrar resultados escritos en minúscula.

## Sección 3 — Autenticación con Supabase Auth

### Principio de diseño

`verificar_sesion()` (`core/app.py:103`) lee tres claves de la sesión de Flask:
`usuario_id`, `usuario_rol` y `debe_cambiar_password`. **Mientras esas tres se
sigan poblando, el resto del sistema no se entera del cambio.** La protección
global de rutas, `es_admin()`, `inject_usuario()` y los 30+ templates quedan
igual.

El alcance real son 4 pantallas: `/login`, `/logout`, `/cambiar-password` y
`/usuarios`.

Supabase Auth pasa a ser el **almacén de credenciales**; Flask sigue manejando
la sesión con su cookie firmada, lo que preserva intacta la protección CSRF.

### Quién guarda qué

| Dato | Dónde vive |
|---|---|
| Email y contraseña (hash) | Supabase Auth (`auth.users`) |
| 2FA / TOTP (a futuro) | Supabase Auth |
| `username`, `nombre`, `rol`, `activo` | Tabla propia `usuarios` |
| `debe_cambiar_password` | Tabla propia `usuarios` |
| `intentos_fallidos`, `bloqueado_hasta` | Tabla propia `usuarios` |

`usuarios.password_hash` **se elimina**. `usuarios.id` pasa de `INTEGER` a
`uuid` ligado a `auth.users.id`, con un trigger que crea el perfil al dar de
alta un usuario (mismo patrón `profiles` de hogar-gestión).

### Login con usuario o email

Supabase Auth se basa en email, pero el formulario de login se resuelve del
lado del servidor, así que se admite cualquiera de los dos:

1. Un solo campo, como hoy, donde se escribe `admin` o `matias@ejemplo.com`.
2. Si el texto contiene `@`, se trata como email. Si no, se busca en `usuarios`
   la fila con ese `username` y se obtiene su email asociado.
3. En ambos casos se llama a Supabase Auth con el email real.

La columna `username` se mantiene `UNIQUE` y funciona como alias del email.

**Requisito de seguridad:** el mensaje de error debe ser idéntico cuando el
usuario no existe y cuando la contraseña es incorrecta ("Usuario o contraseña
incorrectos"). Mensajes distintos permitirían enumerar qué usuarios existen.

### Qué se conserva

- **Bloqueo por 5 intentos fallidos / 15 minutos**, sobre la fila de
  `usuarios`, sin importar si se entró por usuario o por email. Se suma al
  rate limiting propio de Supabase: dos capas donde antes había una.
- **Cambio de contraseña obligatorio** al primer ingreso o tras un reseteo
  (Supabase no lo trae de fábrica).
- **Roles `admin` / `empleado`.**

### Qué se gana

- Recuperación de contraseña por email (hoy inexistente: depende de que un
  admin la resetee a mano).
- El hashing de contraseñas deja de ser código propio a mantener.
- Base lista para 2FA por TOTP, confirmado gratuito en todos los proyectos de
  Supabase (solo el MFA por SMS es pago).

### Primer admin

Se crea desde el panel de Supabase (**Authentication → Users → Add user**) y
después un `update usuarios set rol = 'admin'` por única vez — el mismo
procedimiento ya documentado en el README de hogar-gestión. Reemplaza a
`credenciales_iniciales.txt`.

Se agrega `supabase` a `requirements.txt`. `SUPABASE_SERVICE_ROLE_KEY` (que
`/usuarios` necesita para crear cuentas) es una variable **solo del servidor**:
nunca debe llegar al navegador, porque saltea todas las políticas de la base.

La tienda pública (`/tienda`) y el webhook de Mercado Pago siguen exentos de
login, y los `clientes` del negocio siguen siendo una tabla aparte sin cuenta
de usuario.

## Sección 4 — Fotos, scripts y verificación

### Fotos de producto → Supabase Storage

Las funciones `guardar_imagen_producto()` (`core/app.py:294`) y
`eliminar_imagen_producto()` (`core/app.py:307`) **conservan su firma**; solo
cambia su interior: en vez de `file_storage.save(...)` y `os.remove(...)`,
suben y borran contra un bucket público `productos` en Supabase Storage.

`productos.imagen` sigue guardando el nombre del archivo, y se agrega un helper
que arma la URL pública. Cambian 4 templates, solo en la línea que arma la
dirección de la imagen: `productos.html`, `tienda_catalogo.html`,
`producto_form.html` y `compra_importar_factura.html`.

`CARPETA_IMAGENES_PRODUCTOS` y el `os.makedirs` de `core/app.py:290-291`
desaparecen.

### Scripts de línea de comandos

Los 6 scripts de `scripts/` siguen corriéndose desde la Mac de Celes, pero se
conectan a Supabase por internet. **Usan un pooler distinto que la app**: son
procesos largos con cargas masivas, así que van por el pooler en **modo sesión
(puerto 5432)**, no por el de transacción. Ambos funcionan sobre IPv4 en el
plan gratuito.

### Verificación

1. Postgres local con Docker (`npx supabase start`) para todo el trabajo, sin
   tocar la cuota ni la nube.
2. **Cada consulta migrada se compara contra la original.** Son ~193:
   146 en `core/app.py`, 36 en `core/database.py`, 6 en `facturacion_afip.py`,
   3 en `tienda_pagos.py`, 2 en `importar_factura.py`. Ninguna se reescribe de
   memoria.
3. Datos de ejemplo cargados y recorrido de las pantallas principales.
4. Atención especial a los 3 buscadores (`LIKE` → `ILIKE`), que fallarían en
   silencio, y a la aritmética con `Decimal`.
5. Recién con todo verde: aplicar migraciones al proyecto Supabase y desplegar
   en Vercel.

## Qué NO cambia

- La lógica de negocio completa: ventas, stock, promociones, cuenta corriente,
  pedidos, comparador de precios de proveedores.
- `facturacion_afip.py` (Factura A/B, CAE, QR), `tienda_pagos.py` (Mercado
  Pago), `envio_mail.py`, `comprobante_pdf.py` e `importar_factura.py`: su
  lógica queda intacta, solo se traduce el dialecto de sus consultas.
- La tienda pública y el webhook, salvo que el deploy les resuelve el pendiente
  de la URL pública.
- Los otros ~26 templates y todo el CSS.

## Riesgos conocidos

| Riesgo | Mitigación |
|---|---|
| `LIKE` → `ILIKE` omitido: buscadores fallan en silencio | Revisión explícita de los 3 buscadores en la verificación |
| Prepared statements con el pooler en modo transacción: falla diferida | `prepare_threshold=None` documentado en el código |
| `Decimal` mezclado con `float`: `TypeError` | El error es ruidoso, no silencioso; revisión de toda la aritmética de montos |
| Proxy de Vercel y `request.host` en el handler CSRF | Configurar `ProxyFix` |
| Proyecto Supabase pausado tras 1 semana sin uso | Esperable solo antes de que el negocio lo use a diario |
| Tamaño del bundle de Python en Vercel | `excludeFiles` en `vercel.json` |
| Sin entorno de test separado una vez que el proyecto pase a producción | Postgres local con Docker cubre esa necesidad |

## Fuera de alcance

- **2FA (TOTP):** se implementa cuando el sistema esté en producción. El
  diseño lo deja habilitado, no requiere trabajo previo.
- **Row Level Security:** no aplica en esta arquitectura (ver alternativas
  descartadas).
- **Cargar los datos reales del negocio:** sigue dependiendo de que se complete
  `plantillas/Plantilla_Carga_Datos.xlsx`.
- **Cuentas de AFIP SDK y Mercado Pago:** siguen siendo pasos humanos
  pendientes, ajenos a esta migración.

## Pendientes humanos

1. Crear el proyecto en Supabase (1 lugar libre en la organización actual).
2. Crear el proyecto en Vercel y conectarlo al repositorio.
3. Cargar las variables de entorno en Vercel.
4. Crear el primer usuario admin desde el panel de Supabase.
5. Cuando el proyecto pase de test a producción: limpiar los datos de prueba.
