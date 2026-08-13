# Proyecto: Sistema integral — Repuestos San Ignacio (Frenos & Embragues)

Memoria del proyecto. Objetivo: producto completo de gestión para el negocio
de venta de frenos y embragues (negocio del hermano de Celes). Hoy el negocio
funciona con un Excel y sin sistema de clientes ni stock.

## Identidad del negocio

- **Nombre comercial**: Repuestos San Ignacio — "Casa de frenos y embragues".
- **Titular**: Caamaño Matías Ezequiel — CUIT 20-35075394-0 (**Responsable
  Inscripto**, alta IVA 12-2024, alta autónomo 07-2016). Corregido el
  09/08/2026: una versión anterior de este archivo y del código de
  facturación asumía monotributo por error — la propia alta IVA 12-2024 ya
  era evidencia de lo contrario (un monotributista no se da de alta en
  IVA). Como Responsable Inscripto, el comprobante correcto es Factura A
  (si el cliente también es Responsable Inscripto con CUIT) o Factura B
  (cualquier otro caso), nunca Factura C — ver `facturacion_afip.py`.
- **Dirección**: San Ignacio 2115, Ituzaingó Norte.
- **WhatsApp**: +54 9 11 6130-5237.
- **Redes**: Instagram @repuestos_sanignacio, Facebook "Repuestos San
  Ignacio", web frenosi.com.ar.
