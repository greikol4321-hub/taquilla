# Taquilla — Sistema de Entradas QR

Vendedor / Portero / Admin por Lugar. Flask + Supabase + Vercel.

## Estructura ordenada
```
Entradas/
├── app.py              # Flask app + cache TTL + APIs
├── api/
│   ├── index.py        # Entry Vercel (from app import app)
│   └── requirements.txt
├── templates/          # Jinja2 (base, login, elegir, vendedor, portero, centro, admin)
├── supabase/
│   ├── config.toml
│   └── migrations/     # SQL versionado (colegios→lugares, índices, RLS)
├── rls.sql             # Row Level Security (ejecutar en Supabase SQL Editor)
├── schema.sql          # Esquema completo para instalar desde cero
├── requirements.txt    # deps Python
├── vercel.json         # headers cache
└── .env                # local (no se commitea)
```

## Deploy
- Env vars en Vercel: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SECRET_KEY`
- Push a `master` → deploy automático (12s) a `taquilla-quepos.vercel.app`

## Roles
- `grei` admin general (ve todo)
- Admins de Lugar crean eventos y staff de su lugar
- Vendedores generan QR, porteros validan

## Notas
- Cache: `private, max-age=8, stale-while-revalidate=20` + `sessionStorage` por evento/usuario
- Cámara portero: fallback `environment → user → true`, Html5Qrcode con CDN dinámico
