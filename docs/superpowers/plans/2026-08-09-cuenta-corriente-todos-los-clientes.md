# Cuenta corriente para cualquier cliente + columna de saldo — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Desacoplar el acceso a la cuenta corriente de `tipo_cliente == 'mecanico'` para que cualquier cliente (incluidos los particulares) pueda tener cargos/pagos, y agregar una columna de saldo pendiente en `/clientes` para verlo de un vistazo.

**Architecture:** Cambio casi enteramente de UI (Jinja templates). El backend de cuenta corriente ya es genérico (no filtra por tipo de cliente en ningún lado), así que solo se toca la condición que oculta el ícono, dos textos que asumían "mecánico" por default, y la consulta SQL de `clientes_lista()` para sumar el saldo por cliente.

**Tech Stack:** Flask + Jinja2 (templates), SQLite vía el módulo `sqlite3` estándar de Python (sin ORM). Sin frameworks de test: el proyecto no tiene suite automatizada (no hay carpeta `tests/`, no hay `pytest` en `requirements.txt`) — toda verificación en este plan es manual/reproducible por comandos (sqlite3 CLI, `grep`, correr la app y mirar el navegador), siguiendo el mismo patrón que ya usa el proyecto (ver `CLAUDE.md`: cada feature dice "probado de punta a punta" a mano, no con una suite).

## Global Constraints

- No se toca la base de datos ni las rutas de backend de cuenta corriente (`cuenta_corriente_ver`, `cuenta_corriente_nueva`, `/clientes/top-deudores`) — ya son genéricas.
- `tipo_cliente` se mantiene como campo informativo (no se elimina el select ni la columna).
- Columna "Saldo" en `/clientes`: vacía si `saldo <= 0`; si `saldo > 0`, se muestra en rojo (`text-danger`) usando el filtro Jinja `money` ya existente ([core/app.py:232](../../../core/app.py:232), registrado en [core/app.py:259](../../../core/app.py:259)).
- No se agrega ningún framework de testing nuevo — mantener el patrón de verificación manual del proyecto.

---

### Task 1: Desacoplar el ícono de cuenta corriente de `tipo_cliente` y generalizar el copy "mecánico"

**Files:**
- Modify: `templates/clientes.html:33-35`
- Modify: `templates/cliente_form.html:44,46`
- Modify: `templates/cuenta_corriente.html:60`

**Interfaces:**
- No produce ni consume funciones/tipos — son ediciones de texto/condicionales en templates ya renderizados por rutas existentes (`clientes_lista`, `clientes_nuevo`/`clientes_editar`, `cuenta_corriente_ver`), sin tocar `core/app.py` en esta tarea.

- [ ] **Step 1: Sacar el gate `tipo_cliente == 'mecanico'` del ícono de cuenta corriente**

En `templates/clientes.html`, reemplazar:

```html
        <td class="text-end">
          {% if c.tipo_cliente == 'mecanico' %}
            <a href="{{ url_for('cuenta_corriente_ver', cliente_id=c.id) }}" class="btn btn-sm btn-outline-primary" title="Cuenta corriente"><i class="bi bi-journal-text"></i></a>
          {% endif %}
          <a href="{{ url_for('clientes_editar', cliente_id=c.id) }}" class="btn btn-sm btn-outline-secondary"><i class="bi bi-pencil"></i></a>
```

por:

```html
        <td class="text-end">
          <a href="{{ url_for('cuenta_corriente_ver', cliente_id=c.id) }}" class="btn btn-sm btn-outline-primary" title="Cuenta corriente"><i class="bi bi-journal-text"></i></a>
          <a href="{{ url_for('clientes_editar', cliente_id=c.id) }}" class="btn btn-sm btn-outline-secondary"><i class="bi bi-pencil"></i></a>
```

- [ ] **Step 2: Verificar que el gate desapareció**

Run: `grep -n "tipo_cliente == 'mecanico'" templates/clientes.html`
Expected: sin resultados (0 matches) — antes del cambio el comando devolvía 2 líneas (la del badge, línea 26, que se mantiene, y la del ícono, línea 33, que se borró). Confirmar con `grep -c` que ahora hay 1 sola coincidencia:

Run: `grep -c "tipo_cliente == 'mecanico'" templates/clientes.html`
Expected: `1` (solo queda la del badge "Mecánico" en la columna Tipo, que no se toca)

- [ ] **Step 3: Generalizar el texto del tipo de cliente en el formulario de alta/edición**

