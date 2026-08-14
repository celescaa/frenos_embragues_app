# Buscador de productos con filtros (rubro, marca, auto compatible)

**Fecha**: 2026-08-14
**Estado**: aprobado, listo para plan de implementación

## Contexto

Celes compartió tres fotos del buscador **Lupa** (`lupa.distrisuper.com`), el
sistema de un distribuidor mayorista, porque a su hermano le resulta cómodo
para buscar repuestos. Lo que ese sistema tiene:

1. Buscador de texto grande, con cuatro filtros al lado: Rubros, Líneas
   (marcas de repuesto), Marca y Modelo (de auto).
2. Los rubros y las marcas se eligen desde una **grilla visual con fotos y
   logos**, no desde un desplegable.
3. Cada resultado es **un repuesto**, no un producto suelto: una descripción,
   el auto compatible, y al costado las **varias marcas que lo fabrican con
   el código de cada una** (VTH 5939 / UNDERCAR UB02062 / AXIOS AXI044.1243).
4. La fila trae el stock a la vista, un `- 0 +` y un botón PEDIR: buscar y
   pedir son la misma pantalla.

**De eso, Celes descartó explícitamente el punto 2**: no quiere el diseño con
imágenes ("no me gusta el diseño"). Lo que sí quiere es **poder ir
seleccionando rubro y filtrando en cascada** para que a su hermano le resulte
lo más fácil posible encontrar algo.

El **punto 3 entró después**, al preguntar Celes qué era: el negocio sí llega a
tener la misma pieza en varias marcas al mismo tiempo, así que agruparlas
tiene sentido. Entra como fase 6, en la versión barata (grupos de
equivalencia), no como concepto de "pieza" por encima de los productos.

Estado actual del sistema, para dimensionar el cambio:

- `/productos` ([templates/productos.html](../../../templates/productos.html))
  ya tiene filtros de categoría y subcategoría, pero hay que apretar
  "Filtrar", no dicen cuántos productos hay en cada uno, y no se puede
  filtrar por marca ni por auto.
- `productos.marca` y `productos.modelo_compatible` son **texto libre** en la
  ficha del producto. El auto compatible se escribe todo junto en un renglón
  (`VW Gol / Voyage 1.6`), así que no hay forma de armar un desplegable
  prolijo de autos ni de responder "mostrame todo lo que sirve para Palio".
- El criterio de "buscar un producto" está escrito **tres veces**: en
  `productos_lista()` (SQL con `ILIKE`), en `productos_para_buscador()` (JSON
  embebido en el HTML, filtrado por JavaScript) y en el catálogo de la
  tienda. Ya divergieron entre sí.
- Nueva venta manda **todos los productos embebidos en el HTML** de la
  página. Con los 29 productos de prueba no se nota; con los ~6.000 reales de
  las listas de proveedores esa pantalla se vuelve pesada.

## Decisiones tomadas con el usuario

- **Dónde**: el buscador va en **Nueva venta** (el caso del mostrador) y en
  **Stock** (`/productos`), más el catálogo de la **tienda online**. Queda
  explícitamente **fuera de alcance** un buscador para comprarle a
  proveedores (cruzar las listas de precios de los 13 proveedores), que se
  ofreció y se descartó.
- **Sin grilla de fotos**: los filtros son controles comunes, con el mismo
  Bootstrap que el resto del sistema.
- **Filtros pedidos**: rubro y subrubro, marca del repuesto, auto compatible,
  y un tilde de "sólo lo que hay en stock".
- **El auto va estructurado**, separado de la descripción. Celes marcó que la
  descripción del proveedor ya suele traer el auto adentro
  (`BUJE SOPORTE PARRILLA FIAT PALIO`), y que está bueno que quede aparte.
