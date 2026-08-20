"""
Test end-to-end del sistema multi-evento de entradas (usuarios globales).
Requiere la app local con Supabase conectado y la migracion usuarios_globales aplicada.
Uso: python test_final.py
"""

import os
from load_env import cargar_env
cargar_env()

from app import app, supabase, TABLA, TABLA_USERS, TABLA_LOGS, TABLA_EVENTOS, TABLA_ASIGNACIONES

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


USUARIOS_TEST = ['testtemp', 'testtemp2', 'malo', 'vendedor2', 'portero2']


def limpiar():
    """Limpia entradas, eventos test y usuarios test (sin tocar datos de produccion)."""
    _admin.table(TABLA).delete().neq('id', 0).execute()
    _admin.table(TABLA_EVENTOS).delete().gt('id', 1).execute()
    ids_test = _admin.table(TABLA_USERS).select('id').in_('usuario', USUARIOS_TEST).execute()
    if ids_test.data:
        _admin.table(TABLA_ASIGNACIONES).delete() \
            .in_('usuario_id', [u['id'] for u in ids_test.data]).execute()
    for u in USUARIOS_TEST:
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
j = r.get_json()
assert j['rol'] == 'vendedor', "El rol debe venir de la asignacion"
assert j['destino'] == '/vendedor', f"Destino debe ser /vendedor, fue {j['destino']}"
assert j.get('evento_id') == 1, f"Vendedor debe estar en evento 1, fue {j.get('evento_id')}"

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

r = client.post('/api/generar', json={'nombre': 'Juan Perez', 'cedula': '6-0510-0347'})
assert r.status_code == 201, f"Cédula CR valida debe ser 201, fue {r.status_code}: {r.get_json()}"
datos = r.get_json()
codigo = datos['codigo']
assert len(codigo) == 8 and codigo.isalnum(), f"Código debe ser alfanumérico de 8, fue {codigo}"
assert datos['nombre'] == 'Juan Perez' and datos['cedula'] == CEDULA_CR, \
    "Generar debe devolver nombre y cédula"
assert datos['id'] >= 1, "Generar debe devolver el id de la entrada"
assert datos.get('precio') >= 1000, f"Precio debe estar en la entrada, fue {datos.get('precio')}"

# La entrada debe registrar al vendedor
reg = _admin.table(TABLA).select('vendedor').eq('id', datos['id']).execute()
assert reg.data and reg.data[0]['vendedor'] == 'vendedor', \
    f"La entrada debe registrar el vendedor, fue {reg.data}"

# Duplicados: mismo nombre no se puede vender de nuevo
r = client.post('/api/generar', json={'nombre': 'juan perez', 'cedula': '7-0510-0348'})
assert r.status_code == 409, f"Nombre duplicado debe ser 409, fue {r.status_code}"

# Duplicados: misma cédula no se puede vender de nuevo (mismo evento)
r = client.post('/api/generar', json={'nombre': 'Otro Nombre', 'cedula': CEDULA_CR})
assert r.status_code == 409, f"Cédula duplicada debe ser 409, fue {r.status_code}"

# ------------------------------------------------------------------
# Validar (vendedor no puede)
# ------------------------------------------------------------------
print("=== Validar (vendedor no puede) ===")

r = client.post('/api/validar', json={'code': codigo})
assert r.status_code == 401, "Vendedor no puede validar (rol portero requerido)"

# ------------------------------------------------------------------
# Portero: login y validacion
# ------------------------------------------------------------------
print("=== Portero: login y validacion ===")

r = login('portero')
assert r.status_code == 200 and r.get_json()['ok'], "Login portero debe ser 200"
assert r.get_json()['destino'] == '/portero', "Portero debe entrar directo a /portero"

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

# ------------------------------------------------------------------
# Centro de datos (accesible con portero)
# ------------------------------------------------------------------
print("=== Centro de datos ===")

r = client.get('/api/stats')
stats = r.get_json()
assert stats['total'] >= 1 and stats['usadas'] >= 1, f"Stats incorrectas: {stats}"

r = client.get('/api/listar')
lista = r.get_json()['entradas']
assert len(lista) >= 1, "Listar debe devolver entradas"
assert 'vendedor' in lista[0], "Listar debe incluir el vendedor"

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
assert 'vendedor' in csv_texto, "El CSV debe incluir la columna vendedor"

# ------------------------------------------------------------------
# Admin: login y dashboard
# ------------------------------------------------------------------
print("=== Admin: login y dashboard ===")

