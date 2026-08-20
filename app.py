"""
Sistema de Venta y Validacion de Entradas con Codigos QR — Multi-Evento
=======================================================================
Backend: Flask + Supabase (PostgreSQL serverless)
Deploy: Vercel (funcion serverless)

Caracteristicas multi-evento:
  - Un "admin general" gestiona varios eventos desde un solo panel.
  - Cada evento tiene su propio nombre y precio de entrada.
  - Usuarios con roles (vendedor/portero) estan asociados a un evento.
  - Admin global (evento_id = NULL) puede gestionar todos los eventos.
  - Todos los datos (entradas, logs, usuarios) se filtran por evento.
  - Cedula validada en formato costa-ricense: X-XXXX-XXXX (ej. 6-0510-0347)

Acceso: login con usuario + password (hash scrypt). El hash se almacena
en la tabla users. El rol se lee de la base de datos.
"""

import os
import re
import uuid
import io
import csv
from functools import wraps
from flask import (Flask, request, jsonify, render_template,
                   session, redirect, url_for, Response)
from werkzeug.security import check_password_hash, generate_password_hash
from supabase import create_client, Client

# Cargar .env en desarrollo local (Vercel usa env vars configuradas en el dashboard)
try:
    from load_env import cargar_env
    cargar_env()
except ImportError:
    pass

# -----------------------------------------------------------
# Configuracion Supabase
# -----------------------------------------------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://bibdstpwmtfsvbcduvey.supabase.co")

# Service role key: usado server-side (bypasses RLS). Se lee de env
# para no hardcodearlo en el repositorio. El anon key es fallback.
_ANON_KEY = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
             "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJpYmRzdHB3bXRmc3ZiY2R1dmV5Iiw"
             "icm9sZSI6ImFub24iLCJpYXQiOjE3ODcwNzczODUsImV4cCI6MjEwMjY1MzM4NX0."
             "5je41P3CCoHH8XeWSBKH9e9AcCM2JitJd_beHXKLSD8")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", _ANON_KEY)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# -----------------------------------------------------------
