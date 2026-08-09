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
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from . import database as db
from . import facturacion_afip
from . import tienda_pagos
from . import importar_factura
from . import comprobante_pdf
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

# La clave de sesión se genera una sola vez y se guarda en un archivo local
# (nunca hardcodeada en el código ni en el repositorio). Vive en la misma
# carpeta que data.db (db.INSTANCE_DIR) para que en Docker quede en el
# volumen persistente y no se pierda al recrear el contenedor.
_SECRET_KEY_PATH = os.path.join(db.INSTANCE_DIR, ".secret_key")
if os.path.exists(_SECRET_KEY_PATH):
    with open(_SECRET_KEY_PATH) as _f:
        app.secret_key = _f.read().strip()
else:
    app.secret_key = secrets.token_hex(32)
    with open(_SECRET_KEY_PATH, "w") as _f:
        _f.write(app.secret_key)

app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=12)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Cuando el sistema quede accesible por HTTPS (hosting), sumar:
# app.config["SESSION_COOKIE_SECURE"] = True

LOCKOUT_INTENTOS = 5
LOCKOUT_MINUTOS = 15

db.init_db()
db.seed_demo_data()
db.seed_admin_user()


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
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = db.get_connection()
        usuario = conn.execute("SELECT * FROM usuarios WHERE username = ?", (username,)).fetchone()

        # ¿La cuenta está bloqueada por intentos fallidos?
        if usuario and usuario["bloqueado_hasta"]:
            bloqueado_hasta = datetime.strptime(usuario["bloqueado_hasta"], "%Y-%m-%d %H:%M:%S")
            if datetime.now() < bloqueado_hasta:
                minutos = int((bloqueado_hasta - datetime.now()).total_seconds() // 60) + 1
                flash(f"Demasiados intentos fallidos. Probá de nuevo en {minutos} minuto(s).", "danger")
                conn.close()
                return render_template("login.html")
            conn.execute("UPDATE usuarios SET intentos_fallidos=0, bloqueado_hasta=NULL WHERE id=?", (usuario["id"],))
            conn.commit()
            usuario = conn.execute("SELECT * FROM usuarios WHERE id=?", (usuario["id"],)).fetchone()

        credenciales_validas = (
            usuario and usuario["activo"] and check_password_hash(usuario["password_hash"], password)
        )

        if not credenciales_validas:
            if usuario and usuario["activo"]:
                intentos = usuario["intentos_fallidos"] + 1
                if intentos >= LOCKOUT_INTENTOS:
                    bloqueado_hasta = (datetime.now() + timedelta(minutes=LOCKOUT_MINUTOS)).strftime("%Y-%m-%d %H:%M:%S")
                    conn.execute(
                        "UPDATE usuarios SET intentos_fallidos=?, bloqueado_hasta=? WHERE id=?",
                        (intentos, bloqueado_hasta, usuario["id"]),
                    )
                    flash(f"Demasiados intentos fallidos. La cuenta queda bloqueada {LOCKOUT_MINUTOS} minutos.", "danger")
                else:
                    conn.execute("UPDATE usuarios SET intentos_fallidos=? WHERE id=?", (intentos, usuario["id"]))
                    flash("Usuario o contraseña incorrectos.", "danger")
                conn.commit()
            else:
                flash("Usuario o contraseña incorrectos.", "danger")
            conn.close()
            return render_template("login.html")

        conn.execute("UPDATE usuarios SET intentos_fallidos=0, bloqueado_hasta=NULL WHERE id=?", (usuario["id"],))
        conn.commit()
        conn.close()

        session.clear()
        session.permanent = True
        session["usuario_id"] = usuario["id"]
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
        usuario = conn.execute("SELECT * FROM usuarios WHERE id=?", (session["usuario_id"],)).fetchone()

        if not obligatorio and not check_password_hash(usuario["password_hash"], actual):
            flash("La contraseña actual no es correcta.", "danger")
        elif len(nueva) < 8:
            flash("La contraseña nueva tiene que tener al menos 8 caracteres.", "danger")
        elif nueva != confirmar:
            flash("Las contraseñas nuevas no coinciden.", "danger")
        else:
            conn.execute(
                "UPDATE usuarios SET password_hash=?, debe_cambiar_password=0 WHERE id=?",
                (generate_password_hash(nueva), usuario["id"]),
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


EXTENSIONES_IMAGEN_PERMITIDAS = {"jpg", "jpeg", "png", "webp"}
CARPETA_IMAGENES_PRODUCTOS = os.path.join(PROJECT_ROOT, "static", "img", "productos")
os.makedirs(CARPETA_IMAGENES_PRODUCTOS, exist_ok=True)


def guardar_imagen_producto(producto_id, file_storage):
    """Guarda la foto subida para un producto y devuelve el nombre de archivo
    a guardar en productos.imagen, o None si no se subió nada válido."""
    if not file_storage or not file_storage.filename:
        return None
    extension = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    if extension not in EXTENSIONES_IMAGEN_PERMITIDAS:
        return None
    nombre_archivo = secure_filename(f"producto_{producto_id}.{extension}")
    file_storage.save(os.path.join(CARPETA_IMAGENES_PRODUCTOS, nombre_archivo))
    return nombre_archivo


def eliminar_imagen_producto(nombre_archivo):
    if not nombre_archivo:
        return
    ruta = os.path.join(CARPETA_IMAGENES_PRODUCTOS, nombre_archivo)
    if os.path.exists(ruta):
        os.remove(ruta)


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

    hoy = datetime.now()
    primer_dia_mes = hoy.replace(day=1).strftime("%Y-%m-%d")
    ventas_mes = conn.execute(
        "SELECT COALESCE(SUM(total),0) AS t FROM ventas WHERE fecha >= ?", (primer_dia_mes,)
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
            "SELECT COALESCE(SUM(total),0) AS t FROM ventas WHERE fecha >= ? AND fecha < ?", (inicio, fin)
        ).fetchone()["t"]
        meses.append(f"{month:02d}/{year}")
        ventas_por_mes.append(round(total, 2))

    # Top 5 productos más vendidos (por cantidad)
    top_productos = conn.execute(
        """SELECT p.nombre, SUM(vi.cantidad) AS cantidad, SUM(vi.subtotal) AS total
           FROM venta_items vi JOIN productos p ON p.id = vi.producto_id
           GROUP BY vi.producto_id ORDER BY cantidad DESC LIMIT 5"""
    ).fetchall()

    # Top 5 clientes por monto comprado
    top_clientes = conn.execute(
        """SELECT c.nombre, SUM(v.total) AS total, COUNT(v.id) AS cant_compras
           FROM ventas v JOIN clientes c ON c.id = v.cliente_id
           GROUP BY v.cliente_id ORDER BY total DESC LIMIT 5"""
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
    if q:
        clientes = conn.execute(
            "SELECT * FROM clientes WHERE nombre LIKE ? OR telefono LIKE ? OR email LIKE ? ORDER BY nombre",
            (f"%{q}%", f"%{q}%", f"%{q}%"),
        ).fetchall()
    else:
        clientes = conn.execute("SELECT * FROM clientes ORDER BY nombre").fetchall()
    conn.close()
    return render_template("clientes.html", clientes=clientes, q=q)


@app.route("/clientes/nuevo", methods=["GET", "POST"])
def clientes_nuevo():
    if request.method == "POST":
        conn = db.get_connection()
        conn.execute(
            """INSERT INTO clientes (nombre, telefono, email, direccion, cuit_dni, tipo_cliente, fecha_alta)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                request.form["nombre"],
                request.form.get("telefono", ""),
                request.form.get("email", ""),
                request.form.get("direccion", ""),
                request.form.get("cuit_dni", ""),
                request.form.get("tipo_cliente", "particular"),
                datetime.now().strftime("%Y-%m-%d"),
            ),
        )
        conn.commit()
        conn.close()
        flash("Cliente creado correctamente.", "success")
        return redirect(url_for("clientes_lista"))
    return render_template("cliente_form.html", cliente=None)


@app.route("/clientes/<int:cliente_id>/editar", methods=["GET", "POST"])
def clientes_editar(cliente_id):
    conn = db.get_connection()
    if request.method == "POST":
        conn.execute(
            "UPDATE clientes SET nombre=?, telefono=?, email=?, direccion=?, cuit_dni=?, tipo_cliente=? WHERE id=?",
            (
                request.form["nombre"],
                request.form.get("telefono", ""),
                request.form.get("email", ""),
                request.form.get("direccion", ""),
                request.form.get("cuit_dni", ""),
                request.form.get("tipo_cliente", "particular"),
                cliente_id,
            ),
        )
        conn.commit()
        conn.close()
        flash("Cliente actualizado.", "success")
        return redirect(url_for("clientes_lista"))
    cliente = conn.execute("SELECT * FROM clientes WHERE id=?", (cliente_id,)).fetchone()
    conn.close()
    return render_template("cliente_form.html", cliente=cliente)


@app.route("/clientes/<int:cliente_id>/eliminar", methods=["POST"])
def clientes_eliminar(cliente_id):
    conn = db.get_connection()
    conn.execute("DELETE FROM clientes WHERE id=?", (cliente_id,))
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
    cliente = conn.execute("SELECT * FROM clientes WHERE id=?", (cliente_id,)).fetchone()
    if not cliente:
        conn.close()
        flash("No encontré ese cliente.", "danger")
        return redirect(url_for("clientes_lista"))
    movimientos = conn.execute(
        """SELECT m.*, p.nombre AS producto_nombre FROM cuenta_corriente_movimientos m
           LEFT JOIN productos p ON p.id = m.producto_id
           WHERE m.cliente_id=? ORDER BY m.fecha DESC, m.id DESC""",
        (cliente_id,),
    ).fetchall()
    saldo = sum(m["monto"] if m["tipo"] == "cargo" else -m["monto"] for m in movimientos)
    productos = conn.execute("SELECT * FROM productos ORDER BY nombre").fetchall()
    conn.close()
    return render_template(
        "cuenta_corriente.html", cliente=cliente, movimientos=movimientos, saldo=saldo,
        productos_json=productos_para_buscador(productos),
        umbral_identificacion=facturacion_afip.UMBRAL_IDENTIFICACION_RECEPTOR,
    )


@app.route("/clientes/<int:cliente_id>/cuenta-corriente/nueva", methods=["POST"])
def cuenta_corriente_nueva(cliente_id):
    conn = db.get_connection()
    cliente = conn.execute("SELECT * FROM clientes WHERE id=?", (cliente_id,)).fetchone()
    if not cliente:
        conn.close()
        flash("No encontré ese cliente.", "danger")
        return redirect(url_for("clientes_lista"))

    tipo = request.form.get("tipo", "cargo")
    if tipo not in ("cargo", "pago"):
        tipo = "cargo"
    try:
        monto = float(request.form.get("monto") or 0)
    except ValueError:
        monto = 0
    if monto <= 0:
        flash("El monto tiene que ser mayor a cero.", "danger")
        conn.close()
        return redirect(url_for("cuenta_corriente_ver", cliente_id=cliente_id))

    if (
        tipo == "cargo"
        and monto > facturacion_afip.UMBRAL_IDENTIFICACION_RECEPTOR
        and not (cliente["cuit_dni"] or "").strip()
    ):
        flash(
            f"Este cargo supera el monto a partir del cual ARCA exige identificar al receptor. "
            f"Cargá el CUIT/DNI de {cliente['nombre']} en su ficha antes de continuar.",
            "danger",
        )
        conn.close()
        return redirect(url_for("cuenta_corriente_ver", cliente_id=cliente_id))

    producto_id = request.form.get("producto_id") or None
    cliente_tercero_nombre = request.form.get("cliente_tercero_nombre", "").strip() or None
    observaciones = request.form.get("observaciones", "").strip() or None

    cur = conn.execute(
        """INSERT INTO cuenta_corriente_movimientos
           (cliente_id, cliente_tercero_nombre, producto_id, monto, tipo, observaciones)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (cliente_id, cliente_tercero_nombre, producto_id, monto, tipo, observaciones),
    )
    movimiento_id = cur.lastrowid
    conn.commit()
    conn.close()

    if tipo == "cargo":
        # Nunca bloquea ni revierte el movimiento si ARCA falla: se puede
        # reintentar después desde esta misma pantalla (igual criterio que
        # con la Factura C de una venta del local).
        facturacion_afip.emitir_factura_c_movimiento(movimiento_id)

    flash("Movimiento registrado en la cuenta corriente.", "success")
    return redirect(url_for("cuenta_corriente_ver", cliente_id=cliente_id))


@app.route("/clientes/<int:cliente_id>/cuenta-corriente/<int:movimiento_id>/facturar", methods=["POST"])
def cuenta_corriente_facturar(cliente_id, movimiento_id):
    """Reintento manual de la Factura C de un cargo de cuenta corriente."""
    facturacion_afip.emitir_factura_c_movimiento(movimiento_id)
    conn = db.get_connection()
    estado = conn.execute(
        "SELECT facturacion_estado, facturacion_error FROM cuenta_corriente_movimientos WHERE id=?",
        (movimiento_id,),
    ).fetchone()
    conn.close()
    if not estado:
        flash("No encontré ese movimiento.", "danger")
    elif estado["facturacion_estado"] == "emitida":
        flash("Factura C emitida correctamente.", "success")
    elif estado["facturacion_estado"] == "sin_configurar":
        flash("Todavía no está configurado el acceso a Afip SDK (AFIPSDK_ACCESS_TOKEN). Ver README.md.", "warning")
    else:
        flash("No se pudo emitir la Factura C: %s" % (estado["facturacion_error"] or "error desconocido"), "danger")
    return redirect(url_for("cuenta_corriente_ver", cliente_id=cliente_id))


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
        desde = (datetime.now() - timedelta(days=int(periodo))).strftime("%Y-%m-%d")
        condicion_fecha = "WHERE v.fecha >= ?"
        parametros = [desde]

    ranking = conn.execute(
        f"""SELECT c.id, c.nombre, c.tipo_cliente, COUNT(v.id) AS cant_compras, SUM(v.total) AS total
            FROM ventas v JOIN clientes c ON c.id = v.cliente_id
            {condicion_fecha}
            GROUP BY v.cliente_id ORDER BY total DESC LIMIT 5""",
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
                WHERE v.cliente_id = ? {"AND v.fecha >= ?" if condicion_fecha else ""}""",
            params_margen,
        ).fetchone()
        margenes[r["id"]] = margen["margen"]

    promociones_vigentes = conn.execute(
        """SELECT pa.*, c.nombre AS cliente_nombre FROM promociones_aplicadas pa
           JOIN clientes c ON c.id = pa.cliente_id
           WHERE fecha_inicio <= date('now') AND (fecha_fin IS NULL OR fecha_fin >= date('now'))
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
        porcentaje_o_monto = float(request.form.get("porcentaje_o_monto") or 0)
    except ValueError:
        porcentaje_o_monto = 0
    alcance = request.form.get("alcance", "todo")
    if alcance not in ("todo", "productos_puntuales"):
        alcance = "todo"
    fecha_inicio = request.form.get("fecha_inicio") or datetime.now().strftime("%Y-%m-%d")
    fecha_fin = request.form.get("fecha_fin") or None
    aprobado_por = session.get("usuario_nombre")

    if porcentaje_o_monto <= 0:
        flash("El valor del descuento tiene que ser mayor a cero.", "danger")
        conn.close()
        return redirect(url_for("clientes_top"))

    cur = conn.execute(
        """INSERT INTO promociones_aplicadas
           (cliente_id, porcentaje_o_monto, tipo, alcance, fecha_inicio, fecha_fin, aprobado_por)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (cliente_id, porcentaje_o_monto, tipo, alcance, fecha_inicio, fecha_fin, aprobado_por),
    )
    promocion_id = cur.lastrowid

    if alcance == "productos_puntuales":
        for producto_id in request.form.getlist("producto_id"):
            conn.execute(
                "INSERT INTO promocion_productos (promocion_id, producto_id) VALUES (?, ?)",
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
        "UPDATE promociones_aplicadas SET fecha_fin=? WHERE id=?",
        (datetime.now().strftime("%Y-%m-%d"), promocion_id),
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

    conn.execute("DELETE FROM producto_proveedor WHERE producto_id=?", (producto_id,))
    vistos = set()
    for proveedor_id, precio, codigo_prov in zip(proveedor_ids, precios, codigos):
        if not proveedor_id or not precio:
            continue
        if proveedor_id in vistos:
            continue  # no permitir el mismo proveedor dos veces en el mismo producto
        vistos.add(proveedor_id)
        conn.execute(
            """INSERT INTO producto_proveedor (producto_id, proveedor_id, precio_costo, codigo_proveedor)
               VALUES (?, ?, ?, ?)""",
            (producto_id, proveedor_id, float(precio), (codigo_prov or "").strip() or None),
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
        condiciones.append("(nombre LIKE ? OR codigo LIKE ? OR marca LIKE ? OR modelo_compatible LIKE ? OR codigo_barras = ?)")
        parametros += [f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%", q]
    if categoria:
        condiciones.append("categoria = ?")
        parametros.append(categoria)
    if subcategoria:
        condiciones.append("subcategoria = ?")
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
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                request.form.get("codigo") or None,
                request.form["nombre"],
                request.form["categoria"],
                request.form.get("subcategoria") or None,
                request.form.get("marca", ""),
                request.form.get("modelo_compatible", ""),
                float(request.form.get("precio_costo") or 0),
                float(request.form.get("precio_venta") or 0),
                int(request.form.get("stock_actual") or 0),
                int(request.form.get("stock_minimo") or 2),
                request.form.get("proveedor_id") or None,
                request.form.get("codigo_barras") or None,
            ),
        )
        producto_id = cur.lastrowid
        guardar_cotizaciones_proveedor(conn, producto_id, request.form)

        nombre_imagen = guardar_imagen_producto(producto_id, request.files.get("imagen"))
        if nombre_imagen:
            conn.execute("UPDATE productos SET imagen=? WHERE id=?", (nombre_imagen, producto_id))

        conn.commit()
        conn.close()
        flash("Producto creado correctamente.", "success")
        return redirect(url_for("productos_lista"))
    proveedores = conn.execute("SELECT * FROM proveedores WHERE activo=1 ORDER BY nombre").fetchall()
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
            """UPDATE productos SET codigo=?, nombre=?, categoria=?, subcategoria=?, marca=?, modelo_compatible=?,
               precio_costo=?, precio_venta=?, stock_actual=?, stock_minimo=?, proveedor_id=?,
               codigo_barras=? WHERE id=?""",
            (
                request.form.get("codigo") or None,
                request.form["nombre"],
                request.form["categoria"],
                request.form.get("subcategoria") or None,
                request.form.get("marca", ""),
                request.form.get("modelo_compatible", ""),
                float(request.form.get("precio_costo") or 0),
                float(request.form.get("precio_venta") or 0),
                int(request.form.get("stock_actual") or 0),
                int(request.form.get("stock_minimo") or 2),
                request.form.get("proveedor_id") or None,
                request.form.get("codigo_barras") or None,
                producto_id,
            ),
        )
        guardar_cotizaciones_proveedor(conn, producto_id, request.form)

        producto_actual = conn.execute("SELECT imagen FROM productos WHERE id=?", (producto_id,)).fetchone()
        if request.form.get("eliminar_imagen") == "1":
            eliminar_imagen_producto(producto_actual["imagen"])
            conn.execute("UPDATE productos SET imagen=NULL WHERE id=?", (producto_id,))
        else:
            nombre_imagen = guardar_imagen_producto(producto_id, request.files.get("imagen"))
            if nombre_imagen:
                eliminar_imagen_producto(producto_actual["imagen"])
                conn.execute("UPDATE productos SET imagen=? WHERE id=?", (nombre_imagen, producto_id))

        conn.commit()
        conn.close()
        flash("Producto actualizado.", "success")
        return redirect(url_for("productos_lista"))
    producto = conn.execute("SELECT * FROM productos WHERE id=?", (producto_id,)).fetchone()
    # incluye también el proveedor actual del producto aunque esté desactivado,
    # para no perderlo de la ficha si ya estaba asignado antes de desactivarlo.
    proveedores = conn.execute(
        "SELECT * FROM proveedores WHERE activo=1 OR id=? ORDER BY nombre", (producto["proveedor_id"],)
    ).fetchall()
    cotizaciones = conn.execute(
        """SELECT pp.*, p.nombre AS proveedor_nombre FROM producto_proveedor pp
           JOIN proveedores p ON p.id = pp.proveedor_id
           WHERE pp.producto_id = ? ORDER BY pp.precio_costo ASC""",
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
    producto = conn.execute("SELECT imagen FROM productos WHERE id=?", (producto_id,)).fetchone()
    if producto:
        eliminar_imagen_producto(producto["imagen"])
    conn.execute("DELETE FROM productos WHERE id=?", (producto_id,))
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
        proveedores = conn.execute("SELECT * FROM proveedores WHERE activo=1 ORDER BY nombre").fetchall()
    conn.close()
    return render_template("proveedores.html", proveedores=proveedores, mostrar_todos=mostrar_todos)


@app.route("/proveedores/nuevo", methods=["GET", "POST"])
def proveedores_nuevo():
    if request.method == "POST":
        conn = db.get_connection()
        conn.execute(
            "INSERT INTO proveedores (nombre, telefono, email, direccion, cuit) VALUES (?, ?, ?, ?, ?)",
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
            "UPDATE proveedores SET nombre=?, telefono=?, email=?, direccion=?, cuit=? WHERE id=?",
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
    proveedor = conn.execute("SELECT * FROM proveedores WHERE id=?", (proveedor_id,)).fetchone()
    conn.close()
    return render_template("proveedor_form.html", proveedor=proveedor)


@app.route("/proveedores/<int:proveedor_id>/eliminar", methods=["POST"])
def proveedores_eliminar(proveedor_id):
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM proveedores WHERE id=?", (proveedor_id,))
        conn.commit()
        flash("Proveedor eliminado.", "info")
    except sqlite3.IntegrityError:
        conn.rollback()
        flash("No se puede eliminar: este proveedor tiene productos, compras o cotizaciones cargadas. "
              "Desactivalo en su lugar (no se va a poder elegir para nada nuevo, pero no rompe lo ya cargado).", "danger")
    conn.close()
    return redirect(url_for("proveedores_lista"))


@app.route("/proveedores/<int:proveedor_id>/activar", methods=["POST"])
def proveedores_activar(proveedor_id):
    conn = db.get_connection()
    conn.execute("UPDATE proveedores SET activo=1 WHERE id=?", (proveedor_id,))
    conn.commit()
    conn.close()
    flash("Proveedor activado.", "success")
    return redirect(url_for("proveedores_lista", todos=request.args.get("todos", "")))


@app.route("/proveedores/<int:proveedor_id>/desactivar", methods=["POST"])
def proveedores_desactivar(proveedor_id):
    conn = db.get_connection()
    conn.execute("UPDATE proveedores SET activo=0 WHERE id=?", (proveedor_id,))
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
        categorias = conn.execute("SELECT * FROM categorias WHERE activo=1 ORDER BY nombre").fetchall()
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
        conn.execute("INSERT INTO categorias (nombre) VALUES (?)", (nombre,))
        conn.commit()
        flash(f"Categoría '{nombre}' creada.", "success")
    except sqlite3.IntegrityError:
        flash(f"Ya existe una categoría '{nombre}'.", "danger")
    conn.close()
    return redirect(url_for("categorias_lista"))


@app.route("/categorias/<int:categoria_id>/eliminar", methods=["POST"])
def categorias_eliminar(categoria_id):
    conn = db.get_connection()
    fila = conn.execute("SELECT nombre FROM categorias WHERE id=?", (categoria_id,)).fetchone()
    en_uso = fila and conn.execute(
        "SELECT COUNT(*) AS c FROM productos WHERE categoria=?", (fila["nombre"],)
    ).fetchone()["c"]
    if en_uso:
        flash("No se puede eliminar: hay productos cargados con esta categoría. "
              "Desactivala en su lugar (no se va a poder elegir para productos nuevos).", "danger")
    else:
        conn.execute("DELETE FROM categorias WHERE id=?", (categoria_id,))
        conn.commit()
        flash("Categoría eliminada.", "info")
    conn.close()
    return redirect(url_for("categorias_lista"))


@app.route("/categorias/<int:categoria_id>/activar", methods=["POST"])
def categorias_activar(categoria_id):
    conn = db.get_connection()
    conn.execute("UPDATE categorias SET activo=1 WHERE id=?", (categoria_id,))
    conn.commit()
    conn.close()
    flash("Categoría activada.", "success")
    return redirect(url_for("categorias_lista", todas=request.args.get("todas", "")))


@app.route("/categorias/<int:categoria_id>/desactivar", methods=["POST"])
def categorias_desactivar(categoria_id):
    conn = db.get_connection()
    conn.execute("UPDATE categorias SET activo=0 WHERE id=?", (categoria_id,))
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
            "INSERT INTO subcategorias (nombre, categoria_id) VALUES (?, ?)", (nombre, categoria_id)
        )
        conn.commit()
        flash(f"Subcategoría '{nombre}' creada.", "success")
    except sqlite3.IntegrityError:
        flash(f"Esa categoría ya tiene una subcategoría '{nombre}'.", "danger")
    conn.close()
    return redirect(url_for("categorias_lista"))


@app.route("/subcategorias/<int:subcategoria_id>/eliminar", methods=["POST"])
def subcategorias_eliminar(subcategoria_id):
    conn = db.get_connection()
    fila = conn.execute("SELECT nombre FROM subcategorias WHERE id=?", (subcategoria_id,)).fetchone()
    en_uso = fila and conn.execute(
        "SELECT COUNT(*) AS c FROM productos WHERE subcategoria=?", (fila["nombre"],)
    ).fetchone()["c"]
    if en_uso:
        flash("No se puede eliminar: hay productos cargados con esta subcategoría. "
              "Desactivala en su lugar.", "danger")
    else:
        conn.execute("DELETE FROM subcategorias WHERE id=?", (subcategoria_id,))
        conn.commit()
        flash("Subcategoría eliminada.", "info")
    conn.close()
    return redirect(url_for("categorias_lista"))


@app.route("/subcategorias/<int:subcategoria_id>/activar", methods=["POST"])
def subcategorias_activar(subcategoria_id):
    conn = db.get_connection()
    conn.execute("UPDATE subcategorias SET activo=1 WHERE id=?", (subcategoria_id,))
    conn.commit()
    conn.close()
    flash("Subcategoría activada.", "success")
    return redirect(url_for("categorias_lista", todas=request.args.get("todas", "")))


@app.route("/subcategorias/<int:subcategoria_id>/desactivar", methods=["POST"])
def subcategorias_desactivar(subcategoria_id):
    conn = db.get_connection()
    conn.execute("UPDATE subcategorias SET activo=0 WHERE id=?", (subcategoria_id,))
    conn.commit()
    conn.close()
    flash("Subcategoría desactivada: no va a aparecer para elegir en productos nuevos.", "info")
    return redirect(url_for("categorias_lista", todas=request.args.get("todas", "")))


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
    fecha = request.args.get("fecha", "").strip() or datetime.now().strftime("%Y-%m-%d")
    medio_pago = request.args.get("medio_pago", "").strip()

    condiciones = ["fecha = ?"]
    parametros = [fecha]
    if medio_pago:
        condiciones.append("metodo_pago = ?")
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
        f"SELECT COUNT(DISTINCT COALESCE(id_operacion, 'v' || id)) AS c FROM ventas WHERE {where}",
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
    hoy = datetime.now().strftime("%Y-%m-%d")
    return conn.execute(
        """SELECT * FROM promociones_aplicadas
           WHERE cliente_id=? AND fecha_inicio<=? AND (fecha_fin IS NULL OR fecha_fin>=?)""",
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
                "SELECT producto_id FROM promocion_productos WHERE promocion_id=?", (promo["id"],)
            ):
                productos_con_promo_puntual.setdefault(f["producto_id"], []).append(promo)

    nuevos = []
    for producto_id, cant, precio_unitario, subtotal in items:
        aplicables = [p for p in promos if p["alcance"] == "todo"] + productos_con_promo_puntual.get(producto_id, [])
        porcentaje = max([p["porcentaje_o_monto"] for p in aplicables if p["tipo"] == "porcentaje"], default=0)
        precio_final = round(precio_unitario * (1 - porcentaje / 100), 2) if porcentaje else precio_unitario
        nuevos.append((producto_id, cant, precio_final, round(cant * precio_final, 2)))

    monto_fijo = max(
        [p["porcentaje_o_monto"] for p in promos if p["tipo"] == "monto_fijo" and p["alcance"] == "todo"], default=0
    )
    total_previo = sum(it[3] for it in nuevos)
    if monto_fijo and total_previo > 0:
        factor = max(0, total_previo - monto_fijo) / total_previo
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
    pedido); tarjeta, transferencia o Mercado Pago -> Factura C electrónica
    automática por ARCA.

    `id_operacion` es opcional: dos ventas registradas con el mismo valor se
    cuentan como una sola operación en /ventas/dia (pago mixto).

    Devuelve (venta_id, tipo_comprobante_final).
    """
    items = aplicar_promociones(conn, cliente_id, items)

    total = sum(it[3] for it in items)
    if metodo_pago in ("Tarjeta", "Transferencia", "Mercado Pago"):
        tipo_comprobante = "Factura C"
    else:
        tipo_comprobante = tipo_comprobante_solicitado

    ultimo = conn.execute("SELECT COUNT(*) AS c FROM ventas").fetchone()["c"]
    numero_comprobante = f"{1000 + ultimo + 1:06d}"

    cur = conn.cursor()
    cur.execute(
        """INSERT INTO ventas (fecha, cliente_id, total, metodo_pago, tipo_comprobante, numero_comprobante, id_operacion)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (datetime.now().strftime("%Y-%m-%d"), cliente_id, total, metodo_pago, tipo_comprobante, numero_comprobante, id_operacion),
    )
    venta_id = cur.lastrowid
    for producto_id, cant, precio_unitario, subtotal in items:
        cur.execute(
            "INSERT INTO venta_items (venta_id, producto_id, cantidad, precio_unitario, subtotal) VALUES (?, ?, ?, ?, ?)",
            (venta_id, producto_id, cant, precio_unitario, subtotal),
        )
        cur.execute("UPDATE productos SET stock_actual = stock_actual - ? WHERE id = ?", (cant, producto_id))
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
            producto = conn.execute("SELECT * FROM productos WHERE id=?", (pid,)).fetchone()
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

        if tipo_comprobante == "Factura C":
            # Nunca bloquea ni revierte la venta si falla: el remito/factura
            # se puede reintentar después desde el comprobante.
            facturacion_afip.emitir_factura_c(venta_id)

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
        "INSERT INTO clientes (nombre, telefono, email, direccion, cuit_dni, fecha_alta) VALUES (?, ?, ?, ?, ?, ?)",
        (
            nombre,
            request.form.get("telefono", "").strip(),
            request.form.get("email", "").strip(),
            request.form.get("direccion", "").strip(),
            request.form.get("cuit_dni", "").strip(),
            datetime.now().strftime("%Y-%m-%d"),
        ),
    )
    cliente_id = cur.lastrowid
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
    precio_costo = float(request.form.get("precio_costo") or 0)
    precio_venta = float(request.form.get("precio_venta") or 0)
    stock_minimo = int(request.form.get("stock_minimo") or 2)
    proveedor_id = request.form.get("proveedor_id") or None

    conn = db.get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO productos
               (codigo, nombre, categoria, subcategoria, marca, precio_costo, precio_venta,
                stock_actual, stock_minimo, proveedor_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (codigo, nombre, categoria, subcategoria, marca, precio_costo, precio_venta, stock_minimo, proveedor_id),
        )
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"ok": False, "error": f"Ya existe un producto con el código '{codigo}'."}), 400
    producto_id = cur.lastrowid
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

    Lo usa la pantalla de ventas cuando se escanea con la pistola lectora.
    """
    codigo = request.args.get("codigo", "").strip()
    if not codigo:
        return jsonify({"encontrado": False})
    conn = db.get_connection()
    producto = conn.execute(
        "SELECT * FROM productos WHERE codigo_barras = ? OR codigo = ?", (codigo, codigo)
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
    })


def _obtener_venta_y_items(conn, venta_id):
    venta = conn.execute(
        """SELECT v.*, c.nombre AS cliente_nombre, c.telefono AS cliente_telefono,
                  c.direccion AS cliente_direccion, c.cuit_dni AS cliente_cuit, c.email AS cliente_email
           FROM ventas v LEFT JOIN clientes c ON c.id = v.cliente_id WHERE v.id=?""",
        (venta_id,),
    ).fetchone()
    items = conn.execute(
        """SELECT vi.*, p.nombre AS producto_nombre, p.codigo AS producto_codigo
           FROM venta_items vi JOIN productos p ON p.id = vi.producto_id WHERE vi.venta_id=?""",
        (venta_id,),
    ).fetchall()
    return venta, items


@app.route("/ventas/<int:venta_id>/comprobante")
def ventas_comprobante(venta_id):
    conn = db.get_connection()
    venta, items = _obtener_venta_y_items(conn, venta_id)
    conn.close()
    qr_url = facturacion_afip.url_qr_venta(venta) if venta and venta["tipo_comprobante"] == "Factura C" else None
    return render_template("comprobante.html", venta=venta, items=items, qr_url=qr_url)


@app.route("/ventas/<int:venta_id>/enviar-mail", methods=["POST"])
def ventas_enviar_mail(venta_id):
    conn = db.get_connection()
    venta, items = _obtener_venta_y_items(conn, venta_id)
    conn.close()
    if not venta:
        flash("No encontré esa venta.", "danger")
        return redirect(url_for("ventas_lista"))

    qr_url = facturacion_afip.url_qr_venta(venta) if venta["tipo_comprobante"] == "Factura C" else None
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
    """Reintento manual de la Factura C (por ejemplo si ARCA no respondió antes)."""
    conn = db.get_connection()
    venta = conn.execute("SELECT * FROM ventas WHERE id=?", (venta_id,)).fetchone()
    conn.close()
    if not venta:
        flash("No encontré esa venta.", "danger")
        return redirect(url_for("ventas_lista"))

    facturacion_afip.emitir_factura_c(venta_id)

    conn = db.get_connection()
    estado = conn.execute("SELECT facturacion_estado, facturacion_error FROM ventas WHERE id=?", (venta_id,)).fetchone()
    conn.close()
    if estado["facturacion_estado"] == "emitida":
        flash("Factura C emitida correctamente.", "success")
    elif estado["facturacion_estado"] == "sin_configurar":
        flash("Todavía no está configurado el acceso a Afip SDK (AFIPSDK_ACCESS_TOKEN). Ver README.md.", "warning")
    else:
        flash("No se pudo emitir la Factura C: %s" % (estado["facturacion_error"] or "error desconocido"), "danger")
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
                "INSERT INTO proveedores (nombre, telefono, email, direccion, cuit) VALUES (?, ?, ?, ?, ?)",
                (
                    nombre_nuevo,
                    request.form.get("proveedor_nuevo_telefono", "").strip() or None,
                    request.form.get("proveedor_nuevo_email", "").strip() or None,
                    request.form.get("proveedor_nuevo_direccion", "").strip() or None,
                    request.form.get("proveedor_nuevo_cuit", "").strip() or None,
                ),
            )
            proveedor_id = cur.lastrowid
            flash(f"Se creó el proveedor '{nombre_nuevo}'.", "success")

        producto_ids = request.form.getlist("producto_id")
        cantidades = request.form.getlist("cantidad")
        precios = request.form.getlist("precio_unitario")

        items = []
        total = 0
        for pid, cant, precio in zip(producto_ids, cantidades, precios):
            if not pid or not cant:
                continue
            cant = int(cant)
            precio = float(precio or 0)
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
            "INSERT INTO compras (fecha, proveedor_id, total, numero_factura_proveedor) VALUES (?, ?, ?, ?)",
            (datetime.now().strftime("%Y-%m-%d"), proveedor_id, total, numero_factura),
        )
        compra_id = cur.lastrowid
        for producto_id, cant, precio_unitario, subtotal in items:
            cur.execute(
                "INSERT INTO compra_items (compra_id, producto_id, cantidad, precio_unitario, subtotal) VALUES (?, ?, ?, ?, ?)",
                (compra_id, producto_id, cant, precio_unitario, subtotal),
            )
            # la compra repone stock, actualiza el costo del producto y
            # limpia la marca de "pedido pendiente" si tenía (ya llegó)
            cur.execute(
                """UPDATE productos SET stock_actual = stock_actual + ?, precio_costo = ?,
                   pedido_pendiente = 0, fecha_pedido_pendiente = NULL WHERE id = ?""",
                (cant, precio_unitario, producto_id),
            )
        conn.commit()
        conn.close()
        flash("Compra registrada y stock actualizado.", "success")
        return redirect(url_for("compras_lista"))

    proveedores = conn.execute("SELECT * FROM proveedores WHERE activo=1 ORDER BY nombre").fetchall()
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
        proveedores = conn.execute("SELECT * FROM proveedores WHERE activo=1 ORDER BY nombre").fetchall()
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

    proveedores = conn.execute("SELECT * FROM proveedores WHERE activo=1 ORDER BY nombre").fetchall()
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
           WHERE stock_actual <= stock_minimo AND stock_minimo > 0 AND pedido_pendiente = 0
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
                    "SELECT nombre, email, telefono FROM proveedores WHERE id=? AND activo=1", (f["proveedor_id"],)
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
        """SELECT * FROM productos WHERE pedido_pendiente = 1 ORDER BY fecha_pedido_pendiente DESC, nombre"""
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
    hoy = datetime.now().strftime("%Y-%m-%d")
    conn.executemany(
        "UPDATE productos SET pedido_pendiente=1, fecha_pedido_pendiente=? WHERE id=?",
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
        "UPDATE productos SET pedido_pendiente=0, fecha_pedido_pendiente=NULL WHERE id=?", (producto_id,)
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
        producto_id = request.form.get("producto_id")
        try:
            cantidad = int(request.form.get("cantidad") or 0)
        except ValueError:
            cantidad = 0
        try:
            precio = float(request.form.get("precio") or 0)
        except ValueError:
            precio = 0
        contraparte = request.form.get("contraparte", "").strip() or None
        observaciones = request.form.get("observaciones", "").strip() or None

        producto = conn.execute("SELECT * FROM productos WHERE id=?", (producto_id,)).fetchone() if producto_id else None
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
               VALUES (?, ?, ?, ?, ?, ?)""",
            (tipo, producto["id"], cantidad, precio, contraparte, observaciones),
        )
        delta = cantidad if tipo == "compra" else -cantidad
        conn.execute("UPDATE productos SET stock_actual = stock_actual + ? WHERE id=?", (delta, producto["id"]))
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
    conn.execute("UPDATE movimientos_no_facturados SET conciliado=1 WHERE id=?", (movimiento_id,))
    conn.commit()
    conn.close()
    flash("Movimiento marcado como conciliado.", "success")
    return redirect(url_for("stock_no_facturado"))


@app.route("/stock/no-facturado/<int:movimiento_id>/desconciliar", methods=["POST"])
def stock_no_facturado_desconciliar(movimiento_id):
    conn = db.get_connection()
    conn.execute("UPDATE movimientos_no_facturados SET conciliado=0 WHERE id=?", (movimiento_id,))
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
        nombre = request.form.get("nombre", "").strip()
        rol = request.form.get("rol", "empleado")
        conn = db.get_connection()
        existente = conn.execute("SELECT id FROM usuarios WHERE username=?", (username,)).fetchone()
        if existente:
            flash(f"Ya existe un usuario con el nombre de usuario '{username}'.", "danger")
            conn.close()
            return redirect(url_for("usuarios_nuevo"))

        password_temporal = db._generar_password_temporal()
        conn.execute(
            """INSERT INTO usuarios (username, password_hash, nombre, rol, activo, debe_cambiar_password, fecha_creacion)
               VALUES (?, ?, ?, ?, 1, 1, ?)""",
            (username, generate_password_hash(password_temporal), nombre, rol, datetime.now().strftime("%Y-%m-%d")),
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


@app.route("/usuarios/<int:usuario_id>/editar", methods=["GET", "POST"])
def usuarios_editar(usuario_id):
    if not es_admin():
        flash("Solo un administrador puede hacer esto.", "danger")
        return redirect(url_for("dashboard"))
    conn = db.get_connection()
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        rol = request.form.get("rol", "empleado")
        activo = 1 if request.form.get("activo") else 0
        conn.execute(
            "UPDATE usuarios SET nombre=?, rol=?, activo=? WHERE id=?",
            (nombre, rol, activo, usuario_id),
        )
        conn.commit()
        conn.close()
        flash("Usuario actualizado.", "success")
        return redirect(url_for("usuarios_lista"))
    usuario = conn.execute("SELECT * FROM usuarios WHERE id=?", (usuario_id,)).fetchone()
    conn.close()
    return render_template("usuario_form.html", usuario=usuario)


@app.route("/usuarios/<int:usuario_id>/resetear-password", methods=["POST"])
def usuarios_resetear_password(usuario_id):
    if not es_admin():
        flash("Solo un administrador puede hacer esto.", "danger")
        return redirect(url_for("dashboard"))
    conn = db.get_connection()
    password_temporal = db._generar_password_temporal()
    conn.execute(
        "UPDATE usuarios SET password_hash=?, debe_cambiar_password=1, intentos_fallidos=0, bloqueado_hasta=NULL WHERE id=?",
        (generate_password_hash(password_temporal), usuario_id),
    )
    conn.commit()
    conn.close()
    flash(
        f"Nueva contraseña temporal: {password_temporal} (anotala ahora, no se vuelve a mostrar).",
        "success",
    )
    return redirect(url_for("usuarios_lista"))


@app.route("/usuarios/<int:usuario_id>/eliminar", methods=["POST"])
def usuarios_eliminar(usuario_id):
    if not es_admin():
        flash("Solo un administrador puede hacer esto.", "danger")
        return redirect(url_for("dashboard"))
    if usuario_id == session.get("usuario_id"):
        flash("No podés eliminar tu propio usuario mientras estás conectado con él.", "danger")
        return redirect(url_for("usuarios_lista"))
    conn = db.get_connection()
    conn.execute("DELETE FROM usuarios WHERE id=?", (usuario_id,))
    conn.commit()
    conn.close()
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
        producto = conn.execute("SELECT * FROM productos WHERE id=?", (int(producto_id_str),)).fetchone()
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
        condiciones.append("(nombre LIKE ? OR marca LIKE ? OR modelo_compatible LIKE ?)")
        parametros += [like, like, like]
    if categoria:
        condiciones.append("categoria = ?")
        parametros.append(categoria)
    if marca:
        condiciones.append("marca = ?")
        parametros.append(marca)
    if modelo:
        condiciones.append("modelo_compatible = ?")
        parametros.append(modelo)
    if precio_min:
        try:
            condiciones.append("precio_venta >= ?")
            parametros.append(float(precio_min))
        except ValueError:
            precio_min = ""
    if precio_max:
        try:
            condiciones.append("precio_venta <= ?")
            parametros.append(float(precio_max))
        except ValueError:
            precio_max = ""

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
    producto_id = request.form.get("producto_id")
    cantidad = int(request.form.get("cantidad", 1) or 1)
    conn = db.get_connection()
    producto = conn.execute("SELECT * FROM productos WHERE id=?", (producto_id,)).fetchone()
    conn.close()
    if not producto or producto["stock_actual"] <= 0:
        flash("Ese producto no está disponible.", "danger")
        return redirect(url_for("tienda_catalogo"))

    carrito = _carrito()
    actual = carrito.get(producto_id, 0)
    carrito[producto_id] = min(actual + cantidad, producto["stock_actual"])
    session.modified = True
    flash(f"Agregado: {producto['nombre']}.", "success")
    return redirect(request.referrer or url_for("tienda_catalogo"))


@app.route("/tienda/carrito/quitar", methods=["POST"])
def tienda_carrito_quitar():
    producto_id = request.form.get("producto_id")
    carrito = _carrito()
    carrito.pop(producto_id, None)
    session.modified = True
    return redirect(url_for("tienda_carrito"))


@app.route("/tienda/carrito/actualizar", methods=["POST"])
def tienda_carrito_actualizar():
    producto_id = request.form.get("producto_id")
    cantidad = int(request.form.get("cantidad", 0) or 0)
    carrito = _carrito()
    if cantidad <= 0:
        carrito.pop(producto_id, None)
    else:
        carrito[producto_id] = cantidad
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
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pendiente_pago')""",
            (datetime.now().strftime("%Y-%m-%d"), nombre, telefono, email, direccion, cuit_dni, total),
        )
        pedido_id = cur.lastrowid
        for it in items:
            cur.execute(
                """INSERT INTO pedido_web_items (pedido_id, producto_id, cantidad, precio_unitario, subtotal)
                   VALUES (?, ?, ?, ?, ?)""",
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
    pedido = conn.execute("SELECT * FROM pedidos_web WHERE id=?", (pedido_id,)).fetchone()
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
    pedido = conn.execute("SELECT * FROM pedidos_web WHERE id=?", (pedido_id,)).fetchone()
    if not pedido:
        conn.close()
        return "", 200

    if pedido["estado"] == "pagado":
        conn.close()  # ya procesado (idempotencia: MP puede reintentar el webhook)
        return "", 200

    estado_pago = pago.get("status")  # approved | pending | rejected | in_process | ...
    if estado_pago != "approved":
        conn.execute(
            "UPDATE pedidos_web SET estado=?, mp_payment_id=? WHERE id=?",
            (estado_pago or pedido["estado"], str(data_id), pedido_id),
        )
        conn.commit()
        conn.close()
        return "", 200

    # pago aprobado: buscamos o creamos el cliente, y generamos la venta real
    items_pedido = conn.execute(
        "SELECT * FROM pedido_web_items WHERE pedido_id=?", (pedido_id,)
    ).fetchall()

    cliente_id = None
    if pedido["email"]:
        cliente = conn.execute("SELECT id FROM clientes WHERE email=?", (pedido["email"],)).fetchone()
        if cliente:
            cliente_id = cliente["id"]
    if not cliente_id and pedido["telefono"]:
        cliente = conn.execute("SELECT id FROM clientes WHERE telefono=?", (pedido["telefono"],)).fetchone()
        if cliente:
            cliente_id = cliente["id"]
    if not cliente_id:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO clientes (nombre, telefono, email, direccion, cuit_dni, fecha_alta) VALUES (?, ?, ?, ?, ?, ?)",
            (
                pedido["nombre_cliente"], pedido["telefono"], pedido["email"], pedido["direccion"],
                pedido["cuit_dni"] or "",
                datetime.now().strftime("%Y-%m-%d"),
            ),
        )
        cliente_id = cur.lastrowid
        conn.commit()

    items = [(it["producto_id"], it["cantidad"], it["precio_unitario"], it["subtotal"]) for it in items_pedido]
    venta_id, tipo_comprobante = registrar_venta(conn, cliente_id, "Mercado Pago", items)

    conn.execute(
        "UPDATE pedidos_web SET estado='pagado', mp_payment_id=?, venta_id=? WHERE id=?",
        (str(data_id), venta_id, pedido_id),
    )
    conn.commit()
    conn.close()

    if tipo_comprobante == "Factura C":
        facturacion_afip.emitir_factura_c(venta_id)

    return "", 200


if __name__ == "__main__":
    # Uso normal: correr `python app.py` desde la raíz (ver el shim ahí).
    # Esto solo se ejecuta si alguien corre core/app.py directamente.
    app.run(debug=True, port=5050)
