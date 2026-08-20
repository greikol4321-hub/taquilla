"""
Sistema de Venta y Validacion de Entradas con Codigos QR — Multi-Evento
=======================================================================
Backend: Flask + Supabase (PostgreSQL serverless)
Deploy: Vercel (funcion serverless)

Modelo de usuarios:
  - La tabla users es GLOBAL: rol 'admin' (administra todo) o NULL (staff).
  - El staff se asigna a eventos via evento_usuarios (evento_id, usuario_id, rol).
    Un usuario puede estar en varios eventos con roles distintos.
  - Al iniciar sesion:
      * admin -> va directo al panel de administracion (dashboard global).
      * staff con 1 evento activo -> entra directo a vendedor/portero.
      * staff con varios eventos -> elige evento en /elegir.
  - El admin NO opera: no vende ni valida, solo administra.
  - Todos los datos (entradas, logs) se filtran por el evento activo en sesion.
  - Cedula validada en formato costa-ricense: X-XXXX-XXXX (ej. 6-0510-0347)
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
TABLA_ASIGNACIONES = "evento_usuarios"

# Regex: cedula costa-ricense X-XXXX-XXXX (ej. 6-0510-0347)
CEDULA_CR = re.compile(r'^\d{1,2}-\d{4}-\d{4}$')


# -----------------------------------------------------------
# Context processor — variables globales en templates
# -----------------------------------------------------------
@app.context_processor
def inject_evento():
    es_admin = session.get("rol") == "admin"
    return {
        "nombre_evento": ("Panel de administración" if es_admin
                          else session.get("evento_nombre", NOMBRE_EVENTO_DEFAULT)),
        "evento_id": session.get("evento_id"),
        "precio_entrada": session.get("precio_entrada", 0),
        "rol": session.get("rol", ""),
        "usuario": session.get("usuario", ""),
        "multi_evento": session.get("multi_evento", False),
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


def asignaciones_usuario(usuario_id):
    """Devuelve las asignaciones activas de un usuario: [{evento_id, nombre, precio, rol}]."""
    resp = supabase.table(TABLA_ASIGNACIONES) \
        .select("evento_id, rol, eventos(nombre, precio_entrada, activo)") \
        .eq("usuario_id", usuario_id).execute()
    eventos = []
    for a in resp.data or []:
        ev = a.get("eventos") or {}
        if ev.get("activo", True):
            eventos.append({
                "evento_id": a["evento_id"],
                "nombre": ev.get("nombre", ""),
                "precio_entrada": ev.get("precio_entrada", 0),
                "rol": a["rol"],
            })
    return sorted(eventos, key=lambda e: e["evento_id"])


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
            if session.get("rol") not in roles and \
                    not (session.get("multi_evento") and "elegir" in roles):
                if request.path.startswith("/api"):
                    return jsonify({"ok": False, "error": "Rol sin permiso"}), 401
                destino = session.get("rol")
                if destino in ("vendedor", "portero", "admin"):
                    return redirect(url_for(destino))
                if destino == "elegir":
                    return redirect(url_for("elegir"))
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
@require_rol("vendedor", "portero", "admin", "elegir")
def index():
    destino = session.get("rol", "vendedor")
    if destino == "admin":
        return redirect(url_for("admin"))
    if destino == "elegir":
        return redirect(url_for("elegir"))
    return redirect(url_for(destino))


@app.route("/elegir")
@require_rol("elegir")
def elegir():
    return render_template("elegir.html")


@app.route("/vendedor")
@require_rol("vendedor")
def vendedor():
    if not require_evento():
        return redirect(url_for("elegir"))
    return render_template("vendedor.html", rol=session.get("rol"))


@app.route("/portero")
@require_rol("portero")
def portero():
    if not require_evento():
        return redirect(url_for("elegir"))
    return render_template("portero.html", rol=session.get("rol"))


@app.route("/centro")
@require_rol("vendedor", "portero")
def centro():
    if not require_evento():
        return redirect(url_for("elegir"))
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
            "id,usuario,password_hash,rol,nombre"
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
    session["usuario"] = user["usuario"]
    session["nombre"] = user.get("nombre") or ""
    session["multi_evento"] = False

    # Admin global: entra directo, no opera sobre eventos
    if user["rol"] == "admin":
        session["rol"] = "admin"
        session["evento_id"] = None
        session["evento_nombre"] = None
        session["precio_entrada"] = 0
        destino = "admin"
        registrar_log("login", f"{user.get('nombre', '')} ({user['usuario']}, admin)")
        return jsonify({"ok": True, "rol": "admin", "destino": "/admin",
                        "usuario": user["usuario"], "nombre": user.get("nombre", "")})

    # Staff: buscar asignaciones en eventos activos
    asignaciones = asignaciones_usuario(user["id"])
    if not asignaciones:
        return jsonify({"ok": False,
                        "error": "Este usuario no está asignado a ningún evento activo"}), 401

    if len(asignaciones) == 1:
        a = asignaciones[0]
        session["rol"] = a["rol"]
        session["evento_id"] = a["evento_id"]
        session["evento_nombre"] = a["nombre"]
        session["precio_entrada"] = a["precio_entrada"]
        destino = a["rol"]
        registrar_log("login", f"{user.get('nombre', '')} ({user['usuario']}, "
                               f"{a['rol']} · {a['nombre']})")
        return jsonify({"ok": True, "rol": a["rol"], "destino": f"/{a['rol']}",
                        "usuario": user["usuario"], "nombre": user.get("nombre", ""),
                        "evento_id": a["evento_id"], "evento_nombre": a["nombre"]})

    # Varios eventos: elegir
    session["rol"] = "elegir"
    session["evento_id"] = None
    session["evento_nombre"] = None
    session["precio_entrada"] = 0
    session["multi_evento"] = True
    registrar_log("login", f"{user.get('nombre', '')} ({user['usuario']}, multi-evento)")
    return jsonify({"ok": True, "rol": "elegir", "destino": "/elegir",
                    "usuario": user["usuario"], "nombre": user.get("nombre", "")})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    registrar_log("logout", session.get("usuario", "?"))
    session.clear()
    return jsonify({"ok": True})


# -----------------------------------------------------------
# API: eventos (admin CRUD)
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


@app.route("/api/mis_eventos")
@require_rol("elegir")
def api_mis_eventos():
    """Eventos activos del usuario logueado, para la pantalla /elegir."""
    user = supabase.table(TABLA_USERS).select("id").eq("usuario", session["usuario"]).execute()
    if not user.data:
        return jsonify({"ok": False, "error": "Usuario no encontrado"}), 404
    return jsonify({"eventos": asignaciones_usuario(user.data[0]["id"])})


@app.route("/api/evento/select", methods=["POST"])
@require_rol("elegir")
def api_evento_select():
    """El staff elige el evento al que quiere entrar (solo los asignados)."""
    data = request.get_json(silent=True) or {}
    evento_id = data.get("evento_id")
    if not evento_id:
        return jsonify({"ok": False, "error": "evento_id requerido"}), 400

    user = supabase.table(TABLA_USERS).select("id").eq("usuario", session["usuario"]).execute()
    if not user.data:
        return jsonify({"ok": False, "error": "Usuario no encontrado"}), 404

    asignaciones = asignaciones_usuario(user.data[0]["id"])
    elegido = next((a for a in asignaciones if a["evento_id"] == int(evento_id)), None)
    if not elegido:
        return jsonify({"ok": False, "error": "No estás asignado a ese evento"}), 403

    session["rol"] = elegido["rol"]
    session["evento_id"] = elegido["evento_id"]
    session["evento_nombre"] = elegido["nombre"]
    session["precio_entrada"] = elegido["precio_entrada"]
    registrar_log("evento_seleccionar", f"{elegido['nombre']} ({elegido['rol']})")
    return jsonify({"ok": True, "destino": f"/{elegido['rol']}",
                    "evento": {"id": elegido["evento_id"], "nombre": elegido["nombre"],
                               "precio_entrada": elegido["precio_entrada"]}})


# -----------------------------------------------------------
# API: generar entrada
# -----------------------------------------------------------
@app.route("/api/generar", methods=["POST"])
@require_rol("vendedor")
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
                "vendedor": session.get("usuario", ""),
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
@require_rol("portero")
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
@require_rol("vendedor", "portero")
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
@require_rol("vendedor", "portero")
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
@require_rol("vendedor", "portero")
def api_listar():
    evento_id = session.get("evento_id")
    if not evento_id:
        return jsonify({"entradas": []})
    try:
        resp = supabase.table(TABLA).select(
            "id,codigo,usado,creado_en,nombre,cedula,precio,vendedor"
        ).eq("evento_id", evento_id).order("id", desc=True).limit(500).execute()
        return jsonify({"entradas": resp.data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/reset", methods=["POST"])
@require_rol("vendedor", "portero")
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
@require_rol("vendedor", "portero")
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
@require_rol("vendedor", "portero")
def api_exportar():
    evento_id = session.get("evento_id")
    if not evento_id:
        return jsonify({"ok": False, "error": "Seleccioná un evento"}), 400

    try:
        resp = supabase.table(TABLA).select(
            "id,codigo,usado,creado_en,nombre,cedula,precio,vendedor"
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
    writer.writerow(["id", "codigo", "nombre", "cedula", "usado", "precio", "vendedor", "creado_en"])
    for row in resp.data:
        writer.writerow([row["id"], row["codigo"], row.get("nombre", ""),
                         row.get("cedula", ""), row["usado"],
                         row.get("precio", precio), row.get("vendedor", ""),
                         row["creado_en"]])

    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=entradas.csv"
    return response


# -----------------------------------------------------------
# API: admin — dashboard, eventos, logs, usuarios y asignaciones
# -----------------------------------------------------------
@app.route("/api/dashboard")
@require_rol("admin")
def api_dashboard():
    """Estadisticas generales y por evento (incluye desglose por vendedor)."""
    try:
        eventos = supabase.table(TABLA_EVENTOS).select(
            "id,nombre,precio_entrada,activo").order("id").execute().data
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    general = {"eventos": len(eventos), "total": 0, "usadas": 0,
               "recaudado_total": 0, "recaudado_usadas": 0}
    por_evento = []

    for ev in eventos:
        eid = ev["id"]
        precio = ev["precio_entrada"]
        total = supabase.table(TABLA).select("id", count="exact") \
            .eq("evento_id", eid).execute().count
        usadas = supabase.table(TABLA).select("id", count="exact") \
            .eq("evento_id", eid).eq("usado", True).execute().count

        por_vendedor = {}
        try:
            rows = supabase.table(TABLA).select("vendedor,usado") \
                .eq("evento_id", eid).execute().data
            for r in rows:
                v = r.get("vendedor") or "—"
                por_vendedor.setdefault(v, {"total": 0, "usadas": 0})
                por_vendedor[v]["total"] += 1
                if r["usado"]:
                    por_vendedor[v]["usadas"] += 1
        except Exception:
            pass

        por_evento.append({
            "id": eid, "nombre": ev["nombre"], "precio_entrada": precio,
            "activo": ev["activo"],
            "total": total, "usadas": usadas, "pendientes": total - usadas,
            "recaudado_total": total * precio,
            "recaudado_usadas": usadas * precio,
            "por_vendedor": por_vendedor,
        })
        general["total"] += total
        general["usadas"] += usadas
        general["recaudado_total"] += total * precio
        general["recaudado_usadas"] += usadas * precio

    return jsonify({"general": general, "por_evento": por_evento})


@app.route("/api/logs")
@require_rol("admin")
def api_logs():
    try:
        resp = supabase.table(TABLA_LOGS).select(
            "id,accion,detalle,usuario,creado_en,evento_id"
        ).order("id", desc=True).limit(300).execute()
        return jsonify({"logs": resp.data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/users")
@require_rol("admin")
def api_users_listar():
    try:
        users = supabase.table(TABLA_USERS).select(
            "id,usuario,rol,nombre,creado_en").order("id").execute().data
        asig = supabase.table(TABLA_ASIGNACIONES).select(
            "usuario_id,evento_id,rol,eventos(nombre)").execute().data
        eventos_nombre = {a["evento_id"]: (a.get("eventos") or {}).get("nombre", "")
                          for a in asig}
        por_usuario = {}
        for a in asig:
            por_usuario.setdefault(a["usuario_id"], []).append({
                "evento_id": a["evento_id"],
                "evento_nombre": eventos_nombre.get(a["evento_id"], ""),
                "rol": a["rol"],
            })
        for u in users:
            u["asignaciones"] = por_usuario.get(u["id"], [])
        return jsonify({"users": users})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/users", methods=["POST"])
@require_rol("admin")
def api_users_crear():
    data = request.get_json(silent=True) or {}
    usuario = (data.get("usuario") or "").strip().lower()
    password = data.get("password") or ""
    admin = bool(data.get("admin"))
    nombre = (data.get("nombre") or "").strip()[:60]

    if not usuario or not password:
        return jsonify({"ok": False, "error": "usuario y password son requeridos"}), 400

    existe = supabase.table(TABLA_USERS).select("id") \
        .eq("usuario", usuario).execute()
    if existe.data:
        return jsonify({"ok": False, "error": "Ese usuario ya existe"}), 409

    supabase.table(TABLA_USERS).insert({
        "usuario": usuario,
        "password_hash": generate_password_hash(password),
        "rol": "admin" if admin else None,
        "nombre": nombre,
    }).execute()
    registrar_log("user_crear", f"{nombre} ({usuario}, {'admin' if admin else 'staff'})")
    return jsonify({"ok": True})


@app.route("/api/users/<int:user_id>", methods=["PUT"])
@require_rol("admin")
def api_users_editar(user_id):
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

    if "admin" in data:
        cambios["rol"] = "admin" if data["admin"] else None

    if data.get("password"):
        cambios["password_hash"] = generate_password_hash(data["password"])

    if not cambios:
        return jsonify({"ok": False, "error": "Nada que editar"}), 400

    prev = supabase.table(TABLA_USERS).select("usuario,nombre,rol").eq("id", user_id).execute()
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
        textos.append(f"admin {antes['rol'] == 'admin'} → {cambios['rol'] == 'admin'}")
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
    registrar_log("user_borrar", f"{u.get('nombre', '')} ({u['usuario']})")
    return jsonify({"ok": True})


@app.route("/api/asignar", methods=["POST"])
@require_rol("admin")
def api_asignar():
    """Asigna un usuario a un evento con un rol (vendedor/portero)."""
    data = request.get_json(silent=True) or {}
    usuario_id = data.get("usuario_id")
    evento_id = data.get("evento_id")
    rol = data.get("rol")

    if not usuario_id or not evento_id or rol not in ("vendedor", "portero"):
        return jsonify({"ok": False, "error": "usuario_id, evento_id y rol (vendedor/portero) requeridos"}), 400

    user = supabase.table(TABLA_USERS).select("usuario").eq("id", usuario_id).execute()
    ev = supabase.table(TABLA_EVENTOS).select("nombre").eq("id", evento_id).execute()
    if not user.data:
        return jsonify({"ok": False, "error": "Usuario no encontrado"}), 404
    if not ev.data:
        return jsonify({"ok": False, "error": "Evento no encontrado"}), 404

    supabase.table(TABLA_ASIGNACIONES).upsert(
        {"usuario_id": usuario_id, "evento_id": evento_id, "rol": rol},
        on_conflict="evento_id,usuario_id").execute()
    registrar_log("user_asignar", f"{user.data[0]['usuario']} → {ev.data[0]['nombre']} ({rol})")
    return jsonify({"ok": True})


@app.route("/api/asignar", methods=["DELETE"])
@require_rol("admin")
def api_desasignar():
    data = request.get_json(silent=True) or {}
    usuario_id = data.get("usuario_id")
    evento_id = data.get("evento_id")
    if not usuario_id or not evento_id:
        return jsonify({"ok": False, "error": "usuario_id y evento_id requeridos"}), 400

    supabase.table(TABLA_ASIGNACIONES).delete() \
        .eq("usuario_id", usuario_id).eq("evento_id", evento_id).execute()
    registrar_log("user_desasignar", f"usuario {usuario_id} quitado de evento {evento_id}")
    return jsonify({"ok": True})


# -----------------------------------------------------------
# Entry point
# -----------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)