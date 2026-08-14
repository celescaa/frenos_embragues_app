# Documentación técnica — Repuestos San Ignacio

Referencia técnica completa del sistema: arquitectura, qué hace cada módulo,
esquema de base de datos, configuración y despliegue. Pensada para quien
programa o mantiene el sistema (Celes, o quien la reemplace).

Para la explicación en términos de negocio (qué resuelve cada pantalla, qué
reemplaza del proceso viejo) ver `docs/DOCUMENTACION_FUNCIONAL.md`. Para la
instalación rápida ver el `README.md` de la raíz.

## 1. Arquitectura general

Aplicación web monolítica: **Flask** (Python) del lado del servidor,
**Postgres** como base de datos (alojado por [Supabase](https://supabase.com),
en desarrollo local corre en un contenedor Docker levantado por la CLI de
Supabase), y **Bootstrap 5 + Chart.js** del lado del cliente (sin build
step, sin frontend framework — las páginas son HTML renderizado por
Jinja2 desde el servidor).

**Migrado desde SQLite a Postgres el 13/08/2026** — ver
`CLAUDE.md` ("Migración a Postgres") para el detalle técnico completo del
cambio (qué cambió en el código, el gotcha de `prepare_threshold=None`,
etc.), acá solo el resumen que importa para entender la arquitectura
actual: un archivo SQLite local no sobrevive en un entorno serverless
(donde no hay disco persistente entre invocaciones) y tampoco permite que
el sistema se use desde varias computadoras/instancias a la vez sin
pisarse — dos requisitos que se volvieron necesarios apenas se definió
desplegar en Vercel (ver §9). El esquema (tablas, columnas) ya no lo crea
`core/database.py`: vive versionado en `supabase/migrations/`.

El sistema corre sobre **Postgres** (Supabase), con **Supabase Auth** como
almacén de credenciales y **Supabase Storage** para las fotos de producto.
Sigue funcionando local con `python app.py` igual que siempre, y está
preparado para desplegarse en **Vercel** (`vercel.json`, región São Paulo).
Ver "Deploy en Vercel" en `CLAUDE.md` para el detalle de esa migración y los
pasos manuales que quedan del lado de los paneles de Supabase y Vercel.

Se eligió este stack a propósito por dos motivos: (1) es lo más simple que
resuelve el problema — un negocio de un local con un puñado de usuarios no
necesita microservicios ni una arquitectura compleja, y (2) es también un
ejercicio de aprendizaje para Celes de cómo se arma un sistema real de
punta a punta, así que la simplicidad es una ventaja pedagógica, no solo
técnica.

**Una sola fuente de verdad.** La decisión de arquitectura más importante
del proyecto: tanto la venta en el local como la venta por la tienda online
escriben en las mismas tablas (`ventas`, `venta_items`, `productos`). No hay
dos sistemas de stock que sincronizar — cuando se vende algo por cualquiera
de los dos canales, es la misma fila de la misma tabla la que se actualiza.
Esto evita la clase de bug más común en sistemas de venta multicanal (stock
desincronizado entre local y web).

**Integraciones externas aisladas y defensivas.** Todo lo que depende de un
servicio de terceros (AFIP/ARCA, Mercado Pago, SMTP) vive en su propio
módulo (`core/facturacion_afip.py`, `core/tienda_pagos.py`, `core/envio_mail.py`) y sigue
la misma regla: **nunca lanzan una excepción hacia afuera**. Si falta
configuración o el servicio externo falla, la función devuelve un estado de
error (o lo guarda en la base) y quien la llamó decide qué avisarle al
usuario — pero la operación de negocio que la disparó (una venta, una
compra) ya quedó guardada antes y nunca se revierte por esto. Esto es
deliberado: un corte de internet o una cuenta de AFIP mal configurada no
tiene que poder impedir que el local venda.

## 2. Stack tecnológico

| Componente | Elección | Por qué |
|---|---|---|
| Backend | Flask 3 | Liviano, sin *boilerplate*, alcanza de sobra para el tamaño del proyecto |
| Base de datos | Postgres (Supabase) | Antes SQLite (un solo archivo) — se cambió el 13/08/2026 porque un archivo local no sobrevive en un entorno serverless sin disco persistente (el destino de deploy elegido, Vercel) y porque impedía usar el sistema desde varias computadoras/instancias a la vez sin arriesgar datos pisados. Supabase da Postgres alojado más, para el Plan 2, autenticación y storage de archivos sin sumar otro proveedor |
| Frontend | Bootstrap 5 + Chart.js (CDN) | Sin paso de build, sin Node.js — cualquiera puede abrir un `.html` y entenderlo |
| PDF | xhtml2pdf | 100% Python (usa reportlab), sin dependencias de sistema (a diferencia de WeasyPrint/wkhtmltopdf, que necesitan Pango/Cairo/GTK instalados aparte) |
| Excel | openpyxl | Lectura/escritura de `.xlsx`, con validaciones de datos (dropdowns) y estilos |
| PDF de facturas de compra | pdfplumber | Extracción de texto/tablas por posición de palabras, no solo por grilla |
| Facturación electrónica | Afip SDK (`afip.py`) | Evita manejar certificados X.509 y SOAP/XML a mano contra WSFE de ARCA |
| Cobro online | SDK oficial de Mercado Pago | Checkout Pro, sin manejar datos de tarjetas en este sistema |
| Autenticación | Supabase Auth | El hashing de contraseñas deja de ser código propio a mantener, y queda la base lista para 2FA por TOTP (gratis en Supabase). Flask sigue manejando la sesión, así que la protección CSRF no cambió |
| Fotos de producto | Supabase Storage | En Vercel no hay disco: una foto guardada en el sistema de archivos desaparece en el siguiente arranque en frío |
| Hosting | Vercel (plan Hobby) | Gratis, detecta Flask solo, y es donde Celes ya tiene otro proyecto. Región São Paulo para quedar cerca de la base |
| Servidor de producción | gunicorn | Flask's dev server (`app.run`) no es apto para producción |
| Contenedor | Docker | Empaquetado para desplegar en cualquier hosting |

Todas las dependencias están fijadas por versión en `requirements.txt`.

## 3. Estructura de carpetas

```
frenos_embragues_app/
├── app.py                    # shim de una línea: from core.app import app
├── core/                      # el núcleo del sistema (ver §4)
│   ├── app.py                    # rutas y lógica (el 90% de la aplicación)
│   ├── database.py               # conexión a Postgres + helpers de consulta/siembra
│   │                                (el esquema en sí vive en supabase/migrations/)
│   ├── supabase_auth.py          # login y gestión de usuarios (Supabase Auth)
│   ├── almacenamiento.py         # fotos de producto (Supabase Storage)
│   ├── facturacion_afip.py       # integración AFIP/ARCA (Factura A/B)
│   ├── tienda_pagos.py           # integración Mercado Pago
│   ├── comprobante_pdf.py        # genera el PDF de un comprobante
│   ├── envio_mail.py             # envía el comprobante por mail (SMTP)
│   └── importar_factura.py       # lee facturas de compra (PDF/Excel/CSV)
├── scripts/                   # herramientas de línea de comandos (ver §6)
│   └── archivo/                 # scripts de un solo uso ya usados, se guardan de referencia
│                                  (uno todavía en dialecto SQLite, ver §6)
├── plantillas/                # Excels que completa el negocio a mano
├── listas_proveedores/        # listas de precios de proveedores (datos del negocio)
├── supabase/                  # esquema de Postgres versionado (ver §5) y config de
│                                 la CLI de Supabase para levantarlo en local
├── tests/                     # suite de pytest (ver §8)
├── templates/                 # vistas HTML (Jinja2) — vive fuera de core/
├── static/                    # CSS propio, logos, fotos de producto — vive fuera de core/
├── docs/                      # esta documentación
├── vercel.json                # config del deploy en Vercel (región gru1)
├── pytest.ini                 # config de la suite de tests
├── Dockerfile, docker-compose.yml, .dockerignore   # desactualizados, ver §9
├── requirements.txt
└── .env.example                # variables de entorno documentadas (copiar a .env),
                                   incluye DATABASE_URL
```

Los 9 módulos de `core/` son el sistema en sí: `core/app.py` los importa
directamente al arrancar. El `app.py` de la raíz es solo un *shim* de una
línea (`from core.app import app`) para que `python app.py` y el `CMD` de
Docker (`gunicorn app:app`) sigan funcionando sin cambios. `templates/` y
`static/` **no** están adentro de `core/` — `core/app.py` le pasa esas
rutas absolutas a `Flask()` explícitamente en vez de dejar que las busque
al lado suyo (que sería adentro de `core/`, donde no están). Todo lo que
hay en `scripts/` son herramientas que alguien corre a mano de vez en
cuando (cargar datos, limpiar una lista de precios) — la aplicación web no
las usa ni depende de ellas para funcionar.

## 4. Módulos core (los que arrancan con la app — carpeta `core/`)

### `core/app.py`
El archivo más grande del proyecto: define todas las rutas HTTP (`@app.route`),
la lógica de cada pantalla, la protección de sesión (`@app.before_request`),
y los *helpers* compartidos (armar el buscador de productos, calcular
totales, registrar una venta). Se levanta a través del `app.py` de la raíz:
`python app.py` sigue siendo el comando de siempre.

Puntos que vale la pena conocer si se va a tocar este archivo:
- `verificar_sesion()` corre antes de **cualquier** request y redirige a
  `/login` si no hay sesión — no hay que acordarse de poner un decorador en
  cada ruta nueva, salvo que la ruta deba ser pública (agregar su prefijo a
  `PREFIJOS_PUBLICOS` o su endpoint a `ENDPOINTS_PUBLICOS`).
- `registrar_venta()` es la función que realmente inserta una venta y
  descuenta stock — la usan tanto "Nueva venta" (local) como el webhook de
  Mercado Pago (tienda online). Si se toca la lógica de venta, es acá.
- `NEGOCIO` (diccionario) tiene todos los datos del negocio (nombre,
  dirección, CUIT, WhatsApp) inyectados a todos los templates vía
  `inject_negocio()`. Para cambiar un dato del negocio, se edita ahí y ya
  se refleja en toda la app (navbar, comprobantes, tienda).

### `core/database.py`
**Reescrito por completo en la migración a Postgres (13/08/2026).** Ya no
define el esquema ni lo migra — eso vive en `supabase/migrations/` (ver
§5) y lo aplica la CLI de Supabase, no Python. Lo que queda acá es:

- `get_connection()`: abre la conexión a Postgres. Trae
  `prepare_threshold=None` — parámetro obligatorio, no cosmético, ver el
  gotcha explicado en `CLAUDE.md` ("Migración a Postgres"): sin él, el
  sistema funciona bien contra el pooler de Supabase en desarrollo y en
  las primeras requests de producción, y empieza a fallar recién cuando
  una consulta llega a su quinta ejecución — un bug tardío e intermitente,
  difícil de relacionar con la causa.
- Helpers de consulta (`obtener_categorias()`, `obtener_subcategorias()`,
  `obtener_cotizaciones_producto()`, `obtener_mejor_precio_por_producto()`)
  y de siembra de datos de ejemplo (`seed_demo_data()`, que sigue
  llamándose una vez al arrancar `core/app.py` y no hace nada si la base
  ya tiene productos cargados).
- Las listas de referencia (`CATEGORIAS_INICIALES`, `SUBCATEGORIAS_INICIALES`,
  etc.) que también usa `scripts/importar_datos.py` para validar — el dato
  de siembra real ahora vive en la migración de Supabase, esto queda de
  documentación/referencia.

Cualquier columna nueva que se agregue a una tabla existente ahora se hace
con un archivo de migración SQL nuevo en `supabase/migrations/`, no
tocando este módulo.

**Ya no existe** `seed_admin_user()` (creaba el primer admin con
contraseña al azar al arrancar): en un entorno serverless no tiene sentido
correr eso en cada arranque en frío. El primer usuario admin se crea a
mano hoy (ver §8) hasta que el Plan 2 pase el login a Supabase Auth.
Tampoco existe ya `INSTANCE_DIR`/`SI_INSTANCE_DIR` (apuntaba a dónde vivía
`data.db`) — la persistencia ahora es la variable `DATABASE_URL` apuntando
a Postgres, no una carpeta de archivos locales.

### `core/facturacion_afip.py`
Emite la factura electrónica contra ARCA vía Afip SDK cuando una venta es
con tarjeta o transferencia. El negocio es **Responsable Inscripto**, así
que el tipo de comprobante lo decide la condición IVA del receptor:
**Factura A** si el cliente también es Responsable Inscripto con CUIT
cargado, **Factura B** en cualquier otro caso (Consumidor Final,
Monotributista, Exento, o sin CUIT/DNI). Nunca Factura C. `datos_receptor()`
es quien hace ese mapeo (CUIT/DNI + `condicion_iva` del cliente →
`DocTipo`/`DocNro`/`CondicionIVAReceptorId` + tipo de comprobante), con los
valores válidos de condición IVA en `CONDICIONES_IVA`. Limitación conocida:
el sistema no consulta el padrón de AFIP, así que la condición IVA es la que
alguien cargó a mano en la ficha del cliente — si está mal cargada, la
factura sale con el tipo equivocado.

La llamada cruda a ARCA está en `_emitir_factura_arca()` (discrimina IVA a
la tasa general del 21%, `ALICUOTA_IVA`, sobre el total con IVA incluido que
ya maneja el sistema; no soporta productos con otra alícuota) y no toca
ninguna tabla. Encima de eso hay dos funciones que sí guardan el resultado:
`emitir_factura(venta_id)` para una venta y
`emitir_factura_movimiento(movimiento_id)` para un cargo de cuenta
corriente. Ninguna lanza una excepción: si falta el `access_token` o ARCA
rechaza el comprobante, guardan `facturacion_estado`
(`sin_configurar`/`error`/`emitida`) en la fila correspondiente y listo — la
venta (o el movimiento) ya está guardada de antes, nunca se revierte. Se
puede reintentar manualmente desde el botón en el comprobante.

Ver la sección "Facturación electrónica AFIP/ARCA" de `CLAUDE.md` para el
detalle completo de la regla de negocio y su historial.

### `core/tienda_pagos.py`
Arma la "preferencia" de pago de Mercado Pago Checkout Pro para el checkout
de la tienda online, y valida la firma del webhook que confirma un pago.
Mismo criterio defensivo: sin `access_token` configurado, el checkout avisa
que el cobro online no está disponible (sugiriendo WhatsApp como
alternativa) en vez de romperse.

### `core/comprobante_pdf.py`
Genera el PDF de un comprobante de venta (remito/recibo/Factura A o B) para
adjuntarlo en el mail al cliente. Usa **xhtml2pdf** en vez de
WeasyPrint/wkhtmltopdf a propósito — es 100% Python, no requiere instalar
librerías de sistema en la compu de quien lo corra. Renderiza su propia
plantilla `templates/comprobante_pdf.html` (HTML/CSS simple, sin Bootstrap,
porque xhtml2pdf no soporta CSS moderno) en vez de reusar `comprobante.html`.

### `core/envio_mail.py`
Manda el PDF del comprobante por SMTP al mail del cliente. Configuración
por variables de entorno (`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, etc.,
ver `.env.example`). Mismo patrón defensivo: sin configurar, devuelve un
mensaje de error claro en vez de excepción.

### `core/importar_factura.py`
El módulo más complejo del proyecto. Lee una factura de compra de un
proveedor (PDF, Excel o CSV) y trata de reconocer código/descripción/
cantidad/precio de cada línea, para precargar la pantalla de "Nueva compra"
en vez de tipear todo a mano. Para PDF sin tabla con grilla (el caso más
común en facturas reales), reconstruye las filas por la **posición de las
palabras** en la página (agrupando por espacios en blanco grandes, no por
coordenadas fijas de columna) — ver la sección de arquitectura de
`docs/DOCUMENTACION_FUNCIONAL.md` o los comentarios del propio archivo para
el detalle de por qué esto hizo falta (una factura real tenía el precio
unitario corrompido por un bug del software que la generó, y calcular el
precio como Importe ÷ Cantidad resultó mucho más confiable). Nunca actualiza
el stock directo: siempre pasa por la pantalla de revisión manual.

## 5. Esquema de base de datos

Todas las tablas viven en Postgres, definidas en
`supabase/migrations/20260813145208_esquema_inicial.sql` (esquema versionado
— cualquier cambio de columna es una migración SQL nueva en esa carpeta, no
un `ALTER TABLE` suelto en Python). Dos diferencias de tipos que importan
si se va a tocar este esquema: las columnas de plata son `NUMERIC(12,2)`
(Python siempre las maneja como `Decimal`, nunca `float` — ver
`a_decimal()` en `core/app.py` y el porqué en `CLAUDE.md`) y las fechas son
`DATE`/`TIMESTAMPTZ` reales, no texto. Resumen de las tablas principales
(ver la migración para las columnas completas):

| Tabla | Para qué |
|---|---|
| `clientes` | Datos de contacto + CUIT/DNI y `condicion_iva` (deciden si corresponde Factura A o B) |
| `proveedores` | Datos de contacto + `activo` (soft-delete, no se borran si tienen historial) |
| `categorias` | Categorías de producto, editables desde `/categorias` |
| `subcategorias` | Subcategorías, cada una atada a una única categoría padre (`categoria_id` FK) — jerarquía estricta, editables desde `/categorias` |
| `productos` | Catálogo: precio costo/venta, stock actual/mínimo, categoría, subcategoría (texto libre, no FK — igual que categoría), proveedor, imagen, código de barras |
| `producto_proveedor` | Cotización de un producto por proveedor (para el comparador de precios) |
| `ventas` / `venta_items` | Una venta (local o tienda online) y sus líneas. Incluye los campos de facturación electrónica (`cae`, `cae_vencimiento`, `tipo_comprobante`, `imp_neto`, `imp_iva`, etc.) |
| `compras` / `compra_items` | Una compra a un proveedor y sus líneas — repone stock y actualiza costo |
| `pedidos_web` / `pedido_web_items` | Carrito "en tránsito" de la tienda online mientras se espera la confirmación del pago (no es un segundo inventario, ver §1) |
| `usuarios` | Login: hash de contraseña, rol (`admin`/`empleado`), bloqueo por intentos fallidos |

Agregar un campo a una tabla que ya existe en producción es un archivo
nuevo en `supabase/migrations/` (aplicado con `npx supabase db reset` en
local, y con el paso de deploy correspondiente en producción) — ya no hay
una función central en Python que lo haga (`database._migrar()` existía en
la versión SQLite y se eliminó en la migración a Postgres).

## 6. Scripts de herramientas (`scripts/`)

Se corren a mano, siempre **desde la raíz del proyecto** (no desde adentro
de `scripts/`), por ejemplo: `python scripts/importar_datos.py`.

| Script | Para qué | Uso |
|---|---|---|
| `importar_datos.py` | Carga masiva inicial: clientes, productos, proveedores y ventas históricas desde `plantillas/Plantilla_Carga_Datos.xlsx`. Idempotente (actualiza en vez de duplicar) | `python scripts/importar_datos.py [archivo] [--reemplazar]` |
| `limpiar_lista_proveedor.py` | Toma el Excel crudo de un proveedor (formato propio de cada uno, vía un "adaptador") y deja solo lo relevante a frenos/embragues con precio de venta sugerido | `python scripts/limpiar_lista_proveedor.py [carpeta] [salida.xlsx]` |
| `generar_planilla_stock_proveedores.py` | Genera una planilla en blanco (una hoja por proveedor) para que alguien del negocio cargue a mano el stock real | `python scripts/generar_planilla_stock_proveedores.py [salida.xlsx]` |
| `cargar_stock_por_proveedor.py` | Importa esa planilla ya completada — "Cantidad en stock" reemplaza el stock actual (no lo suma) | `python scripts/cargar_stock_por_proveedor.py [archivo.xlsx]` |
| `extraer_catalogo_referencia.py` | Separa de esa misma planilla las hojas que en realidad son la lista de precios completa de un proveedor (no stock real) y arma un catálogo de referencia solo con costos. No toca la base | `python scripts/extraer_catalogo_referencia.py <entrada.xlsx> [salida.xlsx]` |
| `matchear_productos_proveedores.py` | Puebla `producto_proveedor` matcheando las listas de precios de varios proveedores contra el catálogo ya cargado (código de barras exacto, con fallback por similitud de texto). Corre en simulación salvo que se pase `--aplicar` | `python scripts/matchear_productos_proveedores.py <archivo.xlsx> [--categoria X] [--subcategoria Y] [--umbral 0.6] [--aplicar]` |
| `archivo/cargar_ejemplo_proveedores.py` | **Archivado**, ya cumplió su función (piloto de carga que después se borró). Se conserva solo de referencia. **No portado a Postgres** (Tarea 12 de la migración lo dejó a propósito en dialecto SQLite — `sqlite3`, `lastrowid`, `PRAGMA` — por ser código retirado): no corre contra la base actual, ver el aviso en el propio archivo | — |

Los scripts que necesitan la base agregan la carpeta raíz del proyecto a
`sys.path` al principio del archivo y hacen `from core import database as
db` (están un nivel más abajo que `core/`), así que siguen funcionando
igual sin importar desde dónde se invoquen, mientras el comando se ejecute
desde la raíz del proyecto.

## 7. Configuración (variables de entorno)

Todo secreto o dato de configuración se lee de variables de entorno, nunca
hardcodeado. Ver `.env.example` en la raíz para la lista completa y
comentada: incluye `DATABASE_URL` (la cadena de conexión a Postgres — ver
§8), AFIP SDK, Mercado Pago y SMTP. El archivo real `.env` nunca se sube al
repositorio (`.gitignore`) ni se comparte por chat.

## 8. Cómo correr en desarrollo

Requiere Postgres local, levantado por la CLI de Supabase (ver el paso a
paso completo, con capturas de qué imprime cada comando, en el `README.md`
de la raíz — acá el resumen técnico):

```
pip install -r requirements.txt
npx supabase start          # levanta Postgres en Docker y aplica supabase/migrations/
python app.py
```

Abre en `http://127.0.0.1:5050`. La primera vez carga datos de ejemplo
(clientes, productos, ventas) si la base está vacía, pero **ya no crea un
usuario admin solo** — `seed_admin_user()` se eliminó en la migración a
Postgres porque no tiene sentido ejecutar eso en cada arranque en frío de
un entorno serverless (ver §4). El primer admin se crea a mano, una sola
vez, desde el panel de Supabase (Authentication → Users → Add user, con
"Auto Confirm User" activado) más un `INSERT` en `usuarios` con ese mismo
id — pasos exactos en el `README.md`. Las contraseñas viven en Supabase
Auth: la tabla `usuarios` ya no guarda ningún hash.

Ojo: los datos de ejemplo se siembran solo al correr `python app.py` a
mano, desde el bloque `__main__` del `app.py` de la raíz. **No** se siembran
al importar el módulo, que es lo que hace un entorno serverless en cada
arranque en frío: como la condición de siembra es "la base está vacía"
—justo el estado de una base de producción recién creada— eso le habría
sembrado datos de mentira a la base del negocio.

`DATABASE_URL` (ver §7) apunta a ese Postgres local por default
(`postgresql://postgres:postgres@127.0.0.1:54322/postgres`); no hace falta
definirla a mano salvo que se levante en otro puerto o se apunte a otra
base.

### Suite de tests

```
python -m pytest tests/ -v
```

Con Postgres local levantado. `tests/conftest.py` deja la base de pruebas
limpia después de cada test (trunca todas las tablas y resiembra
`categorias`/`subcategorias`), así que es segura de correr repetidamente —
pero no apuntarla nunca a la base con datos reales del negocio. Ver
`CLAUDE.md` ("Migración a Postgres") para el detalle de cómo está armada
la suite.

## 9. Despliegue

**El sistema todavía no está desplegado en ningún lado** (corre solo
local) — este es el "Plan 1" de dos, ver §1 y `CLAUDE.md` ("Migración a
Postgres" → "Plan 1 de 2"). El camino de deploy elegido es **Vercel +
Supabase**: Vercel para correr la app (funciones serverless) y Supabase
para Postgres, autenticación y storage de archivos. El Plan 2 (a escribir
en `docs/superpowers/plans/`) cubre lo que falta: migrar el login a
Supabase Auth, mover las fotos de producto a Supabase Storage, `vercel.json`,
`ProxyFix` (necesario detrás del proxy de Vercel), `SESSION_COOKIE_SECURE`,
variables de entorno de producción, y el deploy en sí.

### Docker (desactualizado, escrito para la versión en SQLite)

```
docker compose up --build
```

Este `Dockerfile`/`docker-compose.yml` se escribieron cuando el sistema
corría sobre SQLite y montaban un volumen de disco (`SI_INSTANCE_DIR`) para
que `data.db`, `.secret_key`, `credenciales_iniciales.txt` y las fotos de
producto sobrevivieran a que se recreara el contenedor. Tras la migración
a Postgres, `SI_INSTANCE_DIR` ya no existe en el código (`core/database.py`
no lo define más) — el `Dockerfile` sigue fijando esa variable de entorno
pero el código ya no la lee, así que la promesa de persistencia que
describía esta sección ya no aplica (la persistencia real ahora es
`DATABASE_URL` apuntando a Postgres). Como el plan de deploy ya no es este
camino sino Vercel (arriba), es probable que este `Dockerfile` quede
reemplazado en el Plan 2 en vez de actualizado — ver la nota equivalente
en la sección "Dockerización" de `CLAUDE.md`.

## 10. Seguridad implementada

- Contraseñas hasheadas (`werkzeug.security`), nunca en texto plano.
- Bloqueo de cuenta 15 minutos tras 5 intentos fallidos seguidos.
- Cambio de contraseña obligatorio en el primer ingreso.
- `app.secret_key` generada al azar, guardada fuera del código.
- Toda ruta requiere sesión iniciada por defecto (antes visto en `core/app.py`, §4).
- Protección CSRF (`Flask-WTF`) en todos los formularios y en los 3 `fetch()`
  de alta rápida (clientes/productos). La única excepción es el webhook de
  Mercado Pago, que es server-to-server y no lleva sesión de navegador. Un
  token vencido o inválido muestra un mensaje en español, no una página
  técnica de error.

Pendiente (ver CLAUDE.md, sección "Seguridad", para el detalle actualizado
y el orden de prioridad): HTTPS + `SESSION_COOKIE_SECURE` cuando el sistema
quede expuesto a internet, 2FA. Backups: con Postgres/Supabase (ver §1) esto
cambia respecto a cuando el dato vivía en `data.db` — en producción los
maneja Supabase según el plan contratado, ver el detalle en `CLAUDE.md`.

## 11. Integraciones externas — estado

| Integración | Estado del código | Falta para funcionar de verdad |
|---|---|---|
| Facturación AFIP/ARCA | Completo | Cuenta en app.afipsdk.com + `AFIPSDK_ACCESS_TOKEN` |
| Mercado Pago (tienda online) | Completo | Cuenta de Mercado Pago del negocio + URL pública HTTPS |
| Envío de comprobante por mail | Completo | Credenciales SMTP (`.env`) |
| Mercado Libre | No implementado | Ver "Notas sobre la integración con Mercado Libre" en `CLAUDE.md` |

Todas siguen el mismo patrón: el sistema funciona igual sin la
configuración real, solo deja avisado que esa parte puntual no está activa.
