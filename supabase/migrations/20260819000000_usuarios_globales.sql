-- Migracion: Usuarios globales + asignacion por evento
-- users pasa a ser global: rol 'admin' (global) o NULL (staff).
-- El staff se asigna a eventos con rol vendedor/portero via evento_usuarios.

-- 1) Tabla de asignacion usuario <-> evento
CREATE TABLE IF NOT EXISTS evento_usuarios (
    evento_id   INTEGER NOT NULL REFERENCES eventos(id) ON DELETE CASCADE,
    usuario_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rol         TEXT NOT NULL CHECK (rol IN ('vendedor', 'portero')),
    creado_en   TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (evento_id, usuario_id)
);

-- 2) Migrar usuarios existentes (vendedor/portero con evento_id) a asignaciones
INSERT INTO evento_usuarios (evento_id, usuario_id, rol)
SELECT evento_id, id, rol FROM users
WHERE evento_id IS NOT NULL AND rol IN ('vendedor', 'portero')
ON CONFLICT DO NOTHING;

-- 3) Staff pierde el rol global; solo admin lo conserva
ALTER TABLE users ALTER COLUMN rol DROP NOT NULL;
UPDATE users SET rol = NULL WHERE rol IN ('vendedor', 'portero');

-- 4) Quitar evento_id de users (indices parciales primero)
DROP INDEX IF EXISTS idx_users_usuario_evento;
DROP INDEX IF EXISTS idx_users_usuario_global;
DROP INDEX IF EXISTS idx_users_evento_rol;
ALTER TABLE users DROP COLUMN IF EXISTS evento_id;

-- 5) Usuario unico global (deduplicar primero: se queda el de menor id)
UPDATE users SET usuario = usuario || '_' || id
WHERE id IN (
    SELECT u2.id FROM users u2
    JOIN (SELECT usuario FROM users GROUP BY usuario HAVING count(*) > 1) d
      ON d.usuario = u2.usuario
    WHERE u2.id <> (SELECT MIN(id) FROM users WHERE usuario = u2.usuario)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_usuario ON users (usuario);

-- 6) Registrar quien vendio cada entrada (centro de datos por vendedor)
ALTER TABLE entradas ADD COLUMN IF NOT EXISTS vendedor TEXT;
CREATE INDEX IF NOT EXISTS idx_entradas_evento_vendedor ON entradas (evento_id, vendedor);