En `templates/cliente_form.html`, reemplazar:

```html
        <option value="mecanico" {{ 'selected' if cliente and cliente.tipo_cliente == 'mecanico' else '' }}>Mecánico (compra a cuenta corriente)</option>
      </select>
      <div class="form-text">Un cliente "Mecánico" habilita la pantalla de cuenta corriente para cargarle deuda y registrar pagos.</div>
```

por:

```html
        <option value="mecanico" {{ 'selected' if cliente and cliente.tipo_cliente == 'mecanico' else '' }}>Mecánico / taller</option>
      </select>
      <div class="form-text">Solo a fines informativos — cualquier cliente, sea "Particular" o "Mecánico / taller", puede tener cuenta corriente.</div>
```

- [ ] **Step 4: Verificar el cambio de texto**

Run: `grep -n "compra a cuenta corriente\|habilita la pantalla" templates/cliente_form.html`
Expected: sin resultados (0 matches) — las dos frases viejas ya no están.

Run: `grep -n "Mecánico / taller" templates/cliente_form.html`
Expected: 1 resultado, la línea del `<option>`.

- [ ] **Step 5: Generalizar el copy de "tercero" en la pantalla de cuenta corriente**

En `templates/cuenta_corriente.html`, reemplazar:

```html
          <div class="form-text">Solo referencia si se deja en blanco el CUIT/DNI de abajo. Si el mecánico compra en nombre de otra persona y esa persona tiene CUIT/DNI propio, cargalo para que la factura salga a su nombre.</div>
```

por:

```html
          <div class="form-text">Solo referencia si se deja en blanco el CUIT/DNI de abajo. Si el cliente compra en nombre de otra persona y esa persona tiene CUIT/DNI propio, cargalo para que la factura salga a su nombre.</div>
```

- [ ] **Step 6: Verificar el cambio de copy**

Run: `grep -n "el mecánico compra en nombre" templates/cuenta_corriente.html`
Expected: sin resultados (0 matches)

Run: `grep -n "el cliente compra en nombre" templates/cuenta_corriente.html`
Expected: 1 resultado

- [ ] **Step 7: Commit**

```bash
git add templates/clientes.html templates/cliente_form.html templates/cuenta_corriente.html
git commit -m "Habilitar cuenta corriente para cualquier tipo de cliente

El ícono de cuenta corriente en /clientes ya no depende de
tipo_cliente=='mecanico' -- el backend siempre fue genérico, solo la UI
lo restringía. tipo_cliente se mantiene como dato informativo, y se
generaliza el copy que asumía que el titular de la cuenta siempre era
un mecánico."
```

---

### Task 2: Agregar columna "Saldo" a `/clientes`

**Files:**
- Modify: `core/app.py:395-407` (función `clientes_lista`)
- Modify: `templates/clientes.html` (header de la tabla y fila de cada cliente, después de los cambios de Task 1)

**Interfaces:**
- Consumes: nada de la Task 1 a nivel de código (son archivos hermanos, sin funciones compartidas); sí depende de que Task 1 ya haya limpiado la columna de acciones para no reordenar dos veces el mismo `<tr>`.
- Produces: la fila `sqlite3.Row` que devuelve `clientes_lista()` gana una clave nueva `saldo` (float), leída en el template como `c.saldo` — igual patrón que ya usa `d.saldo` en `templates/clientes_top_deudores.html:19`.

- [ ] **Step 1: Preparar una base de datos de prueba desechable con movimientos de cuenta corriente**

Run:
```bash
rm -rf /tmp/si_test_instance && mkdir -p /tmp/si_test_instance
SI_INSTANCE_DIR=/tmp/si_test_instance python3 -c "from core import database as db; db.init_db()"
sqlite3 /tmp/si_test_instance/data.db "SELECT id, nombre, tipo_cliente FROM clientes ORDER BY id LIMIT 3;"
```
Expected: crea `/tmp/si_test_instance/data.db` con los clientes de ejemplo del proyecto y lista los primeros 3 (para saber qué `id` usar en el paso siguiente).

- [ ] **Step 2: Insertar movimientos de cuenta corriente para dos clientes de prueba y anotar el saldo esperado**

Usando los dos primeros `id` que devolvió el paso anterior (llamalos `<ID1>` y `<ID2>` acá abajo — tienen que ser clientes distintos):

