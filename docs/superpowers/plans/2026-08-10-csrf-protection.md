# Protección CSRF con Flask-WTF Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Proteger todos los POST del sistema (formularios HTML y las 3 llamadas `fetch()` de alta rápida) contra CSRF, usando Flask-WTF.

**Architecture:** `CSRFProtect(app)` global en `core/app.py` protege todo POST/PUT/PATCH/DELETE por default. Se exime solo `/webhooks/mercadopago` (notificación server-to-server de Mercado Pago, no un navegador con sesión). Cada `<form method="post">` de los 20 templates lleva un campo oculto `{{ csrf_token() }}`; los 3 `fetch()` existentes suman el token vía header `X-CSRFToken`, leído de un `<meta>` nuevo en `base.html`/`base_publica.html`. Un `@app.errorhandler(CSRFError)` muestra el mismo patrón de flash+redirect que ya usa el resto de la app en vez de una página de error técnica.

**Tech Stack:** Flask 3.1.3, Flask-WTF (nueva dependencia), Jinja2, vanilla JS (sin framework de frontend).

## Global Constraints

- Spec de referencia: `docs/superpowers/specs/2026-08-10-csrf-protection-design.md`.
- No hay suite de tests automatizada en el proyecto — la verificación de cada tarea es manual (browser / `curl`), como ya definió el spec aprobado. No agregar `pytest` ni infraestructura de tests como parte de este plan (es un gap aparte, ya documentado en `CLAUDE.md`).
- Los forms `method="get"` (buscadores/filtros) NO llevan el campo — CSRF solo aplica a lo que muta estado.
- El snippet a insertar es siempre el mismo, literal:
  ```html
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  ```
  Va como primera línea dentro de cada `<form method="post" ...>`, inmediatamente después de la línea de apertura del form.
- No tocar ningún form `method="get"`, ni `comprobante_pdf.html` (standalone, se renderiza a PDF server-side, no es un request de navegador).

---

### Task 1: Backend — CSRFProtect, exención del webhook, manejo de error

**Files:**
- Modify: `requirements.txt`
- Modify: `core/app.py:10-56` (imports y setup), `core/app.py:2331` (decorador del webhook)

**Interfaces:**
- Produces: variable de módulo `csrf` (instancia de `CSRFProtect`), disponible para cualquier código posterior en `core/app.py` que necesite `@csrf.exempt`.

- [ ] **Step 1: Agregar la dependencia**

En `requirements.txt`, agregar una línea nueva después de `Flask==3.1.3`:
```
Flask==3.1.3
Flask-WTF==1.2.2
```

Instalar:
```bash
pip install -r requirements.txt
```

- [ ] **Step 2: Importar CSRFProtect y CSRFError**

En `core/app.py`, línea 13, agregar el import junto a los demás imports de Flask (no cambia la línea existente, se agrega una nueva justo debajo):

```python
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError
```

- [ ] **Step 3: Inicializar CSRFProtect después de `app.secret_key`**

En `core/app.py`, inmediatamente después del bloque que setea `app.secret_key` (después de la línea 50, `_f.write(app.secret_key)`, y antes de la línea `app.config["PERMANENT_SESSION_LIFETIME"] = ...`), agregar:

```python
csrf = CSRFProtect(app)
```

- [ ] **Step 4: Agregar el error handler**

En `core/app.py`, después del bloque de configuración de sesión (después de la línea `# app.config["SESSION_COOKIE_SECURE"] = True`, antes de `LOCKOUT_INTENTOS = 5`), agregar:

```python
@app.errorhandler(CSRFError)
def manejar_csrf_error(e):
    flash("La página quedó desactualizada. Volvé a intentarlo.", "warning")
    return redirect(request.referrer or url_for("dashboard"))
```

- [ ] **Step 5: Eximir el webhook de Mercado Pago**

En `core/app.py:2331`, agregar el decorador `@csrf.exempt` arriba de `@app.route`:

