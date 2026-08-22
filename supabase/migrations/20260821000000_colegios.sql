-- ============================================================
-- MIGRACIÓN: MULTI-COLEGIO
-- Ejecutar en: Supabase Dashboard → SQL Editor → Run
-- ============================================================
-- Cada evento pertenece a un colegio.
-- users.colegio_id:
--   NULL          -> admin GENERAL (controla todos los colegios)
--   colegio_id=X  -> admin de ESE colegio (solo ve sus eventos)

CREATE TABLE IF NOT EXISTS colegios (
  id        SERIAL PRIMARY KEY,
  nombre    TEXT NOT NULL UNIQUE,
  creado_en TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE eventos ADD COLUMN IF NOT EXISTS colegio_id INT REFERENCES colegios(id) ON DELETE SET NULL;
ALTER TABLE users   ADD COLUMN IF NOT EXISTS colegio_id INT REFERENCES colegios(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_eventos_colegio ON eventos (colegio_id);
CREATE INDEX IF NOT EXISTS idx_users_colegio   ON users (colegio_id);

-- Verificación (debe devolver las 2 columnas nuevas):
-- SELECT column_name FROM information_schema.columns
--  WHERE table_name IN ('eventos','users') AND column_name = 'colegio_id';
