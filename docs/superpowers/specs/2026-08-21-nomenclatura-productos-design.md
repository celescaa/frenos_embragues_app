# Nomenclatura de productos: descripciones limpias, marca y modelo en su lugar

**Fecha**: 2026-08-21
**Estado**: pendiente de revisión de Celes

## Contexto

Alguien del negocio hizo la **primera carga real de stock** sobre
`plantillas/Planilla_Stock_Completa.xlsx` (la planilla de 202.381 filas
armada el 15/08/2026), completando la columna "Cantidad en stock" de **25
filas**: 24 bombas de agua VMG del proveedor Rodamitre y 1 bomba de agua SKF
de Roncal. El archivo llegó como
`Planilla_Stock_Carga_prueba_20260820.xlsx`.

Celes lo miró y pidió tres cosas: una **nomenclatura** que deje las
descripciones limpias y claras, que la **marca y el modelo terminen en su
columna** cuando hoy están metidos adentro de la descripción, y que **todo
quede en mayúscula** para que se vea prolijo.

### Qué tienen esas 25 filas

Nada de esto es un caso raro: es cómo vienen las listas de precios de los
proveedores, y va a volver a pasar en cada carga.

1. **El rubro `Bomba` no existe en la taxonomía v3**, y viene escrito en tres
   grafías distintas (`Bomba`, `Bomba ` con espacio al final, `bomba`).
   `importar_datos._normalizar_categoria()` manda a `Varios` todo rubro que
   no reconoce, así que **las 24 bombas entrarían a Varios y sin subrubro**.
   Es el daño más grande de los seis y no tiene nada que ver con la estética.
2. **La descripción no describe**: `VMG BA013`, `OFERTA VMG BA442`. Es marca
   más código, no el producto.
3. **`OFERTA VMG` cargado como marca** — "OFERTA" es una nota comercial.
4. **El modelo mezcla el auto con la especificación técnica**:
   `...1.6 Polea 19 dientes`, `...turbina 70mm y polea 54mm`. La polea y la
   turbina no son un auto: son justamente lo que diferencia una bomba de otra.
5. **Typos en el modelo**: `Peuget`, `Renaut`, `Chevolet`, `Mbeanz`,
   `fort volvo`, `Susuki`, `Parnert`, `dientas`, `plea`.
6. **La fila de Roncal repite en el modelo el final de la descripción.**

### Restricción técnica que condiciona "todo en mayúscula"

`db.facetas_productos()` ([core/database.py](../../../core/database.py))
agrupa la dimensión `categoria` (y `subcategoria`) por la **columna cruda**,
no normalizada — a diferencia de `marca`, que sí agrupa por
`texto_busqueda()`. Pasar el rubro a mayúscula haría que `MOTOR` y `Motor`
aparecieran como **dos rubros distintos** en el filtro de `/productos`, cada
uno con su propio contador.

Por eso las mayúsculas alcanzan a **nombre, marca y modelo**, y **nunca** a
rubro ni subrubro, que van letra por letra como los escribe la taxonomía
(`Motor`, `Bomba de agua`, `Suspensión`).

## Decisiones tomadas con Celes

### La nomenclatura

```
NOMBRE = PIEZA + MARCA + [ESPECIFICACIÓN] + CÓDIGO
```

En **MAYÚSCULAS y sin acentos** (`CITROEN`, no `CITROËN`). El buscador ya
normaliza acentos de los dos lados vía `texto_busqueda()`, así que sacarlos
no le cuesta nada a la búsqueda y evita tener la misma palabra escrita de dos
formas.

| Parte | Qué es | De dónde sale |
|---|---|---|
| **PIEZA** | forma canónica: `BOMBA DE AGUA` | tabla `PIEZA_POR_SUBRUBRO`, derivada del subrubro de la taxonomía v3. Es lo que hace que todas las bombas de agua se llamen igual |
| **MARCA** | `VMG`, `SKF` | columna Marca, sin ruido comercial (`OFERTA`, `PROMO`, `LIQUIDACION`) |
| **ESPECIFICACIÓN** | `POLEA 19 DIENTES`, `TURBINA 70 MM`, `REFORZADA` | se **extrae del modelo**, donde hoy está mezclada con los autos. Si no hay ninguna, se usan hasta 2 marcas de auto |
| **CÓDIGO** | `BA446` | columna Código. Si la fila no tiene código, no va nada (y el nombre no queda terminado en espacio) |

Ejemplo sobre una fila real:

