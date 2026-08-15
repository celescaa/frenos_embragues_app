"""
Sistema de gestión para venta de frenos y embragues.
Clientes, stock, ventas, compras a proveedores y analítica, todo centralizado.

Cómo correrlo: ver README.md (en resumen, `python app.py` desde la raíz del
proyecto — ese `app.py` es un shim de una línea que expone esta app; el
código en sí vive acá, en core/app.py, junto con el resto del núcleo del
sistema).
"""
import os
import secrets
import psycopg
from decimal import Decimal, InvalidOperation
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError
from datetime import datetime, timedelta, timezone
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from urllib.parse import urlparse
from . import database as db
from . import almacenamiento
from . import supabase_auth
from . import facturacion_afip
from . import tienda_pagos
from . import importar_factura
from . import envio_mail
import tempfile

load_dotenv()  # carga variables de .env (AFIPSDK_ACCESS_TOKEN, etc.) si existe

# Raíz del proyecto: un nivel arriba de core/. templates/ y static/ viven ahí
# (no adentro de core/), así que Flask necesita que se lo indiquen explícito
# en vez de asumir que están al lado de este archivo.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = Flask(
    __name__,
    template_folder=os.path.join(PROJECT_ROOT, "templates"),
    static_folder=os.path.join(PROJECT_ROOT, "static"),
)

# La clave de sesión sale de la variable de entorno SECRET_KEY. En Vercel eso
# no es opcional: no hay disco persistente, así que un archivo se regeneraría
# en cada arranque en frío y tiraría abajo todas las sesiones abiertas.
#
# Corriendo local se conserva el archivo de siempre (nunca hardcodeada en el
# código ni en el repositorio), para no tener que definir la variable a mano
# en cada `python app.py`.
_SECRET_KEY_ENV = os.environ.get("SECRET_KEY")
if _SECRET_KEY_ENV:
    app.secret_key = _SECRET_KEY_ENV
else:
    _SECRET_KEY_PATH = os.path.join(PROJECT_ROOT, ".secret_key")
    if os.path.exists(_SECRET_KEY_PATH):
        with open(_SECRET_KEY_PATH) as _f:
            app.secret_key = _f.read().strip()
    else:
        app.secret_key = secrets.token_hex(32)
        try:
            with open(_SECRET_KEY_PATH, "w") as _f:
                _f.write(app.secret_key)
        except OSError as e:
            # Pasa en Vercel (y en cualquier serverless) si SECRET_KEY quedó
            # sin definir: el filesystem es de solo lectura, así que el
            # archivo no se puede crear. Sin este mensaje, lo único que se ve
            # en el log es un PermissionError sobre un archivo oculto, que no
            # sugiere en ningún momento cuál es la variable que falta.
            #
            # Se corta en vez de seguir con una clave en memoria a propósito:
            # esa clave sería distinta en cada arranque en frío, así que las
            # sesiones se cerrarían solas cada pocos minutos y el problema
            # aparecería como "el sistema me desloguea todo el tiempo", mucho
            # más difícil de rastrear hasta acá.
            raise RuntimeError(
                "Falta la variable de entorno SECRET_KEY y no se puede escribir "
                f"el archivo {_SECRET_KEY_PATH} ({e}). En un hosting sin disco "
                "de escritura (Vercel) SECRET_KEY es obligatoria: generala con "
                "`python -c \"import secrets; print(secrets.token_hex(32))\"` y "
                "cargala en las variables de entorno del proyecto."
            ) from e

csrf = CSRFProtect(app)
# El default de Flask-WTF (WTF_CSRF_TIME_LIMIT = 3600s = 1 hora) es mucho más
# corto que la sesión de este sistema (12hs, ver PERMANENT_SESSION_LIFETIME
# abajo). En pantallas donde un formulario puede quedar abierto un rato largo
# (revisión de factura importada, carga de una venta con muchos productos),
# eso rompía con un "página desactualizada" antes de que la sesión expirara
# de verdad. None hace que la validez del token siga la duración de la
# sesión en vez de un límite fijo aparte — no debilita la protección (el
# token sigue atado a la sesión y firmado), solo saca ese límite arbitrario.
app.config["WTF_CSRF_TIME_LIMIT"] = None

app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=12)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# HTTPS lo provee Vercel. Se activa por variable de entorno en vez de estar
# fijo, porque corriendo local (http://127.0.0.1:5050) una cookie "secure" no
# viajaría nunca y no se podría iniciar sesión.
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE") == "1"

# Vercel pone la aplicación detrás de un proxy que termina el HTTPS y reenvía
# por HTTP. Sin esto, `request.host` sale del header Host crudo — que el
# cliente puede falsificar, y que `manejar_csrf_error` (justo acá abajo) usa
# para su chequeo de mismo origen — y `url_for(_external=True)` arma URLs
# http:// en un sitio https://. Un solo proxy de confianza: el de Vercel.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


@app.errorhandler(CSRFError)
def manejar_csrf_error(e):
    flash("La página quedó desactualizada. Volvé a intentarlo.", "warning")
    # request.referrer lo controla quien hace el request: no redirigir ahí
    # sin validar (open redirect) — solo se honra si es del mismo origen.
    # Sin referrer válido, caer a la tienda pública si la ruta era /tienda
    # (un cliente anónimo no tiene por qué terminar en el panel de admin,
    # que lo rebota a /login) y al dashboard en cualquier otro caso.
    destino = request.referrer
    if not destino or urlparse(destino).netloc != request.host:
        destino = url_for("tienda_catalogo") if request.path.startswith("/tienda") else url_for("dashboard")
    return redirect(destino)

LOCKOUT_INTENTOS = 5
LOCKOUT_MINUTOS = 15


# El esquema (tablas, columnas) no lo crea ni lo migra este módulo: vive en
# supabase/migrations/. El primer usuario admin tampoco se autogenera acá: se
# crea desde el panel de Supabase (ver README).
#
# Los datos de ejemplo se siembran únicamente al correr la app a mano, desde
# el bloque __main__ del `app.py` de la raíz. NO pueden sembrarse a nivel de
# módulo: ahí se ejecutarían en cada arranque en frío de una función
# serverless, y como la condición de siembra es "la base está vacía" —que es
# justo el estado de una base de producción recién creada— el primer visitante
# del sistema real le sembraría productos y ventas de mentira al negocio.
def sembrar_datos_de_ejemplo():
    """Carga los datos de ejemplo si la base está vacía. Solo la llama el
    arranque manual (`python app.py`), nunca el import del módulo."""
    conn = db.get_connection()
    try:
        db.seed_demo_data(conn)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------
ENDPOINTS_PUBLICOS = {"login", "static"}
ENDPOINTS_PERMITIDOS_SIN_CAMBIAR_PASSWORD = {"cambiar_password", "logout", "static"}
# La tienda pública y el webhook de Mercado Pago no requieren login: cualquier
# visitante (o el servidor de Mercado Pago) tiene que poder acceder.
PREFIJOS_PUBLICOS = ("/tienda", "/webhooks/")


@app.before_request
def verificar_sesion():
    if request.endpoint is None or request.endpoint in ENDPOINTS_PUBLICOS:
        return
    if request.path.startswith(PREFIJOS_PUBLICOS):
        return
    if not session.get("usuario_id"):
        return redirect(url_for("login", next=request.path))
    if session.get("debe_cambiar_password") and request.endpoint not in ENDPOINTS_PERMITIDOS_SIN_CAMBIAR_PASSWORD:
        flash("Antes de continuar, tenés que elegir una contraseña nueva.", "warning")
        return redirect(url_for("cambiar_password"))


@app.context_processor
def inject_usuario():
    return {
        "usuario_actual": {
            "nombre": session.get("usuario_nombre"),
            "rol": session.get("usuario_rol"),
        }
    }


