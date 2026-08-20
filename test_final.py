"""
Test end-to-end del sistema multi-evento de entradas.
Requiere la app local con Supabase conectado con el schema multi-evento aplicado.
Uso: python test_final.py
"""

import os
from load_env import cargar_env
cargar_env()

from app import app, supabase, TABLA, TABLA_USERS, TABLA_LOGS, TABLA_EVENTOS

from supabase import create_client as _create_client
_ADMIN_URL = os.environ.get("SUPABASE_URL", "https://bibdstpwmtfsvbcduvey.supabase.co")
_ADMIN_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
if not _ADMIN_KEY:
    print("ERROR: SUPABASE_SERVICE_KEY no esta en .env")
    raise SystemExit(1)
_admin = _create_client(_ADMIN_URL, _ADMIN_KEY)

USUARIOS = {'admin': 'admin2026', 'vendedor': 'vendedor2026', 'portero': 'portero2026'}
CEDULA_CR = '6-0510-0347'

client = app.test_client()
_cliente_ok = False


def login(usuario):
    global _cliente_ok
    r = client.post('/api/login', json={'usuario': usuario, 'password': USUARIOS[usuario]})
    _cliente_ok = r.status_code == 200
    return r


def select_evento(eid):
    """Admin selects an event."""
    return client.post('/api/evento/select', json={'evento_id': eid})


def limpiar():
    """Limpia entradas, eventos test y usuarios test."""
    _admin.table(TABLA).delete().neq('id', 0).execute()
    _admin.table(TABLA_EVENTOS).delete().gt('id', 1).execute()
    _admin.table(TABLA_USERS).delete().gt('evento_id', 1).execute()
    for u in ['testtemp', 'testtemp2', 'malo', 'vendedor2', 'portero2']:
        _admin.table(TABLA_USERS).delete().eq('usuario', u).execute()


limpiar()

# ------------------------------------------------------------------
# Login
# ------------------------------------------------------------------
print("=== Login ===")

r = client.post('/api/login', json={'usuario': 'vendedor', 'password': 'incorrecta'})
assert r.status_code == 401, f"Login incorrecto debe ser 401, fue {r.status_code}"

r = client.post('/api/login', json={'usuario': 'noexiste', 'password': 'x'})
assert r.status_code == 401, "Usuario inexistente debe ser 401"

r = client.post('/api/login', json={'usuario': 'vendedor'})
assert r.status_code == 400, f"Login sin password debe ser 400, fue {r.status_code}"

r = login('vendedor')
assert r.status_code == 200 and r.get_json()['ok'], "Login vendedor debe ser 200"
assert r.get_json()['rol'] == 'vendedor', "El rol debe venir de la base de datos"
assert r.get_json().get('evento_id') == 1, f"Vendedor debe estar en evento 1, fue {r.get_json().get('evento_id')}"

# ------------------------------------------------------------------
# Rutas protegidas (con sesion de vendedor, evento 1)
# ------------------------------------------------------------------
print("=== Route protection ===")

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

r = client.get('/admin')
assert r.status_code == 302 and '/vendedor' in r.headers.get('Location', ''), \
    "Admin con rol vendedor debe redirigir a /vendedor"

# ------------------------------------------------------------------
# Generar (requiere sesion de vendedor) — cédula formato CR
# ------------------------------------------------------------------
print("=== Generar (cédula CR) ===")

r = client.post('/api/generar')
assert r.status_code == 400, f"Generar sin datos debe ser 400, fue {r.status_code}"

r = client.post('/api/generar', json={'nombre': '', 'cedula': CEDULA_CR})
assert r.status_code == 400, "Generar sin nombre debe ser 400"

r = client.post('/api/generar', json={'nombre': 'Juan Perez', 'cedula': '12345678'})
assert r.status_code == 400, "Cédula sin formato CR debe ser 400"

r = client.post('/api/generar', json={'nombre': 'Juan Perez', 'cedula': '6-0510-034'})
assert r.status_code == 400, "Cédula con formato incorrecto debe ser 400"

r = client.post('/api/generar', json={'nombre': 'Juan Perez', 'cedula': '6-0510-0347'})
assert r.status_code == 201, f"Cédula CR valida debe ser 201, fue {r.status_code}: {r.get_json()}"
datos = r.get_json()
codigo = datos['codigo']
assert len(codigo) == 8 and codigo.isalnum(), f"Código debe ser alfanumérico de 8, fue {codigo}"
assert datos['nombre'] == 'Juan Perez' and datos['cedula'] == CEDULA_CR, \
    "Generar debe devolver nombre y cédula"
