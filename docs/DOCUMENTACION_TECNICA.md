# Documentación técnica — Repuestos San Ignacio

Referencia técnica completa del sistema: arquitectura, qué hace cada módulo,
esquema de base de datos, configuración y despliegue. Pensada para quien
programa o mantiene el sistema (Celes, o quien la reemplace).

Para la explicación en términos de negocio (qué resuelve cada pantalla, qué
reemplaza del proceso viejo) ver `docs/DOCUMENTACION_FUNCIONAL.md`. Para la
instalación rápida ver el `README.md` de la raíz.

## 1. Arquitectura general

Aplicación web monolítica: **Flask** (Python) del lado del servidor,
**SQLite** como base de datos (un solo archivo, `data.db`), y **Bootstrap 5 +
Chart.js** del lado del cliente (sin build step, sin frontend framework —
las páginas son HTML renderizado por Jinja2 desde el servidor).

Se eligió este stack a propósito por dos motivos: (1) es lo más simple que
resuelve el problema — un negocio de un local con un puñado de usuarios no
necesita microservicios ni una base de datos cliente-servidor, y (2) es
también un ejercicio de aprendizaje para Celes de cómo se arma un sistema
real de punta a punta, así que la simplicidad es una ventaja pedagógica, no
solo técnica.

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
| Base de datos | SQLite | Un solo archivo, cero configuración, respaldo = copiar un archivo. Corre local sin instalar un servidor de base de datos aparte |
| Frontend | Bootstrap 5 + Chart.js (CDN) | Sin paso de build, sin Node.js — cualquiera puede abrir un `.html` y entenderlo |
| PDF | xhtml2pdf | 100% Python (usa reportlab), sin dependencias de sistema (a diferencia de WeasyPrint/wkhtmltopdf, que necesitan Pango/Cairo/GTK instalados aparte) |
| Excel | openpyxl | Lectura/escritura de `.xlsx`, con validaciones de datos (dropdowns) y estilos |
| PDF de facturas de compra | pdfplumber | Extracción de texto/tablas por posición de palabras, no solo por grilla |
| Facturación electrónica | Afip SDK (`afip.py`) | Evita manejar certificados X.509 y SOAP/XML a mano contra WSFE de ARCA |
| Cobro online | SDK oficial de Mercado Pago | Checkout Pro, sin manejar datos de tarjetas en este sistema |
| Servidor de producción | gunicorn | Flask's dev server (`app.run`) no es apto para producción |
| Contenedor | Docker | Empaquetado para desplegar en cualquier hosting |

Todas las dependencias están fijadas por versión en `requirements.txt`.

## 3. Estructura de carpetas

```
frenos_embragues_app/
├── app.py                    # shim de una línea: from core.app import app
├── core/                      # el núcleo del sistema (ver §4)
│   ├── app.py                    # rutas y lógica (el 90% de la aplicación)
│   ├── database.py               # esquema SQL + migraciones + datos de ejemplo
│   ├── facturacion_afip.py       # integración AFIP/ARCA (Factura C)
│   ├── tienda_pagos.py           # integración Mercado Pago
│   ├── comprobante_pdf.py        # genera el PDF de un comprobante
│   ├── envio_mail.py             # envía el comprobante por mail (SMTP)
│   └── importar_factura.py       # lee facturas de compra (PDF/Excel/CSV)
├── scripts/                   # herramientas de línea de comandos (ver §6)
│   └── archivo/                 # scripts de un solo uso ya usados, se guardan de referencia
├── plantillas/                # Excels que completa el negocio a mano
├── listas_proveedores/        # listas de precios de proveedores (datos del negocio)
├── templates/                 # vistas HTML (Jinja2) — vive fuera de core/
├── static/                    # CSS propio, logos, fotos de producto — vive fuera de core/
├── docs/                      # esta documentación
├── Dockerfile, docker-compose.yml, .dockerignore
├── requirements.txt
├── .env.example                # variables de entorno documentadas (copiar a .env)
└── data.db                     # la base de datos (se crea sola, no se sube al repo)
```

