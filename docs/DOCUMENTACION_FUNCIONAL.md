# Documentación funcional — Repuestos San Ignacio

Qué hace el sistema en términos de negocio: pantalla por pantalla, qué
problema resuelve, qué reemplaza del proceso con Excel y cuánto tiempo o
dolor de cabeza ahorra. Pensada para el hermano de Celes y quien use el
sistema en el día a día, no hace falta saber programar para leerla.

Para el detalle técnico (cómo está construido, qué hace cada archivo) ver
`docs/DOCUMENTACION_TECNICA.md`.

## El problema que había antes

Todo el negocio funcionaba con un Excel: sin control de stock real, sin
historial de clientes, sin forma de saber qué se vendió más, y sin ninguna
alerta cuando algo se estaba por terminar. Cada venta, cada compra y cada
dato de cliente dependía de que alguien lo escribiera bien a mano en la
fila correcta — un solo archivo, sin backups automáticos, que además no se
podía usar al mismo tiempo por dos personas sin pisarse los cambios.

## Quién usa el sistema

- **Administrador** (el hermano, o quien haga las veces de dueño del
  sistema): además de todo lo de un empleado, puede crear/gestionar
  usuarios.
- **Empleado**: vende, carga compras, gestiona clientes y stock — todo
  excepto la gestión de usuarios.

Cada uno entra con su propio usuario y contraseña, así queda registrado
quién cargó cada cosa (algo que con un Excel compartido no existía).

## Pantalla por pantalla

### Panel (dashboard)
Un vistazo del negocio al abrir el sistema: ventas del mes, ventas
históricas, un gráfico de ventas por mes, los 5 productos más vendidos, los
5 mejores clientes y una alerta de qué está por debajo del stock mínimo.

**Antes:** para saber "cómo venimos este mes" había que sumar filas de
Excel a mano, o llevar una cuenta aparte. **Ahora:** es lo primero que se
ve al entrar, sin calcular nada. Ahorra tener que armar (o directamente no
tener) un resumen mensual.

### Ventas
Cargar una venta con varios productos a la vez, elegir cliente (o
Consumidor Final), medio de pago y tipo de comprobante. Al confirmar:
descuenta stock automáticamente, genera el comprobante y — si el medio de
pago es tarjeta o transferencia — dispara la Factura C electrónica sola,
sin que nadie tenga que acordarse de facturar aparte.

Incluye un campo de **escaneo con pistola lectora de código de barras**:
se apunta al producto, se aprieta el gatillo, y el producto se agrega solo
a la venta (si ya estaba en la lista, suma una unidad). También tiene alta
rápida de cliente nuevo sin salir de la pantalla, para no perder la venta
que se está cargando.

**Antes:** anotar la venta en Excel, restar el stock a mano en otra fila
(fácil de olvidarse u equivocarse), y facturar aparte si correspondía.
**Ahora:** una sola carga hace las tres cosas. Con la pistola lectora,
cargar una venta de varios productos pasa de "buscar cada uno por nombre y
tipear la cantidad" a algo del orden de segundos.

### Comprobante de venta
Se genera automáticamente al confirmar una venta: remito/recibo interno
para efectivo, o Factura C con CAE y código QR de ARCA para tarjeta/
transferencia. Se puede imprimir, guardar como PDF desde el navegador, o
**mandar por mail al cliente** con un solo botón (si tiene el mail cargado).

**Antes:** comprobante a mano o inexistente. **Ahora:** un documento
profesional, con la identidad del negocio, en el momento — y sin tener que
copiarlo a mano para mandarlo por mail.

### Stock (productos)
Alta, edición y baja de productos: categoría, marca, modelo compatible,
costo, precio de venta, stock actual y mínimo, código de barras, foto.
Alerta visual en rojo cuando algo está en o por debajo del mínimo. Desde la
ficha del producto también se cargan las cotizaciones de distintos
proveedores para el mismo producto (ver "Pedidos" más abajo).

**Antes:** el stock "real" vivía en la cabeza de alguien o se estimaba. No
había forma sistemática de saber qué faltaba hasta que un cliente lo pedía
y no estaba. **Ahora:** el sistema avisa solo antes de que se termine.

### Categorías
Antes eran cinco categorías fijas escritas en el código (Frenos, Embragues,
Correas, Líquidos, Otros). Ahora hay una pantalla (`/categorias`) para
agregar una categoría nueva en el momento que se empiece a vender algo que
no encaja en las que ya hay, sin que nadie tenga que tocar código ni pedir
un cambio en el sistema.

Cada categoría, además, puede tener sus propias subcategorías para
clasificar mejor sin que la lista principal se haga interminable — por
ejemplo "Suspensión y Dirección" agrupa "Amortiguadores", "Bujes",
"Parrillas", etc. Al cargar o editar un producto, primero se elige la
categoría y la lista de subcategorías se arma sola con las que corresponden
a esa categoría. Tanto categorías como subcategorías se pueden desactivar
(dejan de aparecer para elegir en productos nuevos, pero no se pierde lo ya
cargado) o eliminar si no tienen ningún producto asignado.

**Ahorra:** el tiempo de ida y vuelta de pedir un cambio de código cada vez
que el catálogo de productos crece, y evita que el listado de categorías se
vuelva una lista larga y desordenada a medida que se suman rubros nuevos.

### Clientes
Alta, edición, búsqueda y baja, con teléfono, mail, dirección y CUIT/DNI
(usado para la Factura C — sin CUIT/DNI cargado, la factura sale a
Consumidor Final).

