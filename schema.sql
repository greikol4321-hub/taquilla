-- ============================================================
-- Schema: Sistema de Venta y Validacion de Entradas — Multi-Evento
-- --------------------------------------------------------------
-- Tablas: eventos, entradas, users, logs
-- Un "admin general" gestiona varios eventos desde un solo panel.
-- Cada evento tiene su propio precio, usuarios (vendedor/portero)
-- y entradas. Los datos se filtran por evento_id en cada query.
-- ============================================================

-- 1) Extension para busqueda ILIKE '%...%' rapida
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------
-- 2) Tabla de eventos (el agregador principal)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eventos (
    id              SERIAL PRIMARY KEY,
    nombre          TEXT NOT NULL UNIQUE,
    precio_entrada  INTEGER NOT NULL DEFAULT 1000 CHECK (precio_entrada >= 0),
    activo          BOOLEAN DEFAULT true,
    creado_en       TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------
-- 3) Tabla de entradas (asociada a un evento)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entradas (
    id          SERIAL PRIMARY KEY,
    codigo      TEXT NOT NULL,
    usado       BOOLEAN NOT NULL DEFAULT false,
    nombre      TEXT NOT NULL,
    cedula      TEXT NOT NULL,
    precio      INTEGER DEFAULT 0,
    evento_id   INTEGER NOT NULL REFERENCES eventos(id) ON DELETE CASCADE,
    creado_en   TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now(),

    -- Unicidad por evento: mismo codigo/nombre/cedula NO puede repetirse dentro del mismo evento
    UNIQUE (evento_id, codigo),
    UNIQUE (evento_id, nombre),
    UNIQUE (evento_id, cedula)
);

-- ---------------------------------------------------------------
-- 4) Tabla de usuarios (rol por evento; admin global = evento_id NULL)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    usuario       TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    rol           TEXT NOT NULL CHECK (rol IN ('vendedor', 'portero', 'admin')),
    nombre        TEXT DEFAULT '',
    evento_id     INTEGER REFERENCES eventos(id) ON DELETE SET NULL,
    creado_en     TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now()
);

-- Unique parciales: admins globales (evento_id IS NULL) unicos por usuario;
-- usuarios por evento unicos por (evento_id, usuario)
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_usuario_global
    ON users (usuario) WHERE evento_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_usuario_evento
    ON users (evento_id, usuario) WHERE evento_id IS NOT NULL;

-- ---------------------------------------------------------------
-- 5) Tabla de logs (asociada a un evento; NULL = admin global)
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
-- 6) Datos iniciales
-- ---------------------------------------------------------------
-- Evento por defecto (el que se usaba antes como "Baile CTPM 2026")
INSERT INTO eventos (nombre, precio_entrada)
    VALUES ('Baile CTPM 2026', 1000)
    ON CONFLICT (nombre) DO NOTHING;

-- Admin global (evento_id = NULL → acceso a todos los eventos)
INSERT INTO users (usuario, password_hash, rol, nombre, evento_id)
    VALUES ('admin', 'scrypt:32768:8:1$uDAYSjOA6oLsc0xo$eb8c27961fa79fccc48234860ce9cd260b6b8d47817a1e7363d6fed5e4e671e8ee0e5e8439a6b727dc7c69a0076e8497468871d5db75ed26550e54ecc979adb6',
            'admin', 'Admin', NULL)
    ON CONFLICT (usuario) DO UPDATE
        SET rol = EXCLUDED.rol, evento_id = NULL
        WHERE users.rol IS DISTINCT FROM EXCLUDED.rol
           OR users.evento_id IS DISTINCT FROM EXCLUDED.evento_id;

-- Usuarios por evento (asociados al evento por defecto)
INSERT INTO users (usuario, password_hash, rol, nombre, evento_id)
    VALUES
        ('vendedor', 'scrypt:32768:8:1$gmBfKNaZHR4ztQQX$7c6a66e56ca8493345fe28aa512685bf05258a0487322ff7a6233055a6e838a2c73f0b66f0a57c7551ada20e845b96f4fff86c6d993aba3cb3bbaa7fa875253f',
         'vendedor', 'Vendedor', 1),
        ('portero',  'scrypt:32768:8:1$CAxlpGgoLdDmPW5n$66d9bff05013c75c21351f4eda3be7d5cbf7d72f56304b0b688502583667a251c265eeeb280b0dfa78b3859635adb626924e3ed3eb641e2068b297a07ed28c97',
         'portero', 'Portero', 1)
    ON CONFLICT (usuario) DO UPDATE
        SET evento_id = EXCLUDED.evento_id
        WHERE users.evento_id IS DISTINCT FROM EXCLUDED.evento_id;
