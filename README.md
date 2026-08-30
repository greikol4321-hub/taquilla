# Taquilla — Entradas QR por lugar

Vende y valida entradas con QR por sede. Cada lugar ve solo lo suyo.

Flask + Supabase + Vercel. Sin enredos.

## Qué hace

- **Vendedor** genera la entrada con QR para su evento.
- **Portero** escanea en puerta con la cámara, suena chime y marca como usada.
- **Admin de lugar** crea eventos y su equipo (vendedores/porteros) de su sede.
- **Admin general** ve todo, crea lugares y usuarios.

Todo queda con su sede. Un portero de Quepos no ve lo de Matapalo.

## Demo

`https://taquilla-quepos.vercel.app` — elige lugar, entra como vendedor o portero y prueba.

## Cómo correr local

```bash
pip install -r requirements.txt
cp .env.example .env  # pon SUPABASE_URL, SUPABASE_SERVICE_KEY, SECRET_KEY
python app.py  # http://127.0.0.1:5000
```

Push a `master` despliega solo a Vercel (12s).

## Estructura

```
Entradas/
  app.py            # Flask + APIs
  api/index.py      # entry Vercel
  templates/        # base, login, elegir lugar, vendedor, portero, admin
  supabase/migrations/  # SQL versionado
  schema.sql        # esquema completo
  requirements.txt
  vercel.json
```

Notas: `private, max-age=8` + `sessionStorage` por evento. Cámara con fallback `environment → user`.