- **El motor es obligatorio en el auto; el año es opcional** y no importa si
  queda sin llenar ("el motor si tiene que ir si o si, si quiere pone el año
  no importa si no se llena").
- **La búsqueda tiene que ser a prueba de errores de tipeo y de formato**:
  "tiene que ser a prueba de nabo esto, gente que no usa programas y les
  cuesta". Eso se interpretó como cuatro requisitos concretos, detallados más
  abajo (mayúsculas, acentos, orden de las palabras, errores de tipeo).
- **Se entrega por fases**, no todo junto, para que si el hermano dice "así
  no" se corrija antes de haberlo replicado en tres pantallas.
- **Las marcas del mismo repuesto se agrupan** (fase 6), porque el negocio
  llega a tener la misma pieza en varias marcas a la vez. Se hace con grupos
  de equivalencia, no con un concepto de "pieza" por encima de `productos`.
- **Los contadores cuentan productos, no grupos.** Celes lo confirmó
  explícitamente: tres marcas del mismo buje son tres bujes. Ver el porqué en
  la fase 6.

## Fuera de alcance

- **El concepto de "pieza" como entidad propia** (la pieza se busca y se
  vende, y los productos son "la versión Cobreq de esa pieza"). Tocaría
  stock, ventas, compras y tienda. La fase 6 resuelve la misma necesidad
  visible con una etiqueta que sólo mira el buscador.
- **Buscador contra las listas de precios de proveedores**. Descartado
  explícitamente al elegir dónde va el buscador.
- **Grillas visuales de rubros y marcas con imágenes.** Descartado
  explícitamente.
- **Año/motorización como filtro.** El año se guarda (opcional) pero no se
  usa como filtro en esta etapa; filtrar por año se puede sumar después sin
  cambiar el modelo.

## Modelo de datos

Tres tablas nuevas en la fase 1, más una cuarta en la fase 6.
**Ninguna columna existente se borra ni se renombra**; la única que se agrega
a una tabla que ya existe es `productos.grupo_equivalencia_id`, opcional.

```sql
marcas (
    id      INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    nombre  TEXT NOT NULL UNIQUE
);

vehiculos (
    id          INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    marca_auto  TEXT NOT NULL,          -- FIAT
    modelo      TEXT NOT NULL,          -- Palio
    motor       TEXT NOT NULL,          -- 1.4  |  "Todos los motores"
    anio_desde  INTEGER,                -- opcional
    anio_hasta  INTEGER,                -- opcional
    activo      BOOLEAN NOT NULL DEFAULT true,
    UNIQUE (marca_auto, modelo, motor)
);

producto_vehiculos (
    id           INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    producto_id  INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    vehiculo_id  INTEGER NOT NULL REFERENCES vehiculos(id),
    UNIQUE (producto_id, vehiculo_id)
);

-- fase 6, migración aparte
grupos_equivalencia (
    id      INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    nombre  TEXT NOT NULL          -- "Buje parrilla delantera Palio/Siena"
);
-- y en productos:
--   grupo_equivalencia_id INTEGER REFERENCES grupos_equivalencia(id)
```

Las decisiones detrás de esa forma, con su porqué:

- **`productos.marca` sigue siendo TEXT.** La tabla `marcas` es únicamente la
  fuente del desplegable y de la normalización; el producto sigue guardando
  el nombre de la marca como texto. Es exactamente el patrón que el sistema
  ya usa con `categorias`/`subcategorias` (tabla para administrar, columna
  denormalizada en `productos`). No se introduce un patrón nuevo para esto.
- **Los autos sí necesitan tabla intermedia**, porque un producto sirve para
  varios autos. Ahí no hay forma de denormalizar sin volver al texto libre,
  que es justamente lo que se viene a resolver.
- **`productos.modelo_compatible` no se toca ni se borra.** Sigue existiendo
  como texto libre para todo lo que todavía no esté estructurado, y la
  búsqueda de texto lo sigue mirando. Así nada de lo ya cargado deja de
  encontrarse el día que se aplique la migración, y la fase 5 puede ir
  estructurando de a poco sin apuro.
- **`motor` es NOT NULL, con el valor explícito `"Todos los motores"`** para
  el repuesto que sirve para cualquier motor de ese auto. La alternativa
  (dejarlo vacío) obliga a decidir en cada consulta si vacío significa "no
  sé" o "cualquiera"; la otra alternativa (tildar los cuatro Palio uno por
  uno) multiplica el trabajo de carga. Un valor explícito no es ambiguo y se
  carga una sola vez.
- **`anio_desde`/`anio_hasta` se guardan pero no filtran** en esta etapa. Son
  columnas opcionales desde el arranque justamente para no tener que recargar
  los autos el día que se quiera filtrar por año.
- **`ON DELETE CASCADE` sólo del lado de `productos`**: borrar un producto
  se lleva sus vínculos; borrar un vehículo usado por algún producto tiene
  que fallar, igual que hoy falla borrar un proveedor con productos
  (se desactiva con `activo`, no se borra).