```python
@csrf.exempt
@app.route("/webhooks/mercadopago", methods=["POST"])
def webhook_mercadopago():
```

- [ ] **Step 6: Verificación manual**

Arrancar la app (`python app.py`) y con la app corriendo, en otra terminal:

```bash
# 1. Sin sesión ni token: un POST a una ruta protegida por login debería
#    terminar en /login (ver nota abajo sobre el paso intermedio por el
#    handler de CSRFError).
curl -i -X POST http://127.0.0.1:5050/clientes/1/eliminar

# 2. El webhook sigue aceptando POST sin token CSRF (está exento) — no debe
#    devolver un error de CSRF.
curl -i -X POST http://127.0.0.1:5050/webhooks/mercadopago -H "Content-Type: application/json" -d '{"type":"payment","data":{"id":"123"}}'
```
Expected: la primera responde 302, pero no directo a `/login` como antes de la corrección del open redirect en `manejar_csrf_error` (revisión final, 11/08/2026): un POST anónimo sin token CSRF entra primero al handler de `CSRFError` (registrado antes que la verificación de sesión), que ahora redirige solo a un destino del mismo origen — sin `Referer` válido, cae a `/` (dashboard) — y recién en ese segundo hop `@app.before_request` detecta que no hay sesión y manda a `/login`. Es decir, dos saltos (`/clientes/1/eliminar` → `/` → `/login`), no uno directo. La segunda responde 200, no 401: sin `MERCADOPAGO_WEBHOOK_SECRET` configurado, `tienda_pagos.validar_firma_webhook()` devuelve `(True, "sin validar")` a propósito (mismo criterio defensivo del resto de la app — no bloquea por falta de configuración) y el webhook acepta la notificación en vez de rechazarla; lo que importa verificar acá es que la respuesta NO sea una redirección con el flash de CSRF, que sí confirmaría que la exención no quedó bien aplicada.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt core/app.py
git commit -m "Agregar CSRFProtect global y exención del webhook de Mercado Pago"
```

---

### Task 2: Propagar el token al frontend — meta tag y `fetch()`

**Files:**
- Modify: `templates/base.html:6` (dentro de `<head>`)
- Modify: `templates/base_publica.html:6` (dentro de `<head>`)
- Modify: `templates/venta_form.html:255`
- Modify: `templates/compra_form.html:323`
- Modify: `templates/compra_revisar_factura.html:403`

**Interfaces:**
- Consumes: `csrf_token()` (Jinja global que expone Flask-WTF automáticamente una vez que `CSRFProtect(app)` corrió — Task 1).
- Produces: `<meta name="csrf-token" content="...">` en el `<head>`, que las Tasks 3-8 (forms) no usan pero Task 2 sí, vía JS.

- [ ] **Step 1: Meta tag en `base.html`**

En `templates/base.html`, línea 6 (`<title>{% block title %}...`), agregar debajo:

```html
<title>{% block title %}{{ negocio.nombre }}{% endblock %}</title>
<meta name="csrf-token" content="{{ csrf_token() }}">
```

- [ ] **Step 2: Meta tag en `base_publica.html`**

Mismo cambio en `templates/base_publica.html`, línea 6:

```html
<title>{% block title %}{{ negocio.nombre }}{% endblock %}</title>
<meta name="csrf-token" content="{{ csrf_token() }}">
```

- [ ] **Step 3: Header en el `fetch()` de `venta_form.html`**

En `templates/venta_form.html:255`, el código actual es:

```js
  fetch('/api/clientes-nuevo', { method: 'POST', body: datos })
```

Reemplazar por:

```js
  fetch('/api/clientes-nuevo', {
    method: 'POST',
    headers: { 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content },
    body: datos,
  })
```

- [ ] **Step 4: Header en el `fetch()` de `compra_form.html`**

En `templates/compra_form.html:323`, mismo patrón — el código actual es:

```js
  fetch('/api/productos-nuevo', { method: 'POST', body: datos })
