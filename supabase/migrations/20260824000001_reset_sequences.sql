-- Resetear secuencias para que los IDs empiecen desde 1 tras limpieza
TRUNCATE TABLE entradas RESTART IDENTITY CASCADE;
TRUNCATE TABLE eventos RESTART IDENTITY CASCADE;
TRUNCATE TABLE colegios RESTART IDENTITY CASCADE;
TRUNCATE TABLE logs RESTART IDENTITY CASCADE;
TRUNCATE TABLE evento_usuarios RESTART IDENTITY CASCADE;
-- users se mantiene (grei), solo ajustar secuencia al max existente
SELECT setval('users_id_seq', (SELECT COALESCE(MAX(id), 1) FROM users), true);
