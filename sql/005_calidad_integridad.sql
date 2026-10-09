-- Clasificación de filas físicas para la pestaña Calidad. No duplica filas:
-- EXISTS evita multiplicaciones por las numerosas transformaciones por fila.
CREATE OR REPLACE VIEW mart.integridad AS
WITH clasificacion AS (
    SELECT f.carga_id, f.numero_fila,
           CASE
               WHEN EXISTS (
                   SELECT 1 FROM analytics.consumo c
                   WHERE c.carga_id = f.carga_id AND c.numero_fila = f.numero_fila
               ) THEN 'HECHO'
               WHEN EXISTS (
                   SELECT 1 FROM audit.transformacion t
                   WHERE t.carga_id = f.carga_id AND t.numero_fila = f.numero_fila
                     AND t.resultado = 'IGNORADO_SUBTOTAL'
               ) THEN 'SUBTOTAL'
               WHEN EXISTS (
                   SELECT 1 FROM audit.transformacion t
                   WHERE t.carga_id = f.carga_id AND t.numero_fila = f.numero_fila
                     AND t.resultado = 'IGNORADO_METADATA'
               ) THEN 'METADATA'
               ELSE 'SIN_CLASIFICAR'
           END AS clase
    FROM raw.fila f
)
SELECT COUNT(*) AS filas_originales,
       COUNT(*) FILTER (WHERE clase = 'HECHO') AS hechos_analiticos,
       COUNT(*) FILTER (WHERE clase = 'SUBTOTAL') AS subtotales,
       COUNT(*) FILTER (WHERE clase = 'METADATA') AS metadata,
       COUNT(*) FILTER (WHERE clase IN ('SUBTOTAL', 'METADATA')) AS subtotales_y_metadata,
       COUNT(*) FILTER (WHERE clase = 'SIN_CLASIFICAR') AS sin_clasificar
FROM clasificacion;

GRANT SELECT ON mart.integridad TO metabase_reader;