```

Reemplazar por:

```js
  fetch('/api/productos-nuevo', {
    method: 'POST',
    headers: { 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content },
    body: datos,
  })
```

- [ ] **Step 5: Header en el `fetch()` de `compra_revisar_factura.html`**

En `templates/compra_revisar_factura.html:403`, mismo patrón:

```js
  fetch('/api/productos-nuevo', {
    method: 'POST',
    headers: { 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content },
    body: datos,
  })
```

- [ ] **Step 6: Verificación manual**

Con la app corriendo y logueado:
1. Ir a `/ventas/nueva`, abrir el modal "Cliente nuevo", completar nombre, guardar. Debe crear el cliente y quedar seleccionado (mismo comportamiento que antes).
2. Ver el request en las devtools del navegador (pestaña Network) → confirmar que `POST /api/clientes-nuevo` lleva el header `X-CSRFToken`.
3. Repetir el mismo chequeo para "Producto nuevo" desde `/compras/nueva`.

- [ ] **Step 7: Commit**

```bash
git add templates/base.html templates/base_publica.html templates/venta_form.html templates/compra_form.html templates/compra_revisar_factura.html
git commit -m "Agregar meta tag CSRF y header X-CSRFToken a los fetch() de alta rápida"
```

---

### Task 3: Templates — Autenticación y usuarios

**Files:**
- Modify: `templates/login.html:40`
- Modify: `templates/cambiar_password.html:13`
- Modify: `templates/usuarios.html:33,36`
- Modify: `templates/usuario_form.html:6`

**Interfaces:**
- Consumes: `csrf_token()` (Task 1).

- [ ] **Step 1: `login.html:40`**

El form es `<form method="post">`. Insertar como primera línea dentro:
```html
  <form method="post">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

- [ ] **Step 2: `cambiar_password.html:13`**

```html
  <form method="post">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

- [ ] **Step 3: `usuarios.html:33` y `:36`**

Línea 33: `<form method="post" action="{{ url_for('usuarios_resetear_password', usuario_id=u.id) }}" class="d-inline" onsubmit="return confirm('¿Generar una contraseña temporal nueva para este usuario?');">`. Insertar debajo:
```html
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

Línea 36: `<form method="post" action="{{ url_for('usuarios_eliminar', usuario_id=u.id) }}" class="d-inline" onsubmit="return confirm('¿Eliminar este usuario?');">`. Mismo campo debajo.

- [ ] **Step 4: `usuario_form.html:6`**

```html
  <form method="post">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

- [ ] **Step 5: Verificación manual**

1. Cerrar sesión y loguearse de nuevo en `/login` — tiene que funcionar igual que antes.
2. Si el usuario logueado es admin: ir a `/usuarios`, resetear la contraseña de un usuario de prueba y confirmar que funciona.
3. Crear un usuario nuevo desde `/usuarios/nuevo` y confirmar que se guarda.
4. Cambiar la propia contraseña desde `/cambiar-password`.

- [ ] **Step 6: Commit**

```bash
git add templates/login.html templates/cambiar_password.html templates/usuarios.html templates/usuario_form.html
git commit -m "Agregar campo csrf_token a los forms de autenticación y usuarios"
```

---

### Task 4: Templates — Clientes

**Files:**
- Modify: `templates/cliente_form.html:6`
- Modify: `templates/clientes.html:36`
- Modify: `templates/clientes_top.html:63,79`
- Modify: `templates/cuenta_corriente.html:23,157`

**Interfaces:**
- Consumes: `csrf_token()` (Task 1).

- [ ] **Step 1: `cliente_form.html:6`**
```html
  <form method="post">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

- [ ] **Step 2: `clientes.html:36`** (`<form method="post" action="{{ url_for('clientes_eliminar', cliente_id=c.id) }}" class="d-inline" onsubmit="return confirm('¿Eliminar este cliente?');">`) — NO tocar el form `method="get"` de la línea 13 (buscador).
```html
          <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

- [ ] **Step 3: `clientes_top.html:63` y `:79`** — NO tocar el form `method="get"` de la línea 9 (filtros).

Línea 63 (`<form method="post" action="{{ url_for('promocion_finalizar', promocion_id=p.id) }}" onsubmit="return confirm('¿Finalizar esta promoción ahora?');">`):
```html
          <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

