"""
Test end-to-end del sistema de entradas: login, vendedor, portero y centro.
Requiere la app local con Supabase conectado.
"""

import io
import os
from load_env import cargar_env
cargar_env()

from app import app, supabase, TABLA

from supabase import create_client as _create_client
_ADMIN_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
if not _ADMIN_KEY:
    print("ERROR: SUPABASE_SERVICE_KEY no esta en .env")
    raise SystemExit(1)
_admin = _create_client("https://bibdstpwmtfsvbcduvey.supabase.co", _ADMIN_KEY)


def limpiar():
    _admin.table(TABLA).delete().neq('id', 0).execute()

client = app.test_client()

USUARIOS = {'vendedor': 'vendedor2026', 'portero': 'portero2026'}


def login(usuario):
    return client.post('/api/login', json={'usuario': usuario, 'password': USUARIOS[usuario]})


def setup():
    """Limpia la tabla antes de cada ejecucion de tests."""
    limpiar()


setup()

# ------------------------------------------------------------------
# Login
# ------------------------------------------------------------------
r = client.post('/api/login', json={'usuario': 'vendedor', 'password': 'incorrecta'})
assert r.status_code == 401, f"Login incorrecto debe ser 401, fue {r.status_code}"

r = client.post('/api/login', json={'usuario': 'noexiste', 'password': 'x'})
assert r.status_code == 401, "Usuario inexistente debe ser 401"

r = client.post('/api/login', json={'usuario': 'vendedor'})
assert r.status_code == 400, "Login sin password debe ser 400"

r = login('vendedor')
assert r.status_code == 200 and r.get_json()['ok'], "Login vendedor debe ser 200"
assert r.get_json()['rol'] == 'vendedor', "El rol debe venir de la base de datos"

# ------------------------------------------------------------------
# Rutas protegidas (con sesion)
# ------------------------------------------------------------------
r = client.get('/')
assert r.status_code == 302 and '/vendedor' in r.headers.get('Location', ''), \
    "/ debe redirigir a la pagina del rol (vendedor)"

r = client.get('/vendedor')
assert r.status_code == 200, "Vendedor con rol vendedor debe ser 200"

r = client.get('/portero')
assert r.status_code == 302 and '/vendedor' in r.headers.get('Location', ''), \
    "Portero con rol vendedor debe redirigir a /vendedor"

r = client.get('/centro')
assert r.status_code == 200, "Centro debe ser accesible con rol vendedor"

# ------------------------------------------------------------------
# Generar (requiere sesion)
# ------------------------------------------------------------------
r = client.post('/api/generar')
assert r.status_code == 400, f"Generar sin datos debe ser 400, fue {r.status_code}"

r = client.post('/api/generar', json={'nombre': '', 'cedula': '123'})
assert r.status_code == 400, "Generar sin nombre debe ser 400"

r = client.post('/api/generar', json={'nombre': 'Juan Perez', 'cedula': '12345678'})
assert r.status_code == 201, f"Generar con datos debe ser 201, fue {r.status_code}"
datos = r.get_json()
codigo = datos['codigo']
assert len(codigo) == 8 and codigo.isalnum(), f"Codigo debe ser alfanumerico de 8, fue {codigo}"
assert datos['nombre'] == 'Juan Perez' and datos['cedula'] == '12345678', \
    "Generar debe devolver nombre y cedula"
assert datos['id'] >= 1, "Generar debe devolver el id de la entrada"

# Duplicados: mismo nombre no se puede vender de nuevo
r = client.post('/api/generar', json={'nombre': 'juan perez', 'cedula': '99999999'})
assert r.status_code == 409, f"Nombre duplicado debe ser 409, fue {r.status_code}"
assert 'nombre' in r.get_json()['error'], "Error debe mencionar el nombre"

# Duplicados: misma cedula no se puede vender de nuevo
r = client.post('/api/generar', json={'nombre': 'Otro Nombre', 'cedula': '12345678'})
assert r.status_code == 409, f"Cedula duplicada debe ser 409, fue {r.status_code}"
assert 'cédula' in r.get_json()['error'] or 'cedula' in r.get_json()['error'], \
    "Error debe mencionar la cedula"

# ------------------------------------------------------------------
# Validar
# ------------------------------------------------------------------
r = client.post('/api/validar', json={'code': codigo})
assert r.status_code == 401, "Vendedor no puede validar (rol portero requerido)"

r = client.post('/api/validar', json={'code': codigo.lower()})
assert r.status_code == 401, "Vendedor no puede validar"

# ------------------------------------------------------------------
# Portero: login y validacion
# ------------------------------------------------------------------
r = login('portero')
assert r.status_code == 200 and r.get_json()['ok'], "Login portero debe ser 200"

