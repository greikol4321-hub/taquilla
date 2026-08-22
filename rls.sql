-- ============================================================
-- Seguridad: Row Level Security (RLS) en todas las tablas
-- Ejecutar en: Supabase Dashboard → SQL Editor → Run
--
-- ARQUITECTURA: TODO el acceso a datos pasa por el backend Flask,
-- que usa la SUPABASE_SERVICE_KEY (rol service_role, que ignora
-- RLS). Por eso la política correcta es DENEGAR todo acceso
-- directo con las keys anon/authenticated: sin políticas creadas,
-- RLS bloquea por defecto.
--
-- ⚠️ IMPORTANTE: ejecutar esto SOLO DESPUÉS de configurar
-- SUPABASE_URL y SUPABASE_SERVICE_KEY en Vercel y re-desplegar.
-- Si producción sigue usando la anon key, la app se cae.
-- ============================================================

ALTER TABLE colegios        ENABLE ROW LEVEL SECURITY;
ALTER TABLE eventos         ENABLE ROW LEVEL SECURITY;
ALTER TABLE entradas        ENABLE ROW LEVEL SECURITY;
ALTER TABLE users           ENABLE ROW LEVEL SECURITY;
ALTER TABLE evento_usuarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE logs            ENABLE ROW LEVEL SECURITY;

-- Defensa en profundidad: revocar también los privilegios directos
-- de las roles públicas del API de Supabase.
REVOKE ALL ON colegios, eventos, entradas, users, evento_usuarios, logs
    FROM anon, authenticated;

-- Verificación (todas deben decir row_security=on):
-- SELECT relname, relrowsecurity AS row_security
--   FROM pg_class WHERE relname IN
--   ('colegios','eventos','entradas','users','evento_usuarios','logs');