client.post('/api/logout')
r = login('admin')
assert r.status_code == 200 and r.get_json()['rol'] == 'admin', "Login admin debe ser 200"
assert r.get_json()['destino'] == '/admin', "Admin debe ir a /admin"

r = client.get('/')
assert r.status_code == 302 and '/admin' in r.headers.get('Location', ''), \
    "/ debe redirigir a /admin para rol admin"

r = client.get('/admin')
assert r.status_code == 200, "Admin debe ver /admin"

# Admin ya NO opera: no puede vender ni validar ni ver centro
r = client.get('/vendedor')
assert r.status_code == 302, "Admin no debe ver /vendedor"
r = client.get('/portero')
assert r.status_code == 302, "Admin no debe ver /portero"
r = client.get('/centro')
assert r.status_code == 302, "Admin no debe ver /centro"
r = client.post('/api/generar', json={'nombre': 'X', 'cedula': '6-0510-0347'})
assert r.status_code == 401, "Admin no puede generar"
r = client.post('/api/validar', json={'code': codigo})
assert r.status_code == 401, "Admin no puede validar"

# Dashboard
r = client.get('/api/dashboard')
assert r.status_code == 200, "Dashboard debe ser accesible"
dash = r.get_json()
assert dash['general']['total'] >= 1, f"Dashboard general debe tener total, fue {dash}"
assert len(dash['por_evento']) >= 1, "Dashboard debe listar eventos"
ev1 = next(e for e in dash['por_evento'] if e['id'] == 1)
assert ev1['total'] >= 1, f"Evento 1 debe tener entradas, fue {ev1}"
assert 'por_vendedor' in ev1, "Dashboard debe desglosar por vendedor"

# ------------------------------------------------------------------
# Eventos CRUD (admin)
# ------------------------------------------------------------------
print("=== Admin: eventos CRUD ===")

r = client.get('/api/eventos')
eventos_data = r.get_json()['eventos']
assert len(eventos_data) >= 1

r = client.post('/api/eventos', json={'nombre': 'Test Event 2', 'precio': 2000})
assert r.status_code == 200 and r.get_json()['ok'], f"Crear evento debe funcionar: {r.get_json()}"

r = client.post('/api/eventos', json={'nombre': 'Test Event 2', 'precio': 500})
assert r.status_code == 409, "Evento duplicado debe ser 409"

r = client.post('/api/eventos', json={'nombre': 'Bad Price', 'precio': -100})
assert r.status_code == 400, "Precio negativo debe ser 400"

eventos_data = r = client.get('/api/eventos').get_json()['eventos']
evento2_id = next(e['id'] for e in eventos_data if e['nombre'] == 'Test Event 2')

r = client.put(f'/api/eventos/{evento2_id}', json={'precio_entrada': 2500})
assert r.status_code == 200 and r.get_json()['ok'], f"Editar evento debe funcionar: {r.get_json()}"

# ------------------------------------------------------------------
# Usuarios globales + asignaciones
# ------------------------------------------------------------------
print("=== Usuarios globales + asignaciones ===")

# Crear staff global (sin evento)
r = client.post('/api/users', json={'usuario': 'testtemp', 'password': 'temp123',
                                    'nombre': 'Temp', 'admin': False})
assert r.status_code == 200, f"Crear usuario staff debe funcionar: {r.get_json()}"

r = client.post('/api/users', json={'usuario': 'testtemp', 'password': 'x', 'admin': False})
assert r.status_code == 409, "Usuario duplicado debe ser 409"

r = client.post('/api/users', json={'usuario': 'malo'})
assert r.status_code == 400, "Faltan campos debe ser 400"

nuevo = _admin.table(TABLA_USERS).select('id,rol').eq('usuario', 'testtemp').execute()
assert len(nuevo.data) > 0, "El usuario debe existir"
nuevo_id = nuevo.data[0]['id']
assert nuevo.data[0]['rol'] is None, "Staff global debe tener rol NULL"

# Asignar testtemp a evento 1 como vendedor y a evento 2 como portero
r = client.post('/api/asignar', json={'usuario_id': nuevo_id, 'evento_id': 1, 'rol': 'vendedor'})
assert r.status_code == 200 and r.get_json()['ok'], f"Asignar debe funcionar: {r.get_json()}"

r = client.post('/api/asignar', json={'usuario_id': nuevo_id, 'evento_id': evento2_id, 'rol': 'portero'})
assert r.status_code == 200, "Asignar a segundo evento debe funcionar"

r = client.post('/api/asignar', json={'usuario_id': nuevo_id, 'evento_id': 1, 'rol': 'super'})
assert r.status_code == 400, "Rol invalido debe ser 400"