Línea 79 (`<form method="post" id="formPromocion">`):
```html
      <form method="post" id="formPromocion">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

- [ ] **Step 4: `cuenta_corriente.html:23` y `:157`**

Línea 23 (`<form method="post" action="{{ url_for('cuenta_corriente_nueva', cliente_id=cliente.id) }}" id="movimientoForm">`):
```html
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

Línea 157 (`<form method="post" action="{{ url_for('cuenta_corriente_facturar', cliente_id=cliente.id, movimiento_id=m.id) }}" class="d-inline">`):
```html
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

- [ ] **Step 5: Verificación manual**

1. `/clientes` → crear un cliente nuevo, editarlo, confirmar que ambos formularios funcionan.
2. `/clientes/top` → aplicar una promoción de prueba a un cliente y, si hay alguna promoción activa, finalizarla.
3. Entrar a la cuenta corriente de un cliente (`/clientes/<id>/cuenta-corriente`), cargar un movimiento de prueba.

- [ ] **Step 6: Commit**

```bash
git add templates/cliente_form.html templates/clientes.html templates/clientes_top.html templates/cuenta_corriente.html
git commit -m "Agregar campo csrf_token a los forms de clientes y cuenta corriente"
```

---

### Task 5: Templates — Productos, Stock y Categorías

**Files:**
- Modify: `templates/producto_form.html:6`
- Modify: `templates/productos.html:71`
- Modify: `templates/categorias.html:9,48,52,56,80,84,88,98`
- Modify: `templates/stock_no_facturado.html:11,80,84`

**Interfaces:**
- Consumes: `csrf_token()` (Task 1).

- [ ] **Step 1: `producto_form.html:6`** (`<form method="post" id="productoForm" enctype="multipart/form-data">`)
```html
<form method="post" id="productoForm" enctype="multipart/form-data">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

- [ ] **Step 2: `productos.html:71`** — NO tocar el form `method="get" id="filtroForm"` de la línea 9.
```html
          <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

- [ ] **Step 3: `categorias.html`** — las 8 líneas son todas `method="post"`, insertar el campo debajo de cada una de: 9, 48, 52, 56, 80, 84, 88, 98.
```html
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```
(usar la indentación de cada form correspondiente; el contenido del campo es siempre el mismo).

- [ ] **Step 4: `stock_no_facturado.html:11,80,84`**

Línea 11 (`<form method="post" id="movForm">`):
```html
  <form method="post" id="movForm">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```
Líneas 80 y 84 (forms de conciliar/desconciliar), agregar debajo de cada una:
```html
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

- [ ] **Step 5: Verificación manual**

1. `/productos` → crear un producto nuevo (con foto, para ejercitar `enctype="multipart/form-data"`), editarlo, eliminarlo si es de prueba.
2. `/categorias` → agregar una categoría y una subcategoría de prueba, activar/desactivar, eliminar.
3. `/stock/no-facturado` → cargar un movimiento de prueba y, si hay alguno pendiente, conciliar/desconciliar.

- [ ] **Step 6: Commit**

```bash
git add templates/producto_form.html templates/productos.html templates/categorias.html templates/stock_no_facturado.html
git commit -m "Agregar campo csrf_token a los forms de productos, categorías y stock sin facturar"
```

---

### Task 6: Templates — Proveedores, Compras y Pedidos

**Files:**
- Modify: `templates/proveedor_form.html:6`
- Modify: `templates/proveedores.html:38,42,46`
- Modify: `templates/compra_form.html:6`
- Modify: `templates/compra_importar_factura.html:12`
- Modify: `templates/compra_revisar_factura.html:19`
- Modify: `templates/pedidos.html:40,104`