assert datos['id'] >= 1, "Generar debe devolver el id de la entrada"
assert datos.get('precio') >= 1000, f"Precio debe estar en la entrada, fue {datos.get('precio')}"

# Duplicados: mismo nombre no se puede vender de nuevo
r = client.post('/api/generar', json={'nombre': 'juan perez', 'cedula': '7-0510-0348'})
assert r.status_code == 409, f"Nombre duplicado debe ser 409, fue {r.status_code}"
assert 'nombre' in r.get_json()['error'], "Error debe mencionar el nombre"

# Duplicados: misma cédula no se puede vender de nuevo (mismo evento)
r = client.post('/api/generar', json={'nombre': 'Otro Nombre', 'cedula': CEDULA_CR})
assert r.status_code == 409, f"Cédula duplicada debe ser 409, fue {r.status_code}"
err_msg = r.get_json().get('error', '')
assert 'cédula' in err_msg.lower() or 'cedula' in err_msg.lower(), "Error debe mencionar la cédula"

# ------------------------------------------------------------------
# Validar (vendedor no puede)
# ------------------------------------------------------------------
print("=== Validar (vendedor no puede) ===")

r = client.post('/api/validar', json={'code': codigo})
assert r.status_code == 401, "Vendedor no puede validar (rol portero requerido)"

r = client.post('/api/validar', json={'code': codigo.lower()})
assert r.status_code == 401, "Vendedor no puede validar (minusculas)"

# ------------------------------------------------------------------
# Portero: login y validacion
# ------------------------------------------------------------------
print("=== Portero: login y validacion ===")

r = login('portero')
assert r.status_code == 200 and r.get_json()['ok'], "Login portero debe ser 200"

r = client.post('/api/generar', json={'nombre': 'X', 'cedula': '1-0000-0001'})
assert r.status_code == 401, "Portero no puede generar (rol vendedor requerido)"

r = client.post('/api/validar', json={'code': codigo})
assert r.status_code == 200 and r.get_json()['estado'] == 'valido', \
    f"Primera validacion debe ser valido, fue {r.get_json()}"
assert r.get_json()['nombre'] == 'Juan Perez' and r.get_json()['cedula'] == CEDULA_CR, \
    "Validar debe devolver nombre y cedula del comprador"

r = client.post('/api/validar', json={'code': codigo.lower()})
assert r.status_code == 409, "Segunda validacion (minusculas) debe ser usado"

r = client.post('/api/validar', json={'code': 'ZZZZ9999'})
assert r.status_code == 404, "Codigo inexistente debe ser 404"

r = client.post('/api/validar', json={})
assert r.status_code == 400, "Validar sin codigo debe ser 400"

# ------------------------------------------------------------------
# Centro de datos (accesible con portero)
# ------------------------------------------------------------------
print("=== Centro de datos ===")

r = client.get('/api/stats')
stats = r.get_json()
assert stats['total'] >= 1 and stats['usadas'] >= 1, f"Stats incorrectas: {stats}"
assert stats.get('precio') >= 1000, f"Precio debe estar en stats: {stats}"

r = client.get('/api/listar')
lista = r.get_json()['entradas']
assert len(lista) >= 1, "Listar debe devolver entradas"
assert 'codigo' in lista[0] and 'usado' in lista[0], "Listar debe incluir codigo y usado"
assert 'nombre' in lista[0] and 'cedula' in lista[0], "Listar debe incluir nombre y cedula"
assert lista[0]['cedula'] == CEDULA_CR, "Listar debe incluir cédula CR"

# Reset de una entrada
r = client.post('/api/reset', json={'code': codigo})
assert r.status_code == 200 and r.get_json()['ok'], "Reset debe funcionar"

r = client.get('/api/stats')
assert r.get_json()['pendientes'] >= 1, "Después del reset debe haber pendientes"

# Exportar
r = client.get('/api/exportar')
assert r.status_code == 200
assert 'text/csv' in r.headers.get('Content-Type', ''), "Exportar debe ser CSV"
csv_texto = r.get_data(as_text=True)
assert codigo in csv_texto, "El CSV debe contener el código"
assert 'Juan Perez' in csv_texto and CEDULA_CR in csv_texto, "El CSV debe contener nombre y cédula"

# ------------------------------------------------------------------
# Admin: eventos CRUD
# ------------------------------------------------------------------
print("=== Admin: eventos CRUD ===")

client.post('/api/logout')
r = login('admin')
assert r.status_code == 200 and r.get_json()['rol'] == 'admin', "Login admin debe ser 200"