### Qué hace la migración al aplicarse

1. Crea las tres tablas.
2. Habilita las extensiones `unaccent` y `pg_trgm` (Supabase las trae, no hay
   que instalar nada).
3. Crea el índice trigram sobre los campos de texto de `productos` que se
   buscan. **Sin ese índice, cada búsqueda con `ILIKE '%algo%'` recorre la
   tabla entera** — invisible con 29 productos, un problema real con 6.000.
4. Crea la función `sembrar_marcas_desde_productos()`, que agrega a `marcas`
   las que falten y devuelve cuántas agregó. Es idempotente y queda
   disponible para volver a correrla cuando se importe el catálogo real, no
   sólo en esta migración. Que sea una función y no un `INSERT` suelto es lo
   que permite **probarla con un test** en vez de confiar en que salió bien.
5. **La llama, sembrando `marcas` con los valores distintos de `productos.marca`**,
   agrupando de forma insensible a mayúsculas, acentos y espacios sobrantes:
   `COBREQ`, `Cobreq` y `cobreq ` entran como **una sola** marca. Si no, el
   desplegable "prolijo" termina siendo tres veces la misma marca, y es peor
   que el texto libre que vino a reemplazar.
6. **`vehiculos` arranca vacía.** Se llena en la fase 5, con revisión humana.
   Una migración no adivina datos del negocio.

## Búsqueda: una sola función

El criterio de búsqueda pasa a estar escrito **una vez**, en
`core/database.py`, junto a `obtener_categorias()`:

```python
db.buscar_productos(conn, q=None, categoria=None, subcategoria=None,
                    marca=None, vehiculo_id=None, solo_con_stock=False,
                    limite=None)
```

Las tres pantallas (Stock, Nueva venta vía API, tienda) llaman a esta
función y a ninguna otra. Hoy cada una tiene su propio criterio y ya
divergieron; unificarlas es parte del objetivo, no un refactor aparte.

Y su hermana para los contadores:

```python
db.facetas_productos(conn, ...los mismos filtros...)
# -> {"categoria": {"Frenos": 128, ...}, "marca": {...}, "subcategoria": {...}}
```

Devuelve, para cada opción de cada filtro, cuántos productos quedarían
**con los demás filtros ya aplicados**. Si eligió "Palio", el rubro Frenos
muestra cuántos frenos hay para Palio, no cuántos frenos hay en total. Es lo
que evita que el usuario entre a un rubro y se encuentre con la lista vacía.

### Los cuatro requisitos de "a prueba de nabo"

Los cuatro viven **dentro de `buscar_productos()`**, no en cada pantalla, así
que ninguna pantalla busca mejor que otra.

1. **No distingue mayúsculas ni acentos.** `hidraulico` encuentra
   `HIDRÁULICO`; `bujia` encuentra `BUJÍA`. Se resuelve comparando sobre
   `unaccent(...)` con `ILIKE`. En Postgres `LIKE` **sí** distingue
   mayúsculas (a diferencia de SQLite, de donde viene este proyecto), así que
   un `LIKE` suelto acá es un buscador roto en silencio.
2. **No importa el orden de las palabras.** Lo que se tipea se parte en
   palabras y **cada palabra** tiene que aparecer en algún campo del
   producto, en cualquier orden. Hoy se busca la frase literal: `palio
   pastilla` no devuelve nada aunque exista `PASTILLA DE FRENO FIAT PALIO`.
3. **Aguanta un error de tipeo.** Si la búsqueda no devuelve nada, se ofrecen
   los parecidos ("¿quisiste decir *pastilla*?") usando la similitud de
   `pg_trgm`. Es una sugerencia, no un reemplazo automático: no se le cambia
   al usuario lo que buscó sin avisarle.
4. **Los espacios de más no molestan.** Se normalizan antes de buscar.

Los campos sobre los que busca el texto libre: `nombre`, `codigo`, `marca`,
`modelo_compatible`, `codigo_barras`, y los autos vinculados
(`marca_auto`/`modelo` de `producto_vehiculos`). El `codigo_barras` sigue
matcheando **exacto**, no por parecido: es lo que dispara el escaneo con la
pistola y un match aproximado ahí sería un producto equivocado en la venta.

