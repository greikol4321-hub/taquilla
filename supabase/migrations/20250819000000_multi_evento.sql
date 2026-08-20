-- Migracion: Multi-Evento (para bases existentes)
-- Combina migrar_multievento.sql + optimizacion.sql

-- 1) Extension
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2) Tabla de eventos
CREATE TABLE IF NOT EXISTS eventos (
    id              SERIAL PRIMARY KEY,
    nombre          TEXT NOT NULL UNIQUE,
    precio_entrada  INTEGER NOT NULL DEFAULT 1000 CHECK (precio_entrada >= 0),
    activo          BOOLEAN DEFAULT true,
    creado_en       TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- 3) Agregar columnas a tablas existentes
ALTER TABLE entradas ADD COLUMN IF NOT EXISTS evento_id INTEGER REFERENCES eventos(id) ON DELETE CASCADE;
ALTER TABLE entradas ADD COLUMN IF NOT EXISTS precio INTEGER DEFAULT 0;
ALTER TABLE entradas ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();
ALTER TABLE users ADD COLUMN IF NOT EXISTS evento_id INTEGER REFERENCES eventos(id) ON DELETE SET NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS creado_en TIMESTAMPTZ DEFAULT now();
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();
ALTER TABLE logs ADD COLUMN IF NOT EXISTS evento_id INTEGER REFERENCES eventos(id) ON DELETE SET NULL;

-- 4) Crear evento por defecto y asociar datos existentes
INSERT INTO eventos (nombre, precio_entrada) VALUES ('Baile CTPM 2026', 1000)
    ON CONFLICT (nombre) DO NOTHING;

UPDATE entradas SET evento_id = 1 WHERE evento_id IS NULL;
UPDATE users SET evento_id = 1 WHERE evento_id IS NULL AND rol != 'admin';

-- 5) Migrar precio de entradas existentes
UPDATE entradas e SET precio = (SELECT precio_entrada FROM eventos WHERE id = e.evento_id)
    WHERE e.precio IS NULL OR e.precio = 0;

-- 6) Cambiar constraint de unique: codigo global → (evento_id, codigo)
ALTER TABLE entradas DROP CONSTRAINT IF EXISTS entradas_codigo_key;
DROP INDEX IF EXISTS idx_entradas_codigo;
CREATE UNIQUE INDEX IF NOT EXISTS idx_entradas_codigo_evento ON entradas (evento_id, codigo);

-- 7) Cambiar unique de usuario: usuario global → parciales
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_usuario_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_usuario_global
    ON users (usuario) WHERE evento_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_usuario_evento
    ON users (evento_id, usuario) WHERE evento_id IS NOT NULL;

-- 8) Asegurar que admin existente tenga evento_id = NULL
UPDATE users SET evento_id = NULL WHERE rol = 'admin';

-- 9) Indices por evento
CREATE INDEX IF NOT EXISTS idx_entradas_evento_usado ON entradas (evento_id, usado);
CREATE INDEX IF NOT EXISTS idx_entradas_evento_nombre_trgm ON entradas USING GIN (nombre gin_trgm_ops) WHERE evento_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_entradas_evento_cedula_trgm ON entradas USING GIN (cedula gin_trgm_ops) WHERE evento_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_eventos_activo ON eventos (activo);
CREATE INDEX IF NOT EXISTS idx_logs_evento ON logs (evento_id);
CREATE INDEX IF NOT EXISTS idx_logs_creado ON logs (creado_en DESC);
CREATE INDEX IF NOT EXISTS idx_logs_usuario ON logs (usuario);
CREATE INDEX IF NOT EXISTS idx_users_evento_rol ON users (evento_id, rol);

-- 10) updated_at automatico en entradas, users y eventos
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

DROP TRIGGER IF EXISTS trg_eventos_updated ON eventos;
CREATE TRIGGER trg_eventos_updated BEFORE UPDATE ON eventos
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 11) Proteccion: no se puede borrar ni degradar al ultimo admin
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

-- 12) reset_entradas parametrizado por evento
CREATE OR REPLACE FUNCTION reset_entradas(p_evento_id INTEGER DEFAULT NULL) RETURNS void AS $$
BEGIN
    IF p_evento_id IS NOT NULL THEN
        DELETE FROM entradas WHERE evento_id = p_evento_id;
        EXECUTE 'SELECT setval(pg_get_serial_sequence(''entradas'',''id''), COALESCE((SELECT MAX(id) FROM entradas), 1) + 1, false)';
    ELSE
        TRUNCATE entradas RESTART IDENTITY;
    END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
