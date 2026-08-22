-- ============================================================
-- Schema: Sistema de Venta y Validacion de Entradas — Multi-Evento
-- --------------------------------------------------------------
-- Tablas: colegios, eventos, entradas, users, evento_usuarios, logs
--
-- Modelo de usuarios:
--   users.rol = 'admin'  -> administrador
--     users.colegio_id NULL  -> admin GENERAL (ve todos los colegios)
--     users.colegio_id = X   -> admin de ESE colegio (solo lo suyo)
--   users.rol = NULL     -> staff (vendedor/portero) asignado a
--                           eventos via evento_usuarios
--
-- Este archivo refleja el estado ACTUAL de la base: sirve para
-- instalar desde cero. Las migraciones incrementales estan en
-- supabase/migrations/ (aplicarlas en orden de fecha).
-- ============================================================

-- 1) Extension para busqueda ILIKE '%...%' rapida
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------
-- 2) Tabla de colegios (multi-colegio)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS colegios (
    id        SERIAL PRIMARY KEY,
    nombre    TEXT NOT NULL UNIQUE,
    creado_en TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------
-- 3) Tabla de eventos (el agregador principal)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eventos (
    id              SERIAL PRIMARY KEY,
    nombre          TEXT NOT NULL UNIQUE,
    precio_entrada  INTEGER NOT NULL DEFAULT 1000 CHECK (precio_entrada >= 0),
    activo          BOOLEAN DEFAULT true,
    colegio_id      INTEGER REFERENCES colegios(id) ON DELETE SET NULL,
    creado_en       TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------
-- 4) Tabla de entradas (asociada a un evento)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entradas (
    id          SERIAL PRIMARY KEY,
    codigo      TEXT NOT NULL,
    usado       BOOLEAN NOT NULL DEFAULT false,
    nombre      TEXT NOT NULL,
    cedula      TEXT NOT NULL,
    precio      INTEGER DEFAULT 0,
    vendedor    TEXT,
    evento_id   INTEGER NOT NULL REFERENCES eventos(id) ON DELETE CASCADE,
    creado_en   TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now(),

    -- Unicidad por evento: mismo codigo/nombre/cedula NO puede repetirse dentro del mismo evento
    UNIQUE (evento_id, codigo),
    UNIQUE (evento_id, nombre),
    UNIQUE (evento_id, cedula)
);

-- ---------------------------------------------------------------
-- 5) Tabla de usuarios (global; el staff se asigna por evento)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    usuario       TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    rol           TEXT CHECK (rol = 'admin' OR rol IS NULL),
    nombre        TEXT DEFAULT '',
    colegio_id    INTEGER REFERENCES colegios(id) ON DELETE SET NULL,
    creado_en     TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------
-- 6) Tabla de asignacion usuario <-> evento (staff)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evento_usuarios (
    evento_id   INTEGER NOT NULL REFERENCES eventos(id) ON DELETE CASCADE,
    usuario_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rol         TEXT NOT NULL CHECK (rol IN ('vendedor', 'portero')),
    creado_en   TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (evento_id, usuario_id)
);

-- ---------------------------------------------------------------
-- 7) Tabla de logs (registro de actividad; evento_id NULL = admin)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS logs (
    id          SERIAL PRIMARY KEY,
    accion      TEXT NOT NULL,
    detalle     TEXT NOT NULL DEFAULT '',
    usuario     TEXT NOT NULL DEFAULT '',
    evento_id   INTEGER REFERENCES eventos(id) ON DELETE SET NULL,
    creado_en   TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------
-- 8) Indices
-- ---------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_usuario
    ON users (usuario);
CREATE INDEX IF NOT EXISTS idx_users_colegio
    ON users (colegio_id);
CREATE INDEX IF NOT EXISTS idx_eventos_colegio
    ON eventos (colegio_id);

-- Entradas: conteos del dashboard, validacion en puerta y stats por vendedor
CREATE INDEX IF NOT EXISTS idx_entradas_evento_usado
    ON entradas (evento_id, usado);
CREATE INDEX IF NOT EXISTS idx_entradas_evento_vendedor
    ON entradas (evento_id, vendedor);
CREATE INDEX IF NOT EXISTS idx_entradas_nombre_trgm
    ON entradas USING GIN (nombre gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_entradas_cedula_trgm
    ON entradas USING GIN (cedula gin_trgm_ops);

-- Logs: listado por evento y actividad reciente
CREATE INDEX IF NOT EXISTS idx_logs_evento_id
    ON logs (evento_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_logs_creado
    ON logs (creado_en DESC);

-- Asignaciones en ambas direcciones
CREATE INDEX IF NOT EXISTS idx_asignaciones_usuario
    ON evento_usuarios (usuario_id);
CREATE INDEX IF NOT EXISTS idx_asignaciones_evento
    ON evento_usuarios (evento_id);

-- ---------------------------------------------------------------
-- 9) updated_at automatico + proteccion del ultimo admin
-- ---------------------------------------------------------------
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
    IF TG_OP = 'UPDATE' AND OLD.rol = 'admin' AND NEW.rol IS DISTINCT FROM 'admin' THEN
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

-- ---------------------------------------------------------------
-- 10) Datos iniciales
-- ---------------------------------------------------------------
-- Evento por defecto
INSERT INTO eventos (nombre, precio_entrada)
    VALUES ('Baile CTPM 2026', 1000)
    ON CONFLICT (nombre) DO NOTHING;

-- Admin GENERAL (colegio_id = NULL -> controla todos los colegios)
INSERT INTO users (usuario, password_hash, rol, nombre)
    VALUES ('admin', 'scrypt:32768:8:1$uDAYSjOA6oLsc0xo$eb8c27961fa79fccc48234860ce9cd260b6b8d47817a1e7363d6fed5e4e671e8ee0e5e8439a6b727dc7c69a0076e8497468871d5db75ed26550e54ecc979adb6',
            'admin', 'Admin')
    ON CONFLICT (usuario) DO NOTHING;
