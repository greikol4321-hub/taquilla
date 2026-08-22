-- ============================================================
-- Optimización de la base de datos (índices)
-- Ejecutar en Supabase Dashboard → SQL Editor → Run
-- Todo es idempotente: se puede ejecutar varias veces sin error.
-- ============================================================

-- 1) Entradas por estado dentro de un evento.
--    Acelera el dashboard (conteos total/usadas por evento) y la
--    validación en puerta (buscar entradas usadas/pendientes).
CREATE INDEX IF NOT EXISTS idx_entradas_evento_usado
    ON entradas (evento_id, usado);

-- 2) Logs por evento, más recientes primero.
--    Acelera /api/logs cuando filtra por eventos visibles y ordena por id DESC.
CREATE INDEX IF NOT EXISTS idx_logs_evento_id
    ON logs (evento_id, id DESC);

-- 3) Logs recientes globales (actividad semanal / últimos registros).
CREATE INDEX IF NOT EXISTS idx_logs_creado
    ON logs (creado_en DESC);

-- 4) Asignaciones usuario↔evento en ambas direcciones.
--    Acelera usuario_en_alcance() y el listado de asignaciones.
CREATE INDEX IF NOT EXISTS idx_asignaciones_usuario
    ON evento_usuarios (usuario_id);
CREATE INDEX IF NOT EXISTS idx_asignaciones_evento
    ON evento_usuarios (evento_id);

-- Nota: users.colegio_id y eventos.colegio_id ya tienen índice
-- desde migrar_colegios.sql.

-- 5) Refrescar estadísticas del planificador para que use los índices nuevos.
ANALYZE entradas;
ANALYZE logs;
ANALYZE evento_usuarios;