# Configuracion Flask
# -----------------------------------------------------------
app = Flask(__name__,
            template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates"))

app.secret_key = os.environ.get("SECRET_KEY", "clave-local-de-desarrollo")

# Nombre por defecto de la pagina (no atado a ningun evento en particular)
NOMBRE_EVENTO_DEFAULT = os.environ.get("NOMBRE_EVENTO", "Sistema de Entradas")

# Tablas
TABLA = "entradas"
TABLA_USERS = "users"
TABLA_LOGS = "logs"
TABLA_EVENTOS = "eventos"

# Regex: cedula costa-ricense X-XXXX-XXXX (ej. 6-0510-0347)
CEDULA_CR = re.compile(r'^\d{1,2}-\d{4}-\d{4}$')


# -----------------------------------------------------------
# Context processor — variables globales en templates
# -----------------------------------------------------------
@app.context_processor
def inject_evento():
    return {
        "nombre_evento": session.get("evento_nombre", NOMBRE_EVENTO_DEFAULT),
        "evento_id": session.get("evento_id"),
        "precio_entrada": session.get("precio_entrada", 0),
        "rol": session.get("rol", ""),
        "usuario": session.get("usuario", ""),
    }


# -----------------------------------------------------------
# Helpers
# -----------------------------------------------------------
def validar_cedula(cedula):
    """Valida formato de cedula costa-ricense: X-XXXX-XXXX"""
    return bool(CEDULA_CR.match(cedula.strip()))


def evento_acts():
    """Devuelve el evento activo de la session, o None si no hay uno seleccionado."""
    eid = session.get("evento_id")
    if eid:
        return {
            "id": eid,
            "nombre": session.get("evento_nombre", ""),
            "precio": session.get("precio_entrada", 0),
        }
    return None


def registrar_log(accion, detalle=""):
    """Inserta una accion en la tabla de logs."""
    try:
        supabase.table(TABLA_LOGS).insert({
            "accion": accion,
            "detalle": detalle[:500],
            "usuario": session.get("usuario", "?"),
            "evento_id": session.get("evento_id"),
        }).execute()
    except Exception:
        pass


def generar_codigo():
    """Genera un codigo alfanumerico unico de 8 caracteres."""
    return uuid.uuid4().hex[:8].upper()


def entrada_duplicada(nombre, cedula, evento_id):
    """
    Devuelve 'nombre', 'cedula' o None si ya existe una entrada con esos
    datos DENTRO DEL MISMO EVENTO.
    """
    def escapar(v):
        return v.replace('%', r'\%').replace('_', r'\_')

    r1 = supabase.table(TABLA).select("id").eq("evento_id", evento_id) \
        .ilike("nombre", escapar(nombre)).limit(1).execute()
    if r1.data:
        return "nombre"
    r2 = supabase.table(TABLA).select("id").eq("evento_id", evento_id) \
        .ilike("cedula", escapar(cedula)).limit(1).execute()
    if r2.data:
        return "cedula"
    return None


# -----------------------------------------------------------
# Control de acceso
# -----------------------------------------------------------
def require_rol(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get("auth"):
                if request.path.startswith("/api"):
                    return jsonify({"ok": False, "error": "No autorizado"}), 401
                return redirect(url_for("login"))
            if session.get("rol") not in roles:
                if request.path.startswith("/api"):
                    return jsonify({"ok": False, "error": "Rol sin permiso"}), 401
                destino = session.get("rol")
                if destino in ("vendedor", "portero", "admin"):
                    return redirect(url_for(destino))
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return wrapper
    return decorator


def require_evento():
    """True si hay un evento activo en session."""
    return session.get("evento_id") is not None


# -----------------------------------------------------------
# Rutas de interfaz (protegidas con login)
# -----------------------------------------------------------
@app.route("/login")
def login():
    return render_template("login.html")


@app.route("/")
@require_rol("vendedor", "portero", "admin")
def index():
    destino = session.get("rol", "vendedor")
    if destino == "admin":
        return redirect(url_for("admin"))
    return redirect(url_for(destino))


@app.route("/vendedor")
@require_rol("vendedor", "admin")
def vendedor():
    ev = evento_acts()
    if not ev and session.get("rol") != "admin":
        return redirect(url_for("login"))
    return render_template("vendedor.html", rol=session.get("rol"))


@app.route("/portero")
@require_rol("portero", "admin")
def portero():
    ev = evento_acts()
    if not ev and session.get("rol") != "admin":
        return redirect(url_for("login"))
    return render_template("portero.html", rol=session.get("rol"))


@app.route("/centro")
@require_rol("vendedor", "portero", "admin")
def centro():
    return render_template("centro.html", rol=session.get("rol"))


@app.route("/admin")
@require_rol("admin")
def admin():
    return render_template("admin.html", rol=session.get("rol"))


# -----------------------------------------------------------
# API: login / logout
# -----------------------------------------------------------
@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True)
    if not data or not data.get("usuario") or not data.get("password"):
        return jsonify({"ok": False, "error": "Usuario y contraseña son requeridos"}), 400

    usuario = data["usuario"].strip().lower()
    try:
        resp = supabase.table(TABLA_USERS).select(
            "usuario,password_hash,rol,nombre,evento_id"
        ).eq("usuario", usuario).execute()
    except Exception:
        return jsonify({"ok": False,
                        "error": "La tabla users no existe — ejecutá schema.sql en Supabase"}), 500

    if not resp.data:
        return jsonify({"ok": False, "error": "Usuario o contraseña incorrectos"}), 401

    user = resp.data[0]
    if not check_password_hash(user["password_hash"], data["password"]):
        return jsonify({"ok": False, "error": "Usuario o contraseña incorrectos"}), 401

    session["auth"] = True
    session["rol"] = user["rol"]
    session["usuario"] = user["usuario"]
    session["nombre"] = user.get("nombre") or ""

    # Set evento context from user record
    if user.get("evento_id"):
        ev = supabase.table(TABLA_EVENTOS).select("id,nombre,precio_entrada") \
            .eq("id", user["evento_id"]).execute()
        if ev.data:
            session["evento_id"] = ev.data[0]["id"]
            session["evento_nombre"] = ev.data[0]["nombre"]
            session["precio_entrada"] = ev.data[0]["precio_entrada"]

    # Admin global: auto-seleccionar evento si solo hay uno activo
    if user["rol"] == "admin" and not session.get("evento_id"):
        evs = supabase.table(TABLA_EVENTOS).select("id,nombre,precio_entrada") \
            .eq("activo", True).order("id").execute()
        if evs.data and len(evs.data) == 1:
            session["evento_id"] = evs.data[0]["id"]
            session["evento_nombre"] = evs.data[0]["nombre"]
            session["precio_entrada"] = evs.data[0]["precio_entrada"]

    registrar_log("login", f"{user.get('nombre', '')} ({user['usuario']}, {user['rol']})")
    return jsonify({"ok": True, "rol": user["rol"], "usuario": user["usuario"],
                    "nombre": user.get("nombre", ""), "evento_id": user.get("evento_id")})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    registrar_log("logout", session.get("usuario", "?"))
    session.clear()
    return jsonify({"ok": True})


# -----------------------------------------------------------
# API: eventos (admin CRUD + selection)
# -----------------------------------------------------------
@app.route("/api/eventos")
@require_rol("admin")
def api_eventos_listar():
    try:
        resp = supabase.table(TABLA_EVENTOS).select(
            "id,nombre,precio_entrada,activo,creado_en"
        ).order("id", desc=True).execute()
        return jsonify({"eventos": resp.data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/eventos", methods=["POST"])
@require_rol("admin")
def api_eventos_crear():
    data = request.get_json(silent=True) or {}
    nombre = (data.get("nombre") or "").strip()[:100]
    try:
        precio = int(data.get("precio", 1000))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Precio inválido"}), 400

    if not nombre:
        return jsonify({"ok": False, "error": "Nombre del evento es requerido"}), 400
    if precio < 0:
        return jsonify({"ok": False, "error": "El precio no puede ser negativo"}), 400

    try:
        supabase.table(TABLA_EVENTOS).insert({
            "nombre": nombre,
            "precio_entrada": precio,
        }).execute()
        registrar_log("evento_crear", f"{nombre} | precio {precio}")
        return jsonify({"ok": True, "nombre": nombre, "precio": precio})
    except Exception:
        return jsonify({"ok": False, "error": "Ya existe un evento con ese nombre"}), 409


@app.route("/api/eventos/<int:evento_id>", methods=["PUT"])
@require_rol("admin")
def api_evento_editar(evento_id):
    data = request.get_json(silent=True) or {}
    cambios = {}

    if "nombre" in data:
        nombre = (data.get("nombre") or "").strip()[:100]
        if not nombre:
            return jsonify({"ok": False, "error": "Nombre no puede estar vacío"}), 400
        cambios["nombre"] = nombre

    if "precio_entrada" in data:
        try:
            precio = int(data["precio_entrada"])
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Precio inválido"}), 400
        if precio < 0:
            return jsonify({"ok": False, "error": "El precio no puede ser negativo"}), 400
        cambios["precio_entrada"] = precio

    if "activo" in data:
        cambios["activo"] = bool(data["activo"])

    if not cambios:
        return jsonify({"ok": False, "error": "Nada que editar"}), 400

    try:
        resp = supabase.table(TABLA_EVENTOS).update(cambios).eq("id", evento_id).execute()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 409

    # Actualizar session si es el evento activo
    if session.get("evento_id") == evento_id:
        if "precio_entrada" in cambios:
            session["precio_entrada"] = cambios["precio_entrada"]
        if "nombre" in cambios:
            session["evento_nombre"] = cambios["nombre"]

    detalle = ", ".join(f"{k}: {v}" for k, v in cambios.items())
    registrar_log("evento_editar", f"id {evento_id} · {detalle}")
    return jsonify({"ok": True, "precio": cambios.get("precio_entrada")})


@app.route("/api/eventos/<int:evento_id>", methods=["DELETE"])
@require_rol("admin")
def api_evento_borrar(evento_id):
    if session.get("evento_id") == evento_id:
        session.pop("evento_id", None)
        session.pop("evento_nombre", None)
        session.pop("precio_entrada", None)

    try:
        resp = supabase.table(TABLA_EVENTOS).select("nombre").eq("id", evento_id).execute()
        if not resp.data:
            return jsonify({"ok": False, "error": "Evento no encontrado"}), 404
        nombre = resp.data[0]["nombre"]
        supabase.table(TABLA_EVENTOS).delete().eq("id", evento_id).execute()
        registrar_log("evento_borrar", f"{nombre} (id {evento_id})")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/evento/select", methods=["POST"])
@require_rol("admin")
def api_evento_select():
    data = request.get_json(silent=True) or {}
    evento_id = data.get("evento_id")
    if not evento_id:
        return jsonify({"ok": False, "error": "evento_id requerido"}), 400

    resp = supabase.table(TABLA_EVENTOS).select("id,nombre,precio_entrada,activo") \
        .eq("id", evento_id).execute()
    if not resp.data:
        return jsonify({"ok": False, "error": "Evento no encontrado"}), 404

    session["evento_id"] = int(evento_id)
    session["evento_nombre"] = resp.data[0]["nombre"]
    session["precio_entrada"] = resp.data[0]["precio_entrada"]
    registrar_log("evento_seleccionar", f"{resp.data[0]['nombre']}")
    return jsonify({"ok": True, "evento": resp.data[0]})


@app.route("/api/evento/actual")
@require_rol("admin")
def api_evento_actual():
    return jsonify({
        "evento_id": session.get("evento_id"),
        "evento_nombre": session.get("evento_nombre"),
        "precio_entrada": session.get("precio_entrada", 0),
    })


# -----------------------------------------------------------
# API: generar entrada
# -----------------------------------------------------------
@app.route("/api/generar", methods=["POST"])
@require_rol("vendedor", "admin")
def api_generar():
    evento_id = session.get("evento_id")
    if not evento_id:
        return jsonify({"ok": False, "error": "Seleccioná un evento"}), 400

    data = request.get_json(silent=True) or {}
    nombre = (data.get("nombre") or "").strip()[:80]
    cedula = (data.get("cedula") or "").strip()[:30]

    if not nombre or not cedula:
        return jsonify({"ok": False, "error": "Nombre y cédula son requeridos"}), 400

    if not validar_cedula(cedula):
        return jsonify({"ok": False,
                        "error": "Formato de cédula inválido. Usá: X-XXXX-XXXX (ej. 6-0510-0347)"}), 400

    dup = entrada_duplicada(nombre, cedula, evento_id)
    if dup:
        campo = "nombre" if dup == "nombre" else "cédula"
        return jsonify({"ok": False, "error": f"Ya existe una entrada con ese {campo}"}), 409

    precio = session.get("precio_entrada", 0)
    for _ in range(5):
        codigo = generar_codigo()
        try:
            resp = supabase.table(TABLA).insert({
                "codigo": codigo,
                "usado": False,
                "nombre": nombre,
                "cedula": cedula,
                "evento_id": evento_id,
                "precio": precio,
            }).execute()
            if resp.data:
                registrar_log("venta", f"{nombre} | cédula {cedula} | código {codigo}")
                return jsonify({"ok": True, "codigo": codigo, "id": resp.data[0]["id"],
                                "nombre": nombre, "cedula": cedula, "precio": precio}), 201
        except Exception:
            continue

    return jsonify({"ok": False, "error": "No se pudo generar código"}), 500


# -----------------------------------------------------------
# API: validar entrada
# -----------------------------------------------------------
@app.route("/api/validar", methods=["POST"])
@require_rol("portero", "admin")
def api_validar():
    evento_id = session.get("evento_id")
    if not evento_id:
        return jsonify({"ok": False, "error": "Seleccioná un evento"}), 400

    data = request.get_json(silent=True)
    if not data or not data.get("code"):
        return jsonify({"ok": False, "error": "Código requerido"}), 400

    codigo = data["code"].strip().upper()
    origen = "cámara" if data.get("origen") == "camara" else "manual"

    try:
        resp = supabase.table(TABLA).select("usado,nombre,cedula") \
            .eq("evento_id", evento_id).eq("codigo", codigo).execute()
    except Exception as e:
        return jsonify({"ok": False, "error": f"Error de base de datos: {e}"}), 500

    if not resp.data:
        registrar_log("escaneo", f"{codigo} — {origen} | código no encontrado")
        return jsonify({"ok": False, "estado": "inexistente",
                        "error": "Código no encontrado"}), 404

    if resp.data[0]["usado"]:
        registrar_log("escaneo", f"{codigo} — {origen} | ya usado ({resp.data[0].get('nombre', '')})")
        return jsonify({"ok": False, "estado": "usado",
                        "error": "Código ya fue utilizado"}), 409

    supabase.table(TABLA).update({"usado": True}) \
        .eq("evento_id", evento_id).eq("codigo", codigo).execute()
    registrar_log("escaneo", f"{codigo} — {origen} | válido, {resp.data[0].get('nombre', '')}")

    return jsonify({"ok": True, "estado": "valido", "codigo": codigo,
                    "nombre": resp.data[0].get("nombre", ""),
                    "cedula": resp.data[0].get("cedula", "")}), 200


# -----------------------------------------------------------
# API: contador de entradas generadas
# -----------------------------------------------------------
@app.route("/api/contador")
@require_rol("vendedor", "portero", "admin")
def api_contador():
    evento_id = session.get("evento_id")
    if not evento_id:
        return jsonify({"total": 0})
    try:
        resp = supabase.table(TABLA).select("id", count="exact") \
            .eq("evento_id", evento_id).execute()
        return jsonify({"total": resp.count})
    except Exception:
        return jsonify({"total": 0})


# -----------------------------------------------------------
# API: centro de datos (stats)
# -----------------------------------------------------------
@app.route("/api/stats")
@require_rol("vendedor", "portero", "admin")
def api_stats():
    evento_id = session.get("evento_id")
    precio = session.get("precio_entrada", 0)

    if not evento_id:
        return jsonify({"total": 0, "usadas": 0, "pendientes": 0,
                        "precio": precio, "recaudado_total": 0,
                        "recaudado_usadas": 0, "recaudado_pendientes": 0})

    try:
        ev = supabase.table(TABLA_EVENTOS).select("nombre,precio_entrada") \
            .eq("id", evento_id).execute()
        if ev.data:
            precio = ev.data[0]["precio_entrada"]
            session["precio_entrada"] = precio

        total = supabase.table(TABLA).select("id", count="exact") \
            .eq("evento_id", evento_id).execute().count
        usadas = supabase.table(TABLA).select("id", count="exact") \
            .eq("evento_id", evento_id).eq("usado", True).execute().count
        pendientes = total - usadas

        return jsonify({
            "total": total, "usadas": usadas, "pendientes": pendientes,
            "precio": precio,
            "recaudado_total": total * precio,
            "recaudado_usadas": usadas * precio,
            "recaudado_pendientes": pendientes * precio,
        })
    except Exception:
        return jsonify({"total": 0, "usadas": 0, "pendientes": 0,
                        "precio": precio, "recaudado_total": 0,
                        "recaudado_usadas": 0, "recaudado_pendientes": 0})


@app.route("/api/listar")
@require_rol("vendedor", "portero", "admin")
def api_listar():
    evento_id = session.get("evento_id")
    if not evento_id:
        return jsonify({"entradas": []})
    try:
        resp = supabase.table(TABLA).select(
            "id,codigo,usado,creado_en,nombre,cedula,precio"
        ).eq("evento_id", evento_id).order("id", desc=True).limit(500).execute()
        return jsonify({"entradas": resp.data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/reset", methods=["POST"])
@require_rol("vendedor", "portero", "admin")
def api_reset():
    evento_id = session.get("evento_id")
    if not evento_id:
        return jsonify({"ok": False, "error": "Seleccioná un evento"}), 400

    data = request.get_json(silent=True)
    if not data or not (data.get("code") or data.get("codigo")):
        return jsonify({"ok": False, "error": "Código requerido"}), 400

    codigo = (data.get("code") or data.get("codigo")).strip().upper()
    resp = supabase.table(TABLA).update({"usado": False}) \
        .eq("evento_id", evento_id).eq("codigo", codigo).execute()

    if not resp.data:
        return jsonify({"ok": False, "error": "Código no encontrado"}), 404

    registrar_log("revertir_escaneo", f"código {codigo} marcado como no usado")
    return jsonify({"ok": True, "codigo": codigo})


@app.route("/api/borrar_todas", methods=["POST"])
@require_rol("vendedor", "portero", "admin")
def api_borrar_todas():
    evento_id = session.get("evento_id")
    if not evento_id:
        return jsonify({"ok": False, "error": "Seleccioná un evento"}), 400

    try:
        antes = supabase.table(TABLA).select("id", count="exact") \
            .eq("evento_id", evento_id).execute().count
        supabase.rpc("reset_entradas", {"p_evento_id": int(evento_id)}).execute()
        registrar_log("borrado_total", f"{antes} entradas eliminadas del evento")
        return jsonify({"ok": True, "mensaje": "Entradas eliminadas"})
    except Exception as e:
        return jsonify({"ok": False,
                        "error": "La funcion reset_entradas no existe en Supabase"}), 500


@app.route("/api/exportar")
@require_rol("vendedor", "portero", "admin")
def api_exportar():
    evento_id = session.get("evento_id")
    if not evento_id:
        return jsonify({"ok": False, "error": "Seleccioná un evento"}), 400

    try:
        resp = supabase.table(TABLA).select(
            "id,codigo,usado,creado_en,nombre,cedula,precio"
        ).eq("evento_id", evento_id).order("id").execute()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    registrar_log("exportar_csv", f"{len(resp.data)} entradas exportadas")

    total = len(resp.data)
    usadas = sum(1 for r in resp.data if r["usado"])
    pendientes = total - usadas
    precio = session.get("precio_entrada", 0)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["RESUMEN"])
    writer.writerow(["evento", session.get("evento_nombre", "")])
    writer.writerow(["precio_entrada", precio])
    writer.writerow(["total_generadas", total])
    writer.writerow(["total_usadas", usadas])
    writer.writerow(["total_pendientes", pendientes])
    writer.writerow(["recaudado_total", total * precio])
    writer.writerow(["recaudado_usadas", usadas * precio])
    writer.writerow(["recaudado_pendientes", pendientes * precio])
    writer.writerow([])
    writer.writerow(["id", "codigo", "nombre", "cedula", "usado", "precio", "creado_en"])
    for row in resp.data:
        writer.writerow([row["id"], row["codigo"], row.get("nombre", ""),
                         row.get("cedula", ""), row["usado"],
                         row.get("precio", precio), row["creado_en"]])

    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=entradas.csv"
    return response


# -----------------------------------------------------------
# API: admin — eventos, logs y usuarios
# -----------------------------------------------------------
@app.route("/api/logs")
@require_rol("admin")
def api_logs():
    evento_id = session.get("evento_id")
    try:
        query = supabase.table(TABLA_LOGS).select(
            "id,accion,detalle,usuario,creado_en"
        )
        if evento_id:
            query = query.or_(f"evento_id.eq.{evento_id},evento_id.is.null")
        resp = query.order("id", desc=True).limit(300).execute()
        return jsonify({"logs": resp.data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/users")
@require_rol("admin")
def api_users_listar():
    evento_id = session.get("evento_id")
    try:
        query = supabase.table(TABLA_USERS).select(
            "id,usuario,rol,nombre,evento_id"
        )
        if evento_id:
            query = query.or_(f"evento_id.eq.{evento_id},evento_id.is.null")
        resp = query.order("id").execute()
        return jsonify({"users": resp.data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/users", methods=["POST"])
@require_rol("admin")
def api_users_crear():
    evento_id = session.get("evento_id")
    data = request.get_json(silent=True) or {}
    usuario = (data.get("usuario") or "").strip().lower()
    password = data.get("password") or ""
    rol = data.get("rol") or ""
    nombre = (data.get("nombre") or "").strip()[:60]

    if not usuario or not password or rol not in ("vendedor", "portero", "admin"):
        return jsonify({"ok": False, "error": "usuario, password y rol son requeridos"}), 400

    # Admin global: evento_id = NULL. Vendedor/portero: requiere evento.
    user_evento_id = None if rol == "admin" else evento_id
    if rol != "admin" and not evento_id:
        return jsonify({"ok": False, "error": "Seleccioná un evento para este usuario"}), 400

    # Check duplicate (login busca por usuario globalmente, así que debe ser único global)
    existe = supabase.table(TABLA_USERS).select("id") \
        .eq("usuario", usuario).execute()
    if existe.data:
        return jsonify({"ok": False, "error": "Ese usuario ya existe"}), 409

    supabase.table(TABLA_USERS).insert({
        "usuario": usuario,
        "password_hash": generate_password_hash(password),
        "rol": rol,
        "nombre": nombre,
        "evento_id": user_evento_id,
    }).execute()
    registrar_log("user_crear", f"{nombre} ({usuario}, {rol})")
    return jsonify({"ok": True})


@app.route("/api/users/<int:user_id>", methods=["PUT"])
@require_rol("admin")
def api_users_editar(user_id):
    evento_id = session.get("evento_id")
    data = request.get_json(silent=True) or {}
    cambios = {}

    if "usuario" in data:
        nuevo_usuario = (data.get("usuario") or "").strip().lower()
        if not nuevo_usuario:
            return jsonify({"ok": False, "error": "El usuario no puede estar vacío"}), 400
        existe = supabase.table(TABLA_USERS).select("id") \
            .eq("usuario", nuevo_usuario).execute()
        if existe.data and existe.data[0]["id"] != user_id:
            return jsonify({"ok": False, "error": "Ese usuario ya existe"}), 409
        cambios["usuario"] = nuevo_usuario

    if "nombre" in data:
        cambios["nombre"] = (data.get("nombre") or "").strip()[:60]

    if "rol" in data:
        if data["rol"] not in ("vendedor", "portero", "admin"):
            return jsonify({"ok": False, "error": "Rol inválido"}), 400
        cambios["rol"] = data["rol"]

    if "evento_id" in data:
        cambios["evento_id"] = data["evento_id"] if data["evento_id"] else None

    if data.get("password"):
        cambios["password_hash"] = generate_password_hash(data["password"])

    if not cambios:
        return jsonify({"ok": False, "error": "Nada que editar"}), 400

    prev = supabase.table(TABLA_USERS).select("usuario,nombre,rol,evento_id") \
        .eq("id", user_id).execute()
    if not prev.data:
        return jsonify({"ok": False, "error": "Usuario no encontrado"}), 404

    resp = supabase.table(TABLA_USERS).update(cambios).eq("id", user_id).execute()
    if not resp.data:
        return jsonify({"ok": False, "error": "Usuario no encontrado"}), 404

    # Actualizar session si se edita el propio usuario
    if resp.data[0]["usuario"] == session.get("usuario"):
        session["usuario"] = cambios.get("usuario", resp.data[0]["usuario"])
        if "rol" in cambios:
            session["rol"] = cambios["rol"]

    antes = prev.data[0]
    textos = []
    if "usuario" in cambios:
        textos.append(f"usuario {antes['usuario']} → {cambios['usuario']}")
    if "nombre" in cambios:
        textos.append(f"nombre {antes.get('nombre', '') or '—'} → {cambios['nombre'] or '—'}")
    if "rol" in cambios:
        textos.append(f"rol {antes['rol']} → {cambios['rol']}")
    if "evento_id" in cambios:
        e_nuevo = cambios['evento_id'] or 'NULL'
        e_viejo = antes.get('evento_id') or 'NULL'
        textos.append(f"evento {e_viejo} → {e_nuevo}")
    if "password_hash" in cambios:
        textos.append("contraseña actualizada")
    registrar_log("user_editar", f"id {user_id} · {', '.join(textos)}")
    return jsonify({"ok": True})


@app.route("/api/users/<int:user_id>", methods=["DELETE"])
@require_rol("admin")
def api_users_borrar(user_id):
    prev = supabase.table(TABLA_USERS).select("usuario,nombre,rol").eq("id", user_id).execute()
    if not prev.data:
        return jsonify({"ok": False, "error": "Usuario no encontrado"}), 404

    if prev.data[0]["usuario"] == session.get("usuario"):
        return jsonify({"ok": False, "error": "No podés borrar tu propio usuario"}), 400

    supabase.table(TABLA_USERS).delete().eq("id", user_id).execute()
    u = prev.data[0]
    registrar_log("user_borrar", f"{u.get('nombre', '')} ({u['usuario']}, {u['rol']})")
    return jsonify({"ok": True})


# -----------------------------------------------------------
# Entry point
# -----------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