```bash
sqlite3 /tmp/si_test_instance/data.db "INSERT INTO cuenta_corriente_movimientos (cliente_id, monto, tipo, fecha) VALUES (<ID1>, 10000, 'cargo', '2026-08-01');"
sqlite3 /tmp/si_test_instance/data.db "INSERT INTO cuenta_corriente_movimientos (cliente_id, monto, tipo, fecha) VALUES (<ID1>, 4000, 'pago', '2026-08-02');"
sqlite3 /tmp/si_test_instance/data.db "INSERT INTO cuenta_corriente_movimientos (cliente_id, monto, tipo, fecha) VALUES (<ID2>, 5000, 'cargo', '2026-08-01');"
sqlite3 /tmp/si_test_instance/data.db "INSERT INTO cuenta_corriente_movimientos (cliente_id, monto, tipo, fecha) VALUES (<ID2>, 5000, 'pago', '2026-08-02');"
```
Saldo esperado para `<ID1>`: `10000 - 4000 = 6000` (debe, tiene que aparecer en rojo).
Saldo esperado para `<ID2>`: `5000 - 5000 = 0` (saldado — cargo y pago se cancelan; tiene que aparecer vacío, igual que un cliente sin movimientos).
El resto de los clientes de ejemplo no tienen movimientos, así que su saldo esperado también es "vacío".

- [ ] **Step 3: Escribir y probar la consulta SQL del saldo directamente, antes de tocar `core/app.py`**

Run:
```bash
sqlite3 /tmp/si_test_instance/data.db "
SELECT c.id, c.nombre,
       COALESCE(SUM(CASE WHEN m.tipo='cargo' THEN m.monto ELSE 0 END), 0)
       - COALESCE(SUM(CASE WHEN m.tipo='pago' THEN m.monto ELSE 0 END), 0) AS saldo
FROM clientes c LEFT JOIN cuenta_corriente_movimientos m ON m.cliente_id = c.id
GROUP BY c.id ORDER BY c.nombre;
"
```
Expected: el cliente `<ID1>` aparece con `saldo = 6000.0`; el cliente `<ID2>` aparece con `saldo = 0.0` (cargo y pago se cancelaron); todos los demás clientes de ejemplo aparecen con `saldo = 0.0` (por el `LEFT JOIN` + `COALESCE`, nunca `NULL`). Esto confirma que la consulta es correcta antes de meterla en Flask — es el equivalente de "correr el test y verlo fallar/pasar" para una consulta SQL: acá lo que valida es que el cálculo da lo esperado con datos conocidos.

- [ ] **Step 4: Implementar la consulta en `clientes_lista()`**

En `core/app.py`, reemplazar la función completa (líneas 395-407):

```python
@app.route("/clientes")
def clientes_lista():
    conn = db.get_connection()
    q = request.args.get("q", "").strip()
    if q:
        clientes = conn.execute(
            "SELECT * FROM clientes WHERE nombre LIKE ? OR telefono LIKE ? OR email LIKE ? ORDER BY nombre",
            (f"%{q}%", f"%{q}%", f"%{q}%"),
        ).fetchall()
    else:
        clientes = conn.execute("SELECT * FROM clientes ORDER BY nombre").fetchall()
    conn.close()
    return render_template("clientes.html", clientes=clientes, q=q)
```

por:

```python
@app.route("/clientes")
def clientes_lista():
    conn = db.get_connection()
    q = request.args.get("q", "").strip()
    # Mismo cálculo de saldo que /clientes/top-deudores (cargos menos
    # pagos), para no tener el criterio de "cuánto debe" duplicado con
    # reglas distintas en dos pantallas.
    saldo_expr = (
        "COALESCE(SUM(CASE WHEN m.tipo='cargo' THEN m.monto ELSE 0 END), 0)"
        " - COALESCE(SUM(CASE WHEN m.tipo='pago' THEN m.monto ELSE 0 END), 0) AS saldo"
    )
    if q:
        clientes = conn.execute(
            f"""SELECT c.*, {saldo_expr}
                FROM clientes c LEFT JOIN cuenta_corriente_movimientos m ON m.cliente_id = c.id
                WHERE c.nombre LIKE ? OR c.telefono LIKE ? OR c.email LIKE ?
                GROUP BY c.id ORDER BY c.nombre""",
            (f"%{q}%", f"%{q}%", f"%{q}%"),
        ).fetchall()
    else:
        clientes = conn.execute(
            f"""SELECT c.*, {saldo_expr}
                FROM clientes c LEFT JOIN cuenta_corriente_movimientos m ON m.cliente_id = c.id
                GROUP BY c.id ORDER BY c.nombre"""
        ).fetchall()
    conn.close()
    return render_template("clientes.html", clientes=clientes, q=q)
```