## Fase 2 — Los filtros en Stock (`/productos`)

Una barra arriba de la tabla: **Rubro · Subrubro · Marca · Auto (marca →
modelo/motor) · ☐ Sólo con stock · buscador de texto**.

- **Aplican solos**, sin botón "Filtrar", y quedan en la dirección de la
  página (`?categoria=Frenos&vehiculo_id=12`). Así el botón "atrás" del
  navegador funciona y la búsqueda se puede guardar en favoritos. El
  buscador de texto espera a que deje de tipear antes de recargar, para no
  disparar una consulta por cada tecla.
- **Cada opción muestra cuántos hay** (`Frenos (128)`), calculado con
  `facetas_productos()`.
- **Los filtros activos se ven como etiquetas con una X** para sacarlos de a
  uno, más "Limpiar todo". Es lo que evita el clásico "no aparece nada"
  cuando quedó un filtro puesto de la búsqueda anterior — el caso más
  probable de confusión para alguien que no usa programas.
- **Subrubro y modelo/motor se repueblan en cascada** con un mapa JSON
  embebido, el mismo patrón que ya usan la ficha de producto y el filtro de
  subcategoría actual.
- **Tope de 200 resultados**, con el aviso `Mostrando 200 de 1.340 — afiná el
  filtro`. Con 6.000 productos, dibujar la tabla completa cuelga el
  navegador. El aviso dice la verdad en vez de aparentar que hay 200.

La ficha de producto (`producto_form.html`) suma la sección para vincular
autos: elegir marca/modelo/motor de la lista y agregarlos, con la opción de
crear un vehículo que todavía no exista (mismo patrón de alta rápida por
modal que ya usan cliente y producto).

**Las marcas no tienen pantalla propia.** En la ficha del producto, `marca`
sigue siendo un campo de texto pero con la lista de marcas ya usadas sugerida
al costado, y **al guardar el producto su marca se agrega sola a la tabla**
(normalizada, sin duplicar por mayúsculas ni acentos). Así la lista del
filtro nunca queda desactualizada respecto de los productos, y no hay una
pantalla más que mantener. Por eso `marcas` tampoco lleva columna `activo`:
no hay dónde tocarla, y una marca deja de aparecer cuando ningún producto la
usa. Decidido con Celes al armar el plan, reemplaza la pantalla `/marcas` que
figuraba en la primera versión de este documento.

Los autos **sí** llevan pantalla propia `/vehiculos`, porque un vehículo se
carga con tres datos (marca, modelo, motor) y no se puede deducir de un campo
de texto del producto. Va en el menú desplegable Stock, que ya agrupa
Productos y Categorías.

## Fase 3 — Nueva venta

Botón **"Buscar repuesto"** que abre un panel con la misma barra de filtros;
al tocar un resultado se agrega a la venta y el panel se cierra.

- **El buscador por texto que ya está no se toca.** Cuando el hermano sabe el
  código o escanea con la pistola, ese sigue siendo el camino más rápido; el
  panel es para "necesito pastillas para un Palio".
- **El escaneo de código de barras tiene que seguir funcionando igual**,
  tanto el de la pantalla de venta como el listener global de consulta de
  precio. Es requisito de no-regresión, con test.
- El panel pide los resultados a un endpoint nuevo **`/api/buscar-productos`**
  (GET, JSON, mismos parámetros que `buscar_productos()`), en vez de tener
  todos los productos embebidos en el HTML. Eso arregla de paso el peso de
  esa pantalla con el catálogo real.
- El endpoint pide sesión iniciada, como el resto de `/api/...`.

Las otras pantallas que hoy usan `productos_para_buscador()` (Nueva compra,
revisión de factura importada, movimientos sin factura, cuenta corriente)
**siguen como están** en esta fase. Migrarlas al endpoint es una mejora
aparte, no un requisito de este trabajo.

## Fase 4 — Tienda online

La misma barra de filtros en `/tienda`, reemplazando los botones de categoría
actuales. Sin costo ni stock exacto: sólo "hay" / "no hay".

## Fase 5 — Detección del auto desde la descripción

`scripts/detectar_vehiculos.py` (offline, no lo llama la app): lee las
descripciones ya cargadas, propone `marca_auto`/`modelo`/`motor`, y **escribe
una planilla para revisar**. Nada se aplica a la base sin `--aplicar`, igual
que `matchear_productos_proveedores.py`. Es el mismo criterio del lector de
facturas: lo que se reconoce automáticamente pasa siempre por revisión
humana antes de tocar datos del negocio.