**Interfaces:**
- Consumes: `csrf_token()` (Task 1).

- [ ] **Step 1: `proveedor_form.html:6`**
```html
  <form method="post">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

- [ ] **Step 2: `proveedores.html:38,42,46`** — agregar debajo de cada una de las 3 líneas:
```html
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

- [ ] **Step 3: `compra_form.html:6`** (`<form method="post" id="compraForm">`)
```html
<form method="post" id="compraForm">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

- [ ] **Step 4: `compra_importar_factura.html:12`** (`<form method="post" enctype="multipart/form-data">`)
```html
  <form method="post" enctype="multipart/form-data">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

- [ ] **Step 5: `compra_revisar_factura.html:19`** (`<form method="post" action="{{ url_for('compras_nueva') }}" id="compraForm">`)
```html
<form method="post" action="{{ url_for('compras_nueva') }}" id="compraForm">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

- [ ] **Step 6: `pedidos.html:40,104`**

Línea 40 (`<form method="post" action="{{ url_for('pedidos_marcar') }}">`):
```html
      <form method="post" action="{{ url_for('pedidos_marcar') }}">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```
Línea 104 (`<form method="post" action="{{ url_for('pedidos_desmarcar', producto_id=p.id) }}">`):
```html
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

- [ ] **Step 7: Verificación manual**

1. `/proveedores` → crear un proveedor de prueba, editarlo, desactivarlo/reactivarlo.
2. `/compras/nueva` → registrar una compra de prueba con un producto existente.
3. `/compras/importar-factura` → subir un archivo de prueba (o cancelar si no hay uno a mano) y, si llega a la pantalla de revisión, confirmar que el form de esa pantalla también manda el token.
4. `/pedidos` → si hay algún producto en la lista, marcarlo como pedido y después desmarcarlo.

- [ ] **Step 8: Commit**

```bash
git add templates/proveedor_form.html templates/proveedores.html templates/compra_form.html templates/compra_importar_factura.html templates/compra_revisar_factura.html templates/pedidos.html
git commit -m "Agregar campo csrf_token a los forms de proveedores, compras y pedidos"
```

---

### Task 7: Templates — Ventas y Comprobante

**Files:**
- Modify: `templates/venta_form.html:6`
- Modify: `templates/comprobante.html:10,38`

**Interfaces:**
- Consumes: `csrf_token()` (Task 1).

- [ ] **Step 1: `venta_form.html:6`** (`<form method="post" id="ventaForm">`)
```html
<form method="post" id="ventaForm">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

- [ ] **Step 2: `comprobante.html:10` y `:38`**

Línea 10 (`<form method="post" action="{{ url_for('ventas_enviar_mail', venta_id=venta.id) }}" class="d-inline">`):
```html
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```
Línea 38 (`<form method="post" action="{{ url_for('ventas_facturar', venta_id=venta.id) }}" class="m-0">`):
```html
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

- [ ] **Step 3: Verificación manual**

1. `/ventas/nueva` → registrar una venta de prueba con al menos un producto.
2. Desde el comprobante resultante: si el cliente tiene email cargado, probar "Enviar por mail" (va a fallar por falta de SMTP configurado — verificar que falla con el mensaje esperado de `envio_mail.py`, no con un error de CSRF). Si la venta quedó en `facturacion_estado` distinto de `emitida`, probar el botón "Reintentar facturación".

- [ ] **Step 4: Commit**

```bash
git add templates/venta_form.html templates/comprobante.html
git commit -m "Agregar campo csrf_token a los forms de ventas y comprobante"
```

---

### Task 8: Templates — Tienda pública

**Files:**
- Modify: `templates/tienda_catalogo.html:86`
- Modify: `templates/tienda_carrito.html:21,28`
- Modify: `templates/tienda_checkout.html:17`

**Interfaces:**
- Consumes: `csrf_token()` (Task 1, expuesto también en `base_publica.html` vía Task 2).