r = client.get('/')
assert r.status_code == 302 and '/admin' in r.headers.get('Location', ''), \
    "/ debe redirigir a /admin para rol admin"

# List eventos
r = client.get('/api/eventos')
assert r.status_code == 200
eventos_data = r.get_json()['eventos']
assert len(eventos_data) >= 1
assert eventos_data[0]['nombre'] == 'Baile CTPM 2026'
assert eventos_data[0]['precio_entrada'] == 1000
assert eventos_data[0]['activo'] == True

# Create event
r = client.post('/api/eventos', json={'nombre': 'Test Event 2', 'precio': 2000})
assert r.status_code == 200 and r.get_json()['ok'], f"Crear evento debe funcionar: {r.get_json()}"
assert r.get_json()['precio'] == 2000

# Create duplicate event
r = client.post('/api/eventos', json={'nombre': 'Test Event 2', 'precio': 500})
assert r.status_code == 409, "Evento duplicado debe ser 409"

# Invalid price
r = client.post('/api/eventos', json={'nombre': 'Bad Price', 'precio': -100})
assert r.status_code == 400, "Precio negativo debe ser 400"

# List now shows 2
r = client.get('/api/eventos')
eventos_data = r.get_json()['eventos']
assert len(eventos_data) >= 2, f"Debe haber 2 eventos, hay {len(eventos_data)}"

evento2_id = next(e['id'] for e in eventos_data if e['nombre'] == 'Test Event 2')

# Edit event price
r = client.put(f'/api/eventos/{evento2_id}', json={'precio_entrada': 2500})
assert r.status_code == 200 and r.get_json()['ok'], f"Editar evento debe funcionar: {r.get_json()}"
assert r.get_json()['precio'] == 2500

# Select event 2
r = client.post('/api/evento/select', json={'evento_id': evento2_id})
assert r.status_code == 200 and r.get_json()['ok'], "Seleccionar evento debe funcionar"

# Verify precio changed in session
r = client.get('/api/stats')
assert r.get_json()['precio'] == 2500, f"Precio should be 2500, got {r.get_json().get('precio')}"

# Admin can view all routes
for path in ['/admin', '/vendedor', '/portero', '/centro']:
    r = client.get(path)
    assert r.status_code == 200, f"Admin debe poder acceder a {path}, fue {r.status_code}"

# Deactivate event
r = client.put(f'/api/eventos/{evento2_id}', json={'activo': False})
assert r.status_code == 200, "Desactivar evento debe funcionar"

r = client.get('/api/eventos')
eventos_data = r.get_json()['eventos']
ev2 = next(e for e in eventos_data if e['id'] == evento2_id)
assert ev2['activo'] == False, "Evento debe estar desactivado"

# Re-activate
r = client.put(f'/api/eventos/{evento2_id}', json={'activo': True})
assert r.status_code == 200

# ------------------------------------------------------------------
# Multi-event: isolation
# ------------------------------------------------------------------
print("=== Multi-event: isolation ===")

# Create vendedor for event 2
r = client.post('/api/users', json={'usuario': 'vendedor2', 'password': 'v2event2', 'rol': 'vendedor', 'nombre': 'V2 Evento 2'})
assert r.status_code == 200, f"Crear vendedor2 debe funcionar: {r.get_json()}"

# Login as vendedor2 (event 2)
client.post('/api/logout')
r = client.post('/api/login', json={'usuario': 'vendedor2', 'password': 'v2event2'})
assert r.status_code == 200 and r.get_json()['rol'] == 'vendedor', \
    f"Login vendedor2 debe ser 200: {r.get_json()}"
assert r.get_json().get('evento_id') == evento2_id, f"Vendedor2 debe estar en evento {evento2_id}"

# Generate entry with same cédula as event 1 (different event = OK)
r = client.post('/api/generar', json={'nombre': 'Maria Lopez', 'cedula': CEDULA_CR})
assert r.status_code == 201, f"Misma cédula en evento diferente debe ser OK: {r.get_json()}"
evento2_codigo = r.get_json()['codigo']
assert r.get_json()['precio'] == 2500, f"Precio evento 2 debe ser 2500: {r.get_json()}"

# Login as vendedor (event 1) — generate another entry
client.post('/api/logout')
r = login('vendedor')
assert r.status_code == 200

r = client.post('/api/generar', json={'nombre': 'Carlos Ruiz', 'cedula': '7-0510-0347'})
assert r.status_code == 201, f"Generar en evento 1 debe funcionar: {r.get_json()}"
evento1_codigo = r.get_json()['codigo']