```
antes   nombre  'VMG BA446'
        marca   'VMG'
        rubro   'Bomba ' / (vacío)
        modelo  'Peugeot Citroen -P206-207-307 Parnet-208-301-308-408-2008-
                 C 3-C4- Xsara Berlingo -C4 Captus 1.6 Polea 19 dientes'

ahora   nombre  'BOMBA DE AGUA VMG POLEA 19 DIENTES BA446'
        marca   'VMG'
        rubro   'Motor' / 'Bomba de agua'
        modelo  'PEUGEOT CITROEN / P206 / 207 / 307 / PARTNER / 208 / 301 /
                 308 / 408 / 2008 / C 3 / C4 / XSARA / BERLINGO / C4 CAPTUS 1.6'
```

Dos detalles del ejemplo que importan porque muestran los límites del módulo.
`Parnet` → `PARTNER` sale de `ALIAS_MODELO`, o sea que **alguien lo confirmó
antes**; no lo dedujo el módulo solo. Y `C4 Captus` queda como `C4 CAPTUS`
aunque el modelo real sea Cactus: ese cambio todavía no está confirmado, así
que aparece propuesto en la hoja `REVISAR` y no se aplica.

**El código va siempre al final**, incluso cuando el nombre ya sería único.
Se evaluó agregarlo solo cuando el nombre repite, pero eso deja un formato
disparejo (algunos productos con código y otros sin). Sin el código, 14 de
las 25 filas quedaban con el nombre **idéntico** (`BOMBA DE AGUA VMG`).

**El auto no va en el nombre.** Va en `modelo_compatible`, que es lo que el
buscador ya mira: `TEXTO_PRODUCTO_SQL`
([core/database.py:237](../../../core/database.py)) concatena nombre, código,
marca y modelo, así que buscar `palio 1.6` encuentra el producto sin que el
auto esté en el nombre. Con 15 autos por bomba, meterlos en el nombre lo
volvería ilegible en `/productos` y en el remito.

### Nunca va en el nombre

La lista de autos, el proveedor, el precio, ni palabras comerciales.

### Las otras columnas

- **Marca** → mayúsculas sin acentos, sin ruido comercial.
- **Modelo compatible** → mayúsculas sin acentos, marcas de auto canónicas,
  separador único ` / `, y **sin las especificaciones técnicas**, que se
  fueron al nombre.
- **Rubro / Subrubro** → exactamente como los escribe la taxonomía v3. Nunca
  en mayúscula (ver la restricción técnica de más arriba).

### Las bombas son bombas de agua

Confirmado por Celes el 21/08/2026. Importa dejar asentado el razonamiento,
porque el rubro `Bomba` que manda el proveedor es ambiguo y la taxonomía ya
les da **tres casas distintas** a las bombas:

| Tipo | Dónde vive |
|---|---|
| de freno | `Frenos / Cilindros (bomba freno, cilindros de rueda)` |
| de embrague | `Embrague / Bombas y cilindros de embrague` |
| de agua | `Motor / Bomba de agua` |

No hace falta crear ninguna subcategoría nueva. Estas 24 son de agua: sus
modelos hablan de `turbina 70mm`, `polea 54mm` y `alabes alto` — una bomba de
embrague no tiene ninguna de las tres — y la fila 25, la de Roncal, es
idéntica en forma y viene declarada `Motor / Bomba de agua` por el propio
proveedor.

**El módulo nunca resuelve `bomba` a secas por su cuenta.** El mapeo vive en
una tabla explícita por proveedor y rubro crudo (`ALIAS_RUBRO_CRUDO`), y lo
que no está en esa tabla queda marcado para revisión en vez de adivinarse.

### Mayúscula al tipear, no solo al limpiar

Pedido de Celes: que el formulario ya tome todo en mayúscula cuando alguien
carga algo, para no tener que limpiarlo después. Se hace en **dos capas**,
y las dos hacen falta:

- `text-transform: uppercase` en el campo, para que se vea mientras se
  escribe. **Es solo visual**: el valor que se manda al servidor sigue siendo
  lo que la persona tipeó.
- Normalización del lado del servidor al guardar, que es la que **garantiza**
  lo que queda en la base.

Alcance: los campos Nombre, Marca y Modelo compatible de la ficha de producto
(`templates/producto_form.html`) y del alta rápida desde una compra
(`/api/productos-nuevo`).

## El diccionario de modelos, y por qué se propone en vez de aplicarse

Al decidir que el auto vive en su columna en vez del nombre, esa columna pasa
a ser **la llave de búsqueda**. Y entonces los typos dejan de ser un problema
estético: rompen la búsqueda en silencio.

