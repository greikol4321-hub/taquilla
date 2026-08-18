import json
import urllib.request
import urllib.error
import http.cookiejar

BASE = 'https://fiesta-anual-2026.vercel.app'

cj = http.cookiejar.CookieJar()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), NoRedirect)


def req(path, payload=None, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    if method is None:
        method = 'POST' if payload is not None else 'GET'
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={'Content-Type': 'application/json'} if data else {})
    try:
        resp = opener.open(r, timeout=25)
        return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


# 1. Sin sesion: raiz redirige a login
try:
    r = opener.open(BASE + '/', timeout=25)
    raise AssertionError(f"Raiz deberia redirigir, dio {r.status}")
except urllib.error.HTTPError as e:
    assert e.code == 302 and '/login' in e.headers['Location'], \
        f"Raiz debe redirigir a login: {e.code} {e.headers.get('Location')}"
    print('1. Raiz sin sesion ->', e.code, '->', e.headers['Location'])

# 2. Pagina de login
status, body = req('/login')
assert status == 200 and 'Contraseña' in body, f"Login page: {status}"
print('2. /login ->', status, '(contiene input password)')

# 3. Login incorrecto
status, body = req('/api/login', {'password': 'mal'})
assert status == 401, f"Login incorrecto: {status}"
print('3. Login incorrecto ->', status)

# 4. Login correcto
status, body = req('/api/login', {'password': 'admin2026'})
assert status == 200, f"Login correcto: {status} {body}"
print('4. Login correcto ->', status)

# 5. Generar
status, body = req('/api/generar', method='POST')
data = json.loads(body)
assert status == 201 and len(data['codigo']) == 8, f"Generar: {status} {body}"
print('5. Generar ->', status, data['codigo'])

# 6. Validar
status, body = req('/api/validar', {'code': data['codigo']})
assert status == 200 and json.loads(body)['estado'] == 'valido', f"Validar: {status} {body}"
print('6. Validar valido ->', status)

status, body = req('/api/validar', {'code': data['codigo']})
assert status == 409, f"Validar usado: {status}"
print('7. Validar usado ->', status)

# 8. Stats
status, body = req('/api/stats')
stats = json.loads(body)
assert status == 200 and stats['total'] >= 1, f"Stats: {status} {body}"
print('8. Stats ->', status, stats)

# 9. Listar
status, body = req('/api/listar')
assert status == 200 and len(json.loads(body)['entradas']) >= 1, f"Listar: {status}"
print('9. Listar ->', status, 'entradas OK')

# 10. Reset
status, body = req('/api/reset', {'codigo': data['codigo']})
assert status == 200, f"Reset: {status} {body}"
print('10. Reset ->', status)

# 11. Exportar
status, body = req('/api/exportar')
assert status == 200 and data['codigo'] in body, f"Exportar: {status}"
print('11. Exportar CSV ->', status, 'contiene codigo')

# 12. Logout y proteccion
status, body = req('/api/logout', method='POST')
assert status == 200, f"Logout: {status}"
status, body = req('/api/generar', method='POST')
assert status == 401, f"Generar tras logout: {status}"
print('12. Logout -> proteccion OK (401 tras salir)')

print('TODO OK EN PRODUCCION')