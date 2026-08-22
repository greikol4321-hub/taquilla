-- ============================================================
-- TAQUILLA · Migración: color por colegio + integridad de datos
-- Ejecutar en Supabase SQL Editor
-- ============================================================

-- 1. Color del colegio para las gráficas del resumen
ALTER TABLE colegios ADD COLUMN IF NOT EXISTS color text;

-- Colores iniciales según orden alfabético (paleta oscura)
WITH orden AS (
  SELECT id, row_number() OVER (ORDER BY nombre) - 1 AS i
  FROM colegios
)
UPDATE colegios SET color = (ARRAY[
  '#d9ff3d', '#4dd4ac', '#5aa9ff', '#ff7ab6',
  '#ffb84d', '#b78bff', '#ff6b6b', '#4dd4ff'
])[1 + (i % 8)]
FROM orden WHERE colegios.id = orden.id AND colegios.color IS NULL;

-- 2. Integridad: un staff solo se asigna a eventos de SU colegio.
--    Los eventos globales (colegio_id NULL) aceptan staff de cualquier colegio,
--    y el staff sin colegio (legacy) puede asignarse a cualquier evento.
CREATE OR REPLACE FUNCTION validar_asignacion_colegio() RETURNS trigger AS $$
DECLARE
  u_colegio int;
  e_colegio int;
BEGIN
  SELECT colegio_id INTO u_colegio FROM users WHERE id = NEW.usuario_id;
  SELECT colegio_id INTO e_colegio FROM eventos WHERE id = NEW.evento_id;
  IF u_colegio IS NOT NULL AND e_colegio IS NOT NULL AND u_colegio <> e_colegio THEN
    RAISE EXCEPTION 'Usuario (%) pertenece al colegio % pero el evento (%) es del colegio %',
      NEW.usuario_id, u_colegio, NEW.evento_id, e_colegio
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_asignacion_colegio ON evento_usuarios;
CREATE TRIGGER trg_asignacion_colegio
BEFORE INSERT OR UPDATE ON evento_usuarios
FOR EACH ROW EXECUTE FUNCTION validar_asignacion_colegio();

-- 3. Integridad extra: el precio no puede ser negativo
ALTER TABLE eventos DROP CONSTRAINT IF EXISTS eventos_precio_no_negativo;
ALTER TABLE eventos ADD CONSTRAINT eventos_precio_no_negativo CHECK (precio_entrada >= 0);