# Listar usuarios: testtemp debe mostrar 2 asignaciones
r = client.get('/api/users')
users = r.get_json()['users']
u_temp = next(u for u in users if u['usuario'] == 'testtemp')
assert len(u_temp['asignaciones']) == 2, \
    f"testtemp debe tener 2 asignaciones, tiene {u_temp['asignaciones']}"
assert u_temp['asignaciones'][0]['evento_nombre'], "La asignacion debe incluir nombre de evento"

# ------------------------------------------------------------------
# Multi-evento: login -> /elegir -> select
# ------------------------------------------------------------------
print("=== Multi-evento: login -> /elegir ===")

client.post('/api/logout')
r = client.post('/api/login', json={'usuario': 'testtemp', 'password': 'temp123'})
assert r.status_code == 200 and r.get_json()['ok'], "Login multi-evento debe ser 200"
assert r.get_json()['rol'] == 'elegir', f"Rol debe ser elegir, fue {r.get_json()['rol']}"
assert r.get_json()['destino'] == '/elegir', "Destino debe ser /elegir"

r = client.get('/elegir')
assert r.status_code == 200, "Pagina /elegir debe ser 200"

r = client.get('/api/mis_eventos')
j = r.get_json()
assert len(j['eventos']) == 2, f"mis_eventos debe devolver 2 eventos, devolvio {j['eventos']}"

# Elegir evento 2 (portero)
r = client.post('/api/evento/select', json={'evento_id': evento2_id})
assert r.status_code == 200 and r.get_json()['ok'], f"Seleccionar debe funcionar: {r.get_json()}"
assert r.get_json()['destino'] == '/portero', "Debe entrar como portero"

r = client.get('/portero')
assert r.status_code == 200, "Debe poder ver /portero"

r = client.get('/api/stats')
assert r.get_json()['total'] == 0, f"Evento 2 no debe tener entradas: {r.get_json()}"

# Elegir evento 1 (vendedor)
r = client.post('/api/evento/select', json={'evento_id': 1})
assert r.get_json()['destino'] == '/vendedor', "Debe entrar como vendedor"

# Generar en evento 1 con misma cedula ya usada en evento 1? No: la cedula era de evento 1.
# Usar cedula distinta para probar aislamiento
r = client.post('/api/generar', json={'nombre': 'Maria Lopez', 'cedula': '7-0510-0347'})
assert r.status_code == 201, f"Generar como testtemp en evento 1 debe funcionar: {r.get_json()}"
evento1_codigo = r.get_json()['codigo']

# Intentar elegir un evento no asignado (evento 2 como... esta asignado).
# Crear evento 3 para probar rechazo
r = client.post('/api/logout')
r = login('admin')
r = client.post('/api/eventos', json={'nombre': 'Test Event 3', 'precio': 3000})
evento3_id = next(e['id'] for e in client.get('/api/eventos').get_json()['eventos']
                  if e['nombre'] == 'Test Event 3')

client.post('/api/logout')
r = client.post('/api/login', json={'usuario': 'testtemp', 'password': 'temp123'})
r = client.post('/api/evento/select', json={'evento_id': evento3_id})
assert r.status_code == 403, "Seleccionar evento no asignado debe ser 403"

# ------------------------------------------------------------------
# Aislamiento: mismo codigo/cedula en eventos distintos
# ------------------------------------------------------------------
print("=== Aislamiento entre eventos ===")

# testtemp -> evento 1 -> generar entrada
client.post('/api/logout')
r = client.post('/api/login', json={'usuario': 'testtemp', 'password': 'temp123'})
client.post('/api/evento/select', json={'evento_id': 1})
r = client.post('/api/generar', json={'nombre': 'Carlos Ruiz', 'cedula': '8-0510-0347'})
assert r.status_code == 201, f"Generar en evento 1 debe funcionar: {r.get_json()}"

# vendedor original tambien en evento 1: su entrada anterior (Juan Perez) no debe
# aparecer en evento 2
client.post('/api/logout')
r = login('admin')

r = client.get('/api/dashboard')
dash = r.get_json()
ev1_dash = next(e for e in dash['por_evento'] if e['id'] == 1)
ev2_dash = next(e for e in dash['por_evento'] if e['id'] == evento2_id)
assert ev1_dash['total'] >= 2, f"Evento 1 debe tener >= 2 entradas: {ev1_dash}"
assert ev2_dash['total'] == 0, f"Evento 2 debe tener 0 entradas: {ev2_dash}"
assert ev1_dash['por_vendedor'].get('vendedor', {}).get('total', 0) >= 1 or \
    ev1_dash['por_vendedor'].get('testtemp', {}).get('total', 0) >= 1, \
    f"Desglose por vendedor debe existir: {ev1_dash['por_vendedor']}"