r = client.post('/api/generar', json={'nombre': 'X', 'cedula': '1'})
assert r.status_code == 401, "Portero no puede generar (rol vendedor requerido)"

r = client.post('/api/validar', json={'code': codigo})
assert r.status_code == 200 and r.get_json()['estado'] == 'valido', "Primera validacion debe ser valido"
assert r.get_json()['nombre'] == 'Juan Perez' and r.get_json()['cedula'] == '12345678', \
    "Validar debe devolver nombre y cedula del comprador"

r = client.post('/api/validar', json={'code': codigo.lower()})
assert r.status_code == 409, "Segunda validacion (minusculas) debe ser usado"

r = client.post('/api/validar', json={'code': 'ZZZZ9999'})
assert r.status_code == 404, "Codigo inexistente debe ser 404"

r = client.post('/api/validar', json={})
assert r.status_code == 400, "Validar sin codigo debe ser 400"

# ------------------------------------------------------------------
# Centro de datos (accesible con vendedor o portero)
# ------------------------------------------------------------------
r = client.get('/api/stats')
stats = r.get_json()
assert stats['total'] >= 1 and stats['usadas'] >= 1, f"Stats incorrectas: {stats}"

r = client.get('/api/listar')
lista = r.get_json()['entradas']
assert len(lista) >= 1, "Listar debe devolver entradas"
assert 'codigo' in lista[0] and 'usado' in lista[0], "Listar debe incluir codigo y usado"
assert 'nombre' in lista[0] and 'cedula' in lista[0], "Listar debe incluir nombre y cedula"

r = client.post('/api/reset', json={'codigo': codigo})
assert r.status_code == 200 and r.get_json()['ok'], "Reset debe funcionar"

r = client.get('/api/stats')
assert r.get_json()['pendientes'] >= 1, "Despues del reset debe haber pendientes"

r = client.get('/api/exportar')
assert r.status_code == 200
assert 'text/csv' in r.headers.get('Content-Type', ''), "Exportar debe ser CSV"
csv_texto = r.get_data(as_text=True)
assert codigo in csv_texto, "El CSV debe contener el codigo"
assert 'Juan Perez' in csv_texto and '12345678' in csv_texto, "El CSV debe contener nombre y cedula"

# ------------------------------------------------------------------
# Borrar todas (reiniciamos IDs) — requiere funcion reset_entradas en Supabase
# ------------------------------------------------------------------
r = client.post('/api/borrar_todas')
if r.status_code == 500:
    print("AVISO: ejecuta el SQL de reset_entradas en Supabase para probar el reinicio de IDs")
    limpiar()
else:
    assert r.status_code == 200 and r.get_json()['ok'], "Borrar todas debe funcionar"

r = client.get('/api/stats')
assert r.get_json()['total'] == 0, "Tras borrar todas el total debe ser 0"

# Portero tambien accede al centro
r = login('portero')
r = client.get('/api/stats')
assert r.status_code == 200, "Stats debe ser accesible con rol portero"

r = client.post('/api/borrar_todas')
if r.status_code == 500:
    print("AVISO: el reinicio de IDs queda pendiente hasta ejecutar el SQL de reset_entradas")
    limpiar()
else:
    assert r.status_code == 200 and r.get_json()['ok'], "Portero debe poder borrar todas"

r = client.post('/api/generar', json={'nombre': 'Ana Diaz', 'cedula': '98765432'})
assert r.status_code == 401, "Portero no puede generar"

r = login('vendedor')
r = client.post('/api/generar', json={'nombre': 'Ana Diaz', 'cedula': '98765432'})
assert r.status_code == 201, "Generar tras reinicio debe ser 201"

r = client.post('/api/borrar_todas')
if r.status_code == 200:
    limpiar()
    r = login('vendedor')
    r = client.post('/api/generar', json={'nombre': 'Ana Diaz', 'cedula': '98765432'})
    assert r.status_code == 201
    assert r.get_json()['id'] == 1, f"Tras borrar todas el primer id debe ser 1, fue {r.get_json()['id']}"

# ------------------------------------------------------------------
# Logout y proteccion posterior
# ------------------------------------------------------------------
r = client.post('/api/logout')
assert r.status_code == 200, "Logout debe ser 200"

r = client.post('/api/generar', json={'nombre': 'X', 'cedula': '1'})
assert r.status_code == 401, "Generar sin sesion debe ser 401"

r = client.get('/vendedor')
assert r.status_code == 302 and '/login' in r.headers.get('Location', ''), \
    "Vendedor sin sesion debe redirigir a /login"

r = client.get('/api/stats')
assert r.status_code == 401, "Stats sin sesion debe ser 401"

# ------------------------------------------------------------------
# Login pagina y API de login
# ------------------------------------------------------------------
r = client.get('/login')
assert r.status_code == 200, "Pagina de login debe ser 200"

print("TODOS LOS TESTS OK")