## Fase 6 — Equivalencias entre marcas

El negocio llega a tener la misma pieza en varias marcas al mismo tiempo (el
buje de Palio en Cobreq y en VTH, por ejemplo). Hoy son productos separados
sin nada que los relacione: quien busca "buje palio" ve dos filas sueltas y
tiene que darse cuenta solo de que son lo mismo.

**Se resuelve con un grupo, no con vínculos de a pares.** Todos los productos
que comparten `grupo_equivalencia_id` son equivalentes entre sí. Con vínculos
de a pares, marcar `Cobreq ≡ VTH` y `VTH ≡ Axios` y olvidarse de
`Cobreq ≡ Axios` deja el grupo incompleto y el buscador muestra una marca de
menos **sin avisar**; con un grupo eso es imposible por construcción: o el
producto está en el grupo o no está.

**El grupo es sólo una etiqueta que mira el buscador.** No tiene stock, ni
precio, ni se vende. Stock, ventas, compras y tienda no se enteran de que
existe. Lo que se vende sigue siendo el producto concreto de la marca que el
cliente eligió — es lo que separa esta solución del "concepto de pieza" que
quedó fuera de alcance.

Cómo se ve un grupo en los resultados:

```
Buje parrilla delantera — FIAT Palio / Siena
   Cobreq   CB-1234    $ 12.400    hay 4
   VTH      VTH5939    $ 14.900    hay 2
   Axios    AXI044     $ 11.200    sin stock
```

- **Un producto sin grupo aparece como una fila suelta, igual que hoy.** No
  hay que agrupar nada para que el sistema siga funcionando: el grupo es
  siempre opcional.
- **Se carga desde la ficha del producto**: "este repuesto también lo tengo
  en otras marcas" → elegir un grupo existente o crear uno. El nombre viene
  precargado con el nombre del producto y se puede editar.
- **Un script propone los grupos, una persona los confirma.**
  `scripts/proponer_equivalencias.py` cruza los productos por mismo rubro +
  mismo auto vinculado + descripción parecida, y escribe una planilla con los
  candidatos para tildar cuáles son de verdad. No aplica nada sin
  `--aplicar`, igual que `matchear_productos_proveedores.py`. El trabajo
  manual pasa a ser tildar una lista, no buscar las equivalencias de cero.

### Por qué las equivalencias no se pueden resolver solas

Es la diferencia con `producto_proveedor` (el mismo artículo cotizado por dos
proveedores), que **sí** se llena automáticamente con
`matchear_productos_proveedores.py`. Ahí el match es confiable porque es
literalmente el mismo artículo del mismo fabricante, y el código de barras
—que asigna la marca que fabrica, no quien revende— es un identificador
compartido entre las dos listas.

Entre marcas distintas no hay ningún dato compartido: códigos de barras
distintos, códigos de producto distintos. Lo único parecido es la
descripción, y ahí el problema es que se parecen **demasiado**:

```
BUJE PARRILLA DELANTERA FIAT PALIO     <- Cobreq
BUJE PARRILLA TRASERA   FIAT PALIO     <- VTH
```

Una palabra de diferencia, y agruparlas manda al cliente a casa con la pieza
equivocada. Lo mismo con izquierdo/derecho, con sensor/sin sensor, o con dos
medidas distintas. Por eso el script propone y no aplica.

**Fuente mejor, pendiente de confirmar**: la propia pantalla de Lupa muestra
las tres marcas de un mismo buje, o sea que ese distribuidor ya tiene la
equivalencia cargada. Si alguna de las listas de precios de los proveedores
trae una columna de "equivalencias" o "reemplaza a", eso es dato confirmado y
le gana a cualquier detección por parecido de texto. Celes va a revisar las
listas que tiene; si aparece esa columna, el plan de implementación debe
priorizar leerla por sobre el script de propuestas.
- **En Nueva venta se agrega el producto concreto que se tocó, nunca el
  grupo.** El stock es por producto y no puede ser de otra manera.
- **Un producto pertenece a lo sumo a un grupo** (una sola columna, no una
  tabla de N a N). Es lo que hace que la simetría y la transitividad salgan
  gratis en vez de haber que mantenerlas.