- [ ] **Step 1: `tienda_catalogo.html:86`** (`<form method="post" action="{{ url_for('tienda_carrito_agregar') }}" class="d-flex gap-2">`) — NO tocar el form `method="get"` de la línea 9 (buscador/filtro).
```html
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

- [ ] **Step 2: `tienda_carrito.html:21` y `:28`**

Línea 21 (`<form method="post" action="{{ url_for('tienda_carrito_actualizar') }}" class="d-flex gap-1">`):
```html
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```
Línea 28 (`<form method="post" action="{{ url_for('tienda_carrito_quitar') }}">`):
```html
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

- [ ] **Step 3: `tienda_checkout.html:17`** (`<form method="post">`)
```html
      <form method="post">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

- [ ] **Step 4: Verificación manual (sin sesión iniciada, en una ventana de incógnito)**

1. Ir a `/tienda`, agregar un producto al carrito.
2. Ir a `/tienda/carrito`, actualizar la cantidad de un item y luego quitarlo.
3. Agregar otro producto y avanzar a `/tienda/checkout`, completar los datos y confirmar — el flujo se corta si falta `MERCADOPAGO_ACCESS_TOKEN` (esperado, no es un error de CSRF), pero el POST del formulario de checkout tiene que llegar a procesarse antes de ese punto.
4. Confirmar en las devtools que la cookie de sesión se está seteando ya desde la primera visita a `/tienda` (sin login) — es lo que sostiene el token CSRF también para visitantes anónimos.

- [ ] **Step 5: Commit**

```bash
git add templates/tienda_catalogo.html templates/tienda_carrito.html templates/tienda_checkout.html
git commit -m "Agregar campo csrf_token a los forms de la tienda pública"
```

---

### Task 9: Verificación final end-to-end y actualización de CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (sección "Seguridad")

**Interfaces:**
- Consumes: todo lo implementado en Tasks 1-8.

- [ ] **Step 1: Barrido de cobertura**

Correr, desde la raíz del proyecto:
```bash
grep -c 'method="post"' templates/*.html | grep -v ':0'
grep -c 'name="csrf_token"' templates/*.html | grep -v ':0'
```
Expected: para cada archivo listado en el primer comando, el segundo comando tiene que reportar el mismo número (o más, si hay algún caso con dos forms post uno adentro del otro — no debería pasar en este proyecto) para ese mismo archivo. Si algún archivo aparece en el primer listado y no en el segundo (o con un número menor), hay un form sin el campo — corregirlo antes de seguir.

- [ ] **Step 2: Smoke test completo logueado**

Recorrer en el navegador, logueado como admin: crear/editar/eliminar en Clientes, Productos, Proveedores, Categorías; registrar una Venta y una Compra; cambiar la propia contraseña. Ninguna de estas acciones debería mostrar el mensaje "La página quedó desactualizada" (si aparece, algún form quedó sin el campo o con un token vencido por session distinta).

- [ ] **Step 3: Smoke test tienda pública (sin login)**

En una ventana de incógnito: recorrer `/tienda` → agregar al carrito → checkout, igual que en la verificación de Task 8.

- [ ] **Step 4: Actualizar `CLAUDE.md`**

En la sección "Seguridad" de `CLAUDE.md`, mover la protección CSRF de "Pendiente" a "Ya resuelto", agregando una línea nueva al bloque de "Ya resuelto":

```
- Protección CSRF (`Flask-WTF`) en todos los formularios y en los 3
  `fetch()` de alta rápida (clientes/productos), con excepción del webhook
  de Mercado Pago (server-to-server, no lleva sesión de navegador). Errores
  de token muestran un mensaje en español en vez de una página técnica.
```

Y quitar esa línea del punto 3 de "Pendiente" (que hoy dice "protección CSRF en los formularios" junto con HTTPS/rate limiting — dejar el resto del punto 3 igual, solo sacar la mención a CSRF).

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "Documentar protección CSRF ya implementada en CLAUDE.md"
```