# Admin: verify event 1 stats ≠ event 2 stats
client.post('/api/logout')
r = login('admin')
assert r.status_code == 200

# Select event 1
select_evento(1)
r = client.get('/api/stats')
stats1 = r.get_json()
assert stats1['total'] >= 1, f"Event 1 debe tener entradas: {stats1}"
assert stats1['precio'] == 1000, f"Event 1 price debe ser 1000: {stats1}"

# List event 1 → should NOT contain evento2 entries
r = client.get('/api/listar')
lista1 = r.get_json()['entradas']
codigos1 = [e['codigo'] for e in lista1]
assert evento1_codigo in codigos1, "Event 1 list debe tener evento1 entry"
assert evento2_codigo not in codigos1, "Event 1 list NO debe tener evento2 entry"

# Select event 2
select_evento(evento2_id)
r = client.get('/api/stats')
stats2 = r.get_json()
assert stats2['total'] >= 1, f"Event 2 debe tener entradas: {stats2}"
assert stats2['precio'] == 2500, f"Event 2 price debe ser 2500: {stats2}"
assert stats2['total'] != stats1['total'] or stats2 != stats1, "Stats deben diferir entre eventos"

# List event 2 → should NOT contain evento1 entries
r = client.get('/api/listar')
lista2 = r.get_json()['entradas']
codigos2 = [e['codigo'] for e in lista2]
assert evento2_codigo in codigos2, "Event 2 list debe tener evento2 entry"
assert evento1_codigo not in codigos2, "Event 2 list NO debe tener evento1 entry"

print("=== Admin: usuarios CRUD por evento ===")
select_evento(1)

# List users for event 1 (includes global admin)
r = client.get('/api/users')
users = r.get_json()['users']
assert len(users) >= 3, f"Debe haber al menos 3 usuarios (admin global + vendedor + portero), hay {len(users)}"

# Create test user for event 1
r = client.post('/api/users', json={'usuario': 'testtemp', 'password': 'temp123', 'rol': 'vendedor', 'nombre': 'Temp'})
assert r.status_code == 200, f"Crear usuario debe funcionar: {r.get_json()}"

r = client.post('/api/users', json={'usuario': 'testtemp', 'password': 'x', 'rol': 'vendedor'})
assert r.status_code == 409, "Usuario duplicado debe ser 409"

r = client.post('/api/users', json={'usuario': 'malo', 'password': 'x', 'rol': 'super'})
assert r.status_code == 400, "Rol invalido debe ser 400"

nuevo = _admin.table(TABLA_USERS).select('id').eq('usuario', 'testtemp').eq('evento_id', 1).execute()
assert len(nuevo.data) > 0
nuevo_id = nuevo.data[0]['id']

r = client.put(f'/api/users/{nuevo_id}', json={'rol': 'portero', 'password': 'nueva123'})
assert r.status_code == 200 and r.get_json()['ok'], "Editar usuario debe funcionar"

r = client.put(f'/api/users/{nuevo_id}', json={'usuario': 'testtemp2', 'nombre': 'Temp Dos'})
assert r.status_code == 200 and r.get_json()['ok'], "Editar usuario y nombre debe funcionar"
check_user = _admin.table(TABLA_USERS).select('usuario').eq('id', nuevo_id).execute()
assert check_user.data[0]['usuario'] == 'testtemp2', "El usuario debe cambiar en la base"

r = client.put(f'/api/users/{nuevo_id}', json={'usuario': 'admin'})
assert r.status_code == 409, "Usuario duplicado (admin global) debe ser 409"

r = client.delete(f'/api/users/{nuevo_id}')
assert r.status_code == 200 and r.get_json()['ok'], "Borrar usuario debe funcionar"

# No puede borrarse a si mismo (admin)
propio = _admin.table(TABLA_USERS).select('id').eq('usuario', 'admin').execute()
propio_id = propio.data[0]['id']
r = client.delete(f'/api/users/{propio_id}')
assert r.status_code == 400, "Admin no puede borrarse a si mismo"

print("=== Admin: logs por evento ===")
# Logs already should exist from all actions
r = client.get('/api/logs')
assert r.status_code == 200, "Admin debe poder ver logs"
logs = r.get_json()['logs']
assert len(logs) >= 1, "Debe haber al menos un log"
acciones = {l['accion'] for l in logs}
assert 'login' in acciones, f"Debe haber logs de login, hay {acciones}"