def es_admin():
    return session.get("usuario_rol") == "admin"


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("usuario_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        identificador = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = db.get_connection()

        # Se admite entrar con el nombre de usuario o con el email. Supabase
        # Auth solo entiende de emails, así que un username se traduce contra
        # nuestra propia tabla antes de preguntarle a Supabase.
        if "@" in identificador:
            usuario = conn.execute(
                "SELECT * FROM usuarios WHERE email = %s", (identificador,)
            ).fetchone()
        else:
            usuario = conn.execute(
                "SELECT * FROM usuarios WHERE username = %s", (identificador,)
            ).fetchone()

        # ¿La cuenta está bloqueada por intentos fallidos? bloqueado_hasta es
        # timestamptz: psycopg ya lo devuelve como datetime tz-aware, no hace
        # falta parsearlo a mano — comparar contra un datetime.now() naive
        # lanzaría TypeError, así que "ahora" también se pide tz-aware.
        if usuario and usuario["bloqueado_hasta"]:
            bloqueado_hasta = usuario["bloqueado_hasta"]
            ahora = datetime.now(timezone.utc)
            if ahora < bloqueado_hasta:
                minutos = int((bloqueado_hasta - ahora).total_seconds() // 60) + 1
                flash(f"Demasiados intentos fallidos. Probá de nuevo en {minutos} minuto(s).", "danger")
                conn.close()
                return render_template("login.html")
            conn.execute("UPDATE usuarios SET intentos_fallidos=0, bloqueado_hasta=NULL WHERE id=%s", (usuario["id"],))
            conn.commit()
            usuario = conn.execute("SELECT * FROM usuarios WHERE id=%s", (usuario["id"],)).fetchone()

        # Solo se le pregunta a Supabase si el perfil existe y está activo:
        # dar de baja a alguien tiene que cerrarle la puerta aunque su cuenta
        # siga existiendo del otro lado.
        id_verificado = None
        if usuario and usuario["activo"] and usuario["email"]:
            id_verificado = supabase_auth.verificar_credenciales(usuario["email"], password)

        credenciales_validas = bool(
            id_verificado and str(id_verificado) == str(usuario["id"])
        )

        if not credenciales_validas:
            if usuario and usuario["activo"]:
                intentos = usuario["intentos_fallidos"] + 1
                if intentos >= LOCKOUT_INTENTOS:
                    bloqueado_hasta = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTOS)
                    conn.execute(
                        "UPDATE usuarios SET intentos_fallidos=%s, bloqueado_hasta=%s WHERE id=%s",
                        (intentos, bloqueado_hasta, usuario["id"]),
                    )
                    flash(f"Demasiados intentos fallidos. La cuenta queda bloqueada {LOCKOUT_MINUTOS} minutos.", "danger")
                else:
                    conn.execute("UPDATE usuarios SET intentos_fallidos=%s WHERE id=%s", (intentos, usuario["id"]))
                    flash("Usuario o contraseña incorrectos.", "danger")
                conn.commit()
            else:
                flash("Usuario o contraseña incorrectos.", "danger")
            conn.close()
            return render_template("login.html")

        conn.execute("UPDATE usuarios SET intentos_fallidos=0, bloqueado_hasta=NULL WHERE id=%s", (usuario["id"],))
        conn.commit()
        conn.close()

        session.clear()
        session.permanent = True
        # str(): el id es un UUID, y la cookie de sesión se serializa a JSON.
        session["usuario_id"] = str(usuario["id"])
        session["usuario_nombre"] = usuario["nombre"]
        session["usuario_rol"] = usuario["rol"]
        session["debe_cambiar_password"] = bool(usuario["debe_cambiar_password"])

        if usuario["debe_cambiar_password"]:
            return redirect(url_for("cambiar_password"))
        flash(f"Bienvenido, {usuario['nombre']}.", "success")
        siguiente = request.args.get("next")
        return redirect(siguiente or url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Cerraste sesión.", "info")
    return redirect(url_for("login"))


@app.route("/cambiar-password", methods=["GET", "POST"])
def cambiar_password():
    obligatorio = bool(session.get("debe_cambiar_password"))
    if request.method == "POST":
        actual = request.form.get("actual", "")
        nueva = request.form.get("nueva", "")
        confirmar = request.form.get("confirmar", "")

        conn = db.get_connection()
        usuario = conn.execute("SELECT * FROM usuarios WHERE id=%s", (session["usuario_id"],)).fetchone()

        # La contraseña actual se verifica pidiéndole a Supabase que inicie
        # sesión con ella: si entra, era la correcta. No se pide cuando el
        # cambio es obligatorio (el usuario acaba de escribirla para entrar).
        actual_valida = obligatorio or bool(
            supabase_auth.verificar_credenciales(usuario["email"], actual)
        )

        # El orden de las ramas importa: el cambio contra Supabase va ÚLTIMO,
        # después de validar largo y coincidencia. Al revés, una contraseña
        # que el sistema rechaza ya habría quedado guardada del otro lado.
        if not actual_valida:
            flash("La contraseña actual no es correcta.", "danger")
        elif len(nueva) < 8:
            flash("La contraseña nueva tiene que tener al menos 8 caracteres.", "danger")
        elif nueva != confirmar:
            flash("Las contraseñas nuevas no coinciden.", "danger")
        elif not supabase_auth.cambiar_password(usuario["id"], nueva):
            flash("No se pudo cambiar la contraseña. Probá de nuevo en un momento.", "danger")
        else:
            conn.execute(
                "UPDATE usuarios SET debe_cambiar_password=false WHERE id=%s",
                (usuario["id"],),
            )
            conn.commit()
            conn.close()
            session["debe_cambiar_password"] = False
            flash("Contraseña actualizada correctamente.", "success")
            return redirect(url_for("dashboard"))
        conn.close()

    return render_template("cambiar_password.html", obligatorio=obligatorio)


# ---------------------------------------------------------------------------
# Datos del negocio (aparecen en el encabezado y en los comprobantes)
# ---------------------------------------------------------------------------
NEGOCIO = {
    "nombre": "Repuestos San Ignacio",
    "subtitulo": "Casa de frenos y embragues",
    "titular": "Caamaño Matías Ezequiel",
    "direccion": "San Ignacio 2115, Ituzaingó Norte",
    "telefono": "+54 9 11 6130-5237",
    "cuit": "20-35075394-0",
    "instagram": "@repuestos_sanignacio",
    "facebook": "Repuestos San Ignacio",
    "web": "frenosi.com.ar",
}


@app.context_processor
def inject_negocio():
    return {"negocio": NEGOCIO}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def money(v):
    try:
        return f"${v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return v


def whatsapp_url(mensaje=None):
    """Arma el link de wa.me al WhatsApp real del negocio, con un mensaje
    precargado opcional. Se usa en la tienda pública (botón flotante, footer,
    checkout y páginas de estado del pedido)."""
    from urllib.parse import quote
    numero = "".join(ch for ch in NEGOCIO["telefono"] if ch.isdigit())
    url = f"https://wa.me/{numero}"
    if mensaje:
        url += f"?text={quote(mensaje)}"
    return url


def instagram_url():
    return "https://instagram.com/" + NEGOCIO["instagram"].lstrip("@")


app.jinja_env.globals["whatsapp_url"] = whatsapp_url
app.jinja_env.globals["instagram_url"] = instagram_url


app.jinja_env.filters["money"] = money


app.jinja_env.filters["url_imagen"] = almacenamiento.url_publica

EXTENSIONES_IMAGEN_PERMITIDAS = {"jpg", "jpeg", "png", "webp"}


def a_decimal(valor):
    """Convierte un valor de formulario a Decimal para una columna de plata
    (NUMERIC en Postgres). Nunca usar float() acá: mezclar Decimal con
    float en una cuenta más adelante lanza TypeError, y float ya venía
    acumulando error de redondeo desde antes de esta migración.

    Mismo criterio que el `or 0` que ya usaba cada sitio: valor ausente o
    vacío da Decimal("0"). No se le suma tolerancia a formatos nuevos (por
    ejemplo coma decimal) — un valor inválido tiene que fallar igual que
    fallaba antes con float(), no silenciarse acá."""
    return Decimal(str(valor or 0))


def a_entero(valor, default=None):
    """Convierte un valor de formulario a int para una columna INTEGER (un id,
    una cantidad), o devuelve `default` si no es un número.

    Hace falta porque Postgres es estricto donde SQLite era permisivo: con
    SQLite, `WHERE id = 'abc'` no matcheaba nada y la app seguía por la rama
    de "no existe"; Postgres aborta la consulta con
    `invalid input syntax for type integer` y la ruta termina en un 500. Sin
    esto, cualquiera puede romper `/tienda/carrito/*` (pública, sin login)
    posteando un id que no sea un número."""
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return default


def guardar_imagen_producto(producto_id, file_storage):
    """Guarda la foto subida para un producto y devuelve el nombre de archivo
    a guardar en productos.imagen, o None si no se subió nada válido.

    La foto va a Supabase Storage, no al disco: en Vercel el disco no
    sobrevive al siguiente arranque en frío. `productos.imagen` sigue
    guardando solo el nombre del archivo, igual que antes -- lo que cambió es
    de dónde lo sirve el navegador (ver el filtro `url_imagen`)."""
    if not file_storage or not file_storage.filename:
        return None
    extension = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    if extension not in EXTENSIONES_IMAGEN_PERMITIDAS:
        return None
    nombre_archivo = secure_filename(f"producto_{producto_id}.{extension}")
    if not almacenamiento.subir_imagen(
        nombre_archivo, file_storage.read(), file_storage.content_type
    ):
        return None
    return nombre_archivo


def eliminar_imagen_producto(nombre_archivo):
    almacenamiento.borrar_imagen(nombre_archivo)


def productos_para_buscador(productos):
    """Lista liviana de productos en JSON para el buscador tipo autocompletar
    (Nueva venta, Nueva compra, movimientos sin factura). Incluye
    modelo_compatible para que buscar por auto (ej. "Gol") también matchee,
    no solo nombre/código/marca."""
    return [
        {
            "id": p["id"],
            "nombre": p["nombre"],
            "codigo": p["codigo"] or "",
            "marca": p["marca"] or "",
            "modelo_compatible": p["modelo_compatible"] or "",
            "precio_venta": p["precio_venta"],
            "precio_costo": p["precio_costo"],
            "stock_actual": p["stock_actual"],
        }
        for p in productos
    ]


def subcategorias_por_categoria_json(conn):
    """{"Nombre categoría": ["Subcat 1", "Subcat 2", ...], ...} para armar el
    desplegable de subcategoría en cascada (JS) según la categoría elegida."""
    mapa = {}
    for s in db.obtener_subcategorias(conn, solo_activas=True):
        mapa.setdefault(s["categoria_nombre"], []).append(s["nombre"])
    return mapa


# ---------------------------------------------------------------------------
# Dashboard / Analítica
# ---------------------------------------------------------------------------
@app.route("/")
def dashboard():
    conn = db.get_connection()

    total_ventas_hist = conn.execute("SELECT COALESCE(SUM(total),0) AS t FROM ventas").fetchone()["t"]

    hoy = db.hoy()
    primer_dia_mes = hoy.replace(day=1)
    ventas_mes = conn.execute(
        "SELECT COALESCE(SUM(total),0) AS t FROM ventas WHERE fecha >= %s", (primer_dia_mes,)
    ).fetchone()["t"]

    cant_clientes = conn.execute("SELECT COUNT(*) AS c FROM clientes").fetchone()["c"]
    cant_productos = conn.execute("SELECT COUNT(*) AS c FROM productos").fetchone()["c"]

    # Ventas por mes (últimos 6 meses)
    meses = []
    ventas_por_mes = []
    for i in range(5, -1, -1):
        ref = (hoy.replace(day=1) - timedelta(days=1)) if i == 0 else hoy
        # calcular primer día del mes i meses atrás
        year = hoy.year
        month = hoy.month - i
        while month <= 0:
            month += 12
            year -= 1
        inicio = f"{year:04d}-{month:02d}-01"
        if month == 12:
            fin = f"{year+1:04d}-01-01"
        else:
            fin = f"{year:04d}-{month+1:02d}-01"
        total = conn.execute(
            "SELECT COALESCE(SUM(total),0) AS t FROM ventas WHERE fecha >= %s AND fecha < %s", (inicio, fin)
        ).fetchone()["t"]
        meses.append(f"{month:02d}/{year}")
        ventas_por_mes.append(round(total, 2))

    # Top 5 productos más vendidos (por cantidad). GROUP BY p.id (no
    # vi.producto_id): Postgres exige agrupar por la primary key de la
    # tabla de la que sale p.nombre -- vi.producto_id no alcanza aunque el
    # JOIN garantice el mismo agrupamiento fila por fila.
    top_productos = conn.execute(
        """SELECT p.nombre, SUM(vi.cantidad) AS cantidad, SUM(vi.subtotal) AS total
           FROM venta_items vi JOIN productos p ON p.id = vi.producto_id
           GROUP BY p.id ORDER BY cantidad DESC LIMIT 5"""
    ).fetchall()

    # Top 5 clientes por monto comprado (mismo motivo: GROUP BY c.id).
    top_clientes = conn.execute(
        """SELECT c.nombre, SUM(v.total) AS total, COUNT(v.id) AS cant_compras
           FROM ventas v JOIN clientes c ON c.id = v.cliente_id
           GROUP BY c.id ORDER BY total DESC LIMIT 5"""
    ).fetchall()

    # Stock bajo
    stock_bajo = conn.execute(
        "SELECT * FROM productos WHERE stock_actual <= stock_minimo ORDER BY stock_actual ASC"
    ).fetchall()

    conn.close()

    return render_template(
        "dashboard.html",
        total_ventas_hist=total_ventas_hist,
        ventas_mes=ventas_mes,
        cant_clientes=cant_clientes,
        cant_productos=cant_productos,
        meses=meses,
        ventas_por_mes=ventas_por_mes,
        top_productos=top_productos,
        top_clientes=top_clientes,
        stock_bajo=stock_bajo,
    )


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------
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
                WHERE c.nombre ILIKE %s OR c.telefono ILIKE %s OR c.email ILIKE %s
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


@app.route("/clientes/nuevo", methods=["GET", "POST"])
def clientes_nuevo():
    if request.method == "POST":
        conn = db.get_connection()
        conn.execute(
            """INSERT INTO clientes (nombre, telefono, email, direccion, cuit_dni, tipo_cliente, condicion_iva, fecha_alta)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                request.form["nombre"],
                request.form.get("telefono", ""),
                request.form.get("email", ""),
                request.form.get("direccion", ""),
                request.form.get("cuit_dni", ""),
                request.form.get("tipo_cliente", "particular"),
                request.form.get("condicion_iva", "consumidor_final"),
                db.hoy(),
            ),
        )
        conn.commit()
        conn.close()
        flash("Cliente creado correctamente.", "success")
        return redirect(url_for("clientes_lista"))
    return render_template("cliente_form.html", cliente=None, condiciones_iva=facturacion_afip.CONDICIONES_IVA)


@app.route("/clientes/<int:cliente_id>/editar", methods=["GET", "POST"])
def clientes_editar(cliente_id):
    conn = db.get_connection()
    if request.method == "POST":
        conn.execute(
            """UPDATE clientes SET nombre=%s, telefono=%s, email=%s, direccion=%s, cuit_dni=%s, tipo_cliente=%s,
               condicion_iva=%s WHERE id=%s""",
            (
                request.form["nombre"],
                request.form.get("telefono", ""),
                request.form.get("email", ""),
                request.form.get("direccion", ""),
                request.form.get("cuit_dni", ""),
                request.form.get("tipo_cliente", "particular"),
                request.form.get("condicion_iva", "consumidor_final"),
                cliente_id,
            ),
        )
        conn.commit()
        conn.close()
        flash("Cliente actualizado.", "success")
        return redirect(url_for("clientes_lista"))
    cliente = conn.execute("SELECT * FROM clientes WHERE id=%s", (cliente_id,)).fetchone()
    conn.close()
    return render_template("cliente_form.html", cliente=cliente, condiciones_iva=facturacion_afip.CONDICIONES_IVA)


@app.route("/clientes/<int:cliente_id>/eliminar", methods=["POST"])
def clientes_eliminar(cliente_id):
    conn = db.get_connection()
    conn.execute("DELETE FROM clientes WHERE id=%s", (cliente_id,))
    conn.commit()
    conn.close()
    flash("Cliente eliminado.", "info")
    return redirect(url_for("clientes_lista"))


# ---------------------------------------------------------------------------
# Cuenta corriente de clientes (típicamente mecánicos que compran a crédito
# para un tercero — el auto/cliente final queda solo como referencia).
# ---------------------------------------------------------------------------
@app.route("/clientes/<int:cliente_id>/cuenta-corriente")
def cuenta_corriente_ver(cliente_id):
    conn = db.get_connection()
    cliente = conn.execute("SELECT * FROM clientes WHERE id=%s", (cliente_id,)).fetchone()
    if not cliente:
        conn.close()
        flash("No encontré ese cliente.", "danger")
        return redirect(url_for("clientes_lista"))
    movimientos = conn.execute(
        """SELECT * FROM cuenta_corriente_movimientos
           WHERE cliente_id=%s ORDER BY fecha DESC, id DESC""",
        (cliente_id,),
    ).fetchall()
    movimientos = [dict(m) for m in movimientos]
    for m in movimientos:
        # ojo: no llamarla "items" — Jinja resuelve m.items contra el
        # método dict.items() antes que la clave, y el template quedaría
        # iterando sobre el método en vez de esta lista.
        m["renglones"] = conn.execute(
            """SELECT i.*, p.nombre AS producto_nombre, p.codigo AS producto_codigo
               FROM cuenta_corriente_movimiento_items i JOIN productos p ON p.id = i.producto_id
               WHERE i.movimiento_id=%s""",
            (m["id"],),
        ).fetchall()
    saldo = sum(m["monto"] if m["tipo"] == "cargo" else -m["monto"] for m in movimientos)
    productos = conn.execute("SELECT * FROM productos ORDER BY nombre").fetchall()
    conn.close()
    return render_template(
        "cuenta_corriente.html", cliente=cliente, movimientos=movimientos, saldo=saldo,
        productos_json=productos_para_buscador(productos),
        umbral_identificacion=facturacion_afip.UMBRAL_IDENTIFICACION_RECEPTOR,
        condiciones_iva=facturacion_afip.CONDICIONES_IVA,
    )


@app.route("/clientes/<int:cliente_id>/cuenta-corriente/nueva", methods=["POST"])
def cuenta_corriente_nueva(cliente_id):
    """Registra un movimiento de cuenta corriente.

    - `pago`: cancela deuda, monto libre, no toca stock ni factura.
    - `cargo`: el mecánico se lleva uno o más productos a crédito — mismo
      criterio que una venta (el stock se descuenta al confirmarse, no
      cuando se termina de pagar) pero sin cobrar en el momento. Puede
      facturarse a nombre del mecánico (default) o de un tercero
      identificado con su propio CUIT/DNI (`tercero_cuit_dni`) — por
      ejemplo cuando el mecánico compra en nombre de un cliente suyo.
    """
    conn = db.get_connection()
    cliente = conn.execute("SELECT * FROM clientes WHERE id=%s", (cliente_id,)).fetchone()
    if not cliente:
        conn.close()
        flash("No encontré ese cliente.", "danger")
        return redirect(url_for("clientes_lista"))

    tipo = request.form.get("tipo", "cargo")
    if tipo not in ("cargo", "pago"):
        tipo = "cargo"
    cliente_tercero_nombre = request.form.get("cliente_tercero_nombre", "").strip() or None
    observaciones = request.form.get("observaciones", "").strip() or None

    if tipo == "pago":
        try:
            monto = a_decimal(request.form.get("monto"))
        except InvalidOperation:
            monto = Decimal("0")
        if monto <= 0:
            flash("El monto tiene que ser mayor a cero.", "danger")
            conn.close()
            return redirect(url_for("cuenta_corriente_ver", cliente_id=cliente_id))

        conn.execute(
            """INSERT INTO cuenta_corriente_movimientos
               (cliente_id, cliente_tercero_nombre, monto, tipo, observaciones)
               VALUES (%s, %s, %s, 'pago', %s)""",
            (cliente_id, cliente_tercero_nombre, monto, observaciones),
        )
        conn.commit()
        conn.close()
        flash("Pago registrado en la cuenta corriente.", "success")
        return redirect(url_for("cuenta_corriente_ver", cliente_id=cliente_id))

    # tipo == "cargo": uno o más productos, como una mini venta a crédito.
    tercero_cuit_dni = request.form.get("tercero_cuit_dni", "").strip() or None
    tercero_condicion_iva = request.form.get("tercero_condicion_iva", "").strip() or None
    producto_ids = request.form.getlist("producto_id")
    cantidades = request.form.getlist("cantidad")

    items = []
    for pid, cant in zip(producto_ids, cantidades):
        if not pid or not cant:
            continue
        try:
            cant = int(cant)
        except ValueError:
            continue
        if cant <= 0:
            continue
        producto = conn.execute("SELECT * FROM productos WHERE id=%s", (pid,)).fetchone()
        if not producto:
            continue
        subtotal = cant * producto["precio_venta"]
        items.append((producto["id"], cant, producto["precio_venta"], subtotal))

    if not items:
        flash("Agregá al menos un producto al cargo.", "danger")
        conn.close()
        return redirect(url_for("cuenta_corriente_ver", cliente_id=cliente_id))

    monto = sum(it[3] for it in items)
    receptor_cuit_dni = tercero_cuit_dni or (cliente["cuit_dni"] or "")
    if monto > facturacion_afip.UMBRAL_IDENTIFICACION_RECEPTOR and not receptor_cuit_dni.strip():
        a_quien = cliente_tercero_nombre or cliente["nombre"]
        flash(
            f"Este cargo supera el monto a partir del cual ARCA exige identificar al receptor. "
            f"Cargá el CUIT/DNI de {a_quien} (ficha del cliente, o el campo de CUIT/DNI del tercero) antes de continuar.",
            "danger",
        )
        conn.close()
        return redirect(url_for("cuenta_corriente_ver", cliente_id=cliente_id))

    cur = conn.execute(
        """INSERT INTO cuenta_corriente_movimientos
           (cliente_id, cliente_tercero_nombre, tercero_cuit_dni, tercero_condicion_iva, monto, tipo, observaciones)
           VALUES (%s, %s, %s, %s, %s, 'cargo', %s) RETURNING id""",
        (cliente_id, cliente_tercero_nombre, tercero_cuit_dni, tercero_condicion_iva, monto, observaciones),
    )
    movimiento_id = cur.fetchone()["id"]
    for producto_id, cant, precio_unitario, subtotal in items:
        conn.execute(
            """INSERT INTO cuenta_corriente_movimiento_items
               (movimiento_id, producto_id, cantidad, precio_unitario, subtotal) VALUES (%s, %s, %s, %s, %s)""",
            (movimiento_id, producto_id, cant, precio_unitario, subtotal),
        )
        # el producto se lo lleva ahora mismo, solo falta que se pague —
        # mismo criterio que una venta al contado.
        conn.execute("UPDATE productos SET stock_actual = stock_actual - %s WHERE id=%s", (cant, producto_id))
    conn.commit()
    conn.close()

    # Nunca bloquea ni revierte el movimiento si ARCA falla: se puede
    # reintentar después desde esta misma pantalla (igual criterio que con
    # la factura de una venta del local).
    facturacion_afip.emitir_factura_movimiento(movimiento_id)

    flash("Cargo registrado en la cuenta corriente y stock descontado.", "success")
    return redirect(url_for("cuenta_corriente_ver", cliente_id=cliente_id))


@app.route("/clientes/<int:cliente_id>/cuenta-corriente/<int:movimiento_id>/facturar", methods=["POST"])
def cuenta_corriente_facturar(cliente_id, movimiento_id):
    """Reintento manual de la Factura A/B de un cargo de cuenta corriente."""
    facturacion_afip.emitir_factura_movimiento(movimiento_id)
    conn = db.get_connection()
    estado = conn.execute(
        "SELECT facturacion_estado, facturacion_error FROM cuenta_corriente_movimientos WHERE id=%s",
        (movimiento_id,),
    ).fetchone()
    conn.close()
    if not estado:
        flash("No encontré ese movimiento.", "danger")
    elif estado["facturacion_estado"] == "emitida":
        flash("Factura emitida correctamente.", "success")
    elif estado["facturacion_estado"] == "sin_configurar":
        flash("Todavía no está configurado el acceso a Afip SDK (AFIPSDK_ACCESS_TOKEN). Ver README.md.", "warning")
    else:
        flash("No se pudo emitir la factura: %s" % (estado["facturacion_error"] or "error desconocido"), "danger")
    return redirect(url_for("cuenta_corriente_ver", cliente_id=cliente_id))


@app.route("/clientes/top-deudores")
def clientes_top_deudores():
    """Ranking de los clientes con mayor saldo pendiente en su cuenta
    corriente (cargos menos pagos), para priorizar a quién reclamarle."""
    conn = db.get_connection()
    deudores = conn.execute(
        """SELECT c.id, c.nombre, c.telefono,
                  COALESCE(SUM(CASE WHEN m.tipo='cargo' THEN m.monto ELSE 0 END), 0)
                  - COALESCE(SUM(CASE WHEN m.tipo='pago' THEN m.monto ELSE 0 END), 0) AS saldo
           FROM clientes c JOIN cuenta_corriente_movimientos m ON m.cliente_id = c.id
           GROUP BY c.id
           HAVING COALESCE(SUM(CASE WHEN m.tipo='cargo' THEN m.monto ELSE 0 END), 0)
                  - COALESCE(SUM(CASE WHEN m.tipo='pago' THEN m.monto ELSE 0 END), 0) > 0
           ORDER BY saldo DESC
           LIMIT 5"""
    ).fetchall()
    conn.close()
    return render_template("clientes_top_deudores.html", deudores=deudores)


# ---------------------------------------------------------------------------
# Ranking de clientes + descuentos aprobados manualmente
# ---------------------------------------------------------------------------
PERIODOS_RANKING = {"30": "Últimos 30 días", "90": "Últimos 90 días", "365": "Último año", "todo": "Histórico"}


@app.route("/clientes/top")
def clientes_top():
    conn = db.get_connection()
    periodo = request.args.get("periodo", "90")
    if periodo not in PERIODOS_RANKING:
        periodo = "90"

    parametros = []
    condicion_fecha = ""
    if periodo != "todo":
        desde = db.hoy() - timedelta(days=int(periodo))
        condicion_fecha = "WHERE v.fecha >= %s"
        parametros = [desde]

    ranking = conn.execute(
        f"""SELECT c.id, c.nombre, c.tipo_cliente, COUNT(v.id) AS cant_compras, SUM(v.total) AS total
            FROM ventas v JOIN clientes c ON c.id = v.cliente_id
            {condicion_fecha}
            GROUP BY c.id ORDER BY total DESC LIMIT 5""",
        parametros,
    ).fetchall()

    # Margen estimado con el costo ACTUAL de cada producto (aproximación:
    # el costo real al momento de la venta pudo ser distinto si cambió
    # desde entonces). Sirve como referencia para quien aprueba el descuento,
    # no como número contable exacto.
    margenes = {}
    for r in ranking:
        params_margen = [r["id"]] + parametros
        margen = conn.execute(
            f"""SELECT COALESCE(SUM(vi.cantidad * (vi.precio_unitario - p.precio_costo)), 0) AS margen
                FROM venta_items vi JOIN ventas v ON v.id = vi.venta_id JOIN productos p ON p.id = vi.producto_id
                WHERE v.cliente_id = %s {"AND v.fecha >= %s" if condicion_fecha else ""}""",
            params_margen,
        ).fetchone()
        margenes[r["id"]] = margen["margen"]

    promociones_vigentes = conn.execute(
        """SELECT pa.*, c.nombre AS cliente_nombre FROM promociones_aplicadas pa
           JOIN clientes c ON c.id = pa.cliente_id
           WHERE fecha_inicio <= CURRENT_DATE AND (fecha_fin IS NULL OR fecha_fin >= CURRENT_DATE)
           ORDER BY fecha_aprobacion DESC"""
    ).fetchall()

    productos = conn.execute("SELECT * FROM productos ORDER BY nombre").fetchall()
    conn.close()
    return render_template(
        "clientes_top.html", ranking=ranking, margenes=margenes, periodo=periodo, periodos=PERIODOS_RANKING,
        promociones_vigentes=promociones_vigentes, productos=productos,
    )


@app.route("/clientes/<int:cliente_id>/promocion/nueva", methods=["POST"])
def promocion_nueva(cliente_id):
    """Aplica manualmente un descuento aprobado a un cliente (ver
    /clientes/top). Se usa en registrar_venta() -> aplicar_promociones()
    para el resto de las ventas mientras esté vigente."""
    conn = db.get_connection()
    tipo = request.form.get("tipo", "porcentaje")
    if tipo not in ("porcentaje", "monto_fijo"):
        tipo = "porcentaje"
    try:
        porcentaje_o_monto = a_decimal(request.form.get("porcentaje_o_monto"))
    except InvalidOperation:
        porcentaje_o_monto = Decimal("0")
    alcance = request.form.get("alcance", "todo")
    if alcance not in ("todo", "productos_puntuales"):
        alcance = "todo"
    fecha_inicio = request.form.get("fecha_inicio") or db.hoy()
    fecha_fin = request.form.get("fecha_fin") or None
    aprobado_por = session.get("usuario_nombre")

    if porcentaje_o_monto <= 0:
        flash("El valor del descuento tiene que ser mayor a cero.", "danger")
        conn.close()
        return redirect(url_for("clientes_top"))

    cur = conn.execute(
        """INSERT INTO promociones_aplicadas
           (cliente_id, porcentaje_o_monto, tipo, alcance, fecha_inicio, fecha_fin, aprobado_por)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (cliente_id, porcentaje_o_monto, tipo, alcance, fecha_inicio, fecha_fin, aprobado_por),
    )
    promocion_id = cur.fetchone()["id"]

    if alcance == "productos_puntuales":
        for producto_id in request.form.getlist("producto_id"):
            conn.execute(
                "INSERT INTO promocion_productos (promocion_id, producto_id) VALUES (%s, %s)",
                (promocion_id, producto_id),
            )

    conn.commit()
    conn.close()
    flash("Promoción aplicada.", "success")
    return redirect(url_for("clientes_top", periodo=request.form.get("periodo", "90")))


@app.route("/promociones/<int:promocion_id>/finalizar", methods=["POST"])
def promocion_finalizar(promocion_id):
    conn = db.get_connection()
    conn.execute(
        "UPDATE promociones_aplicadas SET fecha_fin=%s WHERE id=%s",
        (db.hoy(), promocion_id),
    )
    conn.commit()
    conn.close()
    flash("Promoción finalizada.", "info")
    return redirect(url_for("clientes_top"))


def guardar_cotizaciones_proveedor(conn, producto_id, form):
    """Sincroniza las filas de 'precio por proveedor' que vienen del formulario.

    Es más simple borrar todo lo que había para este producto y volver a
    insertar lo que se mandó, que tratar de calcular altas/bajas/cambios.
    """
    proveedor_ids = form.getlist("cotiz_proveedor_id")
    precios = form.getlist("cotiz_precio_costo")
    codigos = form.getlist("cotiz_codigo_proveedor")

    conn.execute("DELETE FROM producto_proveedor WHERE producto_id=%s", (producto_id,))
    vistos = set()
    for proveedor_id, precio, codigo_prov in zip(proveedor_ids, precios, codigos):
        if not proveedor_id or not precio:
            continue
        if proveedor_id in vistos:
            continue  # no permitir el mismo proveedor dos veces en el mismo producto
        vistos.add(proveedor_id)
        conn.execute(
            """INSERT INTO producto_proveedor (producto_id, proveedor_id, precio_costo, codigo_proveedor)
               VALUES (%s, %s, %s, %s)""",
            (producto_id, proveedor_id, a_decimal(precio), (codigo_prov or "").strip() or None),
        )


# ---------------------------------------------------------------------------
# Productos / Stock
# ---------------------------------------------------------------------------
@app.route("/productos")
def productos_lista():
    conn = db.get_connection()
    q = request.args.get("q", "").strip()
    categoria = request.args.get("categoria", "").strip()
    subcategoria = request.args.get("subcategoria", "").strip()

    condiciones = []
    parametros = []
    if q:
        # el mismo buscador de texto libre de siempre, ahora también matchea
        # por modelo de auto compatible (ej. "Gol") además de nombre/código/
        # marca — no hace falta un campo de búsqueda aparte para eso.
        condiciones.append("(nombre ILIKE %s OR codigo ILIKE %s OR marca ILIKE %s OR modelo_compatible ILIKE %s OR codigo_barras = %s)")
        parametros += [f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%", q]
    if categoria:
        condiciones.append("categoria = %s")
        parametros.append(categoria)
    if subcategoria:
        condiciones.append("subcategoria = %s")
        parametros.append(subcategoria)

    consulta = "SELECT * FROM productos"
    if condiciones:
        consulta += " WHERE " + " AND ".join(condiciones)
    consulta += " ORDER BY categoria, nombre"
    productos = conn.execute(consulta, parametros).fetchall()

    categorias = db.obtener_categorias(conn)
    subcategorias_json = subcategorias_por_categoria_json(conn)
    # mismo criterio de "mejor precio" que ya usa /pedidos (db.obtener_mejor_precio_por_producto),
    # calculado solo, sin que haga falta elegir manualmente un proveedor.
    mejores_precios = {p["id"]: db.obtener_mejor_precio_por_producto(conn, p["id"]) for p in productos}
    conn.close()
    return render_template(
        "productos.html", productos=productos, q=q, categoria=categoria, subcategoria=subcategoria,
        categorias=categorias, subcategorias_json=subcategorias_json, mejores_precios=mejores_precios,
    )


@app.route("/productos/nuevo", methods=["GET", "POST"])
def productos_nuevo():
    conn = db.get_connection()
    if request.method == "POST":
        cur = conn.execute(
            """INSERT INTO productos
               (codigo, nombre, categoria, subcategoria, marca, modelo_compatible, precio_costo, precio_venta, stock_actual, stock_minimo, proveedor_id, codigo_barras)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (
                request.form.get("codigo") or None,
                request.form["nombre"],
                request.form["categoria"],
                request.form.get("subcategoria") or None,
                request.form.get("marca", ""),
                request.form.get("modelo_compatible", ""),
                a_decimal(request.form.get("precio_costo")),
                a_decimal(request.form.get("precio_venta")),
                int(request.form.get("stock_actual") or 0),
                int(request.form.get("stock_minimo") or 2),
                request.form.get("proveedor_id") or None,
                request.form.get("codigo_barras") or None,
            ),
        )
        producto_id = cur.fetchone()["id"]
        guardar_cotizaciones_proveedor(conn, producto_id, request.form)

        nombre_imagen = guardar_imagen_producto(producto_id, request.files.get("imagen"))
        if nombre_imagen:
            conn.execute("UPDATE productos SET imagen=%s WHERE id=%s", (nombre_imagen, producto_id))

        conn.commit()
        conn.close()
        flash("Producto creado correctamente.", "success")
        return redirect(url_for("productos_lista"))
    proveedores = conn.execute("SELECT * FROM proveedores WHERE activo IS TRUE ORDER BY nombre").fetchall()
    categorias = db.obtener_categorias(conn)
    subcategorias_json = subcategorias_por_categoria_json(conn)
    conn.close()
    return render_template(
        "producto_form.html", producto=None, proveedores=proveedores, cotizaciones=[],
        categorias=categorias, subcategorias_json=subcategorias_json,
    )


@app.route("/productos/<int:producto_id>/editar", methods=["GET", "POST"])
def productos_editar(producto_id):
    conn = db.get_connection()
    if request.method == "POST":
        conn.execute(
            """UPDATE productos SET codigo=%s, nombre=%s, categoria=%s, subcategoria=%s, marca=%s, modelo_compatible=%s,
               precio_costo=%s, precio_venta=%s, stock_actual=%s, stock_minimo=%s, proveedor_id=%s,
               codigo_barras=%s WHERE id=%s""",
            (
                request.form.get("codigo") or None,
                request.form["nombre"],
                request.form["categoria"],
                request.form.get("subcategoria") or None,
                request.form.get("marca", ""),
                request.form.get("modelo_compatible", ""),
                a_decimal(request.form.get("precio_costo")),
                a_decimal(request.form.get("precio_venta")),
                int(request.form.get("stock_actual") or 0),
                int(request.form.get("stock_minimo") or 2),
                request.form.get("proveedor_id") or None,
                request.form.get("codigo_barras") or None,
                producto_id,
            ),
        )
        guardar_cotizaciones_proveedor(conn, producto_id, request.form)

        producto_actual = conn.execute("SELECT imagen FROM productos WHERE id=%s", (producto_id,)).fetchone()
        if request.form.get("eliminar_imagen") == "1":
            eliminar_imagen_producto(producto_actual["imagen"])
            conn.execute("UPDATE productos SET imagen=NULL WHERE id=%s", (producto_id,))
        else:
            nombre_imagen = guardar_imagen_producto(producto_id, request.files.get("imagen"))
            if nombre_imagen:
                eliminar_imagen_producto(producto_actual["imagen"])
                conn.execute("UPDATE productos SET imagen=%s WHERE id=%s", (nombre_imagen, producto_id))

        conn.commit()
        conn.close()
        flash("Producto actualizado.", "success")
        return redirect(url_for("productos_lista"))
    producto = conn.execute("SELECT * FROM productos WHERE id=%s", (producto_id,)).fetchone()
    # incluye también el proveedor actual del producto aunque esté desactivado,
    # para no perderlo de la ficha si ya estaba asignado antes de desactivarlo.
    proveedores = conn.execute(
        "SELECT * FROM proveedores WHERE activo IS TRUE OR id=%s ORDER BY nombre", (producto["proveedor_id"],)
    ).fetchall()
    cotizaciones = conn.execute(
        """SELECT pp.*, p.nombre AS proveedor_nombre FROM producto_proveedor pp
           JOIN proveedores p ON p.id = pp.proveedor_id
           WHERE pp.producto_id = %s ORDER BY pp.precio_costo ASC""",
        (producto_id,),
    ).fetchall()
    cotizaciones = [dict(c) for c in cotizaciones]
    categorias = db.obtener_categorias(conn)
    # si la categoría actual del producto fue desactivada, la sumamos igual
    # para no perderla de la ficha (mismo criterio que con el proveedor).
    if producto["categoria"] and producto["categoria"] not in categorias:
        categorias = sorted(categorias + [producto["categoria"]])
    subcategorias_json = subcategorias_por_categoria_json(conn)
    # mismo criterio con la subcategoría actual, por si se desactivó.
    if producto["subcategoria"] and producto["categoria"]:
        del_producto = subcategorias_json.setdefault(producto["categoria"], [])
        if producto["subcategoria"] not in del_producto:
            del_producto.append(producto["subcategoria"])
    conn.close()
    return render_template(
        "producto_form.html", producto=producto, proveedores=proveedores, cotizaciones=cotizaciones,
        categorias=categorias, subcategorias_json=subcategorias_json,
    )


@app.route("/productos/<int:producto_id>/eliminar", methods=["POST"])
def productos_eliminar(producto_id):
    conn = db.get_connection()
    producto = conn.execute("SELECT imagen FROM productos WHERE id=%s", (producto_id,)).fetchone()
    if producto:
        eliminar_imagen_producto(producto["imagen"])
    conn.execute("DELETE FROM productos WHERE id=%s", (producto_id,))
    conn.commit()
    conn.close()
    flash("Producto eliminado.", "info")
    return redirect(url_for("productos_lista"))


# ---------------------------------------------------------------------------
# Proveedores
# ---------------------------------------------------------------------------
@app.route("/proveedores")
def proveedores_lista():
    conn = db.get_connection()
    mostrar_todos = request.args.get("todos") == "1"
    if mostrar_todos:
        proveedores = conn.execute("SELECT * FROM proveedores ORDER BY activo DESC, nombre").fetchall()
    else:
        proveedores = conn.execute("SELECT * FROM proveedores WHERE activo IS TRUE ORDER BY nombre").fetchall()
    conn.close()
    return render_template("proveedores.html", proveedores=proveedores, mostrar_todos=mostrar_todos)


@app.route("/proveedores/nuevo", methods=["GET", "POST"])
def proveedores_nuevo():
    if request.method == "POST":
        conn = db.get_connection()
        conn.execute(
            "INSERT INTO proveedores (nombre, telefono, email, direccion, cuit) VALUES (%s, %s, %s, %s, %s)",
            (
                request.form["nombre"],
                request.form.get("telefono", ""),
                request.form.get("email", ""),
                request.form.get("direccion", ""),
                request.form.get("cuit", ""),
            ),
        )
        conn.commit()
        conn.close()
        flash("Proveedor creado correctamente.", "success")
        return redirect(url_for("proveedores_lista"))
    return render_template("proveedor_form.html", proveedor=None)


@app.route("/proveedores/<int:proveedor_id>/editar", methods=["GET", "POST"])
def proveedores_editar(proveedor_id):
    conn = db.get_connection()
    if request.method == "POST":
        conn.execute(
            "UPDATE proveedores SET nombre=%s, telefono=%s, email=%s, direccion=%s, cuit=%s WHERE id=%s",
            (
                request.form["nombre"],
                request.form.get("telefono", ""),
                request.form.get("email", ""),
                request.form.get("direccion", ""),
                request.form.get("cuit", ""),
                proveedor_id,
            ),
        )
        conn.commit()
        conn.close()
        flash("Proveedor actualizado.", "success")
        return redirect(url_for("proveedores_lista"))
    proveedor = conn.execute("SELECT * FROM proveedores WHERE id=%s", (proveedor_id,)).fetchone()
    conn.close()
    return render_template("proveedor_form.html", proveedor=proveedor)


@app.route("/proveedores/<int:proveedor_id>/eliminar", methods=["POST"])
def proveedores_eliminar(proveedor_id):
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM proveedores WHERE id=%s", (proveedor_id,))
        conn.commit()
        flash("Proveedor eliminado.", "info")
    except psycopg.errors.ForeignKeyViolation:
        conn.rollback()
        flash("No se puede eliminar: este proveedor tiene productos, compras o cotizaciones cargadas. "
              "Desactivalo en su lugar (no se va a poder elegir para nada nuevo, pero no rompe lo ya cargado).", "danger")
    conn.close()
    return redirect(url_for("proveedores_lista"))


@app.route("/proveedores/<int:proveedor_id>/activar", methods=["POST"])
def proveedores_activar(proveedor_id):
    conn = db.get_connection()
    conn.execute("UPDATE proveedores SET activo=true WHERE id=%s", (proveedor_id,))
    conn.commit()
    conn.close()
    flash("Proveedor activado.", "success")
    return redirect(url_for("proveedores_lista", todos=request.args.get("todos", "")))


@app.route("/proveedores/<int:proveedor_id>/desactivar", methods=["POST"])
def proveedores_desactivar(proveedor_id):
    conn = db.get_connection()
    conn.execute("UPDATE proveedores SET activo=false WHERE id=%s", (proveedor_id,))
    conn.commit()
    conn.close()
    flash("Proveedor desactivado: no va a aparecer para elegir en compras nuevas, pero lo ya cargado sigue intacto.", "info")
    return redirect(url_for("proveedores_lista", todos=request.args.get("todos", "")))


# ---------------------------------------------------------------------------
# Categorías de producto
# ---------------------------------------------------------------------------
@app.route("/categorias")
def categorias_lista():
    conn = db.get_connection()
    mostrar_todas = request.args.get("todas") == "1"
    if mostrar_todas:
        categorias = conn.execute("SELECT * FROM categorias ORDER BY activo DESC, nombre").fetchall()
        subcategorias_todas = db.obtener_subcategorias(conn, solo_activas=False)
    else:
        categorias = conn.execute("SELECT * FROM categorias WHERE activo IS TRUE ORDER BY nombre").fetchall()
        subcategorias_todas = db.obtener_subcategorias(conn, solo_activas=True)
    conteo = {
        r["categoria"]: r["c"]
        for r in conn.execute("SELECT categoria, COUNT(*) AS c FROM productos GROUP BY categoria")
    }
    conteo_subcategoria = {
        r["subcategoria"]: r["c"]
        for r in conn.execute(
            "SELECT subcategoria, COUNT(*) AS c FROM productos WHERE subcategoria IS NOT NULL GROUP BY subcategoria"
        )
    }
    # agrupar subcategorías por categoria_id para pintarlas anidadas en la plantilla
    subcategorias_por_categoria = {}
    for s in subcategorias_todas:
        subcategorias_por_categoria.setdefault(s["categoria_id"], []).append(s)
    conn.close()
    return render_template(
        "categorias.html", categorias=categorias, conteo=conteo, mostrar_todas=mostrar_todas,
        subcategorias_por_categoria=subcategorias_por_categoria, conteo_subcategoria=conteo_subcategoria,
    )


@app.route("/categorias/nueva", methods=["POST"])
def categorias_nueva():
    nombre = request.form.get("nombre", "").strip()
    if not nombre:
        flash("El nombre de la categoría es obligatorio.", "danger")
        return redirect(url_for("categorias_lista"))
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO categorias (nombre) VALUES (%s)", (nombre,))
        conn.commit()
        flash(f"Categoría '{nombre}' creada.", "success")
    except psycopg.errors.UniqueViolation:
        conn.rollback()
        flash(f"Ya existe una categoría '{nombre}'.", "danger")
    conn.close()
    return redirect(url_for("categorias_lista"))


@app.route("/categorias/<int:categoria_id>/eliminar", methods=["POST"])
def categorias_eliminar(categoria_id):
    conn = db.get_connection()
    fila = conn.execute("SELECT nombre FROM categorias WHERE id=%s", (categoria_id,)).fetchone()
    en_uso = fila and conn.execute(
        "SELECT COUNT(*) AS c FROM productos WHERE categoria=%s", (fila["nombre"],)
    ).fetchone()["c"]
    if en_uso:
        flash("No se puede eliminar: hay productos cargados con esta categoría. "
              "Desactivala en su lugar (no se va a poder elegir para productos nuevos).", "danger")
    else:
        conn.execute("DELETE FROM categorias WHERE id=%s", (categoria_id,))
        conn.commit()
        flash("Categoría eliminada.", "info")
    conn.close()
    return redirect(url_for("categorias_lista"))


@app.route("/categorias/<int:categoria_id>/activar", methods=["POST"])
def categorias_activar(categoria_id):
    conn = db.get_connection()
    conn.execute("UPDATE categorias SET activo=TRUE WHERE id=%s", (categoria_id,))
    conn.commit()
    conn.close()
    flash("Categoría activada.", "success")
    return redirect(url_for("categorias_lista", todas=request.args.get("todas", "")))


@app.route("/categorias/<int:categoria_id>/desactivar", methods=["POST"])
def categorias_desactivar(categoria_id):
    conn = db.get_connection()
    conn.execute("UPDATE categorias SET activo=FALSE WHERE id=%s", (categoria_id,))
    conn.commit()
    conn.close()
    flash("Categoría desactivada: no va a aparecer para elegir en productos nuevos, pero lo ya cargado sigue intacto.", "info")
    return redirect(url_for("categorias_lista", todas=request.args.get("todas", "")))


@app.route("/categorias/<int:categoria_id>/subcategorias/nueva", methods=["POST"])
def subcategorias_nueva(categoria_id):
    nombre = request.form.get("nombre", "").strip()
    if not nombre:
        flash("El nombre de la subcategoría es obligatorio.", "danger")
        return redirect(url_for("categorias_lista"))
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO subcategorias (nombre, categoria_id) VALUES (%s, %s)", (nombre, categoria_id)
        )
        conn.commit()
        flash(f"Subcategoría '{nombre}' creada.", "success")
    except psycopg.errors.UniqueViolation:
        conn.rollback()
        flash(f"Esa categoría ya tiene una subcategoría '{nombre}'.", "danger")
    conn.close()
    return redirect(url_for("categorias_lista"))


@app.route("/subcategorias/<int:subcategoria_id>/eliminar", methods=["POST"])
def subcategorias_eliminar(subcategoria_id):
    conn = db.get_connection()
    fila = conn.execute("SELECT nombre FROM subcategorias WHERE id=%s", (subcategoria_id,)).fetchone()
    en_uso = fila and conn.execute(
        "SELECT COUNT(*) AS c FROM productos WHERE subcategoria=%s", (fila["nombre"],)
    ).fetchone()["c"]
    if en_uso:
        flash("No se puede eliminar: hay productos cargados con esta subcategoría. "
              "Desactivala en su lugar.", "danger")
    else:
        conn.execute("DELETE FROM subcategorias WHERE id=%s", (subcategoria_id,))
        conn.commit()
        flash("Subcategoría eliminada.", "info")
    conn.close()
    return redirect(url_for("categorias_lista"))


@app.route("/subcategorias/<int:subcategoria_id>/activar", methods=["POST"])
def subcategorias_activar(subcategoria_id):
    conn = db.get_connection()
    conn.execute("UPDATE subcategorias SET activo=TRUE WHERE id=%s", (subcategoria_id,))
    conn.commit()
    conn.close()
    flash("Subcategoría activada.", "success")
    return redirect(url_for("categorias_lista", todas=request.args.get("todas", "")))


@app.route("/subcategorias/<int:subcategoria_id>/desactivar", methods=["POST"])
def subcategorias_desactivar(subcategoria_id):
    conn = db.get_connection()
    conn.execute("UPDATE subcategorias SET activo=FALSE WHERE id=%s", (subcategoria_id,))
    conn.commit()
    conn.close()
    flash("Subcategoría desactivada: no va a aparecer para elegir en productos nuevos.", "info")
    return redirect(url_for("categorias_lista", todas=request.args.get("todas", "")))


@app.route("/vehiculos")
def vehiculos_lista():
    conn = db.get_connection()
    vehiculos = db.obtener_vehiculos(conn, solo_activos=False)
    usos = {
        fila["vehiculo_id"]: fila["n"]
        for fila in conn.execute(
            "SELECT vehiculo_id, count(*) AS n FROM producto_vehiculos GROUP BY vehiculo_id"
        ).fetchall()
    }
    conn.close()
    return render_template("vehiculos.html", vehiculos=vehiculos, usos=usos)


@app.route("/vehiculos/nuevo", methods=["POST"])
def vehiculos_nuevo():
    marca_auto = request.form.get("marca_auto", "").strip()
    modelo = request.form.get("modelo", "").strip()
    motor = request.form.get("motor", "").strip()
    if not (marca_auto and modelo and motor):
        flash("Marca, modelo y motor son obligatorios.", "warning")
        return redirect(url_for("vehiculos_lista"))
    conn = db.get_connection()
    try:
        conn.execute(
            """INSERT INTO vehiculos (marca_auto, modelo, motor, anio_desde, anio_hasta)
               VALUES (%s, %s, %s, %s, %s)""",
            (marca_auto, modelo, motor,
             a_entero(request.form.get("anio_desde")),
             a_entero(request.form.get("anio_hasta"))),
        )
        conn.commit()
        flash(f"Se agregó {marca_auto} {modelo} {motor}.", "success")
    except psycopg.errors.UniqueViolation:
        conn.rollback()
        flash(f"{marca_auto} {modelo} {motor} ya estaba cargado.", "warning")
    conn.close()
    return redirect(url_for("vehiculos_lista"))


@app.route("/vehiculos/<int:vehiculo_id>/activar", methods=["POST"])
def vehiculos_activar(vehiculo_id):
    conn = db.get_connection()
    conn.execute("UPDATE vehiculos SET activo = NOT activo WHERE id = %s", (vehiculo_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("vehiculos_lista"))


@app.route("/vehiculos/<int:vehiculo_id>/eliminar", methods=["POST"])
def vehiculos_eliminar(vehiculo_id):
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM vehiculos WHERE id = %s", (vehiculo_id,))
        conn.commit()
        flash("Auto eliminado.", "success")
    except psycopg.errors.ForeignKeyViolation:
        # Mismo criterio que un proveedor con compras cargadas: se avisa con
        # un mensaje claro y se ofrece desactivarlo, en vez de dejar escapar
        # el error de la base.
        conn.rollback()
        flash("No se puede eliminar: hay productos vinculados a este auto. "
              "Desactivalo si no querés que aparezca más.", "warning")
    conn.close()
    return redirect(url_for("vehiculos_lista"))


# ---------------------------------------------------------------------------
# Ventas
# ---------------------------------------------------------------------------
@app.route("/ventas")
def ventas_lista():
    conn = db.get_connection()
    ventas = conn.execute(
        """SELECT v.*, c.nombre AS cliente_nombre
           FROM ventas v LEFT JOIN clientes c ON c.id = v.cliente_id
           ORDER BY v.fecha DESC, v.id DESC"""
    ).fetchall()
    conn.close()
    return render_template("ventas.html", ventas=ventas)


@app.route("/ventas/dia")
def ventas_dia():
    """Resumen de ventas de un día agrupado por medio de pago (efectivo,
    transferencia, tarjeta, Mercado Pago), para el arqueo del local.
    Filtrable por día puntual (`fecha`) y por medio de pago (`medio_pago`),
    sin tocar el modelo de datos de ventas ni el flujo de carga — es
    puramente una pantalla de lectura sobre lo que ya se registró."""
    conn = db.get_connection()
    fecha = request.args.get("fecha", "").strip() or db.hoy()
    medio_pago = request.args.get("medio_pago", "").strip()

    condiciones = ["fecha = %s"]
    parametros = [fecha]
    if medio_pago:
        condiciones.append("metodo_pago = %s")
        parametros.append(medio_pago)
    where = " AND ".join(condiciones)

    resumen = conn.execute(
        f"""SELECT metodo_pago, COUNT(*) AS cantidad, COALESCE(SUM(total),0) AS total
            FROM ventas WHERE {where} GROUP BY metodo_pago ORDER BY total DESC""",
        parametros,
    ).fetchall()
    total_dia = sum(r["total"] for r in resumen)

    # Cantidad de operaciones reales del día: si dos ventas comparten
    # id_operacion (un mismo pago dividido en efectivo + tarjeta, por
    # ejemplo) cuentan como una sola, no dos.
    cant_operaciones = conn.execute(
        f"SELECT COUNT(DISTINCT COALESCE(id_operacion, 'v' || id::text)) AS c FROM ventas WHERE {where}",
        parametros,
    ).fetchone()["c"]

    ventas = conn.execute(
        f"""SELECT v.*, c.nombre AS cliente_nombre
            FROM ventas v LEFT JOIN clientes c ON c.id = v.cliente_id
            WHERE {where} ORDER BY v.id DESC""",
        parametros,
    ).fetchall()

    medios_pago_disponibles = [
        r["metodo_pago"] for r in conn.execute(
            "SELECT DISTINCT metodo_pago FROM ventas WHERE metodo_pago IS NOT NULL AND metodo_pago != '' ORDER BY metodo_pago"
        )
    ]
    conn.close()
    return render_template(
        "ventas_dia.html", fecha=fecha, medio_pago=medio_pago, medios_pago_disponibles=medios_pago_disponibles,
        resumen=resumen, total_dia=total_dia, cant_operaciones=cant_operaciones, ventas=ventas,
    )


def _promociones_vigentes_cliente(conn, cliente_id):
    hoy = db.hoy()
    return conn.execute(
        """SELECT * FROM promociones_aplicadas
           WHERE cliente_id=%s AND fecha_inicio<=%s AND (fecha_fin IS NULL OR fecha_fin>=%s)""",
        (cliente_id, hoy, hoy),
    ).fetchall()


def aplicar_promociones(conn, cliente_id, items):
    """Ajusta precios/subtotales de `items` según las promociones vigentes
    del cliente (ver /clientes/top -> "Aplicar promoción"). Descuentos
    porcentuales se aplican por ítem alcanzado; descuentos de monto fijo
    (solo con alcance 'todo') se prorratean sobre el total de la venta.
    `items` es una lista de tuplas (producto_id, cantidad, precio_unitario,
    subtotal); devuelve una lista nueva con la misma forma."""
    if not cliente_id:
        return items
    promos = _promociones_vigentes_cliente(conn, cliente_id)
    if not promos:
        return items

    productos_con_promo_puntual = {}
    for promo in promos:
        if promo["alcance"] == "productos_puntuales":
            for f in conn.execute(
                "SELECT producto_id FROM promocion_productos WHERE promocion_id=%s", (promo["id"],)
            ):
                productos_con_promo_puntual.setdefault(f["producto_id"], []).append(promo)

    nuevos = []
    for producto_id, cant, precio_unitario, subtotal in items:
        aplicables = [p for p in promos if p["alcance"] == "todo"] + productos_con_promo_puntual.get(producto_id, [])
        porcentaje = max(
            [p["porcentaje_o_monto"] for p in aplicables if p["tipo"] == "porcentaje"], default=Decimal("0")
        )
        precio_final = round(precio_unitario * (1 - porcentaje / 100), 2) if porcentaje else precio_unitario
        nuevos.append((producto_id, cant, precio_final, round(cant * precio_final, 2)))

    monto_fijo = max(
        [p["porcentaje_o_monto"] for p in promos if p["tipo"] == "monto_fijo" and p["alcance"] == "todo"],
        default=Decimal("0"),
    )
    total_previo = sum(it[3] for it in nuevos)
    if monto_fijo and total_previo > 0:
        factor = max(Decimal("0"), total_previo - monto_fijo) / total_previo
        nuevos = [
            (pid, cant, round(pu * factor, 2), round(cant * pu * factor, 2))
            for pid, cant, pu, _ in nuevos
        ]

    return nuevos


def registrar_venta(conn, cliente_id, metodo_pago, items, tipo_comprobante_solicitado="Remito", id_operacion=None):
    """Inserta una venta + sus items y descuenta stock. Usado tanto por la
    venta manual del local (Nueva venta) como por la tienda online una vez
    que Mercado Pago confirma el pago — es la misma tabla, el mismo stock,
    una sola fuente de verdad.

    `items` es una lista de tuplas (producto_id, cantidad, precio_unitario,
    subtotal) ya resueltas por quien llama. Si el cliente tiene una
    promoción vigente (ver /clientes/top), el precio unitario se ajusta acá
    antes de calcular el total.

    Regla del negocio: efectivo -> remito/recibo interno (el que se haya
    pedido); tarjeta, transferencia o Mercado Pago -> Factura A o B
    electrónica automática por ARCA (A si el cliente es Responsable
    Inscripto con CUIT cargado, B en cualquier otro caso — nunca C, el
    negocio es Responsable Inscripto).

    `id_operacion` es opcional: dos ventas registradas con el mismo valor se
    cuentan como una sola operación en /ventas/dia (pago mixto).

    Devuelve (venta_id, tipo_comprobante_final).
    """
    items = aplicar_promociones(conn, cliente_id, items)

    total = sum(it[3] for it in items)
    if metodo_pago in ("Tarjeta", "Transferencia", "Mercado Pago"):
        cliente = conn.execute("SELECT cuit_dni, condicion_iva FROM clientes WHERE id=%s", (cliente_id,)).fetchone() if cliente_id else None
        receptor = facturacion_afip.datos_receptor(
            cliente["cuit_dni"] if cliente else None, cliente["condicion_iva"] if cliente else None
        )
        tipo_comprobante = receptor["tipo_comprobante"]
    else:
        tipo_comprobante = tipo_comprobante_solicitado

    ultimo = conn.execute("SELECT COUNT(*) AS c FROM ventas").fetchone()["c"]
    numero_comprobante = f"{1000 + ultimo + 1:06d}"

    cur = conn.cursor()
    cur.execute(
        """INSERT INTO ventas (fecha, cliente_id, total, metodo_pago, tipo_comprobante, numero_comprobante, id_operacion)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (db.hoy(), cliente_id, total, metodo_pago, tipo_comprobante, numero_comprobante, id_operacion),
    )
    venta_id = cur.fetchone()["id"]
    for producto_id, cant, precio_unitario, subtotal in items:
        cur.execute(
            "INSERT INTO venta_items (venta_id, producto_id, cantidad, precio_unitario, subtotal) VALUES (%s, %s, %s, %s, %s)",
            (venta_id, producto_id, cant, precio_unitario, subtotal),
        )
        cur.execute("UPDATE productos SET stock_actual = stock_actual - %s WHERE id = %s", (cant, producto_id))
    conn.commit()
    return venta_id, tipo_comprobante


@app.route("/ventas/nueva", methods=["GET", "POST"])
def ventas_nueva():
    conn = db.get_connection()
    if request.method == "POST":
        cliente_id = request.form.get("cliente_id") or None
        metodo_pago = request.form.get("metodo_pago", "Efectivo")
        tipo_comprobante_solicitado = request.form.get("tipo_comprobante", "Remito")
        id_operacion = request.form.get("id_operacion", "").strip() or None

        producto_ids = request.form.getlist("producto_id")
        cantidades = request.form.getlist("cantidad")

        items = []
        for pid, cant in zip(producto_ids, cantidades):
            if not pid or not cant:
                continue
            cant = int(cant)
            if cant <= 0:
                continue
            producto = conn.execute("SELECT * FROM productos WHERE id=%s", (pid,)).fetchone()
            if not producto:
                continue
            subtotal = cant * producto["precio_venta"]
            items.append((producto["id"], cant, producto["precio_venta"], subtotal))

        if not items:
            flash("Agregá al menos un producto a la venta.", "danger")
            conn.close()
            return redirect(url_for("ventas_nueva"))

        venta_id, tipo_comprobante = registrar_venta(
            conn, cliente_id, metodo_pago, items, tipo_comprobante_solicitado, id_operacion=id_operacion
        )
        conn.close()

        if tipo_comprobante in ("Factura A", "Factura B"):
            # Nunca bloquea ni revierte la venta si falla: el remito/factura
            # se puede reintentar después desde el comprobante.
            facturacion_afip.emitir_factura(venta_id)

        flash("Venta registrada correctamente.", "success")
        return redirect(url_for("ventas_comprobante", venta_id=venta_id))

    clientes = conn.execute("SELECT * FROM clientes ORDER BY nombre").fetchall()
    productos = conn.execute("SELECT * FROM productos ORDER BY nombre").fetchall()
    conn.close()
    return render_template(
        "venta_form.html", clientes=clientes, productos=productos,
        productos_json=productos_para_buscador(productos),
    )


@app.route("/api/clientes-nuevo", methods=["POST"])
def api_clientes_nuevo():
    """Alta rápida de cliente desde la pantalla de Nueva venta (vía modal),
    para no perder la venta que se está cargando."""
    nombre = request.form.get("nombre", "").strip()
    if not nombre:
        return jsonify({"ok": False, "error": "El nombre es obligatorio."}), 400

    conn = db.get_connection()
    cur = conn.execute(
        "INSERT INTO clientes (nombre, telefono, email, direccion, cuit_dni, fecha_alta) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (
            nombre,
            request.form.get("telefono", "").strip(),
            request.form.get("email", "").strip(),
            request.form.get("direccion", "").strip(),
            request.form.get("cuit_dni", "").strip(),
            db.hoy(),
        ),
    )
    cliente_id = cur.fetchone()["id"]
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": cliente_id, "nombre": nombre})


@app.route("/api/productos-nuevo", methods=["POST"])
def api_productos_nuevo():
    """Alta rápida de producto desde Nueva compra o la revisión de una
    factura importada (vía modal), para no tener que salir a /productos/nuevo
    y perder la compra que se está cargando. Arranca con stock 0: la propia
    compra que se está registrando le suma la cantidad comprada al guardar."""
    nombre = request.form.get("nombre", "").strip()
    if not nombre:
        return jsonify({"ok": False, "error": "El nombre es obligatorio."}), 400

    codigo = request.form.get("codigo", "").strip() or None
    categoria = request.form.get("categoria", "").strip() or "Otros"
    if categoria not in db.obtener_categorias():
        categoria = "Otros"
    subcategoria = request.form.get("subcategoria", "").strip() or None
    marca = request.form.get("marca", "").strip() or None
    precio_costo = a_decimal(request.form.get("precio_costo"))
    precio_venta = a_decimal(request.form.get("precio_venta"))
    stock_minimo = int(request.form.get("stock_minimo") or 2)
    proveedor_id = request.form.get("proveedor_id") or None

    conn = db.get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO productos
               (codigo, nombre, categoria, subcategoria, marca, precio_costo, precio_venta,
                stock_actual, stock_minimo, proveedor_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s, %s) RETURNING id""",
            (codigo, nombre, categoria, subcategoria, marca, precio_costo, precio_venta, stock_minimo, proveedor_id),
        )
    except psycopg.errors.UniqueViolation:
        conn.rollback()
        conn.close()
        return jsonify({"ok": False, "error": f"Ya existe un producto con el código '{codigo}'."}), 400
    producto_id = cur.fetchone()["id"]
    conn.commit()
    conn.close()
    return jsonify({
        "ok": True, "id": producto_id, "nombre": nombre, "codigo": codigo or "",
        "marca": marca or "", "precio_costo": precio_costo, "precio_venta": precio_venta,
        "stock_actual": 0,
    })


@app.route("/api/producto-por-codigo")
def api_producto_por_codigo():
    """Busca un producto por código de barras o código interno.

    Lo usan dos cosas: la pantalla de ventas, que suma el producto a la venta
    al escanearlo, y el popup de consulta de precio (templates/_escaneo_precio.html),
    que se dispara al escanear en cualquier otra pantalla. De ahí que devuelva
    marca, modelo y stock mínimo: son los datos que muestra ese popup.
    """
    codigo = request.args.get("codigo", "").strip()
    if not codigo:
        return jsonify({"encontrado": False})
    conn = db.get_connection()
    producto = conn.execute(
        "SELECT * FROM productos WHERE codigo_barras = %s OR codigo = %s", (codigo, codigo)
    ).fetchone()
    conn.close()
    if not producto:
        return jsonify({"encontrado": False})
    return jsonify({
        "encontrado": True,
        "id": producto["id"],
        "nombre": producto["nombre"],
        "codigo": producto["codigo"],
        "precio_venta": producto["precio_venta"],
        "stock_actual": producto["stock_actual"],
        "stock_minimo": producto["stock_minimo"],
        "marca": producto["marca"],
        "modelo_compatible": producto["modelo_compatible"],
    })


def _obtener_venta_y_items(conn, venta_id):
    venta = conn.execute(
        """SELECT v.*, c.nombre AS cliente_nombre, c.telefono AS cliente_telefono,
                  c.direccion AS cliente_direccion, c.cuit_dni AS cliente_cuit,
                  c.condicion_iva AS cliente_condicion_iva, c.email AS cliente_email
           FROM ventas v LEFT JOIN clientes c ON c.id = v.cliente_id WHERE v.id=%s""",
        (venta_id,),
    ).fetchone()
    items = conn.execute(
        """SELECT vi.*, p.nombre AS producto_nombre, p.codigo AS producto_codigo
           FROM venta_items vi JOIN productos p ON p.id = vi.producto_id WHERE vi.venta_id=%s""",
        (venta_id,),
    ).fetchall()
    return venta, items


def _es_factura(tipo_comprobante):
    return tipo_comprobante in ("Factura A", "Factura B")


@app.route("/ventas/<int:venta_id>/comprobante")
def ventas_comprobante(venta_id):
    conn = db.get_connection()
    venta, items = _obtener_venta_y_items(conn, venta_id)
    conn.close()
    qr_url = facturacion_afip.url_qr_venta(venta) if venta and _es_factura(venta["tipo_comprobante"]) else None
    return render_template("comprobante.html", venta=venta, items=items, qr_url=qr_url)


@app.route("/ventas/<int:venta_id>/enviar-mail", methods=["POST"])
def ventas_enviar_mail(venta_id):
    conn = db.get_connection()
    venta, items = _obtener_venta_y_items(conn, venta_id)
    conn.close()
    if not venta:
        flash("No encontré esa venta.", "danger")
        return redirect(url_for("ventas_lista"))

    qr_url = facturacion_afip.url_qr_venta(venta) if _es_factura(venta["tipo_comprobante"]) else None
    ok, error = envio_mail.enviar_comprobante_por_mail(
        venta, items, venta["cliente_email"], qr_url=qr_url, negocio=NEGOCIO
    )
    if ok:
        flash(f"Comprobante enviado por mail a {venta['cliente_email']}.", "success")
    else:
        flash(f"No se pudo enviar el mail: {error}", "danger")
    return redirect(url_for("ventas_comprobante", venta_id=venta_id))


@app.route("/ventas/<int:venta_id>/facturar", methods=["POST"])
def ventas_facturar(venta_id):
    """Reintento manual de la Factura A/B (por ejemplo si ARCA no respondió antes)."""
    conn = db.get_connection()
    venta = conn.execute("SELECT * FROM ventas WHERE id=%s", (venta_id,)).fetchone()
    conn.close()
    if not venta:
        flash("No encontré esa venta.", "danger")
        return redirect(url_for("ventas_lista"))

    facturacion_afip.emitir_factura(venta_id)

    conn = db.get_connection()
    estado = conn.execute("SELECT facturacion_estado, facturacion_error FROM ventas WHERE id=%s", (venta_id,)).fetchone()
    conn.close()
    if estado["facturacion_estado"] == "emitida":
        flash("Factura emitida correctamente.", "success")
    elif estado["facturacion_estado"] == "sin_configurar":
        flash("Todavía no está configurado el acceso a Afip SDK (AFIPSDK_ACCESS_TOKEN). Ver README.md.", "warning")
    else:
        flash("No se pudo emitir la factura: %s" % (estado["facturacion_error"] or "error desconocido"), "danger")
    return redirect(url_for("ventas_comprobante", venta_id=venta_id))


# ---------------------------------------------------------------------------
# Compras a proveedores
# ---------------------------------------------------------------------------
@app.route("/compras")
def compras_lista():
    conn = db.get_connection()
    compras = conn.execute(
        """SELECT co.*, p.nombre AS proveedor_nombre
           FROM compras co LEFT JOIN proveedores p ON p.id = co.proveedor_id
           ORDER BY co.fecha DESC, co.id DESC"""
    ).fetchall()
    conn.close()
    return render_template("compras.html", compras=compras)


@app.route("/compras/nueva", methods=["GET", "POST"])
def compras_nueva():
    conn = db.get_connection()
    if request.method == "POST":
        proveedor_id = request.form.get("proveedor_id") or None
        numero_factura = request.form.get("numero_factura_proveedor", "")

        # si no se eligió un proveedor de la lista pero se completó el
        # nombre de uno nuevo (viene de "Nueva compra" o de la revisión de
        # una factura importada), se crea acá antes de registrar la compra.
        nombre_nuevo = request.form.get("proveedor_nuevo_nombre", "").strip()
        if not proveedor_id and nombre_nuevo:
            cur = conn.execute(
                "INSERT INTO proveedores (nombre, telefono, email, direccion, cuit) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (
                    nombre_nuevo,
                    request.form.get("proveedor_nuevo_telefono", "").strip() or None,
                    request.form.get("proveedor_nuevo_email", "").strip() or None,
                    request.form.get("proveedor_nuevo_direccion", "").strip() or None,
                    request.form.get("proveedor_nuevo_cuit", "").strip() or None,
                ),
            )
            proveedor_id = cur.fetchone()["id"]
            flash(f"Se creó el proveedor '{nombre_nuevo}'.", "success")

        producto_ids = request.form.getlist("producto_id")
        cantidades = request.form.getlist("cantidad")
        precios = request.form.getlist("precio_unitario")

        items = []
        total = Decimal("0")
        for pid, cant, precio in zip(producto_ids, cantidades, precios):
            if not pid or not cant:
                continue
            cant = int(cant)
            precio = a_decimal(precio)
            if cant <= 0:
                continue
            subtotal = cant * precio
            total += subtotal
            items.append((pid, cant, precio, subtotal))

        if not items:
            flash("Agregá al menos un producto a la compra.", "danger")
            conn.close()
            return redirect(url_for("compras_nueva"))

        cur = conn.cursor()
        cur.execute(
            "INSERT INTO compras (fecha, proveedor_id, total, numero_factura_proveedor) VALUES (%s, %s, %s, %s) RETURNING id",
            (db.hoy(), proveedor_id, total, numero_factura),
        )
        compra_id = cur.fetchone()["id"]
        for producto_id, cant, precio_unitario, subtotal in items:
            cur.execute(
                "INSERT INTO compra_items (compra_id, producto_id, cantidad, precio_unitario, subtotal) VALUES (%s, %s, %s, %s, %s)",
                (compra_id, producto_id, cant, precio_unitario, subtotal),
            )
            # la compra repone stock, actualiza el costo del producto y
            # limpia la marca de "pedido pendiente" si tenía (ya llegó)
            cur.execute(
                """UPDATE productos SET stock_actual = stock_actual + %s, precio_costo = %s,
                   pedido_pendiente = false, fecha_pedido_pendiente = NULL WHERE id = %s""",
                (cant, precio_unitario, producto_id),
            )
        conn.commit()
        conn.close()
        flash("Compra registrada y stock actualizado.", "success")
        return redirect(url_for("compras_lista"))

    proveedores = conn.execute("SELECT * FROM proveedores WHERE activo IS TRUE ORDER BY nombre").fetchall()
    productos = conn.execute("SELECT * FROM productos ORDER BY nombre").fetchall()
    categorias = db.obtener_categorias(conn)
    subcategorias_json = subcategorias_por_categoria_json(conn)
    conn.close()
    return render_template(
        "compra_form.html", proveedores=proveedores, productos=productos,
        productos_json=productos_para_buscador(productos), categorias=categorias,
        subcategorias_json=subcategorias_json,
    )


EXTENSIONES_FACTURA_VALIDAS = (".pdf", ".xlsx", ".xls", ".csv")


@app.route("/compras/importar-factura", methods=["GET", "POST"])
def compras_importar_factura():
    """Sube una factura de compra (PDF/Excel/CSV) del proveedor, la lee con
    importar_factura.py y muestra una pantalla de revisión pre-cargada (el
    mismo formulario de Nueva compra, pero con productos/cantidades/precios
    ya completados según lo que se pudo reconocer). No toca el stock acá:
    eso solo pasa cuando se confirma en la pantalla de revisión, que
    reutiliza /compras/nueva."""
    conn = db.get_connection()
    if request.method == "POST":
        archivo = request.files.get("factura")
        if not archivo or archivo.filename == "":
            flash("Elegí un archivo de factura (PDF, Excel o CSV).", "danger")
            conn.close()
            return redirect(url_for("compras_importar_factura"))

        nombre_archivo = archivo.filename
        ext = os.path.splitext(nombre_archivo)[1].lower()
        if ext not in EXTENSIONES_FACTURA_VALIDAS:
            flash("Formato no soportado. Subí un PDF, Excel (.xlsx/.xls) o CSV.", "danger")
            conn.close()
            return redirect(url_for("compras_importar_factura"))

        ruta_temporal = os.path.join(tempfile.gettempdir(), f"factura_{secrets.token_hex(8)}{ext}")
        archivo.save(ruta_temporal)
        try:
            resultado = importar_factura.procesar_factura(ruta_temporal, nombre_archivo, conn)
        finally:
            try:
                os.remove(ruta_temporal)
            except OSError:
                pass

        if resultado.get("error"):
            flash(resultado["error"], "danger")
            conn.close()
            return redirect(url_for("compras_importar_factura"))

        if not resultado["filas"]:
            for aviso in resultado["avisos"]:
                flash(aviso, "warning")
            flash("No reconocí productos en el archivo. Podés cargar la compra a mano.", "warning")
            conn.close()
            return redirect(url_for("compras_nueva"))

        productos = conn.execute("SELECT * FROM productos ORDER BY nombre").fetchall()
        proveedores = conn.execute("SELECT * FROM proveedores WHERE activo IS TRUE ORDER BY nombre").fetchall()
        categorias = db.obtener_categorias(conn)
        subcategorias_json = subcategorias_por_categoria_json(conn)
        conn.close()
        return render_template(
            "compra_revisar_factura.html",
            resultado=resultado, proveedores=proveedores,
            productos_json=productos_para_buscador(productos),
            nombre_archivo=nombre_archivo, categorias=categorias,
            subcategorias_json=subcategorias_json,
        )

    proveedores = conn.execute("SELECT * FROM proveedores WHERE activo IS TRUE ORDER BY nombre").fetchall()
    conn.close()
    return render_template("compra_importar_factura.html", proveedores=proveedores)


# ---------------------------------------------------------------------------
# Lista de pedidos a proveedores (sugerencia de reposición)
# ---------------------------------------------------------------------------
@app.route("/pedidos")
def pedidos_lista():
    """Arma la lista de lo que hay que reponer, agrupada por el proveedor más
    conveniente para cada producto (el de menor precio_costo cargado)."""
    conn = db.get_connection()
    # stock_minimo=0 significa "no controlar reposición de este producto"
    # (ej: productos de prueba/catálogo aún no confirmados) — así la lista no
    # se llena con cosas que todavía no se decidió si se van a reponer.
    # pedido_pendiente=1 significa "ya se le pidió a este proveedor, está en
    # camino" — se saca de la lista de faltantes hasta que llegue (se limpia
    # solo cuando se registra la compra) o se desmarque a mano.
    faltantes = conn.execute(
        """SELECT * FROM productos
           WHERE stock_actual <= stock_minimo AND stock_minimo > 0 AND pedido_pendiente IS FALSE
           ORDER BY nombre"""
    ).fetchall()

    grupos = {}
    ahorro_total = 0
    for f in faltantes:
        cotizaciones = db.obtener_cotizaciones_producto(conn, f["id"])

        hay_alternativas = len(cotizaciones) > 1
        if cotizaciones:
            mejor = cotizaciones[0]
            proveedor_nombre = mejor["proveedor_nombre"]
            proveedor_email = mejor["proveedor_email"]
            proveedor_telefono = mejor["proveedor_telefono"]
            precio_costo = mejor["precio_costo"]
            codigo_proveedor = mejor["codigo_proveedor"]
            ahorro_unitario = (cotizaciones[-1]["precio_costo"] - mejor["precio_costo"]) if hay_alternativas else 0
        else:
            # sin cotizaciones activas cargadas: usar el proveedor habitual de
            # la ficha del producto, pero solo si sigue activo.
            proveedor = (
                conn.execute(
                    "SELECT nombre, email, telefono FROM proveedores WHERE id=%s AND activo IS TRUE", (f["proveedor_id"],)
                ).fetchone()
                if f["proveedor_id"] else None
            )
            if not proveedor:
                # ni cotizaciones de un proveedor activo ni proveedor de ficha
                # activo: no hay a quién pedirle, no tiene sentido mostrarlo.
                continue
            proveedor_nombre = proveedor["nombre"]
            proveedor_email = proveedor["email"]
            proveedor_telefono = proveedor["telefono"]
            precio_costo = f["precio_costo"]
            codigo_proveedor = None
            ahorro_unitario = 0

        clave = proveedor_nombre
        if clave not in grupos:
            grupos[clave] = {"email": proveedor_email, "telefono": proveedor_telefono, "items": [], "total_estimado": 0}

        # repone hasta el doble del mínimo, con al menos 1 unidad
        sugerido = max((f["stock_minimo"] * 2) - f["stock_actual"], 1)
        costo_estimado = sugerido * precio_costo
        ahorro_total += ahorro_unitario * sugerido
        grupos[clave]["items"].append({
            "producto_id": f["id"],
            "codigo": f["codigo"],
            "codigo_proveedor": codigo_proveedor,
            "nombre": f["nombre"],
            "stock_actual": f["stock_actual"],
            "stock_minimo": f["stock_minimo"],
            "sugerido": sugerido,
            "precio_costo": precio_costo,
            "costo_estimado": costo_estimado,
            "hay_alternativas": hay_alternativas,
        })
        grupos[clave]["total_estimado"] += costo_estimado

    pendientes = conn.execute(
        """SELECT * FROM productos WHERE pedido_pendiente IS TRUE ORDER BY fecha_pedido_pendiente DESC, nombre"""
    ).fetchall()

    conn.close()
    total_general = sum(g["total_estimado"] for g in grupos.values())
    return render_template(
        "pedidos.html", grupos=grupos, total_general=total_general, ahorro_total=ahorro_total,
        pendientes=pendientes,
    )


@app.route("/pedidos/marcar", methods=["POST"])
def pedidos_marcar():
    """Marca como 'ya pedido' todos los productos de un proveedor (los que
    se están mostrando en ese momento en /pedidos), para que dejen de
    aparecer en la lista de faltantes hasta que llegue la mercadería."""
    producto_ids = request.form.getlist("producto_id")
    if not producto_ids:
        flash("No había productos para marcar.", "warning")
        return redirect(url_for("pedidos_lista"))
    conn = db.get_connection()
    hoy = db.hoy()
    cur = conn.cursor()
    cur.executemany(
        "UPDATE productos SET pedido_pendiente=true, fecha_pedido_pendiente=%s WHERE id=%s",
        [(hoy, pid) for pid in producto_ids],
    )
    conn.commit()
    conn.close()
    flash(f"Marcado como pedido ({len(producto_ids)} producto/s). Va a volver a la lista si desmarcás o si la compra tarda y querés revisar de nuevo.", "success")
    return redirect(url_for("pedidos_lista"))


@app.route("/pedidos/desmarcar/<int:producto_id>", methods=["POST"])
def pedidos_desmarcar(producto_id):
    conn = db.get_connection()
    conn.execute(
        "UPDATE productos SET pedido_pendiente=false, fecha_pedido_pendiente=NULL WHERE id=%s", (producto_id,)
    )
    conn.commit()
    conn.close()
    flash("Desmarcado: si sigue bajo el mínimo, vuelve a aparecer en la lista de faltantes.", "info")
    return redirect(url_for("pedidos_lista"))


# ---------------------------------------------------------------------------
# Compras/ventas sin factura (no pasan por compras/ventas ni por AFIP, pero
# sí impactan el mismo stock_actual que todo lo demás).
# ---------------------------------------------------------------------------
@app.route("/stock/no-facturado", methods=["GET", "POST"])
def stock_no_facturado():
    conn = db.get_connection()
    if request.method == "POST":
        tipo = request.form.get("tipo", "compra")
        if tipo not in ("compra", "venta"):
            tipo = "compra"
        producto_id = a_entero(request.form.get("producto_id"))
        cantidad = a_entero(request.form.get("cantidad"), 0) or 0
        try:
            precio = a_decimal(request.form.get("precio"))
        except InvalidOperation:
            precio = Decimal("0")
        contraparte = request.form.get("contraparte", "").strip() or None
        observaciones = request.form.get("observaciones", "").strip() or None

        producto = (
            conn.execute("SELECT * FROM productos WHERE id=%s", (producto_id,)).fetchone()
            if producto_id is not None
            else None
        )
        if not producto or cantidad <= 0:
            flash("Elegí un producto válido (de la lista) y una cantidad mayor a cero.", "danger")
            conn.close()
            return redirect(url_for("stock_no_facturado"))

        if tipo == "venta" and cantidad > producto["stock_actual"]:
            flash(f"No hay stock suficiente de {producto['nombre']} (stock actual: {producto['stock_actual']}).", "danger")
            conn.close()
            return redirect(url_for("stock_no_facturado"))

        conn.execute(
            """INSERT INTO movimientos_no_facturados (tipo, producto_id, cantidad, precio, contraparte, observaciones)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (tipo, producto["id"], cantidad, precio, contraparte, observaciones),
        )
        delta = cantidad if tipo == "compra" else -cantidad
        conn.execute("UPDATE productos SET stock_actual = stock_actual + %s WHERE id=%s", (delta, producto["id"]))
        conn.commit()
        conn.close()
        flash("Movimiento registrado y stock actualizado.", "success")
        return redirect(url_for("stock_no_facturado"))

    movimientos = conn.execute(
        """SELECT m.*, p.nombre AS producto_nombre, p.codigo AS producto_codigo FROM movimientos_no_facturados m
           JOIN productos p ON p.id = m.producto_id ORDER BY m.fecha DESC, m.id DESC"""
    ).fetchall()
    productos = conn.execute("SELECT * FROM productos ORDER BY nombre").fetchall()
    conn.close()
    return render_template(
        "stock_no_facturado.html", movimientos=movimientos, productos_json=productos_para_buscador(productos),
    )


@app.route("/stock/no-facturado/<int:movimiento_id>/conciliar", methods=["POST"])
def stock_no_facturado_conciliar(movimiento_id):
    conn = db.get_connection()
    conn.execute("UPDATE movimientos_no_facturados SET conciliado=true WHERE id=%s", (movimiento_id,))
    conn.commit()
    conn.close()
    flash("Movimiento marcado como conciliado.", "success")
    return redirect(url_for("stock_no_facturado"))


@app.route("/stock/no-facturado/<int:movimiento_id>/desconciliar", methods=["POST"])
def stock_no_facturado_desconciliar(movimiento_id):
    conn = db.get_connection()
    conn.execute("UPDATE movimientos_no_facturados SET conciliado=false WHERE id=%s", (movimiento_id,))
    conn.commit()
    conn.close()
    flash("Movimiento desmarcado.", "info")
    return redirect(url_for("stock_no_facturado"))


# ---------------------------------------------------------------------------
# Usuarios (solo administradores)
# ---------------------------------------------------------------------------
@app.route("/usuarios")
def usuarios_lista():
    if not es_admin():
        flash("Solo un administrador puede ver esta pantalla.", "danger")
        return redirect(url_for("dashboard"))
    conn = db.get_connection()
    usuarios = conn.execute("SELECT * FROM usuarios ORDER BY nombre").fetchall()
    conn.close()
    return render_template("usuarios.html", usuarios=usuarios)


@app.route("/usuarios/nuevo", methods=["GET", "POST"])
def usuarios_nuevo():
    if not es_admin():
        flash("Solo un administrador puede hacer esto.", "danger")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        nombre = request.form.get("nombre", "").strip()
        rol = request.form.get("rol", "empleado")
        conn = db.get_connection()
        existente = conn.execute(
            "SELECT id FROM usuarios WHERE username=%s OR email=%s", (username, email)
        ).fetchone()
        if existente:
            flash("Ya existe un usuario con ese nombre de usuario o ese email.", "danger")
            conn.close()
            return redirect(url_for("usuarios_nuevo"))

        password_temporal = db._generar_password_temporal()
        # Primero la cuenta: su id es el que va a llevar el perfil. Si esto
        # falla no se escribe nada en nuestra tabla, así que nunca queda un
        # perfil con rol y permisos pero sin forma de autenticarse.
        usuario_id = supabase_auth.crear_cuenta(email, password_temporal)
        if not usuario_id:
            flash(
                "No se pudo crear la cuenta. Revisá que el email sea válido y que no esté en uso.",
                "danger",
            )
            conn.close()
            return redirect(url_for("usuarios_nuevo"))

        # fecha_creacion queda afuera: la columna es timestamptz NOT NULL
        # DEFAULT now(), mismo criterio ya usado en compras/cuenta corriente
        # para no pisar el default con un valor de solo fecha.
        conn.execute(
            """INSERT INTO usuarios (id, username, email, nombre, rol, activo, debe_cambiar_password)
               VALUES (%s, %s, %s, %s, %s, TRUE, TRUE)""",
            (usuario_id, username, email, nombre, rol),
        )
        conn.commit()
        conn.close()
        flash(
            f"Usuario '{username}' creado. Contraseña temporal: {password_temporal} "
            "(anotala ahora, no se vuelve a mostrar — el sistema le va a pedir que la cambie al ingresar).",
            "success",
        )
        return redirect(url_for("usuarios_lista"))
    return render_template("usuario_form.html", usuario=None)


@app.route("/usuarios/<uuid:usuario_id>/editar", methods=["GET", "POST"])
def usuarios_editar(usuario_id):
    if not es_admin():
        flash("Solo un administrador puede hacer esto.", "danger")
        return redirect(url_for("dashboard"))
    conn = db.get_connection()
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        rol = request.form.get("rol", "empleado")
        activo = bool(request.form.get("activo"))
        conn.execute(
            "UPDATE usuarios SET nombre=%s, rol=%s, activo=%s WHERE id=%s",
            (nombre, rol, activo, usuario_id),
        )
        conn.commit()
        conn.close()
        flash("Usuario actualizado.", "success")
        return redirect(url_for("usuarios_lista"))
    usuario = conn.execute("SELECT * FROM usuarios WHERE id=%s", (usuario_id,)).fetchone()
    conn.close()
    return render_template("usuario_form.html", usuario=usuario)


@app.route("/usuarios/<uuid:usuario_id>/resetear-password", methods=["POST"])
def usuarios_resetear_password(usuario_id):
    if not es_admin():
        flash("Solo un administrador puede hacer esto.", "danger")
        return redirect(url_for("dashboard"))
    conn = db.get_connection()
    password_temporal = db._generar_password_temporal()
    # La contraseña vive en Supabase: primero se cambia allá. Si fallara y de
    # este lado ya hubiéramos marcado el cambio obligatorio, la persona
    # quedaría con la contraseña vieja pero obligada a cambiarla con una
    # temporal que nunca existió.
    if not supabase_auth.cambiar_password(usuario_id, password_temporal):
        flash("No se pudo resetear la contraseña. Probá de nuevo en un momento.", "danger")
        conn.close()
        return redirect(url_for("usuarios_lista"))
    conn.execute(
        "UPDATE usuarios SET debe_cambiar_password=true, intentos_fallidos=0, bloqueado_hasta=NULL WHERE id=%s",
        (usuario_id,),
    )
    conn.commit()
    conn.close()
    flash(
        f"Nueva contraseña temporal: {password_temporal} (anotala ahora, no se vuelve a mostrar).",
        "success",
    )
    return redirect(url_for("usuarios_lista"))


@app.route("/usuarios/<uuid:usuario_id>/eliminar", methods=["POST"])
def usuarios_eliminar(usuario_id):
    if not es_admin():
        flash("Solo un administrador puede hacer esto.", "danger")
        return redirect(url_for("dashboard"))
    if str(usuario_id) == str(session.get("usuario_id")):
        flash("No podés eliminar tu propio usuario mientras estás conectado con él.", "danger")
        return redirect(url_for("usuarios_lista"))
    # Se borra la cuenta y el perfil se va solo (ON DELETE CASCADE). Hacer las
    # dos cosas por separado abre la puerta a que el DELETE local salga bien y
    # el borrado de la cuenta falle: quedaría alguien que todavía puede
    # autenticarse contra Supabase pero ya no tiene perfil ni rol.
    if not supabase_auth.borrar_cuenta(usuario_id):
        flash("No se pudo eliminar el usuario. Probá de nuevo en un momento.", "danger")
        return redirect(url_for("usuarios_lista"))
    flash("Usuario eliminado.", "info")
    return redirect(url_for("usuarios_lista"))


# ---------------------------------------------------------------------------
# Tienda online (pública, sin login) — catálogo, carrito y checkout con
# Mercado Pago. Comparte el mismo stock que la venta del local: no hay dos
# sistemas separados que sincronizar.
# ---------------------------------------------------------------------------
def _carrito():
    return session.setdefault("carrito", {})


def _carrito_detalle(conn):
    """Resuelve el carrito de la sesión contra la base (nombre/precio/stock
    vigentes) y arma el resumen para mostrar en carrito/checkout."""
    carrito = _carrito()
    items = []
    total = 0
    for producto_id_str, cantidad in carrito.items():
        # Las rutas del carrito ya normalizan la clave a str(int), pero se
        # revalida acá: una sesión abierta antes de esa corrección puede
        # traer una clave que no sea un número, y reventar el carrito y el
        # checkout de ese visitante hasta que borre la cookie.
        producto_id = a_entero(producto_id_str)
        if producto_id is None:
            continue
        producto = conn.execute("SELECT * FROM productos WHERE id=%s", (producto_id,)).fetchone()
        if not producto:
            continue
        # nunca dejamos pedir más de lo que hay disponible ahora mismo
        cantidad = max(0, min(cantidad, producto["stock_actual"]))
        if cantidad == 0:
            continue
        subtotal = cantidad * producto["precio_venta"]
        total += subtotal
        items.append({
            "producto_id": producto["id"],
            "nombre": producto["nombre"],
            "codigo": producto["codigo"],
            "precio_unitario": producto["precio_venta"],
            "cantidad": cantidad,
            "subtotal": subtotal,
            "stock_actual": producto["stock_actual"],
        })
    return items, total


@app.route("/tienda")
def tienda_catalogo():
    conn = db.get_connection()
    categorias_activas = db.obtener_categorias(conn)
    q = request.args.get("q", "").strip()
    categoria = request.args.get("categoria", "").strip()
    if categoria not in categorias_activas:
        categoria = ""
    marca = request.args.get("marca", "").strip()
    modelo = request.args.get("modelo", "").strip()
    precio_min = request.args.get("precio_min", "").strip()
    precio_max = request.args.get("precio_max", "").strip()

    condiciones = ["stock_actual > 0"]
    parametros = []
    if q:
        like = f"%{q}%"
        # Tercer y último buscador del sistema: ILIKE, no LIKE -- en SQLite
        # LIKE ya era case-insensitive para ASCII, en Postgres no.
        condiciones.append("(nombre ILIKE %s OR marca ILIKE %s OR modelo_compatible ILIKE %s)")
        parametros += [like, like, like]
    if categoria:
        condiciones.append("categoria = %s")
        parametros.append(categoria)
    if marca:
        condiciones.append("marca = %s")
        parametros.append(marca)
    if modelo:
        condiciones.append("modelo_compatible = %s")
        parametros.append(modelo)
    if precio_min:
        try:
            valor_precio_min = a_decimal(precio_min)
        except (ValueError, InvalidOperation):
            precio_min = ""
        else:
            # Agregar la condición solo si la conversión no falló: si se
            # agrega antes (como pasaba acá), un valor inválido deja un
            # %s en la consulta sin su parámetro y el filtro rompe la
            # página en vez de ignorarse (hallazgo de Tarea 12).
            condiciones.append("precio_venta >= %s")
            parametros.append(valor_precio_min)
    if precio_max:
        try:
            valor_precio_max = a_decimal(precio_max)
        except (ValueError, InvalidOperation):
            precio_max = ""
        else:
            condiciones.append("precio_venta <= %s")
            parametros.append(valor_precio_max)

    productos = conn.execute(
        f"SELECT * FROM productos WHERE {' AND '.join(condiciones)} ORDER BY nombre", parametros
    ).fetchall()

    # Para armar los desplegables de marca/auto y los contadores de categoría
    # se usa todo lo que hay en stock (no solo el resultado ya filtrado), así
    # los filtros no "desaparecen" opciones a medida que se combinan.
    conteo_categorias = {
        r["categoria"]: r["c"]
        for r in conn.execute("SELECT categoria, COUNT(*) AS c FROM productos WHERE stock_actual > 0 GROUP BY categoria")
    }
    marcas_disponibles = [
        r["marca"] for r in conn.execute(
            "SELECT DISTINCT marca FROM productos WHERE stock_actual > 0 AND marca IS NOT NULL AND marca != '' ORDER BY marca"
        )
    ]
    modelos_disponibles = [
        r["modelo_compatible"] for r in conn.execute(
            "SELECT DISTINCT modelo_compatible FROM productos WHERE stock_actual > 0 AND modelo_compatible IS NOT NULL AND modelo_compatible != '' ORDER BY modelo_compatible"
        )
    ]
    conn.close()
    cantidad_carrito = sum(_carrito().values())
    return render_template(
        "tienda_catalogo.html", productos=productos, q=q, categoria=categoria,
        categorias=categorias_activas, conteo_categorias=conteo_categorias,
        marca=marca, marcas_disponibles=marcas_disponibles,
        modelo=modelo, modelos_disponibles=modelos_disponibles,
        precio_min=precio_min, precio_max=precio_max,
        cantidad_carrito=cantidad_carrito,
    )


@app.route("/tienda/carrito/agregar", methods=["POST"])
def tienda_carrito_agregar():
    producto_id = a_entero(request.form.get("producto_id"))
    cantidad = a_entero(request.form.get("cantidad"), 1) or 1
    if producto_id is None:
        flash("Ese producto no está disponible.", "danger")
        return redirect(url_for("tienda_catalogo"))
    conn = db.get_connection()
    producto = conn.execute("SELECT * FROM productos WHERE id=%s", (producto_id,)).fetchone()
    conn.close()
    if not producto or producto["stock_actual"] <= 0:
        flash("Ese producto no está disponible.", "danger")
        return redirect(url_for("tienda_catalogo"))

    # La clave del carrito se normaliza a str(int): así "5" y "05" son el
    # mismo renglón y no dos, y nunca entra a la sesión algo que después
    # `_carrito_detalle()` no pueda convertir.
    clave = str(producto_id)
    carrito = _carrito()
    actual = carrito.get(clave, 0)
    carrito[clave] = min(actual + cantidad, producto["stock_actual"])
    session.modified = True
    flash(f"Agregado: {producto['nombre']}.", "success")
    return redirect(request.referrer or url_for("tienda_catalogo"))


@app.route("/tienda/carrito/quitar", methods=["POST"])
def tienda_carrito_quitar():
    producto_id = a_entero(request.form.get("producto_id"))
    carrito = _carrito()
    if producto_id is not None:
        carrito.pop(str(producto_id), None)
    session.modified = True
    return redirect(url_for("tienda_carrito"))


@app.route("/tienda/carrito/actualizar", methods=["POST"])
def tienda_carrito_actualizar():
    producto_id = a_entero(request.form.get("producto_id"))
    cantidad = a_entero(request.form.get("cantidad"), 0) or 0
    carrito = _carrito()
    if producto_id is not None:
        if cantidad <= 0:
            carrito.pop(str(producto_id), None)
        else:
            carrito[str(producto_id)] = cantidad
    session.modified = True
    return redirect(url_for("tienda_carrito"))


@app.route("/tienda/carrito")
def tienda_carrito():
    conn = db.get_connection()
    items, total = _carrito_detalle(conn)
    conn.close()
    return render_template("tienda_carrito.html", items=items, total=total)


@app.route("/tienda/checkout", methods=["GET", "POST"])
def tienda_checkout():
    conn = db.get_connection()
    items, total = _carrito_detalle(conn)
    if not items:
        conn.close()
        flash("Tu carrito está vacío.", "warning")
        return redirect(url_for("tienda_catalogo"))

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        telefono = request.form.get("telefono", "").strip()
        email = request.form.get("email", "").strip()
        direccion = request.form.get("direccion", "").strip()
        cuit_dni = request.form.get("cuit_dni", "").strip()

        if not nombre or not telefono:
            flash("Completá al menos tu nombre y un teléfono de contacto.", "danger")
            conn.close()
            return render_template("tienda_checkout.html", items=items, total=total, tienda_lista=tienda_pagos.tienda_configurada())

        cur = conn.cursor()
        cur.execute(
            """INSERT INTO pedidos_web (fecha, nombre_cliente, telefono, email, direccion, cuit_dni, total, estado)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 'pendiente_pago') RETURNING id""",
            (db.hoy(), nombre, telefono, email, direccion, cuit_dni, total),
        )
        pedido_id = cur.fetchone()["id"]
        for it in items:
            cur.execute(
                """INSERT INTO pedido_web_items (pedido_id, producto_id, cantidad, precio_unitario, subtotal)
                   VALUES (%s, %s, %s, %s, %s)""",
                (pedido_id, it["producto_id"], it["cantidad"], it["precio_unitario"], it["subtotal"]),
            )
        conn.commit()
        conn.close()

        init_point = tienda_pagos.crear_preferencia(pedido_id)
        if not init_point:
            flash(
                "El cobro online todavía no está disponible (falta terminar de configurar Mercado Pago). "
                "Escribinos por WhatsApp para coordinar el pedido: " + NEGOCIO["telefono"],
                "warning",
            )
            return redirect(url_for("tienda_carrito"))

        session["carrito"] = {}  # se vacía recién al confirmar la preferencia
        session.modified = True
        return redirect(init_point)

    tienda_lista = tienda_pagos.tienda_configurada()
    conn.close()
    return render_template("tienda_checkout.html", items=items, total=total, tienda_lista=tienda_lista)


def _pedido_web_o_404(pedido_id):
    conn = db.get_connection()
    pedido = conn.execute("SELECT * FROM pedidos_web WHERE id=%s", (pedido_id,)).fetchone()
    conn.close()
    return pedido


@app.route("/tienda/pedido/<int:pedido_id>/exito")
def tienda_pedido_exito(pedido_id):
    pedido = _pedido_web_o_404(pedido_id)
    return render_template("tienda_pedido_estado.html", pedido=pedido, resultado="exito")


@app.route("/tienda/pedido/<int:pedido_id>/pendiente")
def tienda_pedido_pendiente(pedido_id):
    pedido = _pedido_web_o_404(pedido_id)
    return render_template("tienda_pedido_estado.html", pedido=pedido, resultado="pendiente")


@app.route("/tienda/pedido/<int:pedido_id>/fallo")
def tienda_pedido_fallo(pedido_id):
    pedido = _pedido_web_o_404(pedido_id)
    return render_template("tienda_pedido_estado.html", pedido=pedido, resultado="fallo")


@csrf.exempt
@app.route("/webhooks/mercadopago", methods=["POST"])
def webhook_mercadopago():
    """Notificación de Mercado Pago. Es la ÚNICA fuente de verdad del pago
    (nunca las back_urls del navegador). Confirma el pago, genera la venta
    real y descuenta el mismo stock que usa el local."""
    body = request.get_json(silent=True) or {}
    data_id = request.args.get("data.id") or body.get("data", {}).get("id")
    tipo = request.args.get("type") or body.get("type")

    if tipo != "payment" or not data_id:
        return "", 200  # otros tipos de notificación (merchant_order, etc.) se ignoran

    valido, motivo = tienda_pagos.validar_firma_webhook(
        request.headers.get("x-signature"), request.headers.get("x-request-id"), data_id
    )
    if not valido:
        return jsonify({"error": "firma inválida"}), 401

    pago = tienda_pagos.obtener_pago(data_id)
    if not pago:
        return "", 200

    pedido_id = pago.get("external_reference")
    if not pedido_id:
        return "", 200

    conn = db.get_connection()
    pedido = conn.execute("SELECT * FROM pedidos_web WHERE id=%s", (pedido_id,)).fetchone()
    if not pedido:
        conn.close()
        return "", 200

    if pedido["estado"] == "pagado":
        conn.close()  # ya procesado (idempotencia: MP puede reintentar el webhook)
        return "", 200

    estado_pago = pago.get("status")  # approved | pending | rejected | in_process | ...
    if estado_pago != "approved":
        conn.execute(
            "UPDATE pedidos_web SET estado=%s, mp_payment_id=%s WHERE id=%s",
            (estado_pago or pedido["estado"], str(data_id), pedido_id),
        )
        conn.commit()
        conn.close()
        return "", 200

    # pago aprobado: buscamos o creamos el cliente, y generamos la venta real
    items_pedido = conn.execute(
        "SELECT * FROM pedido_web_items WHERE pedido_id=%s", (pedido_id,)
    ).fetchall()

    cliente_id = None
    if pedido["email"]:
        cliente = conn.execute("SELECT id FROM clientes WHERE email=%s", (pedido["email"],)).fetchone()
        if cliente:
            cliente_id = cliente["id"]
    if not cliente_id and pedido["telefono"]:
        cliente = conn.execute("SELECT id FROM clientes WHERE telefono=%s", (pedido["telefono"],)).fetchone()
        if cliente:
            cliente_id = cliente["id"]
    if not cliente_id:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO clientes (nombre, telefono, email, direccion, cuit_dni, fecha_alta) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (
                pedido["nombre_cliente"], pedido["telefono"], pedido["email"], pedido["direccion"],
                pedido["cuit_dni"] or "",
                db.hoy(),
            ),
        )
        cliente_id = cur.fetchone()["id"]
        conn.commit()

    items = [(it["producto_id"], it["cantidad"], it["precio_unitario"], it["subtotal"]) for it in items_pedido]
    venta_id, tipo_comprobante = registrar_venta(conn, cliente_id, "Mercado Pago", items)

    conn.execute(
        "UPDATE pedidos_web SET estado='pagado', mp_payment_id=%s, venta_id=%s WHERE id=%s",
        (str(data_id), venta_id, pedido_id),
    )
    conn.commit()
    conn.close()

    if _es_factura(tipo_comprobante):
        facturacion_afip.emitir_factura(venta_id)

    return "", 200


if __name__ == "__main__":
    # Uso normal: correr `python app.py` desde la raíz (ver el shim ahí).
    # Esto solo se ejecuta si alguien corre core/app.py directamente.
    sembrar_datos_de_ejemplo()
    app.run(debug=True, port=5050)
