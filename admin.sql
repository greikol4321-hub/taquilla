-- Tabla de logs (registro inmutable de todas las acciones)
CREATE TABLE IF NOT EXISTS logs (
  id SERIAL PRIMARY KEY,
  accion TEXT NOT NULL,
  detalle TEXT NOT NULL DEFAULT '',
  usuario TEXT NOT NULL DEFAULT '',
  creado_en TIMESTAMPTZ DEFAULT now()
);

-- Permitir rol 'admin' en la tabla users
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_rol_check;
ALTER TABLE users ADD CONSTRAINT users_rol_check CHECK (rol IN ('vendedor', 'portero', 'admin'));

-- Usuario admin inicial (admin2026)
INSERT INTO users (usuario, password_hash, rol, nombre) VALUES
('admin', 'scrypt:32768:8:1$uDAYSjOA6oLsc0xo$eb8c27961fa79fccc48234860ce9cd260b6b8d47817a1e7363d6fed5e4e671e8ee0e5e8439a6b727dc7c69a0076e8497468871d5db75ed26550e54ecc979adb6', 'admin', 'Admin')
ON CONFLICT (usuario) DO NOTHING;