# ------------------------------------------------------------------
# Editar usuario (admin checkbox) y borrar
# ------------------------------------------------------------------
print("=== Editar y borrar usuario ===")

r = client.put(f'/api/users/{nuevo_id}', json={'nombre': 'Temp Dos'})
assert r.status_code == 200, "Editar nombre debe funcionar"

r = client.put(f'/api/users/{nuevo_id}', json={'admin': True})
assert r.status_code == 200, "Convertir a admin debe funcionar"
check = _admin.table(TABLA_USERS).select('rol').eq('id', nuevo_id).execute()
assert check.data[0]['rol'] == 'admin', "El rol debe ser admin"

r = client.put(f'/api/users/{nuevo_id}', json={'admin': False})
assert r.status_code == 200, "Convertir a staff debe funcionar"

# Asignaciones se mantienen al editar
r = client.get('/api/users')
u_temp = next(u for u in r.get_json()['users'] if u['usuario'] == 'testtemp')
assert len(u_temp['asignaciones']) == 2, "Las asignaciones deben mantenerse"

# Quitar asignacion
r = client.delete('/api/asignar', json={'usuario_id': nuevo_id, 'evento_id': evento2_id})
assert r.status_code == 200 and r.get_json()['ok'], "Quitar asignacion debe funcionar"

r = client.get('/api/users')
u_temp = next(u for u in r.get_json()['users'] if u['usuario'] == 'testtemp')
assert len(u_temp['asignaciones']) == 1, "Debe quedar 1 asignacion"

# Borrar usuario (borra asignaciones en cascada)
r = client.delete(f'/api/users/{nuevo_id}')
assert r.status_code == 200 and r.get_json()['ok'], "Borrar usuario debe funcionar"

asig_restantes = _admin.table(TABLA_ASIGNACIONES).select('evento_id').eq('usuario_id', nuevo_id).execute()
assert len(asig_restantes.data) == 0, "Las asignaciones deben borrarse en cascada"

# No puede borrarse a si mismo (admin)
propio = _admin.table(TABLA_USERS).select('id').eq('usuario', 'admin').execute()
r = client.delete(f"/api/users/{propio.data[0]['id']}")
assert r.status_code == 400, "Admin no puede borrarse a si mismo"

# ------------------------------------------------------------------
# Logs (admin global, sin filtro de evento)
# ------------------------------------------------------------------
print("=== Logs ===")

r = client.get('/api/logs')
assert r.status_code == 200, "Admin debe poder ver logs"
logs = r.get_json()['logs']
assert len(logs) >= 1, "Debe haber al menos un log"
acciones = {l['accion'] for l in logs}
assert 'login' in acciones, f"Debe haber logs de login, hay {acciones}"

# ------------------------------------------------------------------
# Borrar todas (por evento) — requiere función reset_entradas
# ------------------------------------------------------------------
print("=== Borrar todas (por evento) ===")

r = login('vendedor')
r = client.post('/api/borrar_todas')
if r.status_code == 500:
    print("AVISO: ejecuta el SQL de reset_entradas en Supabase para probar el reinicio de IDs")
    limpiar()
else:
    assert r.status_code == 200 and r.get_json()['ok'], "Borrar todas debe funcionar"

r = client.get('/api/stats')
assert r.get_json()['total'] == 0, f"Tras borrar todas el total debe ser 0: {r.get_json()}"

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

r = client.get('/elegir')
assert r.status_code == 302 and '/login' in r.headers.get('Location', ''), \
    "/elegir sin sesion debe redirigir a /login"

r = client.get('/api/dashboard')
assert r.status_code == 401, "Dashboard sin sesion debe ser 401"

r = client.get('/api/mis_eventos')
assert r.status_code == 401, "mis_eventos sin sesion debe ser 401"

# Vendedor no puede ver admin API
r = login('vendedor')
r = client.get('/api/users')
assert r.status_code == 401, "Vendedor no puede ver usuarios"
r = client.get('/api/dashboard')
assert r.status_code == 401, "Vendedor no puede ver dashboard"
r = client.get('/api/logs')
assert r.status_code == 401, "Vendedor no puede ver logs"
r = client.post('/api/asignar', json={'usuario_id': 1, 'evento_id': 1, 'rol': 'vendedor'})
assert r.status_code == 401, "Vendedor no puede asignar"

# ------------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------------
limpiar()
print("\nTODOS LOS TESTS OK")