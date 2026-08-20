-- ============================================================
-- Migracion: Multi-Evento (para bases existentes)
-- --------------------------------------------------------------
-- Ejecuta este script si ya tenias las tablas antiguas
-- (entradas, users, logs sin evento_id).
-- ============================================================

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

-- 3) Agregar evento_id a tablas existentes
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

-- Asociar entradas existentes al evento por defecto (id=1)
UPDATE entradas SET evento_id = 1 WHERE evento_id IS NULL;
-- Asociar usuarios existentes (no admin) al evento por defecto
UPDATE users SET evento_id = 1 WHERE evento_id IS NULL AND rol != 'admin';
-- Admin global: evento_id = NULL (ya está)

-- 5) Migrar el precio default de entradas existentes al precio del evento
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