- **Borrar un grupo no borra productos**: quedan sin agrupar.

**Los contadores siguen contando productos, no grupos.** Si el rubro Frenos
dice `(128)` y ahí adentro hay tres marcas del mismo buje, esas tres cuentan
como tres. Contar grupos daría un número más parecido a lo que ve quien
busca, pero rompería que el mismo número sirva en Stock, donde 128 productos
son 128 fichas que administrar. Se prefiere un número que signifique siempre
lo mismo en las tres pantallas. Confirmado con Celes: "está bien porque
serían 3 bujes de distintas marcas".

## Cómo se prueba

Tests de pytest sobre `buscar_productos()` y `facetas_productos()`, que es
donde vive toda la lógica:

- `PASTILLA` se encuentra escribiendo `pastilla` (mayúsculas).
- `HIDRÁULICO` se encuentra escribiendo `hidraulico` (acentos).
- `palio pastilla` encuentra `PASTILLA DE FRENO FIAT PALIO` (orden).
- `pastila` no devuelve resultados pero sí sugerencias (tipeo).
- "Sólo con stock" no devuelve los que están en cero.
- Filtrar por un vehículo devuelve los productos vinculados a ese vehículo, y
  no los que sólo lo mencionan en el texto libre.
- Los contadores de `facetas_productos()` respetan los demás filtros.
- El código de barras sigue matcheando exacto y no por parecido.
- No-regresión: `/api/producto-por-codigo` y el escaneo de la pistola siguen
  funcionando igual.

De la fase 6:

- Tres productos del mismo grupo salen agrupados en un resultado; uno sin
  grupo sale como fila suelta.
- Los contadores cuentan los tres productos del grupo como tres, no como uno.
- "Sólo con stock" deja el grupo visible mostrando únicamente las marcas que
  tienen stock.
- Borrar un grupo deja sus productos sin agrupar, sin borrar ninguno.

**Limitación conocida, ya documentada en el proyecto**: pytest no ve el
JavaScript. Los desplegables en cascada, el panel de Nueva venta y las
etiquetas de filtros activos hay que probarlos en un navegador real, como se
hizo con el escaneo de la pistola y con los dos bugs de validación nativa de
HTML5 de `producto_form.html` y `compra_revisar_factura.html`.

## Riesgos anotados

- **La carga de datos crece.** Vincular autos a cada producto es trabajo
  manual que hoy no existe. Se mitiga con la fase 5 (detección desde la
  descripción) y con que el filtro de auto sea opcional: un producto sin
  autos vinculados sigue apareciendo en todo lo demás.
- **El filtro de auto sólo sirve para lo que esté vinculado.** Mientras
  `vehiculos` esté poco cargada, ese filtro va a devolver poco. Por eso
  `modelo_compatible` sigue vivo y la búsqueda de texto lo sigue mirando: el
  sistema no empeora respecto de hoy en ningún momento de la transición.
- **El código de barras puede no ser un identificador global.** Todo el
  argumento de arriba (por qué `producto_proveedor` sí se puede llenar
  automáticamente y las equivalencias no) se apoya en que el EAN lo asigna el
  fabricante y es el mismo en todas las listas. En autopartes eso se rompe
  seguido: muchos repuestos nacionales no tienen EAN, y algunos distribuidores
  le pegan su propia etiqueta con su propio código. Si pasa,
  `productos.codigo_barras` deja de ser global y
  `matchear_productos_proveedores.py` —que hoy confía en él como match
  exacto— estaría cruzando sobre una premisa falsa. **Ese script todavía no
  se probó nunca contra listas de precios reales**, así que no está ni
  confirmado ni descartado. Se chequea sin programar nada: comparar el código
  de barras impreso en la caja de un mismo repuesto comprado a dos
  proveedores distintos. Si difieren, el criterio del matcher tiene que pasar
  a ser código de barras **por proveedor**, no global. No bloquea este
  trabajo — la fase 6 no usa códigos de barras — pero afecta a un script que
  ya está en el repositorio.
- **`unaccent` no es inmutable en Postgres**, así que no se puede indexar
  directamente en un índice de expresión sin envolverla. Es un detalle que el
  plan de implementación tiene que resolver explícitamente (envolverla en una
  función propia marcada `IMMUTABLE`, el camino habitual), no descubrirlo al
  aplicar la migración.