- [ ] **Step 5: Verificar que `app.py` sigue siendo Python válido**

Run: `python3 -m py_compile core/app.py`
Expected: sin salida, sin error (exit code 0)

- [ ] **Step 6: Agregar la columna "Saldo" a la tabla en `templates/clientes.html`**

Reemplazar el encabezado:

```html
      <tr><th>Nombre</th><th>Tipo</th><th>Teléfono</th><th>Email</th><th>Dirección</th><th>CUIT/DNI</th><th>Alta</th><th></th></tr>
```

por:

```html
      <tr><th>Nombre</th><th>Tipo</th><th>Teléfono</th><th>Email</th><th>Dirección</th><th>CUIT/DNI</th><th>Alta</th><th class="text-end">Saldo</th><th></th></tr>
```

Reemplazar la fila de "no hay clientes":

```html
      <tr><td colspan="8" class="text-center text-muted py-4">No hay clientes cargados todavía.</td></tr>
```

por:

```html
      <tr><td colspan="9" class="text-center text-muted py-4">No hay clientes cargados todavía.</td></tr>
```

Y agregar la celda del saldo justo antes de la celda de acciones (la que ya quedó con el ícono de cuenta corriente + editar + eliminar de la Task 1):

```html
        <td>{{ c.fecha_alta }}</td>
        <td class="text-end">
          <a href="{{ url_for('cuenta_corriente_ver', cliente_id=c.id) }}" class="btn btn-sm btn-outline-primary" title="Cuenta corriente"><i class="bi bi-journal-text"></i></a>
```

por:

```html
        <td>{{ c.fecha_alta }}</td>
        <td class="text-end">{% if c.saldo and c.saldo > 0 %}<span class="text-danger fw-bold">{{ c.saldo|money }}</span>{% endif %}</td>
        <td class="text-end">
          <a href="{{ url_for('cuenta_corriente_ver', cliente_id=c.id) }}" class="btn btn-sm btn-outline-primary" title="Cuenta corriente"><i class="bi bi-journal-text"></i></a>
```

- [ ] **Step 7: Levantar la app contra la base de prueba y verificar visualmente**

Run:
```bash
SI_INSTANCE_DIR=/tmp/si_test_instance python3 app.py
```
Dejarla corriendo, abrir `http://127.0.0.1:5050/clientes` en el navegador. La primera vez que corre esta base de prueba, `core/database.py` genera un admin con contraseña aleatoria en `/tmp/si_test_instance/credenciales_iniciales.txt` — usar esas credenciales para loguearse.

Run (en otra terminal, para ver el usuario/contraseña generados): `cat /tmp/si_test_instance/credenciales_iniciales.txt`

Expected en `/clientes`:
- El cliente `<ID1>` muestra `$6.000,00` en rojo en la columna Saldo.
- El cliente `<ID2>` (saldado, cargo y pago se cancelan) **no** muestra nada en la columna Saldo.
- El resto de los clientes de ejemplo tampoco muestran nada en esa columna.
- **Todos** los clientes (no solo los "Mecánico") tienen el ícono de cuenta corriente visible y funcional — hacer clic en el de un cliente "Particular" y confirmar que entra a `/clientes/<id>/cuenta-corriente` sin error.
- Buscar por el nombre de `<ID1>` con el campo de búsqueda de arriba (`?q=...`) y confirmar que sigue apareciendo en los resultados con el mismo saldo `$6.000,00` (para probar que el `WHERE ... GROUP BY` combinados no rompieron el cálculo).

Cortar el servidor con Ctrl+C cuando termine la verificación.

- [ ] **Step 8: Limpiar la base de prueba desechable**

Run: `rm -rf /tmp/si_test_instance`

- [ ] **Step 9: Commit**

```bash
git add core/app.py templates/clientes.html
git commit -m "Mostrar saldo pendiente de cuenta corriente en /clientes

Mismo cálculo (cargos - pagos) que ya usa /clientes/top-deudores,
via LEFT JOIN + GROUP BY sobre cuenta_corriente_movimientos. Solo se
muestra la celda cuando el cliente debe algo (saldo > 0)."
```