- **Horario**: lunes a viernes 8:30-12:00 y 14:00-18:00, sábados 8:30-13:00.
- **Identidad visual**: fondo negro, dorado/amarillo (#f2b705) como color de
  marca, blanco para texto secundario. Ya aplicado en la app (navbar, tarjetas
  del panel, botones primarios y encabezado del comprobante) — ver
  `templates/base.html` (variables CSS `--si-black` / `--si-gold`) y el dict
  `NEGOCIO` en `app.py`, que además inyecta estos datos a todos los templates
  vía `inject_negocio()`. Si cambia algún dato del negocio, se edita solo ahí.

## Objetivo final

Centralizar **ventas, stock y clientes** en un solo lugar y sobre eso hacer
analítica. La visión es un producto completo, no un prototipo. Celes además
usa este proyecto para aprender a construir un sistema real de punta a punta
(no es solo para el hermano).

## Visión de producto (definida con Celes)

1. Que le sirva al hermano para tener stock y vender en el local — **listo**.
2. Sumar venta por internet. Habían arrancado una tienda en Tiendanube pero
   no la terminaron.
3. Que quede un **producto core fuerte**: vender tanto en el local como por
   internet con el stock *siempre* sincronizado (una sola fuente de verdad,
   no dos sistemas separados que haya que sincronizar), y poder armar compras
   a proveedores comparando cuál tiene el mejor precio para cada producto.
4. Analítica de verdad sobre esos datos — esto también es la parte que más le
   interesa a Celes como ejercicio de "sistema de nicho chico pero con datos
   reales para analizar y vender mejor".
5. Alcance claro por fase, ir sumando de a una.

### Decisión de arquitectura: tienda propia, no Tiendanube

Se evaluaron dos caminos para el canal de venta por internet:

- **Integrar Tiendanube por API** (descartado por ahora): requiere plan
  Escala o Tiendanube Evolución para el camino simple de token ("aplicaciones
  a medida"); si no, hay que armar una app OAuth completa. Además implica dos
  stocks separados que sincronizar constantemente (push al vender acá,
  webhook al vender allá).
- **Construir la tienda online adentro de este mismo sistema** (elegido):
  un solo stock, sin nada que sincronizar para la venta web. Más trabajo de
  entrada (catálogo público, carrito, checkout, medio de pago) pero es el
  "producto core" que se busca, y mejor ejercicio de aprendizaje.

Mercado Libre queda aparte: es un marketplace con tráfico propio que no se
reemplaza, así que esa integración (stock por API + webhooks de pedidos) se
mantiene en el roadmap sin importar lo anterior.

## Decisiones tomadas

- **Arquitectura**: web app Flask + Postgres (migrado desde SQLite el
  13/08/2026, ver la sección "Migración a Postgres" más abajo). Corre local
  contra un Postgres levantado por la CLI de Supabase; en producción
  apuntaría al Postgres alojado por Supabase — ver esa misma sección para
  el porqué y el detalle técnico.
- **Usuarios**: el hermano + 1-2 empleados.
- **Alcance acordado**: ventas, stock, clientes, **facturación/comprobantes**
  y **compras a proveedores**.
- **Datos**: se arrancó de cero con datos de ejemplo (no se migró un Excel).
  Celes está completando `plantillas/Plantilla_Carga_Datos.xlsx` con los datos reales.

## Estado actual

Implementado y probado end-to-end:

- Clientes: alta, edición, búsqueda, baja.
- Productos/stock: categoría (Freno/Embrague/Otro), marca, modelo compatible,
  costo, precio de venta, stock actual y mínimo, alerta de stock bajo.
- Ventas: multi-producto, descuenta stock automáticamente, genera
  remito/recibo imprimible (exportable a PDF desde el navegador).
- Proveedores y compras: registrar compra repone stock y actualiza el costo.
- Panel de analítica: ventas del mes, histórico, gráfico de ventas por mes,
  top 5 productos, top 5 clientes, alertas de reposición.

Base actual: 5 clientes, 14 productos, 3 proveedores, 45 ventas — **todos de
ejemplo**, falta cargar los datos reales.

Agregado después:

- **Carga masiva por Excel**: `plantillas/Plantilla_Carga_Datos.xlsx` (hojas
  INSTRUCCIONES / PROVEEDORES / PRODUCTOS / CLIENTES / VENTAS HISTORICAS) +
  `scripts/importar_datos.py` que la importa. El importador es idempotente
  (actualiza en vez de duplicar), tolera formato de números argentino
  (`12.500,50`), varios formatos de fecha, agrupa las ventas multi-producto
  por N° de comprobante y crea proveedores/clientes faltantes avisando.
  Uso (desde la raíz del proyecto): `python scripts/importar_datos.py [archivo.xlsx] [--reemplazar]`.
- **Código de barras**: columna `codigo_barras` en productos, con migración
  automática e idempotente en `init_db()` para bases ya existentes. La
  pantalla de venta tiene un campo de escaneo: la pistola lectora funciona
  como teclado (tipea el código + Enter), busca contra
  `/api/producto-por-codigo` y suma el producto a la venta; si ya está en la
  lista le suma una unidad. Avisa si el producto no existe o está sin stock.
- **Lista de pedidos** (`/pedidos`): productos en o bajo el mínimo agrupados
  por proveedor, con cantidad sugerida (repone hasta el doble del mínimo) y
  costo estimado por proveedor y total. Imprimible.
- **Comparador de precios de proveedores**: tabla `producto_proveedor`
  (producto + proveedor + precio_costo + código del proveedor para ese
  producto). Se carga desde la ficha del producto (sección "Precios por
  proveedor", filas repetibles). La lista de pedidos ahora agrupa cada
  producto por el proveedor más barato entre los cargados (no por el
  "proveedor preferido" fijo de la ficha), marca esos casos con la insignia
  "mejor precio" y muestra el ahorro total estimado del pedido. Si un
  producto no tiene cotizaciones cargadas, cae al comportamiento viejo
  (proveedor preferido de la ficha).
- **Autocompletado de productos**: en Nueva venta y Nueva compra, el
  `<select>` de producto se reemplazó por un buscador tipo autocompletar
  (no case-sensitive, filtra por nombre/código/marca en un JSON embebido en
  la página). Integrado con el escaneo de código de barras. Si se escribe
  texto sin elegir una opción de la lista, el formulario avisa y no
  permite enviar la venta/compra con un producto inválido.
- **Login y usuarios** (`usuarios`, tabla nueva): sistema de autenticación
  completo.
  - Contraseñas hasheadas con `werkzeug.security` (nunca en texto plano).
  - Roles `admin` (gestiona usuarios) y `empleado` (todo lo demás).
  - Bloqueo de cuenta por 15 minutos tras 5 intentos fallidos seguidos
    (`intentos_fallidos` / `bloqueado_hasta` en la tabla `usuarios`).
  - Cambio de contraseña obligatorio en el primer ingreso o después de un
    reseteo por un admin (`debe_cambiar_password`).
  - Protección global vía `@app.before_request` (no decorador por ruta):
    cualquier ruta no logueada redirige a `/login`; si falta cambiar la
    contraseña, redirige a `/cambiar-password` hasta que lo haga.
  - Primer usuario admin se crea solo (`seed_admin_user()` en
    `database.py`) con contraseña aleatoria guardada en
    `credenciales_iniciales.txt` (fuera del control de versiones, se borra
    después de usarla).
  - `app.secret_key` se genera una vez y se guarda en `.secret_key` (no
    hardcodeada en el código).
  - Pendiente para cuando el sistema esté online: activar
    `SESSION_COOKIE_SECURE = True` (ya está la línea comentada en `app.py`).
- **Alta rápida de cliente desde Nueva venta**: modal en `venta_form.html`
  que llama a `/api/clientes-nuevo` (POST) sin recargar la página, así no se
  pierde la venta que se está cargando. El cliente nuevo queda seleccionado
  automáticamente en el `<select>`.
- **Facturación electrónica AFIP/ARCA (Factura A/B)** — implementada vía
  [Afip SDK](https://afipsdk.com) (paquete `afip.py` + `python-dotenv`, ver
  `requirements.txt`).
  - Regla de negocio (la pedida por el negocio, ver más abajo el aviso de
    cumplimiento): venta en **efectivo** → remito/recibo interno de siempre
    (se elige en el formulario). Venta en **tarjeta o transferencia** →
    **Factura A o B** automática (no es una opción manual; en
    `venta_form.html` el `<select>` de tipo de comprobante se deshabilita y
    se muestra un aviso cuando el medio de pago lo dispara). El negocio es
    **Responsable Inscripto** (corregido el 09/08/2026, ver "Identidad del
    negocio" — una versión anterior de esto asumía monotributo por error y
    solo emitía Factura C), así que cuál de las dos depende del receptor:
    Factura A si es Responsable Inscripto con CUIT cargado, Factura B en
    cualquier otro caso (Consumidor Final, Monotributista, Exento, o sin
    CUIT/DNI). Columna `clientes.condicion_iva` (select en `cliente_form.html`,
    valores en `facturacion_afip.CONDICIONES_IVA`) guarda esa condición;
    default `consumidor_final` para no romper clientes ya cargados.
  - `facturacion_afip.py`: módulo standalone.
    - `afip_configurado()` / `get_afip_client()`: leen `AFIPSDK_ACCESS_TOKEN`,
      `AFIPSDK_CUIT` (default: CUIT de prueba compartido
      `20409378472`), `AFIPSDK_PRODUCTION`, `AFIPSDK_PUNTO_VENTA`,
      `AFIPSDK_CERT`/`AFIPSDK_KEY` desde variables de entorno (`.env`, vía
      `python-dotenv`, cargado en `app.py` con `load_dotenv()`).
    - `datos_receptor(cuit_dni, condicion_iva)`: mapea CUIT/DNI + condición
      IVA del cliente a `DocTipo`/`DocNro`/`CondicionIVAReceptorId` de ARCA
      y decide `tipo_comprobante` ("Factura A" solo si es Responsable
      Inscripto con CUIT de 11 dígitos, si no "Factura B"); sin CUIT/DNI
      cargado cae a Consumidor Final/Factura B. **Limitación conocida**: no
      hay forma de consultar el padrón de AFIP desde acá, así que "es
      Responsable Inscripto" es lo que se cargó a mano — si está mal
      cargado, la factura sale con el tipo equivocado.
    - `_emitir_factura_arca(cuit_dni, condicion_iva, total, fecha)`: llamada
      cruda a ARCA (no toca tablas), discrimina IVA a la tasa general 21%
      (`ALICUOTA_IVA`, constante — no soporta productos con otra alícuota)
      sobre el `total` que ya maneja el sistema (se asume con IVA
      incluido, como se muestra al público) y arma el array `Iva` que
      exige ARCA para Factura A/B (a diferencia de Factura C, que no lo
      llevaba). Usada tanto por `emitir_factura()` (ventas) como por
      `emitir_factura_movimiento()` (cargos de cuenta corriente).
    - `emitir_factura(venta_id)`: hace `getLastVoucher` + `createVoucher`
      contra `afip.ElectronicBilling` (API confirmada leyendo el paquete
      instalado, no solo la documentación) y guarda `cae`,
      `cae_vencimiento`, `punto_venta_arca`, `numero_factura_arca`,
      `imp_neto`, `imp_iva`, `tipo_comprobante` en la venta. **Nunca lanza
      una excepción hacia afuera**: si falla (o si no hay `access_token`
      configurado), guarda `facturacion_estado`
      (`sin_configurar` / `error` / `emitida`) y `facturacion_error`, sin
      bloquear ni revertir la venta ya registrada.
    - `url_qr_venta(venta)`: arma la URL del QR según la especificación
      RG 4291 de AFIP, usando el `tipo_comprobante` real de la venta.
  - Migración idempotente en `database.py` (`_migrar`) agrega a `ventas`:
    `cae`, `cae_vencimiento`, `punto_venta_arca`, `numero_factura_arca`,
    `facturacion_estado`, `facturacion_error`, `imp_neto`, `imp_iva`; y a
    `clientes`: `condicion_iva`.
  - `app.py`: `registrar_venta()` calcula el `tipo_comprobante` ("Factura
    A"/"Factura B") en el momento con `datos_receptor()` (sin llamar a
    ARCA, solo para dejarlo etiquetado); `ventas_nueva()` llama a
    `emitir_factura()` después de confirmar la venta (nunca antes ni
    dentro de la misma transacción, para no arriesgar la venta si ARCA
    falla), que recalcula y sobreescribe el mismo campo al emitir de
    verdad. Ruta `/ventas/<id>/facturar` (POST) para reintento manual.
  - `comprobante.html`/`comprobante_pdf.html`: si la venta es Factura A/B y
    tiene CAE, muestran CAE, vencimiento, número de comprobante, desglose
    Neto/IVA/Total y un QR (generado vía `api.qrserver.com`, sin librería
    nueva) en vez del aviso de "remito interno". Si es Factura A/B pero
    todavía no tiene CAE (sin configurar o con error), muestran un aviso
    con botón "Reintentar facturación".
  - `.env.example` documenta todas las variables; `.env` real está en
    `.gitignore` (nunca se sube ni se pega en el chat).
  - **Pendiente para que factura de verdad**: alguien con acceso al negocio
    (el hermano) tiene que crear la cuenta gratuita en
    https://app.afipsdk.com (no es algo que se pueda crear en su nombre) y
    completar `AFIPSDK_ACCESS_TOKEN` en un `.env` local. Sin eso, el sistema
    funciona pero deja las ventas con tarjeta/transferencia marcadas como
    "sin_configurar", reintentables desde el comprobante.
  - Ya probado sin necesitar un `access_token` real: la migración de la
    base, el mapeo de receptor (Factura A vs B según condición IVA), el
    cálculo de neto/IVA, la construcción de la URL del QR, y que el
    flujo de venta nunca se rompe ni se bloquea cuando falta la
    configuración (queda en `facturacion_estado='sin_configurar'`). Falta
    probar la emisión real contra ARCA (ambiente de homologación) en cuanto
    haya un `access_token`.
- **Tienda online propia** (`/tienda`, pública, sin login) — implementada vía
  Mercado Pago Checkout Pro (paquete `mercadopago`). Ver la sección dedicada
  más abajo para el detalle técnico y lo que falta para que cobre de verdad.
  Comparte las mismas tablas `ventas`/`venta_items`/`productos` que la venta
  del local: cuando Mercado Pago confirma un pago, se genera ahí mismo una
  venta real (mismo stock, misma Factura A/B automática) — no hay dos
  stocks que sincronizar, tal como se definió en la visión de producto.
- **Foto de producto**: campo opcional en la ficha (JPG/PNG/WEBP), se guarda
  en `static/img/productos/` (fuera de git, son datos del negocio) y se
  muestra tanto en el listado de Stock como en el catálogo de la tienda.
- **Categorías del catálogo**: `Frenos, Embragues, Correas, Líquidos, Otros`
  (antes eran solo Freno/Embrague/Otro — `database.py` tiene
  `CATEGORIAS_RENOMBRADAS` y migra automáticamente los productos viejos a la
  taxonomía nueva; ver más abajo "Categorías de producto editables", que
  reemplazó la lista fija por una tabla). El catálogo público tiene botones
  para filtrar por categoría, combinables con el buscador de texto.
  `scripts/importar_datos.py` acepta tanto la lista nueva como la vieja (sin
  importar mayúsculas o acentos) para no romper la
  `plantillas/Plantilla_Carga_Datos.xlsx` si ya tiene datos cargados con el
  desplegable anterior.
- **Limpieza de listas de precios de proveedores**: `scripts/limpiar_lista_proveedor.py`
  toma un Excel crudo de un proveedor (formato propio de cada uno, vía un
  "adaptador" por proveedor) y genera `listas_proveedores/Lista_Proveedores_Limpia.xlsx`
  con solo lo relevante a frenos/embragues, precio de venta sugerido (margen
  configurable, 30% por defecto) y una columna para marcar qué cargar. Los
  valores de precio sugerido/diferencia se escriben como números fijos, no
  fórmulas de Excel: con miles de filas, LibreOffice tarda más de lo que
  este entorno permite recalcular, así que si cambia el costo o el margen
  hay que regenerar el archivo en vez de esperar que Excel recalcule solo.
  Incluye una hoja "Coincidencias" con productos que parecen ser el mismo
  repuesto entre dos proveedores distintos (detección por parecido de texto,
  no infalible — pensada para revisión manual antes de cargar el mismo
  producto con dos cotizaciones). `scripts/archivo/cargar_ejemplo_proveedores.py`
  (archivado, ya cumplió su función) importaba una cantidad configurable de
  filas de cada hoja de proveedor directamente a la base (stock en 0, con su
  cotización en `producto_proveedor`) para probar el flujo antes de hacer la
  carga completa y ya revisada — se usó una sola vez para un piloto que
  después se borró.
- **Importar factura de compra (PDF/Excel/CSV)**: en `/compras`, el botón
  "Importar factura" (`importar_factura.py`) lee el archivo del proveedor y
  trata de reconocer productos, cantidades y precios. Para Excel/CSV busca
  una tabla real (encabezados tipo Código/Descripción/Cantidad/Precio). Para
  PDF prueba, en orden: (1) reconstruir las filas por la **posición de las
  palabras** (`_filas_desde_posicion_pdf`) — funciona sin necesidad de que
  el PDF tenga líneas de grilla, que es el caso más común en facturas
  reales, agrupando palabras por saltos de espacio en blanco grandes en vez
  de por coordenadas fijas de columna (los encabezados no siempre están
  alineados con los datos); (2) `extract_tables()` de `pdfplumber` si el PDF
  sí tiene una grilla real; (3) un parseo línea por línea del texto plano,
  el más frágil, como último recurso. En los tres casos el **precio unitario
  se calcula como Importe ÷ Cantidad cuando la factura tiene una columna de
  Importe separada** (en vez de leer directo la columna de precio unitario):
  se detectó con una factura real (Label25/Distrisuper) que cuando la
  descripción es larga, el generador de la factura puede pisar el precio
  unitario con el final de la descripción (columnas apretadas, sin grilla),
  mientras que el importe —al ser la última columna, pegada al margen
  derecho— casi nunca se corrompe. También reconstruye descripciones que se
  envuelven en dos líneas dentro de una misma celda (PDF con grilla).
  Cada línea se matchea contra el catálogo por código exacto o, si no hay,
  por parecido de texto en la descripción (`difflib`), con un nivel de
  confianza (código / texto / sin match). Nunca actualiza el stock directo:
  siempre pasa por una pantalla de revisión (mismo formulario que "Nueva
  compra", precargado) donde cada línea tiene un check "Cargar" — las que no
  se pudieron matchear con confianza arrancan destildadas para forzar la
  revisión manual, tal como lo pidió Celes. Limitaciones conocidas: no lee
  PDFs escaneados como imagen (sin texto seleccionable, haría falta OCR,
  no implementado); la detección de proveedor y N° de factura es best-effort
  (busca el nombre del proveedor ya cargado en el texto de la factura); en
  facturas con la descripción realmente corrompida (superpuesta con el
  precio) la descripción reconocida puede quedar cortada — el código y el
  precio calculado por importe/cantidad siguen siendo confiables igual.
  Requiere `pdfplumber` (agregado a `requirements.txt` — correr
  `pip install -r requirements.txt` para tenerlo).
- **Crear proveedor desde la factura importada**: en la pantalla de revisión
  de `/compras/importar-factura`, si el proveedor no matchea con ninguno ya
  cargado, `importar_factura.py` también busca CUIT (regex), email y un
  candidato de razón social (la línea de texto justo arriba de donde
  aparece el CUIT) y los ofrece en un bloque "crear proveedor nuevo"
  editable — al confirmar la compra, el proveedor se crea junto con todo.
  El match automático por proveedor ahora prioriza CUIT (más confiable) y
  cae a buscar el nombre ya cargado en el texto si no hay CUIT o no matchea.
  La misma opción ("Es un proveedor nuevo") está en "Nueva compra" manual.
- **Proveedores activos/inactivos**: columna `activo` en `proveedores`
  (migración idempotente, default 1). En vez de borrar un proveedor con
  productos/compras/cotizaciones cargadas (rompería la referencia y tira
  `IntegrityError`, ahora capturado con un mensaje claro), se puede
  desactivar desde `/proveedores` — deja de aparecer para elegir en
  Nueva compra, la ficha de producto y la revisión de facturas importadas,
  pero no borra ni afecta nada de lo ya cargado. Se puede reactivar en
  cualquier momento. `/proveedores` muestra solo activos por defecto, con
  un link "ver también los desactivados". Los 3 proveedores de ejemplo
  originales (Frenos del Sur SA, Embragues Rosario SRL, Distribuidora
  Autopartes Litoral) ya están desactivados así, en vez de borrados —
  siguen ahí porque todavía sostienen los 14 productos de ejemplo; cuando
  se carguen los productos reales y se reemplacen esos 14, recién ahí se
  pueden borrar definitivamente si se quiere.
- **Lista de pedidos: solo lo vigente**: `/pedidos` ahora excluye productos
  con `stock_minimo = 0` (se usa como "no controlar reposición de esto
  todavía", útil para catálogo en revisión) y, si el proveedor con mejor
  precio o el proveedor de la ficha está desactivado, no lo muestra — no
  tiene sentido sugerir reponerle a un proveedor que ya no se usa. Si un
  producto no tiene ningún proveedor activo disponible (ni cotización ni
  ficha), se salta directamente en vez de caer en un grupo "sin proveedor".
- **Marcar pedido como realizado**: columnas `pedido_pendiente` y
  `fecha_pedido_pendiente` en `productos` (migración idempotente). Cada
  grupo de proveedor en `/pedidos` tiene un botón "Marcar todo esto como ya
  pedido" que saca esos productos de la lista de faltantes (no tiene
  sentido seguir viéndolos si ya se los pedimos). Quedan visibles en una
  sección aparte "Ya pedidos, esperando que lleguen", con un botón para
  desmarcar a mano si hace falta. La marca se limpia sola cuando se
  registra la compra (llegó la mercadería) — tanto desde "Nueva compra"
  como desde la revisión de una factura importada, porque las dos pasan por
  el mismo `compras_nueva()`.
- **Alta rápida de producto desde Nueva compra / revisión de factura**: el
  buscador de productos de esas dos pantallas ahora siempre muestra, al
  final de los resultados, la opción "Crear producto nuevo" (aunque haya
  matches, por si ninguno es el correcto). Abre un modal —mismo patrón que
  el alta rápida de cliente en Nueva venta— que llama a
  `/api/productos-nuevo` (POST) sin recargar la página ni perder la compra
  que se está cargando. El producto arranca con `stock_actual=0`: la propia
  compra le suma la cantidad al confirmarse. Precarga nombre y código desde
  la descripción/código de la factura cuando corresponde (incluso si la
  línea vino "sin match" y el buscador está vacío, enfocarlo ya sugiere
  crear el producto con esos datos), adivina la categoría por palabras
  clave (mismo criterio que `scripts/limpiar_lista_proveedor.py`) y sugiere el
  precio de venta con 30% de margen sobre el costo ya cargado en la fila,
  todo editable antes de guardar. Si el código ya existe, devuelve error en
  vez de romper (columna `codigo` es `UNIQUE`).

- **Planilla de stock real por proveedor**: para cuando llega una lista de
  precios y no se sabe de qué proveedor es (le pasó a Celes con una lista
  que le pasó la hermana). `scripts/generar_planilla_stock_proveedores.py`
  arma `plantillas/Planilla_Stock_Por_Proveedor.xlsx` con una hoja por cada
  proveedor ya cargado (activo) más una hoja "SIN IDENTIFICAR" para lo que
  no se pueda ubicar. Cada hoja tiene los campos relevantes para dar de alta
  un producto (Código, Categoría, Descripción, Marca, Modelo compatible,
  Precio costo, Precio venta, **Cantidad en stock real**, Stock mínimo,
  Código de barras) más un check "Cargar SI/NO". A diferencia de
  `scripts/limpiar_lista_proveedor.py` (que limpia un Excel de un proveedor
  puntual), esta planilla arranca en blanco para que alguien del negocio la
  complete a mano con lo que hay físicamente.
  `scripts/cargar_stock_por_proveedor.py` la importa: el proveedor de cada
  producto lo toma del nombre de la hoja (no hace falta una columna aparte),
  "Cantidad en stock" **reemplaza** el stock actual (no lo suma, a
  diferencia de una compra — es para cargar el estado real de una vez). Si
  hay filas en "SIN IDENTIFICAR", crea un proveedor placeholder "Proveedor
  sin identificar (revisar)" para no perder esos productos, avisando que
  hay que reasignarles el proveedor real después. Es idempotente (actualiza
  por código o nombre si ya existe).
  Uso (desde la raíz del proyecto): `python scripts/cargar_stock_por_proveedor.py [archivo.xlsx]`.
- **Lista de precios sin identificar (05/08/2026)**: se cargó como tercera
  hoja "SIN IDENTIFICAR" en `listas_proveedores/Lista_Proveedores_Limpia.xlsx`
  (junto a Roncal y Eine Frenos) una lista de precios enorme (34.815
  productos, no solo frenos/embragues — rodamientos, amortiguadores,
  líquidos, etc.) que llegó sin nombre de proveedor ni CUIT en el archivo.
  Quedaron 6.055 filas relevantes a frenos/embragues tras el filtro de
  siempre. Nuevo adaptador `adaptador_desconocido` en
  `scripts/limpiar_lista_proveedor.py` (usa "Costo IVA"
  como costo real, mismo criterio que el adaptador de Eine). Falta que
  alguien identifique de qué proveedor es (marcas: Wagner Lockheed, SKF,
  Monroe, Wildbrake, Cobreq, Griffo, Axios, VTH; columnas de stock por
  sucursal Pico/MDP/BA/ROS pueden ser una pista).
- **Categorías de producto editables**: dejaron de estar fijas en el código.
  Tabla `categorias` nueva (`nombre`, `activo`), sembrada al migrar con las
  iniciales (`db.CATEGORIAS_INICIALES` en `database.py`) más lo que ya
  hubiera cargado en productos que no estuviera en la lista. Se sumaron
  **Rodamientos** y **Amortiguadores** a las iniciales porque aparecieron
  mucho en la lista de precios sin identificar de arriba — se pueden borrar
  desde la pantalla si al final no se terminan vendiendo. Pantalla nueva
  `/categorias` (link en el navbar) para agregar categorías nuevas y
  activar/desactivar/eliminar, mismo patrón activo/inactivo que proveedores
  (no se puede borrar una categoría con productos cargados, hay que
  desactivarla). `db.obtener_categorias(conn, solo_activas=True)` es el
  punto único de lectura, usado en la ficha de producto, el catálogo de la
  tienda, el alta rápida de producto y
  `scripts/generar_planilla_stock_proveedores.py`.
  `scripts/importar_datos.py` valida contra las categorías cargadas en la
  tabla (ya no una lista fija) al importar la planilla de datos.
- **Menú reorganizado en desplegables**: la barra de navegación (`base.html`)
  agrupó Stock (Productos, Categorías) y Proveedores (Proveedores, Compras,
  Pedidos) en dos menús desplegables Bootstrap, para no seguir estirando la
  barra horizontal cada vez que se suma una pantalla nueva. Panel, Ventas y
  Clientes quedan como enlaces directos por ser los más usados.
- **Enviar comprobante por mail**: botón "Enviar por mail" en la pantalla de
  comprobante (`/ventas/<id>/enviar-mail`, solo visible si el cliente tiene
  email cargado). Genera el PDF del comprobante en el servidor —plantilla
  standalone `comprobante_pdf.html` (no reutiliza `comprobante.html` porque
  esa depende de Bootstrap/CDN y del navbar) renderizada a PDF con
  `xhtml2pdf` en `comprobante_pdf.py`— y lo manda por SMTP con
  `envio_mail.py`. Se eligió `xhtml2pdf` en vez de WeasyPrint/wkhtmltopdf a
  propósito: es 100% Python (usa reportlab), sin dependencias de sistema
  (Pango/Cairo/GTK) que haya que instalarle aparte al hermano en su compu.
  Mismo patrón defensivo que `facturacion_afip.py`/`tienda_pagos.py`: nunca
  lanza excepción, si falta configuración o falla el envío devuelve un
  mensaje de error y no afecta la venta ya registrada.
  **Pendiente para que mande de verdad**: completar `SMTP_HOST`,
  `SMTP_USER`, `SMTP_PASSWORD` en el `.env` (ver `.env.example`). Con Gmail,
  `SMTP_PASSWORD` tiene que ser una "contraseña de aplicación"
  (myaccount.google.com/apppasswords, necesita verificación en dos pasos
  activada), no la contraseña normal de la cuenta.
  Ya probado sin credenciales SMTP reales: que el botón solo aparece con
  email cargado, que sin configurar avisa en vez de romper, que el PDF se
  genera bien (logo, tabla de items, CAE/QR si es Factura A/B) y que el envío
  arma bien el mensaje (asunto, adjunto, destinatario) simulando el
  servidor SMTP. Falta probar el envío real en cuanto haya credenciales.
- **Subcategorías (jerarquía estricta, 06/08/2026)**: a pedido de Celes, que
  compartió una lista armada en otro chat con 7 rubros nuevos que no entraban
  bien en las categorías existentes (Rodamientos y Mazas, Suspensión y
  Dirección, Filtros, Retenes y Juntas, Transmisión, Motor, Ferretería). En
  vez de sumarlas como categorías sueltas, cada categoría ahora puede tener
  subcategorías propias — jerarquía estricta: una subcategoría siempre
  cuelga de una sola categoría padre. Tabla `subcategorias` nueva
  (`nombre`, `categoria_id` FK, `activo`, `UNIQUE(categoria_id, nombre)`);
  `productos` suma la columna `subcategoria` (TEXT libre, no FK — mismo
  criterio que ya se usaba para `productos.categoria`, para no romper el
  patrón denormalizado que ya recorre todo el código). Al migrar se siembran
  las categorías nuevas (`CATEGORIAS_INICIALES` en `database.py` ahora
  incluye los 7 rubros) con sus subcategorías (`SUBCATEGORIAS_INICIALES`), y
  las categorías viejas **Rodamientos** y **Amortiguadores** (sumadas hace
  poco, sección de arriba) se migran solas a
  `Rodamientos y Mazas → Rodamientos` y `Suspensión y Dirección →
  Amortiguadores` (`CATEGORIAS_REEMPLAZADAS_POR_SUBCATEGORIA`), reasignando
  los productos que ya las tuvieran cargadas y borrando la categoría vieja
  si quedó sin productos.
  `/categorias` ahora muestra cada categoría como una tarjeta con su tabla
  de subcategorías anidada (nombre, cantidad de productos, activa/
  desactivada, con los mismos botones activar/desactivar/eliminar que ya
  tenían las categorías) y un mini-formulario al pie para agregar una
  subcategoría nueva a esa categoría puntual.
  En la ficha de producto (`producto_form.html`), la ficha de compra
  (`compra_form.html`) y el alta rápida desde la revisión de una factura
  importada (`compra_revisar_factura.html`) el select de subcategoría se
  arma con JavaScript a partir de un mapa `categoría → [subcategorías]`
  (`subcategorias_por_categoria_json()` en `app.py`) y se repuebla solo
  cuando cambia la categoría elegida — el mismo patrón que ya usaba el
  buscador de productos por JSON embebido. Al editar un producto que tiene
  una subcategoría ya desactivada, esa opción se agrega igual a la lista
  para no perder el dato cargado (mismo criterio ya usado con categorías
  inactivas). `/api/productos-nuevo` (el alta rápida desde Nueva compra)
  ahora también guarda la subcategoría si se cargó una.
  Por ahora es solo estructura: el negocio todavía no vende filtros, motor,
  ferretería ni transmisión, así que **no** se tocó el filtro de rubros
  relevantes de `scripts/limpiar_lista_proveedor.py` (sigue filtrando solo
  frenos/embragues) — queda pendiente ampliarlo el día que el negocio
  confirme que va a vender esos rubros de verdad.
  Probado de punta a punta con un `data.db` de prueba (copia de la base
  real): la migración corre limpia sobre la base real, `/categorias`
  renderiza la jerarquía completa, se creó y editó un producto cambiando de
  subcategoría (`Rulemanes` → `Mazas de rueda`) y se confirmó que quedó bien
  guardado, el alta rápida vía `/api/productos-nuevo` guardó la
  subcategoría correctamente, y tanto `/compras/nueva` como la pantalla de
  revisión de una factura importada muestran el select y el JSON de
  subcategorías sin errores.
- **Taxonomía de subcategorías reemplazada por una más granular (06/08/2026)**:
  la hermana de Celes compartió `Planilla_Stock_Por_Proveedor_completa.xlsx`
  con una clasificación categoría+subcategoría hecha en otro chat sobre las
  listas de precios reales de 5 proveedores (~107.000 filas) — mucho más
  completa que la taxonomía simple armada antes en este mismo chat. Se
  reemplazó `SUBCATEGORIAS_INICIALES` en `database.py` por esas 33
  subcategorías (nueva función `_migrar_subcategorias_taxonomia_v2`,
  llamada desde `_migrar()`): por cada una de las 7 categorías cubiertas
  (`CATEGORIAS_CON_TAXONOMIA_V2`: Correas, Embragues, Frenos, Rodamientos y
  Mazas, Suspensión y Dirección, Transmisión, Motor) borra las
  subcategorías viejas que ya no están en la lista nueva —solo si ningún
  producto las tiene asignadas, para no perder datos reales— y agrega las
  que falten. Filtros, Retenes y Juntas y Ferretería no estaban cubiertas
  por ese trabajo, así que mantienen la taxonomía simple de antes. Probado
  sobre una copia de la base real: la migración corrió limpia (45→46
  subcategorías) y no había ningún producto real con subcategoría asignada
  todavía, así que no se perdió nada.
- **Catálogo de referencia de proveedores, sin cargarlo como stock
  (06/08/2026)**: de las 12 hojas de `Planilla_Stock_Por_Proveedor_completa.xlsx`,
  solo 5 (Distrisuper, Eine s.r.l, Miguel Angel Sen-Sei, Rio, Roncal
  Repuestos S.A) tenían datos — pero con "Cantidad en stock" y "Precio de
  venta" (ambos obligatorios) vacíos en el 100% de las 107.140 filas: es la
  lista de precios completa de cada proveedor, no el stock real del local.
  Cargarlas tal cual con `cargar_stock_por_proveedor.py` habría creado
  ~107.000 productos fantasma en stock 0 sin precio de venta (y solo un
  33% es Frenos/Embragues — el resto son rubros que el negocio "todavía
  no" vende). Decisión tomada con Celes: no tocar la base de productos con
  esto. Se armó `scripts/extraer_catalogo_referencia.py`, que separa solas
  las hojas "catálogo" (tienen descripción y costo, pero ninguna fila con
  stock real) de las que sí tendrían stock real, y arma
  `listas_proveedores/Catalogo_Referencia_Proveedores.xlsx` (una hoja por
  proveedor, solo código/categoría/subcategoría/descripción/marca/modelo/
  costo, sin tocar la base) para consultar el costo de un proveedor el día
  que se decida sumar ese producto de verdad. Usa `openpyxl` en modo
  `read_only`/`write_only` (en vez de celda por celda) porque con ~107.000
  filas la escritura celda por celda no entraba en el tiempo disponible en
  este entorno — con `write_only` sí. Las 7 hojas de proveedores todavía
  vacías (Deboto, Icepar, Michelli, Papierttei, RM, Rodamitre, Zerbini) en
  ese mismo archivo eran solo para mostrar la estructura de columnas, según
  aclaró Celes — no son stock real todavía, queda pendiente que se
  completen de verdad.
- **Seis mejoras implementadas en una tanda (08/08/2026)**, sobre un prompt
  de implementación que Celes ya había armado con Claude en otro chat,
  respetando los patrones ya existentes (migraciones idempotentes, alta
  rápida vía modal + `/api/...-nuevo`, módulos externos que nunca lanzan
  excepción):
  - **Filtro Categoría→Subcategoría + búsqueda general en `/productos`**:
    dos `<select>` (`categoria`, `subcategoria` — GET, combinables entre
    sí) arriba del buscador de texto libre que ya existía (`q`). El
    desplegable de subcategoría se repuebla en cascada con el mismo JSON
    (`subcategorias_por_categoria_json()`) que ya usaban la ficha de
    producto y el buscador de compras. **No hay un campo de marca/modelo
    aparte** (se probaron las dos variantes en el camino — primero marca,
    después un input de modelo dedicado — y las dos se sacaron): la
    búsqueda de auto compatible se resuelve escribiendo en el mismo `q` de
    siempre, que ahora también matchea contra `productos.modelo_compatible`
    además de nombre/código/marca/código de barras — así "Gol" encuentra
    "VW Gol / Voyage" sin exigir el campo completo. El JSON del buscador
    tipo autocompletar (`productos_para_buscador()`, reusado en Nueva
    venta/Nueva compra/revisión de factura/movimientos sin factura) también
    suma `modelo_compatible` a lo que indexa, por la misma razón.
  - **Columna "Mejor precio" en `/productos`**: informativa, sin selección
    manual — para cada producto muestra el proveedor activo con el
    `precio_costo` más bajo cargado en `producto_proveedor`, si hay
    alguno. La consulta que ya usaba `/pedidos` para elegir el proveedor
    más conveniente se extrajo a `db.obtener_cotizaciones_producto()` /
    `db.obtener_mejor_precio_por_producto()` en `database.py`, para no
    tener el mismo criterio de "mejor precio" duplicado en dos rutas — las
    dos pantallas llaman a la misma función.
  - **Ventas del día por medio de pago** (`/ventas/dia`, link nuevo desde
    `/ventas`): resumen agrupado por `metodo_pago` con cantidad y total,
    más el detalle de cada venta del día. Filtrable por fecha puntual
    (no solo "hoy") y por medio de pago (`?medio_pago=Tarjeta`, desplegable
    con los medios ya usados) — al filtrar por medio de pago, el resumen y
    el detalle quedan acotados a ese subconjunto, sin tocar el modelo de
    ventas ni el flujo de carga, es puramente de lectura. Para pagos mixtos
    (parte efectivo, parte tarjeta/transferencia) se suma la columna
    `ventas.id_operacion` (texto libre, opcional): se cargan dos ventas
    separadas con el mismo valor ahí y el conteo de "operaciones" las
    cuenta como una sola (`COUNT(DISTINCT COALESCE(id_operacion, 'v'||id))`)
    sin tocar el modelo de ventas — se completa a mano en un campo nuevo
    de `venta_form.html`, con la explicación de uso ahí mismo.
  - **Cuenta corriente de clientes** (columna `clientes.tipo_cliente`
    `particular`/`mecanico`; tabla `cuenta_corriente_movimientos`;
    pantalla `/clientes/<id>/cuenta-corriente`, accesible desde un ícono en
    `/clientes` solo para clientes tipo "mecánico"): registra cargos y
    pagos con saldo acumulado. Cada cargo dispara una Factura A o B (según
    la condición IVA del receptor, ver más abajo), reutilizando ARCA: se
    separó `facturacion_afip.emitir_factura()` en una llamada cruda a ARCA
    (`_emitir_factura_arca()`, sin tocar ninguna tabla) más el guardado
    específico de cada caso — `emitir_factura()` sigue escribiendo en
    `ventas` exactamente como antes, y `emitir_factura_movimiento()`
    escribe en `cuenta_corriente_movimientos` (mismas columnas
    `cae`/`cae_vencimiento`/`facturacion_estado`/`facturacion_error`/
    `imp_neto`/`imp_iva`/`tipo_comprobante` que ya tenía `ventas`). Mismo
    criterio defensivo de siempre: nunca bloquea el movimiento si ARCA
    falla, con botón de reintento igual al que ya tenía el comprobante de
    una venta. Si el monto de un cargo supera
    `facturacion_afip.UMBRAL_IDENTIFICACION_RECEPTOR` (constante con nota
    de que ARCA la cambia por resolución y hay que revisarla contra la
    normativa vigente) y no hay ningún CUIT/DNI para identificar al
    receptor, el sistema no deja registrar el cargo hasta que se cargue uno.
    - **Rediseño a pedido de Celes tras la primera versión (09/08/2026)**:
      la primera versión tenía tres problemas de uso real. (1) Un cargo
      solo podía tener un producto y no descontaba stock — pero si el
      mecánico se lleva el repuesto, el producto ya salió del local aunque
      todavía no se haya cobrado. Ahora un cargo es una lista de productos
      (tabla nueva `cuenta_corriente_movimiento_items`, mismo patrón que
      `venta_items`, con el mismo buscador tipo autocompletar que Nueva
      venta/Nueva compra) y **descuenta stock al confirmarse**, igual
      criterio que una venta al contado (el stock baja cuando el producto
      sale, no cuando se termina de cobrar). (2) La factura se emitía
      siempre a nombre del cliente/mecánico dueño de la cuenta — pero en la
      práctica el mecánico a veces compra en nombre de un tercero con su
      propio CUIT/DNI (ej. "José compra a nombre de Marta", la factura
      corresponde a Marta). Columnas nuevas `tercero_cuit_dni` y
      `tercero_condicion_iva`: si se carga el CUIT/DNI del tercero,
      `emitir_factura_movimiento()` factura a nombre de ese tercero (con su
      propia condición IVA, no la del mecánico) en vez del cliente/mecánico;
      `cliente_tercero_nombre` (ya existía) sigue de referencia visual en
      los dos casos. (3) No había forma de ver rápido quién debía más —
      pantalla nueva `/clientes/top-deudores` (link desde `/clientes` y
      desde cada cuenta corriente), top 5 por saldo pendiente
      (`SUM(cargos) - SUM(pagos)`) entre los clientes con movimientos
      cargados.
    - **Cuenta corriente disponible para cualquier cliente + saldo visible
      en la lista (09/08/2026)**: la restricción original de arriba (ícono
      hacia `/clientes/<id>/cuenta-corriente` visible "solo para clientes
      tipo mecánico") era una limitación artificial de la interfaz, no del
      backend — las rutas (`cuenta_corriente_ver`, `cuenta_corriente_nueva`,
      `/clientes/top-deudores`) ya eran genéricas y nunca filtraron por
      `tipo_cliente`. Se sacó ese gate solo en `templates/clientes.html`: el
      ícono ahora se muestra para cualquier cliente. `tipo_cliente`
      (`particular`/`mecanico`) se mantiene, pero pasa a ser puramente
      informativo (una etiqueta/badge), ya no condiciona nada funcional. El
      motivo es de negocio: un cliente particular también puede terminar
      debiendo plata, no es exclusivo de los mecánicos. Se sumó además una
      columna "Saldo" a `/clientes` (`core/app.py`, función
      `clientes_lista()`), calculada con el mismo criterio que ya usaba
      `/clientes/top-deudores` (`SUM(cargos) - SUM(pagos)` vía
      `LEFT JOIN cuenta_corriente_movimientos` + `GROUP BY`) en vez de
      duplicar esa lógica con una regla distinta. La celda solo muestra un
      monto (en rojo) cuando el cliente debe de verdad (`saldo > 0`); queda
      vacía si nunca tuvo movimientos, está saldado o tiene saldo a favor.
      Decisión documentada en
      `docs/superpowers/specs/2026-08-09-cuenta-corriente-todos-los-clientes-design.md`.
  - **Ranking de clientes + descuentos aprobados** (`/clientes/top`, link
    nuevo desde `/clientes`): mismo cálculo de top 5 que ya tenía el panel
    de analítica, pero con período elegible (30/90/365 días o histórico) y
    una columna de margen estimado (con el costo *actual* de cada
    producto — aproximación aclarada en la pantalla, no es un número
    contable exacto). Desde ahí se puede "Aplicar promoción" a un cliente:
    tablas nuevas `promociones_aplicadas` (porcentaje o monto fijo, alcance
    todo el catálogo o productos puntuales, vigencia con fecha de inicio y
    fin opcional, queda quién la aprobó) y `promocion_productos` (tabla
    intermedia para el alcance puntual). `registrar_venta()` llama a la
    función nueva `aplicar_promociones()` antes de calcular el total: los
    descuentos porcentuales se aplican por ítem alcanzado, los de monto
    fijo (solo con alcance "todo") se prorratean sobre el total de la
    venta. Se aplica igual en la venta del local que en la de la tienda
    online (mismo `registrar_venta()`).
  - **Compras/ventas sin factura** (tabla nueva `movimientos_no_facturados`;
    pantalla `/stock/no-facturado`, link nuevo en el menú Stock): para
    movimientos de stock que no ameritan pasar por una compra/venta formal
    ni por AFIP. Alta con el mismo buscador de productos tipo autocompletar
    que ya usaban Nueva venta/Nueva compra. Al confirmar, sí impacta
    `productos.stock_actual` (+cantidad si es compra, -cantidad si es
    venta, validando que no quede negativo) — es la misma columna de
    stock de siempre, la separación es solo en cómo se *registra* la
    operación, no en el stock resultante. Campo `conciliado` (checkbox)
    para marcar a mano si después se terminó cargando también como
    compra/venta facturada normal (para no duplicar el efecto sobre stock,
    revisión manual, no automática).
  - **`scripts/matchear_productos_proveedores.py`** (offline, no lo llama
    la app): puebla `producto_proveedor` automáticamente matcheando las
    listas de precios de varios proveedores (un Excel con una hoja por
    proveedor, mismo formato que ya usan `generar_planilla_stock_proveedores.py`/
    `extraer_catalogo_referencia.py` — encabezados detectados por nombre,
    no por posición fija, para servir a los dos) contra el catálogo ya
    cargado en `productos`. Matching en orden: código de barras exacto
    primero, si no hay o no matchea cae a similitud de texto por
    descripción (`difflib`, mismo criterio que `importar_factura.py`)
    filtrando por igual categoría. Nunca toca `productos` ni stock, solo
    `producto_proveedor` (y crea el proveedor si el nombre de la hoja
    todavía no existe). Corre en modo simulación por defecto (no escribe
    nada en la base) — hace falta `--aplicar` para que persista. Guarda un
    reporte (`listas_proveedores/Reporte_Matching_Proveedores.xlsx`) con
    cada fila y por qué método matcheó o si quedó sin match, para auditar
    antes de confiar en el resultado a escala completa; admite
    `--categoria`/`--subcategoria` para pilotear en un rubro chico primero
    (ej. Frenos → Pastillas) antes de correrlo sobre un archivo con miles
    de filas. **No probado contra listas de precios reales todavía** (no
    hay ninguna en este repo, son datos del negocio fuera de control de
    versiones) — sí probado de punta a punta con un Excel sintético de una
    hoja: matcheó por descripción, dejó sin match lo que no correspondía,
    creó el proveedor nuevo y generó bien el reporte.
  - Probado de punta a punta contra una base de prueba (copia de la
    demo): las 6 migraciones nuevas corren limpias, las 15 rutas
    principales (incluida la tienda pública) responden 200 con sesión
    iniciada, se creó un cliente mecánico, se le cargó un movimiento de
    cuenta corriente (quedó `facturacion_estado='sin_configurar'`, igual
    que con ventas sin `AFIPSDK_ACCESS_TOKEN`), se le aplicó una promoción
    del 10% y una venta nueva a ese cliente aplicó el descuento
    correctamente, dos ventas con el mismo `id_operacion` se contaron como
    una sola operación en `/ventas/dia`, y un movimiento de stock sin
    factura sumó el stock esperado.

## Migración a Postgres (13/08/2026) — Plan 1 de 2

Hasta acá el sistema corría sobre SQLite (`data.db`, un archivo local). Se
migró completo a Postgres, sobre [Supabase](https://supabase.com) como
proveedor: local corre contra el Postgres que levanta la CLI de Supabase en
Docker, y en producción apuntaría al Postgres alojado por Supabase. El
motivo es el próximo paso del roadmap (desplegar en Vercel, ver "Plan 1 de
2" al final de esta sección): Vercel corre el código en funciones
serverless sin disco persistente, así que un archivo SQLite local
simplemente no sobrevive entre invocaciones — hace falta una base de datos
de verdad, alcanzable por red, y Supabase da esa base (Postgres) más,
cuando se ejecute el Plan 2, autenticación y storage de archivos sin sumar
otro proveedor más.

Qué cambió, para quien conocía el sistema por su versión en SQLite:

- **El esquema ya no lo crea `database.py`**: vive en
  `supabase/migrations/` (un archivo SQL versionado por migración, aplicado
  por la CLI de Supabase). `core/database.py` pasó a ser solo conexión +
  helpers de consulta/siembra de datos de ejemplo — ver el docstring al
  principio del archivo.
- **La plata es `NUMERIC(12,2)`, no `REAL`**: psycopg devuelve esas
  columnas como `Decimal` de Python, nunca `float`. Toda conversión desde
  un formulario pasa por `a_decimal()` (helper en `core/app.py`) — nunca
  `float()` en una columna de plata. Esto no es un detalle cosmético: un
  `float()` reintroducido en un cálculo de plata **no lo va a atrapar
  ningún test de integración**, porque el cast de Postgres de `float8` a
  `numeric(12,2)` absorbe el error de redondeo para montos realistas, y
  psycopg siempre devuelve `Decimal` de una columna NUMERIC sin importar
  qué tipo escribió el código que insertó. La única forma de cazar esa
  regresión es leyendo el código o con un test unitario del helper en sí
  (ver `tests/test_database_helpers.py` / los tests de `a_decimal` en
  `tests/test_clientes_productos.py`), no con un test que solo mira lo que
  quedó guardado en la base.
- **Las fechas son tipos de fecha reales** (`DATE`/`TIMESTAMPTZ`), no texto.
  Python trabaja con objetos `date`/`datetime` de verdad en vez de strings
  armados a mano.
- **Búsquedas case-insensitive usan `ILIKE`, no `LIKE`**: en SQLite `LIKE`
  ya era case-insensitive para ASCII; en Postgres no, así que un `LIKE`
  suelto en una búsqueda es un buscador roto en silencio para cualquier
  texto con mayúsculas.

### Desarrollo local

1. `npx supabase start` — levanta Postgres (y el resto de los servicios de
   Supabase) en contenedores Docker locales. Imprime la cadena de conexión;
   por default queda en
   `postgresql://postgres:postgres@127.0.0.1:54322/postgres`, que es el
   default que ya trae `core/database.py` si no se define `DATABASE_URL`.
   `npx supabase stop` la apaga; `npx supabase db reset` vuelve a aplicar
   todas las migraciones de `supabase/migrations/` desde cero (borra los
   datos locales).
2. Variable de entorno `DATABASE_URL`: apunta a esa cadena de conexión (o a
   la del Postgres real en producción). `python app.py` la lee igual que
   antes leía la ubicación de `data.db`.
3. En `supabase/config.toml`, `[analytics] enabled = false` está apagado a
   propósito: en la máquina donde se hizo la migración los contenedores
   analytics/vector (Logflare) no arrancaban (un problema conocido de la
   CLI de Supabase, no de este proyecto) y bloqueaban `npx supabase start`.
   Nada de este sistema usa Analytics/Logflare, así que se apagó en vez de
   perseguir el problema — ver el comentario en el propio archivo.

### Gotcha de `prepare_threshold=None` (importante, rompe recién en producción)

`core/database.py` conecta con `psycopg.connect(DATABASE_URL, row_factory=dict_row,
prepare_threshold=None)`. Ese último parámetro **no es opcional**: psycopg
activa "prepared statements" en el servidor a partir de la quinta vez que
ejecuta la misma consulta, como optimización. El pooler de Supabase en modo
transacción (el que se usa en producción para no agotar conexiones) no
soporta prepared statements, porque cada consulta puede caer en una
conexión física distinta del pool. Sin `prepare_threshold=None`, el sistema
anda perfecto en desarrollo (Postgres local, sin pooler) y en las primeras
requests de producción, y recién empieza a tirar errores cuando una
consulta puntual llega a su quinta ejecución — un bug que aparece tarde,
de forma intermitente, y sin relación obvia con el cambio que lo causó.
Si en algún refactor futuro se agrega una conexión a mano en vez de usar
`db.get_connection()`, hay que repetir este parámetro.

### Suite de tests

`tests/` (pytest). `tests/conftest.py` define `db_conn` (conexión con
rollback automático al final de cada test, para no ensuciar la base) y un
fixture `autouse` que, después de cada test, deja la base como recién
migrada (trunca todas las tablas y resiembra `categorias`/`subcategorias`)
— hace falta porque algunos tests de ruta necesitan commitear de verdad
para que la conexión propia del `test_client` de Flask vea los datos.

Correrla (con `npx supabase start` ya levantado):

```
python -m pytest tests/ -v
```

Por default apunta al mismo Postgres local de arriba
(`postgresql://postgres:postgres@127.0.0.1:54322/postgres`); se puede
apuntar a otra base con la variable `DATABASE_URL_TEST`. `tests/test_rutas.py`
es la red de seguridad más amplia: recorre las rutas GET principales del
sistema (logueado y sin loguear) y solo verifica que ninguna devuelva un
error de servidor — no reemplaza a los tests más específicos de cada
pantalla, que sí verifican números (stock, totales, Decimal exacto, etc.).

### Plan 1 de 2

Esta migración (a la que nos referimos acá como "Plan 1") deja el sistema
corriendo completo sobre Postgres, con la suite de tests de respaldo, y
sigue funcionando local con `python app.py` exactamente igual que antes.
**Todavía no está desplegado en ningún lado** — sigue siendo un sistema que
corre en la compu del local — y el login **sigue siendo el propio**, con la
tabla `usuarios` y `password_hash` (no se tocó nada de autenticación en
esta migración).

El Plan 2 (a escribir en `docs/superpowers/plans/` después de este) cubre
lo que falta para desplegarlo de verdad en Vercel: migrar el login a
Supabase Auth, mover las fotos de producto (`static/img/productos/`) a
Supabase Storage (Vercel tampoco tiene disco persistente para eso),
`vercel.json`, `ProxyFix` (necesario detrás del proxy de Vercel — ver el
gotcha de `Host`/CSRF ya anotado en la sección de Seguridad más abajo),
activar `SESSION_COOKIE_SECURE`, cargar las variables de entorno de
producción, y el deploy en sí. Precondiciones humanas de ese plan (ninguna
hace falta para lo que ya está hecho acá): crear el proyecto en Supabase,
crear el proyecto en Vercel y conectarlo al repositorio, cargar las
variables de entorno ahí, y crear el primer usuario admin desde el panel
de Supabase una vez que el login use Supabase Auth.

## Estructura

```
frenos_embragues_app/
├── app.py                    # shim de una línea: `from core.app import app`
│                               (existe para que `python app.py` y el CMD de
│                               Docker/gunicorn sigan funcionando igual)
├── core/                      # el núcleo del sistema en sí
│   ├── app.py                   # rutas y lógica (Flask) — el archivo grande
│   ├── database.py              # esquema + migraciones + datos de ejemplo
│   ├── facturacion_afip.py      # integración Afip SDK (Factura A/B)
│   ├── tienda_pagos.py          # integración Mercado Pago (tienda online)
│   ├── comprobante_pdf.py       # genera el PDF del comprobante (xhtml2pdf)
│   ├── envio_mail.py            # envío del comprobante por mail (SMTP)
│   └── importar_factura.py      # lector de facturas de compra (PDF/Excel/CSV)
│
├── scripts/                  # herramientas de línea de comandos, se corren
│   │                           a mano de vez en cuando (no las usa la app)
│   ├── importar_datos.py               # carga plantillas/Plantilla_Carga_Datos.xlsx
│   ├── limpiar_lista_proveedor.py      # limpia una lista de precios cruda de un proveedor
│   ├── generar_planilla_stock_proveedores.py  # genera la planilla de stock por proveedor
│   ├── cargar_stock_por_proveedor.py   # importa esa planilla a la base
│   ├── extraer_catalogo_referencia.py  # separa listas de precios completas (no stock real)
│   │                                     de esa misma planilla, sin tocar la base
│   └── archivo/                        # scripts de un solo uso, ya cumplieron su función
│       └── cargar_ejemplo_proveedores.py
│
├── plantillas/                # Excels que completa el negocio a mano
│   ├── Plantilla_Carga_Datos.xlsx           # carga inicial de datos reales
│   └── Planilla_Stock_Por_Proveedor.xlsx    # carga de stock real por proveedor
│
├── listas_proveedores/        # listas de precios de proveedores (datos del
│                                 negocio, no se suben al repositorio)
│
├── supabase/                  # Postgres local (ver "Migración a Postgres")
│   ├── config.toml               # config de la CLI de Supabase
│   └── migrations/               # esquema versionado (SQL), reemplaza lo
│                                    que antes creaba database.py a mano
│
├── tests/                     # suite de pytest (ver "Migración a Postgres")
│   ├── conftest.py               # fixtures compartidas (db_conn, limpieza)
│   └── test_*.py
│
├── docs/                      # documentación técnica y funcional completa
│   ├── DOCUMENTACION_TECNICA.md
│   └── DOCUMENTACION_FUNCIONAL.md
│
├── templates/                 # pantallas (Bootstrap 5, Chart.js en el dashboard)
├── static/                    # CSS/imágenes, incluye fotos de producto subidas
├── Dockerfile                 # imagen para desplegar en cualquier hosting (gunicorn) —
│                                 desactualizada tras la migración a Postgres, ver
│                                 "Dockerización" más abajo
├── docker-compose.yml         # ídem
├── requirements.txt
├── .env.example                # plantilla de variables de entorno (copiar a .env),
│                                  ahora incluye DATABASE_URL
├── README.md                   # guía rápida de instalación y uso
└── CLAUDE.md                   # este archivo: memoria técnica del proyecto
```

Los scripts de `scripts/` siempre se corren desde la **raíz del proyecto**
(no desde adentro de la carpeta `scripts/`), por ejemplo:
`python scripts/importar_datos.py`. Cada uno tiene el uso exacto en su
docstring inicial.

**El core como paquete (`core/`, 06/08/2026):** los 7 módulos que antes
vivían sueltos en la raíz (`app.py`, `database.py`, etc.) se movieron a
`core/` como paquete de Python (`core/__init__.py`). El `app.py` de la raíz
quedó como un *shim* de una sola línea (`from core.app import app`) para no
tener que cambiar `python app.py`, el `CMD` del `Dockerfile`
(`gunicorn app:app`) ni ninguna instrucción del README — todo eso sigue
funcionando exactamente igual. `templates/` y `static/` **no** se movieron
adentro de `core/` (siguen en la raíz), así que `core/app.py` le pasa
`template_folder`/`static_folder` absolutos a `Flask()` en vez de dejar que
adivine solo. Los imports entre estos 7 módulos pasaron a ser relativos
(`from . import database as db`), y los tres paths que se calculaban con
`__file__` asumiendo "la carpeta de este archivo es la raíz del proyecto"
(`database.INSTANCE_DIR`, `app.CARPETA_IMAGENES_PRODUCTOS`,
`comprobante_pdf.RAIZ_PROYECTO`) se corrigieron para subir un nivel más.
Los scripts de `scripts/` que usan la base ahora importan
`from core import database as db` en vez de `import database as db` (el
`sys.path.insert` al principio de cada uno sigue apuntando a la raíz del
proyecto, sin cambios). Probado con gunicorn después del movimiento: la app
levanta, sirve `/login` y `/tienda`, encuentra los templates y los estáticos
(logo, CSS), y genera el PDF del comprobante correctamente (dependía de
encontrar el logo en `static/` desde `core/comprobante_pdf.py`). También se
corrieron los 4 scripts de `scripts/` de punta a punta contra el nuevo
import y funcionaron igual que antes.

Correr la app: `python app.py` → http://127.0.0.1:5050 (sigue igual)

## Pendientes / roadmap

Orden acordado con Celes (actualizado 04/08/2026):

1. ~~Comparador de precios de proveedores~~ — **listo**.
2. ~~Login de usuarios~~ — **listo**. Falta, si hace falta más adelante,
   sumar 2FA (quedó anotado en la sección de seguridad).
3. ~~Facturación electrónica AFIP/ARCA~~ — **código listo**, ver la sección
   dedicada más abajo. Falta un solo paso para que factura de verdad: crear
   la cuenta gratuita en app.afipsdk.com y completar el `.env` con el
   `access_token` (no es algo que se pueda hacer en nombre del negocio).
4. **Cargar datos reales**: ya está la planilla y el importador. Falta que el
   hermano la complete con clientes, productos y proveedores reales.
5. ~~Tienda online propia~~ (reemplaza la idea de integrar Tiendanube) —
   **código listo**, ver la sección dedicada más abajo. Falta lo mismo que
   con AFIP: que el negocio cree su cuenta de Mercado Pago y, para probar el
   cobro de punta a punta, una URL pública (ngrok mientras no haya hosting).
6. **Integración con Mercado Libre**: quieren vender por ML y que el stock se
   mantenga sincronizado. Es viable vía API (ver sección siguiente). A
   diferencia de la tienda propia, acá sí hay dos stocks que sincronizar
   porque ML es una plataforma externa.
7. **Analítica más profunda**: rentabilidad por producto, rotación/lentitud
   de stock, estacionalidad, segmentación de clientes (esto es también lo que
   más le interesa a Celes como ejercicio de análisis de datos).
8. **Hosting**: hoy corre local. ~~Migrar a Postgres~~ — **listo** (13/08,
   ver "Migración a Postgres" más arriba), era el paso previo necesario
   para este punto porque Vercel no tiene disco persistente para SQLite.
   El camino de despliegue elegido es Vercel + Supabase, no el Docker de
   la sección "Dockerización" de abajo (esa sección quedó desactualizada,
   ver la nota al principio). Falta el Plan 2 completo: Supabase Auth,
   Supabase Storage para las fotos, `vercel.json`, `ProxyFix`,
   `SESSION_COOKIE_SECURE`, variables de entorno de producción y el deploy
   en sí. Con la tienda online ya lista, este paso se vuelve más urgente:
   Mercado Pago necesita una URL pública para el webhook de pagos (se puede
   probar con ngrok mientras tanto, ver sección de la tienda). También
   dispara el resto de la sección de seguridad (HTTPS, cookies seguras, 2FA).
9. **Conexión con sistemas de proveedores**: la mayoría de los distribuidores
   de autopartes en Argentina no tiene API pública; el camino realista es
   importar sus listas de precios (Excel/CSV) para actualizar costos en
   lote — se puede combinar con el comparador de precios del punto 1.

## Facturación electrónica AFIP/ARCA (implementada, falta la cuenta real)

**Corrección importante (09/08/2026)**: hasta acá este archivo y el código
de facturación asumían que el negocio era monotributista y por eso solo
emitían Factura C. Celes aclaró que el negocio es **Responsable Inscripto**
(coherente con "alta IVA 12-2024" en la identidad del negocio, que ya
estaba anotado arriba pero no se había cruzado con esta sección). Como
Responsable Inscripto no hay excepción de "siempre el mismo tipo de
comprobante": corresponde **Factura A** cuando el receptor también es
Responsable Inscripto con CUIT cargado, o **Factura B** en cualquier otro
caso (Consumidor Final, Monotributista, Exento, o sin documento) — nunca
Factura C. Se reimplementó `facturacion_afip.py` para elegir A/B según
`clientes.condicion_iva` y discriminar IVA (21%, tasa general) en la
llamada a ARCA. La regla de *cuándo* facturar sigue siendo la misma que
pidió el negocio originalmente: efectivo → remito interno (ya
implementado), tarjeta/transferencia → factura electrónica por ARCA (antes
siempre C, ahora A o B según corresponda). Limitación conocida y avisada:
el sistema no consulta el padrón de AFIP, así que "es Responsable
Inscripto" es lo que se cargue a mano en la ficha del cliente — si esa
condición está mal cargada, la factura sale con el tipo equivocado; no es
responsabilidad de este sistema validarlo contra AFIP.

Camino técnico elegido: **Afip SDK** (afipsdk.com) en vez de integración
directa con el WSFE de ARCA. Motivo: mismo resultado funcional (CAE, QR,
PDF) con muchísimo menos trabajo (evita manejar certificados X.509, tokens
WSAA que vencen cada 12hs y SOAP/XML a mano), tiene un modo de desarrollo con
CUIT de prueba compartido (no hace falta certificado real para empezar a
programar), y el plan gratuito (1 CUIT, 1.000 requests/mes) probablemente
alcance para todo el volumen de este negocio sin pagar nada. Si lo superan,
el siguiente escalón es 25 USD/mes por 10.000 requests.

Se descartó TusFacturasAPP como alternativa: es un sistema de gestión
completo con la facturación incluida, pensado para reemplazar un sistema
propio — no tiene sentido pagarlo (arranca en ~22 USD/mes) cuando ya existe
este sistema y solo hace falta la conexión con ARCA.

Implementado: ver el bloque correspondiente en "Estado actual" más arriba
(`facturacion_afip.py`, migración de `ventas`, ruta de reintento, QR en el
comprobante). Único pendiente real: que el hermano cree la cuenta gratuita en
app.afipsdk.com y complete `AFIPSDK_ACCESS_TOKEN` en un `.env` local (ver
`.env.example`), primero probando en modo test con el CUIT de prueba
compartido antes de pasar al CUIT real del negocio.

## Tienda online propia (implementada, falta la cuenta real + URL pública)

Alcance elegido con Celes para esta primera versión: **catálogo + checkout
con pago online** (de tres opciones ofrecidas — solo catálogo, catálogo +
pedido por WhatsApp, o esto — se prefirió ir directo al pago online en vez
de un paso intermedio más chico).

Decisión de arquitectura clave (coherente con el punto 3 de la visión de
producto — "una sola fuente de verdad, no dos sistemas separados que haya
que sincronizar"): la tienda **no tiene su propio inventario de pedidos
paralelo**. `pedidos_web`/`pedido_web_items` son solo una tabla de "carrito
en tránsito" mientras se espera la confirmación del pago; en cuanto Mercado
Pago confirma que se pagó, el webhook llama a la misma función
`registrar_venta()` que usa la pantalla de Nueva venta del local — mismas
tablas `ventas`/`venta_items`, mismo stock, mismo criterio de Factura A/B
automática (tarjeta/transferencia/Mercado Pago → Factura A o B, según el
receptor). Así el stock
online y el del local literalmente no se pueden desincronizar: son la misma
fila de la misma tabla.

Camino técnico elegido: **Mercado Pago Checkout Pro** (paquete oficial
`mercadopago` para Python). Se arma una "preferencia" de pago server-side
con los items del pedido y se redirige al comprador a la página de pago
alojada por Mercado Pago (no hay que tocar tarjetas ni datos sensibles de
pago en este sistema). La confirmación real del pago llega por **webhook**
(`/webhooks/mercadopago`), nunca por las URLs de vuelta del navegador —
siguiendo la recomendación oficial de Mercado Pago, porque el comprador
puede cerrar la pestaña antes de volver. El SDK trae un validador de firma
(`mercadopago.webhook.WebhookSignatureValidator`) que se usa si se configura
`MERCADOPAGO_WEBHOOK_SECRET`.

Estructura:
- `tienda_pagos.py`: `tienda_configurada()`, `crear_preferencia(pedido_id)`,
  `obtener_pago(payment_id)`, `validar_firma_webhook(...)`. Igual que
  `facturacion_afip.py`, nunca lanza excepciones hacia afuera del checkout —
  si falta configuración, el checkout avisa que el cobro online no está
  disponible todavía (con el WhatsApp del negocio como alternativa) en vez
  de romperse.
- Rutas públicas nuevas en `app.py` (eximidas del login vía el prefijo
  `/tienda` y `/webhooks/` en `verificar_sesion()`): `/tienda` (catálogo),
  `/tienda/carrito` (sesión de Flask, sin login), `/tienda/checkout` (arma
  el `pedido_web` + la preferencia y redirige a Mercado Pago),
  `/tienda/pedido/<id>/exito|pendiente|fallo` (informativas, no confían en
  el resultado), `/webhooks/mercadopago` (confirma el pago, genera la venta
  real, es idempotente por si Mercado Pago reintenta la notificación).
- `registrar_venta()` en `app.py` se extrajo de la lógica que ya tenía
  `ventas_nueva()` para que la compartan ambos flujos.
- Si el comprador no existe todavía como cliente (por email o teléfono), el
  webhook crea uno automáticamente con los datos que dejó en el checkout
  (incluye un campo opcional de CUIT/DNI; sin `condicion_iva` explícita el
  comprador online queda en Consumidor Final por default, así que sale
  Factura B — nunca se le va a emitir Factura A a un comprador de la
  tienda sin que alguien confirme a mano que es Responsable Inscripto).

**Pendiente real para que cobre de verdad** (dos cosas, ninguna la puede
hacer este asistente en nombre del negocio):
1. Que el hermano cree la aplicación en el panel de Mercado Pago
   (developers.mercadopago.com) y complete `MERCADOPAGO_ACCESS_TOKEN` en el
   `.env`.
2. Una URL pública HTTPS en `STORE_BASE_URL` — Mercado Pago no puede llamar
   a `127.0.0.1`. Mientras el sistema corre solo local, se puede probar con
   ngrok; el paso definitivo es el mismo punto 8 del roadmap (hosting).

Ya probado sin necesitar credenciales reales de Mercado Pago: la migración
de la base, el catálogo, el carrito (sesión), que el checkout no se rompe
si falta configuración, y que el webhook procesa correctamente un pago
"aprobado" simulado (genera la venta, descuenta stock, dispara Factura A/B).
Falta probar el flujo real de Checkout Pro (redirección + webhook real) en
cuanto haya `access_token` + URL pública.

## Dockerización (escrita para SQLite, desactualizada tras la migración a Postgres)

**Nota (13/08/2026)**: toda esta sección se escribió cuando el sistema
corría sobre SQLite y describe un mecanismo (volumen `SI_INSTANCE_DIR` con
`data.db`) que ya no existe en el código — `database.py` ya no define
`INSTANCE_DIR`/`DB_PATH`/`CREDENCIALES_PATH` (ver "Migración a Postgres"
más arriba), así que el `Dockerfile`/`docker-compose.yml` actuales fijan
una variable de entorno (`SI_INSTANCE_DIR`) que el código ya no lee. La
imagen probablemente todavía compile y corra (gunicorn no depende de eso),
pero la promesa de persistencia que describe esta sección (SQLite en un
volumen) ya no aplica: la persistencia real ahora es el `DATABASE_URL`
apuntando a Postgres. Se dejó la sección tal cual (sin reescribirla) porque
el plan de deploy real ya no es este camino Docker/VPS sino Vercel (ver
Plan 2 en "Migración a Postgres" más arriba, que define `vercel.json` en
vez de esto) — conviene decidir si este Dockerfile se actualiza, se
reemplaza por el path de Vercel, o se elimina, en vez de parchearlo a
ciegas acá.

Objetivo original: empaquetar el sistema para poder subirlo a cualquier lado (Render,
Railway, Fly.io, un VPS propio, etc.) sin depender de la compu del local —
es el paso técnico que destraba el punto 8 del roadmap (Hosting).

Archivos nuevos:
- `Dockerfile`: imagen basada en `python:3.11-slim`, instala
  `requirements.txt` y corre la app con **gunicorn** (no con
  `app.run(debug=True)`, que es solo para desarrollo local).
- `docker-compose.yml`: para probar todo el paquete local antes de subirlo a
  un hosting (`docker compose up --build`). Cada hosting después tiene su
  propia forma de construir la imagen y declarar volúmenes, este archivo es
  auxiliar.
- `.dockerignore`: mismo criterio que `.gitignore` (no manda datos del
  negocio ni el entorno virtual a la imagen).

Cambio de código necesario para que esto funcione sin perder datos:
`database.py` ahora define `INSTANCE_DIR` (variable de entorno
`SI_INSTANCE_DIR`, default: la carpeta del proyecto — o sea, corriendo local
con `python app.py` nada cambia). `DB_PATH`, `CREDENCIALES_PATH` (en
`database.py`) y `.secret_key` (en `app.py`) viven todos ahí. El
`Dockerfile` fija `SI_INSTANCE_DIR=/app/data`, y `docker-compose.yml` monta
`./data` como volumen sobre esa carpeta — así la base, la clave de sesión y
`credenciales_iniciales.txt` sobreviven a que se recree el contenedor (por
ejemplo, al desplegar una versión nueva). Las fotos de producto
(`static/img/productos/`) se montan como volumen aparte, sin necesitar
ningún cambio de código (ya era una carpeta propia).

**Importante para cuando se elija el hosting**: esto asume un volumen de
disco de verdad. Varios hostings "gratis" con contenedores (por ejemplo el
plan free de Render) borran el disco en cada redeploy o reinicio si no se
contrata explícitamente un "persistent disk" — en esos casos SQLite pierde
todo. Conviene elegir un hosting que soporte un volumen persistente real
(Railway y Fly.io lo soportan en su plan gratuito/básico; un VPS propio
también) antes de mudar el sistema ahí de forma definitiva.

Ya probado sin Docker instalado en este entorno (no está disponible acá):
se corrió la app con gunicorn directamente (mismo comando que usa el
`Dockerfile`) apuntando `SI_INSTANCE_DIR` a una carpeta temporal, y se
confirmó que crea ahí `data.db`, `.secret_key` y
`credenciales_iniciales.txt`, y que gunicorn sirve la app correctamente
(`/login` responde 200). Sin `SI_INSTANCE_DIR` seteada seguía usando la
carpeta del proyecto, igual que antes. Falta probar el build de la imagen
y el `docker compose up` reales en una compu que tenga Docker instalado.

## Seguridad (temas marcados por Celes, priorizados por cuándo aplican)

Ya resuelto:

- Login por usuario con contraseña hasheada, bloqueo por intentos fallidos,
  cambio de contraseña obligatorio en el primer ingreso (ver sección de
  Login y usuarios más arriba).
- `app.secret_key` generada al azar y guardada fuera del código
  (`.secret_key`).
- Protección CSRF (`Flask-WTF`) en todos los formularios y en los 3
  `fetch()` de alta rápida (clientes/productos), con excepción del webhook
  de Mercado Pago (server-to-server, no lleva sesión de navegador). Errores
  de token muestran un mensaje en español en vez de una página técnica.

Pendiente, en orden de cuándo se vuelve necesario:

1. **Backups**: antes de la migración a Postgres (ver "Migración a
   Postgres" más arriba) era copiar `data.db` a mano a Drive/Dropbox. Con
   Postgres/Supabase esto cambia: Supabase hace backups automáticos del
   proyecto alojado (con retención según el plan), así que lo pendiente acá
   es más bien confirmar qué plan de Supabase se va a usar en producción y
   qué retención de backups incluye, no seguir copiando un archivo a mano.
   Sigue pendiente en local (el Postgres que levanta `npx supabase start`
   no tiene backups automáticos, pero tampoco es donde vive el dato real
   del negocio una vez desplegado).
2. **Credenciales de ARCA/Afip SDK y de Mercado Pago**: ya resuelto en el
   código — todos los tokens (`AFIPSDK_ACCESS_TOKEN`, `MERCADOPAGO_ACCESS_TOKEN`,
   `MERCADOPAGO_WEBHOOK_SECRET`, certificados si algún día se pasa a
   producción) se leen de variables de entorno vía `.env` (`.env.example`
   documenta cuáles), nunca hardcodeados ni pegados en el chat, y `.env`
   está en `.gitignore`. Falta el paso humano: cargar los tokens reales una
   vez que existan las cuentas. Si alguno se llega a exponer, se considera
   comprometido y hay que rotarlo desde el panel correspondiente.
3. **Preparar el sistema para internet** (ya se vuelve necesario ahora que
   la tienda online está lista — Mercado Pago necesita webhooks públicos):
   HTTPS vía el hosting, activar `SESSION_COOKIE_SECURE`, límite de
   intentos de login (ya está, pero revisar que siga siendo suficiente con
   tráfico público), nunca correr Flask con `debug=True` en producción.
   Gotcha ya anotado para cuando llegue ese momento: con HTTPS activo,
   `WTF_CSRF_SSL_STRICT` de Flask-WTF (default `True`) va a exigir además un
   header `Referer` del mismo origen en cada POST — un cliente que lo
   suprima (por ejemplo con `Referrer-Policy: no-referrer`) va a ver el
   error de "página desactualizada" de CSRF en cada envío, algo que hoy no
   pasa porque el sistema corre por HTTP local. No es algo para resolver
   ahora, solo una alerta a tener en cuenta junto con el resto de los
   puntos de HTTPS de este ítem. Otro gotcha para ese momento: el chequeo
   de mismo origen que usa `manejar_csrf_error` (el handler de errores
   CSRF, en `core/app.py`) compara contra `request.host`, que sale del
   header `Host` de la request — si el hosting elegido pone el sistema
   detrás de un reverse proxy sin configurar `ProxyFix` o una lista de
   hosts de confianza, ese header se puede falsificar. No aplica hoy
   (corre local, sin proxy), pero conviene revisarlo al elegir el hosting
   definitivo (punto 8 del roadmap).
4. **2FA**: no es prioritario mientras el sistema corra solo en la compu del
   local. Se vuelve razonable sumarlo cuando quede expuesto a internet.
   Técnicamente sencillo de agregar (`pyotp` + un campo de código de un
   solo uso en el login).

## Notas sobre la integración con Mercado Libre

Confirmado que es posible por API:

- Se actualiza el stock con un `PUT /items/{item_id}` modificando el campo
  `available_quantity`. Si queda en 0, la publicación pasa a `paused` con
  subestado `out_of_stock`.
- Requiere crear una aplicación en el panel de desarrolladores de ML para
  obtener **Client ID** y **Client Secret**, y autenticar por **OAuth 2.0**
  (access token + refresh token).
- Importante: la aplicación debe crearse con la cuenta **titular** del negocio
  (no una cuenta personal de prueba) para evitar problemas de transferencia.
  En Argentina hace falta validar los datos del titular antes de poder crear
  la app.
- **Cambio vigente desde el 18/03/2026**: las requests que actualizan
  únicamente el campo `price` son rechazadas con 400. Si se manda `price`
  junto a otros atributos, se procesa con 200 pero el precio se ignora y
  devuelve un warning. Conclusión: **la sincronización de precios hacia ML no
  funciona por este endpoint**, solo la de stock. Hay que buscar el camino
  alternativo para precios cuando se llegue a esa etapa.
- Para que el stock baje también cuando la venta ocurre *en ML* (y no en el
  sistema), hay que consumir las notificaciones/webhooks de órdenes de ML.

## Preferencias de trabajo

- Celes itera el proyecto en **VS Code** sobre
  `/Users/celescaa/Documents/frenos_embragues_app`. Los archivos se editan
  directo en esa carpeta; VS Code recarga solo.
- Responder en español, conciso y directo.