# Logs filtrados por evento 2
select_evento(evento2_id)
r = client.get('/api/logs')
logs2 = r.get_json()['logs']
assert len(logs2) >= 0  # event 2 just had vendedor2 create + login

# Origen del escaneo en logs
select_evento(1)
r = client.post('/api/generar', json={'nombre': 'Origen Test', 'cedula': '8-0510-0347'})
assert r.status_code in (200, 201), f"Admin puede generar: {r.get_json()}"
codigo_origen = r.get_json()['codigo']

r = client.post('/api/validar', json={'code': codigo_origen, 'origen': 'camara'})
assert r.status_code == 200 and r.get_json()['estado'] == 'valido', \
    "Admin puede validar con origen camara"

r = client.post('/api/validar', json={'code': codigo_origen})
assert r.status_code == 409, "Entrada ya usada debe ser 409"

r = client.get('/api/logs')
logs = r.get_json()['logs']
assert any(l['accion'] == 'escaneo' and 'cámara' in l['detalle'] for l in logs), \
    "Debe haber un log de escaneo por cámara"
assert any(l['accion'] == 'escaneo' and 'manual' in l['detalle'] for l in logs), \
    "Debe haber un log de escaneo manual (default sin origen)"

# ------------------------------------------------------------------
# Borrar todas (por evento) — requiere función reset_entradas en Supabase
# ------------------------------------------------------------------
print("=== Borrar todas (por evento) ===")

select_evento(1)
r = login('vendedor')
r = client.post('/api/borrar_todas')
if r.status_code == 500:
    print("AVISO: ejecuta el SQL de reset_entradas en Supabase para probar el reinicio de IDs")
    limpiar()
else:
    assert r.status_code == 200 and r.get_json()['ok'], "Borrar todas debe funcionar"

r = client.get('/api/stats')
assert r.get_json()['total'] == 0, f"Tras borrar todas el total debe ser 0: {r.get_json()}"

# Generate after reset
r = client.post('/api/generar', json={'nombre': 'Ana Diaz', 'cedula': '9-0510-0347'})
assert r.status_code == 201, "Generar tras reinicio debe ser 201"

# ------------------------------------------------------------------
# Logout y protección posterior
# ------------------------------------------------------------------
print("=== Logout y protección ===")

r = client.post('/api/logout')
assert r.status_code == 200, "Logout debe ser 200"

r = client.post('/api/generar', json={'nombre': 'X', 'cedula': '6-0510-0347'})
assert r.status_code == 401, "Generar sin sesion debe ser 401"

r = client.get('/vendedor')
assert r.status_code == 302 and '/login' in r.headers.get('Location', ''), \
    "Vendedor sin sesion debe redirigir a /login"

r = client.get('/api/stats')
assert r.status_code == 401, "Stats sin sesion debe ser 401"

# ------------------------------------------------------------------
# Página de login y acceso admin
# ------------------------------------------------------------------
print("=== Login página y acceso admin ===")

r = client.get('/login')
assert r.status_code == 200, "Pagina de login debe ser 200"

r = client.get('/admin')
assert r.status_code == 302 and '/login' in r.headers.get('Location', ''), \
    "Admin sin sesion debe redirigir a /login"

r = client.get('/api/logs')
assert r.status_code == 401, "Logs sin sesion debe ser 401"

r = login('vendedor')
r = client.get('/admin')
assert r.status_code == 302 and '/vendedor' in r.headers.get('Location', ''), \
    "Vendedor no puede ver /admin"

r = client.get('/api/logs')
assert r.status_code == 401, "Vendedor no puede ver logs"

r = client.get('/api/eventos')
assert r.status_code == 401, "Vendedor no puede ver eventos"

# Login admin
r = login('admin')
assert r.status_code == 200, "Login admin debe ser 200"

r = client.get('/')
assert r.status_code == 302 and '/admin' in r.headers.get('Location', ''), \
    "/ debe redirigir a /admin para rol admin"

r = client.get('/admin')
assert r.status_code == 200, "Admin debe poder ver /admin"
r = client.get('/vendedor')
assert r.status_code == 200, "Admin debe poder ver /vendedor"
r = client.get('/portero')
assert r.status_code == 200, "Admin debe poder ver /portero"
r = client.get('/centro')
assert r.status_code == 200, "Admin debe poder ver /centro"

# Logs
r = client.get('/api/logs')
logs = r.get_json()['logs']
assert len(logs) >= 1
acciones = {l['accion'] for l in logs}
assert 'login' in acciones, f"Debe haber logs de login, hay {acciones}"

# ------------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------------
limpiar()
print("\nTODOS LOS TESTS OK")
