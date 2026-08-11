# Protección CSRF con Flask-WTF

Fecha: 2026-08-10

## Contexto

`CLAUDE.md` (sección "Seguridad") tenía CSRF anotado como pendiente desde
que se implementó el login: "protección CSRF en los formularios", punto 3
de la lista, prioritario ahora que la tienda online (`/tienda`) ya está
expuesta a internet. El sistema no tenía ninguna protección contra CSRF —
cualquier POST autenticado (crear venta, eliminar cliente, resetear
contraseña de un usuario, etc.) podía dispararse desde un sitio de
terceros si la víctima tenía sesión iniciada.

## Alcance

Cubre todos los POST de la app: los ~34 `<form method="post">` repartidos
en 20 templates, y las 3 llamadas `fetch(..., {method:'POST'})` que usan
los modales de alta rápida (cliente en `venta_form.html`, producto en
`compra_form.html` y `compra_revisar_factura.html`). Queda afuera el
webhook `/webhooks/mercadopago`, que no es un POST de navegador con sesión
sino una notificación server-to-server de Mercado Pago (ya tiene su propia
validación de firma en `tienda_pagos.py`, ver `MERCADOPAGO_WEBHOOK_SECRET`).

No incluye armar una suite de tests automatizada (gap aparte, ya
documentado en `CLAUDE.md`) ni tocar `SESSION_COOKIE_SECURE`/HTTPS (depende
de elegir hosting, roadmap punto 8).

## Enfoque elegido

**Flask-WTF** (`CSRFProtect`), en vez de una implementación manual de
tokens. Es el estándar de facto para Flask, protege todos los métodos que
mutan estado (POST/PUT/PATCH/DELETE) globalmente sin decorar ruta por
ruta, y ya sabe validar tanto un campo de formulario (`csrf_token`) como un
header (`X-CSRFToken`) — cubre los dos casos que tiene esta app (forms HTML
tradicionales y los 3 `fetch()` de los modales). Se descartó la
implementación manual por sumar código propio a mantener sin necesidad
real (más superficie para un error sutil, ej. una ruta que se olvide de
validar).

## Diseño

**Backend (`core/app.py`)**

- Nueva dependencia `Flask-WTF` en `requirements.txt`.
- Después de que `app.secret_key` queda seteada (CSRF firma los tokens con
  esa key, así que tiene que existir antes):
  ```python
  from flask_wtf import CSRFProtect
  csrf = CSRFProtect(app)
  ```
- Excepción: `csrf.exempt(webhook_mercadopago)` sobre la función de la
  ruta `/webhooks/mercadopago` (ya definida en `core/app.py`).
- Manejo de error, con el mismo patrón que ya usa el resto de la app
  (flash + redirect, nunca una página de error técnica en inglés):
  ```python
  from flask_wtf.csrf import CSRFError

  @app.errorhandler(CSRFError)
  def manejar_csrf_error(e):
      flash("La página quedó desactualizada. Volvé a intentarlo.", "warning")
      return redirect(request.referrer or url_for("dashboard"))
  ```

**Frontend (templates)**

- Campo oculto `{{ csrf_token() }}` agregado dentro de cada
  `<form method="post">` (no en los `method="get"`, que no mutan estado y
  no lo necesitan). Incluye `login.html`, que es standalone y no extiende
  `base.html`.
- Meta tag nuevo en `base.html` y `base_publica.html`:
  ```html
  <meta name="csrf-token" content="{{ csrf_token() }}">
  ```
- Las 3 llamadas `fetch()` existentes suman el header leído de ese meta
  tag:
  ```js
  fetch('/api/clientes-nuevo', {
    method: 'POST',
    headers: { 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content },
    body: datos,
  })
  ```

## Verificación

No hay suite de tests automatizada en el proyecto. Verificación manual
después de implementar:

1. Login funciona (el form de login también lleva el token, aunque es
   previo a tener sesión iniciada — Flask genera la cookie de sesión igual
   al renderizar `csrf_token()`).
2. Crear una venta nueva (form largo, típico de la app).
3. Alta rápida de cliente desde el modal de Nueva venta (ejercita el
   `fetch()` con header).
4. Un POST sin token (simulado, ej. quitando el campo a mano en devtools)
   cae en el mensaje de error en español + redirect, no en un 400 crudo.
5. El webhook de Mercado Pago sigue respondiendo sin necesitar token
   (simulado, sin credenciales reales — mismo criterio que ya se usó para
   probar el resto de la integración).
6. Catálogo público (`/tienda`) y agregar al carrito (POST sin login)
   siguen funcionando — confirma que el token funciona para sesiones
   anónimas, no solo para usuarios logueados.

## Riesgos / limitaciones conocidas

- Si un formulario queda abierto en una pestaña por mucho tiempo y la
  sesión rota (ej. el servidor se reinicia y cambia `.secret_key` — no
  debería pasar en uso normal, esa key es persistente en disco), el token
  queda inválido y el usuario ve el mensaje de error en vez de que se
  rompa silenciosamente. Es el comportamiento esperado, no un bug.
- No cubre `SESSION_COOKIE_SECURE` ni HTTPS — sigue pendiente hasta elegir
  hosting (roadmap punto 8), sin eso el token viaja igual que cualquier
  otra cookie de sesión hoy.
