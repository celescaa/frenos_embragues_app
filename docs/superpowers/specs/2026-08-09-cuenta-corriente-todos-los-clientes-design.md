# Cuenta corriente disponible para cualquier cliente + saldo visible en la lista

**Fecha**: 2026-08-09
**Estado**: aprobado, listo para plan de implementación

## Contexto

La cuenta corriente (`cuenta_corriente_movimientos`, pantalla
`/clientes/<id>/cuenta-corriente`) hoy solo es accesible desde `/clientes`
para clientes con `tipo_cliente = 'mecanico'`: el ícono que lleva a esa
pantalla está envuelto en `{% if c.tipo_cliente == 'mecanico' %}` en
[templates/clientes.html](../../../templates/clientes.html).

Un cliente particular también puede llegar a tener deuda (por ejemplo, se
lleva un repuesto y paga después), así que esa restricción no tiene que
existir. Al revisar el código se confirmó que **el backend ya es genérico**:
ni `cuenta_corriente_ver`, ni `cuenta_corriente_nueva`, ni
`/clientes/top-deudores` (en `core/app.py`) filtran por `tipo_cliente` en
ningún lado — la restricción está únicamente en esa condición de la UI. Es
el mismo criterio que ya aplica a un proveedor: la capacidad de tener
compras/pedidos es del modelo, no de un subtipo.

De paso, se agrega una columna de saldo pendiente en `/clientes` para verlo
de un vistazo sin tener que entrar a cada cliente.

## Decisiones tomadas con el usuario

- El campo `tipo_cliente` (Particular/Mecánico) **se mantiene**, pero pasa a
  ser puramente informativo — deja de condicionar el acceso a cuenta
  corriente.
- El ícono de "Cuenta corriente" en `/clientes` pasa a mostrarse **siempre**,
  para cualquier cliente, tenga o no movimientos cargados todavía (mismo
  criterio que los botones de editar/eliminar de esa fila, o que un
  proveedor siempre puede recibir una compra nueva sin necesitar historial).
- La columna de saldo nuevo en `/clientes` solo muestra algo si el cliente
  **debe** (`saldo > 0`). Si `saldo <= 0` (sin movimientos, saldado, o con
  saldo a favor) la celda queda vacía — no se distingue "saldado" de "a
  favor" por ahora, porque el pedido es ver quién debe, no un extracto
  contable completo.

## Cambios

### 1. Ícono de cuenta corriente siempre visible

`templates/clientes.html`: sacar el `{% if c.tipo_cliente == 'mecanico' %}`
que envuelve el link a `cuenta_corriente_ver`. El link queda igual que el
resto de las acciones de la fila (editar, eliminar), sin condición.

### 2. `tipo_cliente` pasa a ser solo informativo

`templates/cliente_form.html`: el texto de la opción "Mecánico (compra a
cuenta corriente)" implica una exclusividad que ya no existe. Cambia a un
texto puramente descriptivo, por ejemplo **"Mecánico / taller"**.

No hay cambios en `templates/clientes.html` ni `templates/clientes_top.html`
para el badge Mecánico/Particular — sigue siendo solo informativo, como ya
lo era.

### 3. Copy genérico en la pantalla de cuenta corriente

`templates/cuenta_corriente.html` (línea ~60): el texto de ayuda del campo
"tercero" dice *"Si el mecánico compra en nombre de otra persona..."*,
asumiendo que el titular de la cuenta siempre es un mecánico. Se generaliza
a *"Si el cliente compra en nombre de otra persona..."*.

### 4. Columna "Saldo" en `/clientes`

`core/app.py`, función `clientes_lista()`: la consulta de clientes se
extiende con un `LEFT JOIN cuenta_corriente_movimientos` + `GROUP BY c.id`
para traer, por cliente:

```sql
COALESCE(SUM(CASE WHEN m.tipo='cargo' THEN m.monto ELSE 0 END), 0)
- COALESCE(SUM(CASE WHEN m.tipo='pago' THEN m.monto ELSE 0 END), 0) AS saldo
```

Mismo cálculo que ya usa `/clientes/top-deudores` — se reutiliza el criterio
en vez de inventar uno nuevo. Se aplica tanto en la rama con búsqueda (`q`)
como sin ella, manteniendo el `LIKE` existente sobre `c.nombre`,
`c.telefono`, `c.email` (con alias `c.` para que siga siendo válido junto al
`JOIN`/`GROUP BY`).

`templates/clientes.html`: nueva columna "Saldo" en la tabla. Si
`c.saldo > 0`, muestra el monto formateado en rojo (`text-danger`, mismo
patrón visual que ya usan otras alertas de la app). Si `c.saldo <= 0`, la
celda queda vacía.

## Fuera de alcance

- No se toca la base de datos ni las rutas de cuenta corriente — ya son
  genéricas.
- No se agrega distinción visual para saldo a favor (crédito) — si en el
  futuro hace falta, es una extensión de la misma columna, no un cambio de
  diseño.
- No se toca `/clientes/top-deudores` ni `/clientes/top` — ya funcionan
  igual para cualquier tipo de cliente.

## Testing

- Verificar manualmente: un cliente particular sin movimientos ve el ícono
  de cuenta corriente, puede cargar un cargo, y el saldo aparece en rojo en
  `/clientes` después de guardarlo.
- Un cliente sin movimientos no muestra nada en la columna Saldo.
- Un cliente con cargos y pagos que se cancelan entre sí (saldo = 0) tampoco
  muestra nada.
- La búsqueda (`?q=...`) en `/clientes` sigue funcionando y sigue trayendo
  el saldo correcto.
