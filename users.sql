-- Tabla de usuarios para login por usuario + contraseña
CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  usuario TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  rol TEXT NOT NULL CHECK (rol IN ('vendedor', 'portero')),
  nombre TEXT DEFAULT ''
);

-- Usuarios iniciales (vendedor2026 / portero2026)
INSERT INTO users (usuario, password_hash, rol, nombre) VALUES
('vendedor', 'scrypt:32768:8:1$gmBfKNaZHR4ztQQX$7c6a66e56ca8493345fe28aa512685bf05258a0487322ff7a6233055a6e838a2b73f0b66f0a57c7551ada20e845b96f4fff86c6d993aba3cb3bbaa7fa875253f', 'vendedor', 'Vendedor'),
('portero', 'scrypt:32768:8:1$CAxlpGgoLdDmPW5n$66d9bff05013c75c21351f4eda3be7d5cbf7d72f56304b0b688502583667a251c265eeeb280b0dfa78b3859635adb626924e3ed3eb641e2068b297a07ed28c97', 'portero', 'Portero')
ON CONFLICT (usuario) DO NOTHING;