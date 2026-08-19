"""
Sistema de Venta y Validacion de Entradas con Codigos QR
==========================================================
Backend: Flask + Supabase (PostgreSQL serverless)
Deploy: Vercel (funcion serverless)

Acceso: login con una sola contrasena (SECRET_PASS).
Areas: vendedor (generar QR), portero (validar), centro (datos).
"""

import os
import uuid
import io
import csv
from functools import wraps
from flask import (Flask, request, jsonify, render_template,
                   session, redirect, url_for, Response)
from werkzeug.security import check_password_hash
from supabase import create_client, Client

# -----------------------------------------------------------
# Configuracion Supabase
# -----------------------------------------------------------
SUPABASE_URL = "https://bibdstpwmtfsvbcduvey.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJpYmRzdHB3bXRmc3ZiY2R1dmV5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODcwNzczODUsImV4cCI6MjEwMjY1MzM4NX0.5je41P3CCoHH8XeWSBKH9e9AcCM2JitJd_beHXKLSD8"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# -----------------------------------------------------------
# Configuracion Flask
# -----------------------------------------------------------
app = Flask(__name__,
            template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates"))

# Clave para firmar las sesiones (cookie). En Vercel, definir SECRET_KEY
# como variable de entorno para que las sesiones sobrevivan a los deploys.
app.secret_key = os.environ.get("SECRET_KEY", "clave-local-de-desarrollo")

# Contrasenas de acceso por rol (env vars de Vercel; sin default en el codigo).
ROLES = {
    "vendedor": os.environ.get("SECRET_PASS_VENDEDOR", ""),
    "portero": os.environ.get("SECRET_PASS_PORTERO", ""),
}

# Nombre del evento (para headers y footer)
NOMBRE_EVENTO = os.environ.get("NOMBRE_EVENTO", "Fiesta Anual 2026")

# Precio de cada entrada en colones
PRECIO_ENTRADA = int(os.environ.get("PRECIO_ENTRADA", "1000"))

# Tabla de usuarios (login por usuario + contrasena, rol desde la base)
TABLA = "entradas"
TABLA_USERS = "users"


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
                if destino in ("vendedor", "portero"):
                    return redirect(url_for(destino))
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return wrapper
    return decorator


def generar_codigo():
    """Genera un codigo alfanumerico unico de 8 caracteres."""
    return uuid.uuid4().hex[:8].upper()


# -----------------------------------------------------------
# Rutas de interfaz (protegidas con login)
# -----------------------------------------------------------
@app.route("/login")
def login():
    return render_template("login.html", nombre_evento=NOMBRE_EVENTO)


@app.route("/")
@require_rol("vendedor", "portero")
def index():
    return redirect(url_for(session.get("rol", "vendedor")))


@app.route("/vendedor")
@require_rol("vendedor")
def vendedor():
    return render_template("vendedor.html", nombre_evento=NOMBRE_EVENTO, rol=session.get("rol"))


@app.route("/portero")
@require_rol("portero")
def portero():
    return render_template("portero.html", nombre_evento=NOMBRE_EVENTO, rol=session.get("rol"))


@app.route("/centro")
@require_rol("vendedor", "portero")
def centro():
    return render_template("centro.html", nombre_evento=NOMBRE_EVENTO, rol=session.get("rol"))


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
        resp = supabase.table(TABLA_USERS).select("usuario,password_hash,rol,nombre") \
            .eq("usuario", usuario).execute()
    except Exception:
        return jsonify({"ok": False,
                        "error": "La tabla users no existe — ejecutá users.sql en Supabase"}), 500

    if not resp.data:
        return jsonify({"ok": False, "error": "Usuario o contraseña incorrectos"}), 401

    user = resp.data[0]
    if not check_password_hash(user["password_hash"], data["password"]):
        return jsonify({"ok": False, "error": "Usuario o contraseña incorrectos"}), 401

    session["auth"] = True
    session["rol"] = user["rol"]
    session["usuario"] = user["usuario"]
    return jsonify({"ok": True, "rol": user["rol"], "usuario": user["usuario"],
                    "nombre": user.get("nombre", "")})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


# -----------------------------------------------------------
# API: generar entrada
# -----------------------------------------------------------
@app.route("/api/generar", methods=["POST"])
@require_rol("vendedor")
def api_generar():
    """Genera una nueva entrada con datos del comprador (rol vendedor)."""
    data = request.get_json(silent=True) or {}
    nombre = (data.get("nombre") or "").strip()[:80]
    cedula = (data.get("cedula") or "").strip()[:30]

    if not nombre or not cedula:
        return jsonify({"ok": False, "error": "Nombre y cedula son requeridos"}), 400

    for _ in range(5):
        codigo = generar_codigo()
        try:
            resp = supabase.table(TABLA).insert({
                "codigo": codigo,
                "usado": False,
                "nombre": nombre,
                "cedula": cedula
            }).execute()
            if resp.data:
                return jsonify({"ok": True, "codigo": codigo, "id": resp.data[0]["id"],
                                "nombre": nombre, "cedula": cedula}), 201
        except Exception:
            continue

    return jsonify({"ok": False, "error": "No se pudo generar codigo"}), 500


# -----------------------------------------------------------
# API: validar entrada
# -----------------------------------------------------------
@app.route("/api/validar", methods=["POST"])
@require_rol("portero")
def api_validar():
    """
    Valida un codigo QR (rol portero).
    Estados: valido -> usado -> inexistente
    """
    data = request.get_json(silent=True)
    if not data or not data.get("code"):
        return jsonify({"ok": False, "error": "Codigo requerido"}), 400

    codigo = data["code"].strip().upper()

    try:
        resp = supabase.table(TABLA).select("usado,nombre,cedula").eq("codigo", codigo).execute()
    except Exception as e:
        return jsonify({"ok": False, "error": f"Error de base de datos: {e}"}), 500

    if not resp.data:
        return jsonify({"ok": False, "estado": "inexistente",
                        "error": "Codigo no encontrado"}), 404

    if resp.data[0]["usado"]:
        return jsonify({"ok": False, "estado": "usado",
                        "error": "Codigo ya fue utilizado"}), 409

    supabase.table(TABLA).update({"usado": True}).eq("codigo", codigo).execute()

    return jsonify({"ok": True, "estado": "valido", "codigo": codigo,
                    "nombre": resp.data[0].get("nombre", ""),
                    "cedula": resp.data[0].get("cedula", "")}), 200


# -----------------------------------------------------------
# API: contador de entradas generadas
# -----------------------------------------------------------
@app.route("/api/contador")
@require_rol("vendedor", "portero")
def api_contador():
    try:
        resp = supabase.table(TABLA).select("id", count="exact").execute()
        return jsonify({"total": resp.count})
    except Exception:
        return jsonify({"total": 0})


# -----------------------------------------------------------
# API: centro de datos
# -----------------------------------------------------------
@app.route("/api/stats")
@require_rol("vendedor", "portero")
def api_stats():
    try:
        total = supabase.table(TABLA).select("id", count="exact").execute().count
        usadas = supabase.table(TABLA).select("id", count="exact").eq("usado", True).execute().count
        pendientes = total - usadas
        precio = PRECIO_ENTRADA
        return jsonify({
            "total": total, "usadas": usadas, "pendientes": pendientes,
            "precio": precio,
            "recaudado_total": total * precio,
            "recaudado_usadas": usadas * precio,
            "recaudado_pendientes": pendientes * precio,
        })
    except Exception:
        precio = PRECIO_ENTRADA
        return jsonify({"total": 0, "usadas": 0, "pendientes": 0,
                        "precio": precio, "recaudado_total": 0,
                        "recaudado_usadas": 0, "recaudado_pendientes": 0})


@app.route("/api/listar")
@require_rol("vendedor", "portero")
def api_listar():
    try:
        resp = supabase.table(TABLA).select("id,codigo,usado,creado_en,nombre,cedula") \
            .order("id", desc=True).limit(500).execute()
        return jsonify({"entradas": resp.data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/reset", methods=["POST"])
@require_rol("vendedor", "portero")
def api_reset():
    """Marca una entrada como no utilizada (corrige escaneos erroneos)."""
    data = request.get_json(silent=True)
    if not data or not data.get("codigo"):
        return jsonify({"ok": False, "error": "Codigo requerido"}), 400

    codigo = data["codigo"].strip().upper()
    resp = supabase.table(TABLA).update({"usado": False}).eq("codigo", codigo).execute()

    if not resp.data:
        return jsonify({"ok": False, "error": "Codigo no encontrado"}), 404

    return jsonify({"ok": True, "codigo": codigo})


@app.route("/api/borrar_todas", methods=["POST"])
@require_rol("vendedor", "portero")
def api_borrar_todas():
    """Borra todas las entradas y reinicia los IDs desde 1 (rol centro)."""
    try:
        supabase.rpc("reset_entradas").execute()
        return jsonify({"ok": True, "mensaje": "Entradas eliminadas e IDs reiniciados"})
    except Exception as e:
        return jsonify({"ok": False,
                        "error": "La funcion reset_entradas no existe en Supabase"}), 500


@app.route("/api/exportar")
@require_rol("vendedor", "portero")
def api_exportar():
    try:
        resp = supabase.table(TABLA).select("id,codigo,usado,creado_en,nombre,cedula") \
            .order("id").execute()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    total = len(resp.data)
    usadas = sum(1 for r in resp.data if r["usado"])
    pendientes = total - usadas
    precio = PRECIO_ENTRADA

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["RESUMEN"])
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
                         row.get("cedula", ""), row["usado"], precio, row["creado_en"]])

    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=entradas.csv"
    return response


if __name__ == "__main__":
    # Desarrollo solamente:
    app.run(host="0.0.0.0", port=5000, debug=True)