**Antes:** buscar un cliente en Excel era un `Ctrl+F` con suerte. **Ahora:**
buscador instantáneo, y el historial de compras de cada cliente queda
asociado automáticamente (se ve en el Panel, "top clientes").

### Proveedores y Compras
Registrar una compra repone el stock del producto y actualiza su costo
automáticamente. Los proveedores que ya no se usan más se **desactivan**
en vez de borrarse (para no perder el historial de compras/productos que
todavía dependen de ellos) — quedan fuera de los desplegables de "elegir
proveedor" pero se pueden reactivar en cualquier momento.

**Importar factura de compra**: en vez de tipear cada línea de una factura
de un proveedor a mano, se sube el PDF/Excel/CSV y el sistema reconoce
productos, cantidades y precios solo, dejando todo precargado en una
pantalla de revisión donde cada línea se confirma (o se corrige) antes de
que impacte en el stock — nunca actualiza nada sin que alguien lo revise.
Si el producto de una línea no existe todavía, se puede dar de alta ahí
mismo sin perder la carga de la factura.

**Antes:** cargar una factura de 20-30 líneas a mano llevaba minutos por
línea, con margen de error en cada una. **Ahora:** el sistema arranca el
trabajo, la persona solo revisa y confirma — el ahorro de tiempo crece con
el tamaño de la factura (una factura grande es donde más se nota).

### Pedidos (reposición a proveedores)
Arma automáticamente la lista de qué hay que reponer: toma los productos
en o por debajo del stock mínimo, los agrupa por el proveedor **más
barato** entre los cargados para cada producto (no por un proveedor fijo),
sugiere cuánto pedir y calcula el costo estimado — con un cartel de cuánto
se ahorra comprando siempre al más conveniente. Se puede marcar un pedido
como "ya hecho" para que no siga apareciendo como pendiente hasta que
llegue la mercadería (se limpia solo al registrar la compra).

**Antes:** revisar a ojo qué faltaba, a mano, sin comparar precios entre
proveedores salvo que alguien se acordara de hacerlo. **Ahora:** la lista
se arma sola, ya optimizada por precio, lista para mandarle a cada
proveedor (se puede imprimir o guardar como PDF).

### Tienda online (`/tienda`)
Catálogo público (sin necesidad de usuario ni contraseña) con los productos
que tienen stock, filtros por categoría/marca/modelo/precio, carrito y
cobro con Mercado Pago. Comparte el mismo stock que la venta del local —
cuando se vende algo por acá, es la misma base que se actualiza, no un
sistema aparte que haya que sincronizar a mano.

**Antes:** no existía canal de venta por internet (se había arrancado una
tienda en Tiendanube que no se terminó). **Ahora:** un canal de venta
nuevo, sin duplicar el trabajo de mantener el stock en dos lugares.

### Facturación electrónica (AFIP/ARCA)
Automática para ventas con tarjeta o transferencia (ver "Ventas" arriba).
Si por algún motivo no se pudo emitir (por ejemplo, sin la cuenta de AFIP
SDK configurada todavía), la venta igual queda registrada y se puede
reintentar la facturación después con un botón, sin perder nada.

**Antes:** facturar (si se facturaba) era un trámite aparte, manual.
**Ahora:** es un paso automático de la venta misma.

### Usuarios (solo administrador)
Crear un usuario por empleado, resetear contraseñas olvidadas, desactivar
a alguien que deja de trabajar en el local (sin perder su historial de
ventas cargadas).

**Antes:** un Excel compartido sin ningún control de quién cambió qué.
**Ahora:** cada persona con su propio acceso, y trazabilidad de quién cargó
cada venta/compra.

## Herramientas de carga masiva (para arrancar o migrar datos grandes)

Estas no son pantallas del sistema, son scripts que se corren una vez (o de
vez en cuando) para cargar volúmenes grandes de datos sin tipear todo a
mano — documentadas en detalle en `docs/DOCUMENTACION_TECNICA.md`, sección
6. En términos de negocio, resuelven:

- **Cargar todos los clientes/productos/proveedores reales de una sola
  vez** desde un Excel, en vez de darlos de alta uno por uno desde la
  pantalla (ahorra horas cuando se arranca con el sistema o se migra un
  Excel viejo).
- **Limpiar una lista de precios de miles de productos de un proveedor**
  (algunas listas reales usadas en este proyecto tenían más de 30.000
  filas) y quedarse solo con lo relevante al rubro, con precio de venta ya
  calculado — sería impensable revisar eso fila por fila a mano.
- **Levantar el stock real inicial** cuando alguien del negocio (sin acceso
  al sistema) completa una planilla a mano con lo que hay físicamente en el
  local, organizada por proveedor.

## Qué pasa si algo se cae (AFIP, Mercado Pago, el mail)

Ninguna de estas tres integraciones puede bloquear una venta. Si ARCA no
responde, si Mercado Pago no está configurado, o si no hay credenciales de
mail: el sistema avisa con claridad que esa parte puntual no se pudo hacer,
pero la venta ya está guardada y se puede reintentar la parte que falló más
tarde, sin perder nada ni tener que cargar todo de nuevo.

## Resumen: qué gana el negocio con esto

- Un solo lugar para clientes, stock y ventas — no tres Excels o una
  memoria compartida.
- Alertas de stock automáticas en vez de darse cuenta cuando ya faltó.
- Pedidos a proveedores armados solos y con el mejor precio.
- Facturación electrónica sin trámite manual.
- Un canal de venta online que no duplica trabajo.
- Historial completo de quién compró qué, cuándo, y a quién se le compró
  cada producto — la base para cualquier análisis futuro (rentabilidad por
  producto, estacionalidad, etc., ver el roadmap en `CLAUDE.md`).