Los 7 módulos de `core/` son el sistema en sí: `core/app.py` los importa
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
Define el esquema completo (`SCHEMA`, un `CREATE TABLE IF NOT EXISTS` por
tabla) y `_migrar(conn)`, que agrega columnas nuevas a bases ya existentes
de forma **idempotente** (revisa con `PRAGMA table_info` antes de cada
`ALTER TABLE`, así correrlo de nuevo nunca rompe nada). Cualquier campo
nuevo que se agregue a una tabla existente tiene que pasar por acá, nunca
solo por el `CREATE TABLE` (si no, las bases que ya existen no lo reciben).

También tiene `seed_admin_user()` (crea el primer usuario admin con
contraseña al azar) y `seed_demo_data()` (carga datos de ejemplo si la base
está vacía) — ambas se llaman una vez al arrancar `core/app.py` y no hacen
nada si ya hay datos.

`INSTANCE_DIR` (variable de entorno `SI_INSTANCE_DIR`) controla dónde viven
los archivos que tienen que sobrevivir a un redeploy (`data.db`,
`.secret_key`, `credenciales_iniciales.txt`) — por defecto es la carpeta del
proyecto (no cambia nada corriendo local), y en Docker apunta a un volumen
montado (ver §7).

### `core/facturacion_afip.py`
Emite la Factura C electrónica contra ARCA vía Afip SDK cuando una venta es
con tarjeta o transferencia. `emitir_factura_c(venta_id)` nunca lanza una
excepción: si falta el `access_token` o ARCA rechaza el comprobante, guarda
`facturacion_estado` (`sin_configurar`/`error`/`emitida`) en la venta y
listo — la venta ya está guardada de antes, nunca se revierte. Se puede
reintentar manualmente desde el botón en el comprobante.

### `core/tienda_pagos.py`
Arma la "preferencia" de pago de Mercado Pago Checkout Pro para el checkout
de la tienda online, y valida la firma del webhook que confirma un pago.
Mismo criterio defensivo: sin `access_token` configurado, el checkout avisa
que el cobro online no está disponible (sugiriendo WhatsApp como
alternativa) en vez de romperse.

### `core/comprobante_pdf.py`
Genera el PDF de un comprobante de venta (remito/recibo/Factura C) para
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

Todas las tablas viven en un único archivo SQLite (`data.db`). Resumen de
las principales (ver `core/database.py` para las columnas completas):

| Tabla | Para qué |
|---|---|
| `clientes` | Datos de contacto + CUIT/DNI (para la Factura C) |
| `proveedores` | Datos de contacto + `activo` (soft-delete, no se borran si tienen historial) |
| `categorias` | Categorías de producto, editables desde `/categorias` |
| `subcategorias` | Subcategorías, cada una atada a una única categoría padre (`categoria_id` FK) — jerarquía estricta, editables desde `/categorias` |
| `productos` | Catálogo: precio costo/venta, stock actual/mínimo, categoría, subcategoría (texto libre, no FK — igual que categoría), proveedor, imagen, código de barras |
| `producto_proveedor` | Cotización de un producto por proveedor (para el comparador de precios) |
| `ventas` / `venta_items` | Una venta (local o tienda online) y sus líneas. Incluye los campos de Factura C (`cae`, `cae_vencimiento`, etc.) |
| `compras` / `compra_items` | Una compra a un proveedor y sus líneas — repone stock y actualiza costo |
| `pedidos_web` / `pedido_web_items` | Carrito "en tránsito" de la tienda online mientras se espera la confirmación del pago (no es un segundo inventario, ver §1) |
| `usuarios` | Login: hash de contraseña, rol (`admin`/`empleado`), bloqueo por intentos fallidos |

Todas las migraciones de columnas nuevas están centralizadas en
`database._migrar()` — es el único lugar que hay que tocar para agregar un
campo a una tabla que ya existe en producción.

## 6. Scripts de herramientas (`scripts/`)

Se corren a mano, siempre **desde la raíz del proyecto** (no desde adentro
de `scripts/`), por ejemplo: `python scripts/importar_datos.py`.