| Se busca | Está escrito | Resultado hoy |
|---|---|---|
| `regatta` | `Fiat regat` | no encuentra nada |
| `siena` | `sena` | no encuentra nada |
| `partner` | `Parnert` | no encuentra nada |
| `defender` | `defendert 90110` | no encuentra nada |

### Cómo se detectan

El vocabulario **se deriva de los datos reales, no se inventa**. Sobre las
202.381 filas de la planilla hay 10.306 palabras distintas de 4 letras o más;
**635 aparecen 300 veces o más** y ésas son el vocabulario "bien escrito".
Una palabra rara parecida a una frecuente (`difflib`, el mismo criterio que
ya usan `importar_factura.py` y `matchear_productos_proveedores.py`) es
candidata a typo.

### Por qué NUNCA se aplica solo

Se probó el método contra 23 palabras sacadas de las 25 filas reales:

- **12 aciertos limpios**: `REGAT`→REGATTA, `PARNERT`→PARTNER,
  `DEFENDERT`→DEFENDER, `BLEAZER`→BLAZER, `PEUGET`→PEUGEOT,
  `RENAUT`→RENAULT, `CHEVOLET`→CHEVROLET, `SUSUKI`→SUZUKI, `CUGA`→KUGA,
  `SIMBOL`→SYMBOL, `FIETA`→FIESTA, `DIENTAS`→DIENTES.
- **3 correcciones equivocadas**: `DASTER` → propone MASTER cuando es
  **DUSTER**; `LAGAN` → propone LOGAN cuando es **LAGUNA**; `MEGAM` →
  propone OMEGA cuando es **MEGANE**. Los tres pares son autos reales, así
  que el error no se nota mirando el resultado.
- **3 modelos reales que casi se rompen**: `MOBI` (802 apariciones), `MITO`
  (536) y `TORO` (1003). Los salva únicamente el filtro de frecuencia: son
  demasiado comunes para ser un typo.

Trece por ciento de error, y cada error manda un cliente a casa con la bomba
de otro auto. Es el mismo razonamiento que el CLAUDE.md ya tiene escrito para
los grupos de equivalencia entre marcas (fase 6 del buscador).

Entonces: **el sistema propone, una persona confirma**. Lo confirmado queda
en la tabla `ALIAS_MODELO` del módulo y se aplica desde ahí en adelante, sin
volver a preguntar. Lo no confirmado no se toca.

Las **marcas de auto** sí se corrigen automáticamente (`Peuget`→`PEUGEOT`):
son un conjunto chico y cerrado que se puede escribir a mano y verificar de
una vez, a diferencia de los modelos, que son una lista abierta.

## Arquitectura

### `scripts/nomenclatura.py` (nuevo)

Módulo de **texto puro, sin acceso a la base**, hermano de
`scripts/clasificar_repuestos.py` y con la misma forma: tablas de reglas más
funciones que reciben y devuelven texto. Que no importe `core.database` es lo
que lo hace testeable sin Postgres levantado y usable desde cualquier script.

Tablas:

| Tabla | Qué guarda |
|---|---|
| `PIEZA_POR_SUBRUBRO` | subrubro de la taxonomía → forma canónica de la pieza (`Bomba de agua` → `BOMBA DE AGUA`) |
| `ALIAS_RUBRO_CRUDO` | **(proveedor, rubro crudo)** → (rubro, subrubro) de la taxonomía. La clave lleva el proveedor porque `Bomba` es ambiguo en general pero no dentro de Rodamitre. Sólo lo confirmado: lo que no está se marca para revisar, no se adivina |
| `MARCAS_AUTO` | variantes escritas → marca canónica. Se aplica siempre |
| `ALIAS_MODELO` | modelos confirmados a mano. Arranca con lo verificado de estas 25 filas y crece |
| `ESPECIFICACIONES` | patrones de spec técnica a extraer del modelo (`POLEA N DIENTES`, `TURBINA N MM`, `ANCHO N MM`, `REFORZADA`, `ALABES ALTO`) |
| `RUIDO_COMERCIAL` | `OFERTA`, `PROMO`, `LIQUIDACION` |

Funciones: `normalizar_fila(...)` (el punto de entrada, devuelve la fila
normalizada más un flag de "revisar"), `mayusculas_sin_acentos(texto)`,
`extraer_especificaciones(modelo)`, `normalizar_modelo(modelo)`,
`normalizar_marca(marca)` y `verificar_taxonomia()`.

