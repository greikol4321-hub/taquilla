-- ============================================================
-- Optimizacion de base + triggers (Baile CTPM 2026)
-- ============================================================

-- 1) Extension trigram: acelera las busquedas ILIKE '%...%'
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2) Indices
CREATE UNIQUE INDEX IF NOT EXISTS idx_entradas_codigo ON entradas (codigo);
CREATE INDEX IF NOT EXISTS idx_entradas_nombre_trgm ON entradas USING GIN (nombre gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_entradas_cedula_trgm ON entradas USING GIN (cedula gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_entradas_usado ON entradas (usado);
CREATE INDEX IF NOT EXISTS idx_logs_creado ON logs (creado_en DESC);
CREATE INDEX IF NOT EXISTS idx_logs_usuario ON logs (usuario);
CREATE INDEX IF NOT EXISTS idx_users_rol ON users (rol);

-- 3) updated_at automatico en entradas y users
ALTER TABLE entradas ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_entradas_updated ON entradas;
CREATE TRIGGER trg_entradas_updated BEFORE UPDATE ON entradas
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_users_updated ON users;
CREATE TRIGGER trg_users_updated BEFORE UPDATE ON users
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 4) Proteccion: no se puede borrar ni degradar al ultimo admin
CREATE OR REPLACE FUNCTION proteger_ultimo_admin() RETURNS trigger AS $$
DECLARE
  admins INT;
BEGIN
  IF TG_OP = 'DELETE' AND OLD.rol = 'admin' THEN
    SELECT count(*) INTO admins FROM users WHERE rol = 'admin';
    IF admins <= 1 THEN
      RAISE EXCEPTION 'No se puede borrar al ultimo admin';
    END IF;
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.rol = 'admin' AND NEW.rol <> 'admin' THEN
    SELECT count(*) INTO admins FROM users WHERE rol = 'admin';
    IF admins <= 1 THEN
      RAISE EXCEPTION 'No se puede degradar al ultimo admin';
    END IF;
  END IF;
  RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_users_proteger_admin ON users;
CREATE TRIGGER trg_users_proteger_admin BEFORE UPDATE OR DELETE ON users
  FOR EACH ROW EXECUTE FUNCTION proteger_ultimo_admin();

-- 5) reset_entradas mas rapido (TRUNCATE reinicia IDs al instante)
CREATE OR REPLACE FUNCTION reset_entradas() RETURNS void AS $$
BEGIN
  TRUNCATE entradas RESTART IDENTITY;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;