| Script | Para qué | Uso |
|---|---|---|
| `importar_datos.py` | Carga masiva inicial: clientes, productos, proveedores y ventas históricas desde `plantillas/Plantilla_Carga_Datos.xlsx`. Idempotente (actualiza en vez de duplicar) | `python scripts/importar_datos.py [archivo] [--reemplazar]` |
| `limpiar_lista_proveedor.py` | Toma el Excel crudo de un proveedor (formato propio de cada uno, vía un "adaptador") y deja solo lo relevante a frenos/embragues con precio de venta sugerido | `python scripts/limpiar_lista_proveedor.py [carpeta] [salida.xlsx]` |
| `generar_planilla_stock_proveedores.py` | Genera una planilla en blanco (una hoja por proveedor) para que alguien del negocio cargue a mano el stock real | `python scripts/generar_planilla_stock_proveedores.py [salida.xlsx]` |
| `cargar_stock_por_proveedor.py` | Importa esa planilla ya completada — "Cantidad en stock" reemplaza el stock actual (no lo suma) | `python scripts/cargar_stock_por_proveedor.py [archivo.xlsx]` |
| `archivo/cargar_ejemplo_proveedores.py` | **Archivado**, ya cumplió su función (piloto de carga que después se borró). Se conserva solo de referencia | — |

Los scripts que necesitan la base agregan la carpeta raíz del proyecto a
`sys.path` al principio del archivo y hacen `from core import database as
db` (están un nivel más abajo que `core/`), así que siguen funcionando
igual sin importar desde dónde se invoquen, mientras el comando se ejecute
desde la raíz del proyecto.

## 7. Configuración (variables de entorno)

Todo secreto o dato de configuración se lee de variables de entorno, nunca
hardcodeado. Ver `.env.example` en la raíz para la lista completa y
comentada: incluye AFIP SDK, Mercado Pago, SMTP y las variables de Docker.
El archivo real `.env` nunca se sube al repositorio (`.gitignore`) ni se
comparte por chat.

## 8. Cómo correr en desarrollo

```
pip install -r requirements.txt
python app.py
```

Abre en `http://127.0.0.1:5050`. La primera vez crea `data.db` con datos de
ejemplo y un usuario admin (contraseña en `credenciales_iniciales.txt`).

## 9. Cómo desplegar con Docker

```
docker compose up --build
```

El `Dockerfile` corre la app con **gunicorn** (nunca con `app.run(debug=True)`,
que es solo para desarrollo). Los datos persistentes (`data.db`,
`.secret_key`, `credenciales_iniciales.txt`, fotos de producto) se montan
como volúmenes — sin eso, se pierden cada vez que se recrea el contenedor.
Ver la sección "Dockerización" en `CLAUDE.md` para el detalle completo y el
aviso importante sobre hostings con disco efímero.

## 10. Seguridad implementada

- Contraseñas hasheadas (`werkzeug.security`), nunca en texto plano.
- Bloqueo de cuenta 15 minutos tras 5 intentos fallidos seguidos.
- Cambio de contraseña obligatorio en el primer ingreso.
- `app.secret_key` generada al azar, guardada fuera del código.
- Toda ruta requiere sesión iniciada por defecto (antes visto en `core/app.py`, §4).

Pendiente (ver CLAUDE.md, sección "Seguridad", para el detalle y el orden
de prioridad): backups automáticos, HTTPS + `SESSION_COOKIE_SECURE` cuando
el sistema quede expuesto a internet, protección CSRF, 2FA.

## 11. Integraciones externas — estado

| Integración | Estado del código | Falta para funcionar de verdad |
|---|---|---|
| Facturación AFIP/ARCA | Completo | Cuenta en app.afipsdk.com + `AFIPSDK_ACCESS_TOKEN` |
| Mercado Pago (tienda online) | Completo | Cuenta de Mercado Pago del negocio + URL pública HTTPS |
| Envío de comprobante por mail | Completo | Credenciales SMTP (`.env`) |
| Mercado Libre | No implementado | Ver "Notas sobre la integración con Mercado Libre" en `CLAUDE.md` |

Todas siguen el mismo patrón: el sistema funciona igual sin la
configuración real, solo deja avisado que esa parte puntual no está activa.