`verificar_taxonomia()` compara los nombres de rubro y subrubro que el módulo
escribe a mano contra `db.CATEGORIAS_INICIALES` / `db.SUBCATEGORIAS_INICIALES`,
con test propio — igual que `clasificar_repuestos.verificar_taxonomia()`. Si
una migración renombra un subrubro, salta en el test y no en medio de una
carga.

### `scripts/normalizar_planilla_stock.py` (nuevo)

Toma **la planilla que el negocio ya tiene** y escribe una copia limpia.

Deliberadamente **no se regenera desde las listas de precios** con
`armar_planilla_stock.py`: eso borraría las cantidades ya cargadas a mano,
que son el trabajo humano que no se puede reponer.

Escribe con `write_only` de openpyxl, igual que
`extraer_catalogo_referencia.py` y `armar_planilla_stock.py`, por el volumen
(202.381 filas, ~4 minutos).

Suma una hoja **`REVISAR`** con los typos de modelo propuestos y **no
aplicados**: palabra encontrada, dónde aparece, candidato sugerido, cuántas
veces aparece cada uno. Es la planilla que una persona revisa para alimentar
`ALIAS_MODELO`.

### `scripts/cargar_stock_por_proveedor.py` (modificado)

Aplica `nomenclatura.normalizar_fila()` a cada fila que carga, como red de
seguridad para lo que se tipee a mano directo en la planilla.

Se suma **`--revisar`**: no toca la base y escribe un Excel con el antes y el
después de cada fila que se cargaría. Es el mismo criterio de
`matchear_productos_proveedores.py`, que simula por defecto y necesita
`--aplicar` para persistir; acá va al revés porque el importador ya existe y
su comportamiento por defecto es cargar.

### `scripts/armar_planilla_stock.py` (modificado)

Aplica el mismo módulo al generar, para que la próxima planilla nazca prolija
en vez de tener que limpiarla después.

### `templates/producto_form.html` y `core/app.py` (modificados)

Las dos capas de la mayúscula al tipear, descritas más arriba.

## Qué NO hace, a propósito

- **No auto-corrige modelos de auto.** Propone; una persona confirma. El
  motivo está medido más arriba.
- **No inventa la pieza.** Si no la puede deducir, deja la descripción
  original en mayúsculas y marca la fila para revisión.
- **No toca precios, cantidades ni códigos.**
- **No pasa rubro ni subrubro a mayúscula.**

## Tests (`tests/test_nomenclatura.py`)

| Qué verifica | Por qué |
|---|---|
| Las tres grafías `Bomba` / `Bomba ` / `bomba` caen en `Motor` / `Bomba de agua` | es el bug que mandaba las 24 filas a `Varios` |
| `OFERTA VMG` → `VMG` | ruido comercial fuera de la marca |
| Las specs salen del modelo y entran al nombre | `POLEA 19 DIENTES` no es un auto |
| **Rubro y subrubro nunca quedan en mayúscula** | protege el filtro de `/productos`, que agrupa por la columna cruda |
| Mayúsculas sin acentos en nombre, marca y modelo | `CITROEN`, no `CITROËN` |
| El código va siempre al final, y sin código el nombre no termina en espacio | formato parejo |
| Una fila indeducible queda marcada y conserva su descripción original | el módulo no inventa |
| `verificar_taxonomia()` contra `db.CATEGORIAS_INICIALES` / `SUBCATEGORIAS_INICIALES` | una migración que renombre un subrubro tiene que romper el test |
| `MARCAS_AUTO` se aplica sola; `ALIAS_MODELO` solo con lo confirmado | la distinción que evita el 13% de error |

## Verificación de punta a punta

Sobre las 25 filas reales: que las 24 bombas queden en `Motor` /
`Bomba de agua`, con nombre `BOMBA DE AGUA VMG [spec] BA###`, sin ningún
nombre repetido, y que la fila de Roncal no pierda ninguno de los autos que
ya traía. Después, correr `cargar_stock_por_proveedor.py --revisar` contra el
Postgres local y confirmar que no escribe nada en la base.

Y la suite completa en verde (302 tests hoy).

## Pendiente, fuera de alcance

Un script que proponga typos de modelo **a escala** sobre las 202.381 filas
(hoy la hoja `REVISAR` alcanza porque se cargan 25). Vale la pena recién
cuando el volumen de carga lo justifique.

Vincular estas bombas a la tabla `vehiculos` (el filtro "Auto" estructurado
de `/productos`) es la **fase 5** ya prevista en
`2026-08-14-buscador-productos-filtros-design.md`, y sigue ahí.
