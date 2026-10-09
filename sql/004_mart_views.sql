-- =============================================================================
-- 004_mart_views.sql
-- Capa estable de lectura para Metabase. Las vistas conservan NULL cuando el
-- origen o el cálculo no permiten determinar una métrica.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS mart;

-- Una fila por hecho analítico, sin subtotales (ya excluidos por el ETL).
CREATE OR REPLACE VIEW mart.consumo AS
SELECT
    c.id AS consumo_id,
    c.fecha_inicio,
    c.fecha_fin,
    c.anio,
    c.tipo_periodo,
    c.numero_periodo,
    c.periodo_etiqueta AS periodo,
    c.unidad,
    c.tipo_paciente,
    c.familia,
    c.medicamento_normalizado AS medicamento,
    c.presentacion AS presentacion_normalizada,
    c.medicamento_original,
    c.dosis_gr,
    c.unidades,
    c.gramos_calculados AS gramos_calculados,
    c.ddd_referencia_usada,
    c.ddd_consumidas,
    c.dias_cama,
    c.densidad_calculada AS ddd_100_dias_cama_calculada,
    c.precio_unitario,
    c.gasto_calculado AS gasto_calculado,
    c.gramos_archivo,
    c.ddd_archivo,
    c.densidad_archivo,
    c.gasto_archivo,
    c.densidad_clinica_validada,
    CASE
        WHEN c.densidad_clinica_validada IS FALSE
            THEN 'NO_VALIDADA_CLINICAMENTE_PEDIATRICA_NEONATAL'
        ELSE NULL
    END AS limitacion_clinica_densidad,
    CASE
        WHEN c.ddd_referencia_usada IS NOT NULL THEN FALSE
        WHEN c.ddd_archivo IS NOT NULL THEN TRUE
        ELSE NULL
    END AS ddd_referencia_pendiente_validacion,
    CASE
        WHEN c.densidad_clinica_validada IS FALSE THEN FALSE
        WHEN c.ddd_consumidas IS NOT NULL AND c.dias_cama > 0 THEN TRUE
        ELSE NULL
    END AS densidad_apta_para_agregacion,
    c.archivo_origen,
    c.pestana_origen,
    c.numero_fila,
    c.carga_id
FROM analytics.consumo AS c;

-- Formato largo para gráficos. La densidad no validada se publica con una
-- métrica distinta para que no se confunda con DDD/100 días-cama validada.
CREATE OR REPLACE VIEW mart.consumo_largo AS
SELECT fecha_inicio, periodo, unidad, tipo_paciente, familia, medicamento,
       'unidades'::TEXT AS metrica, unidades AS valor,
       NULL::BOOLEAN AS densidad_clinica_validada
FROM mart.consumo
WHERE unidades IS NOT NULL
UNION ALL
SELECT fecha_inicio, periodo, unidad, tipo_paciente, familia, medicamento,
       'gramos'::TEXT, gramos_calculados,
       NULL::BOOLEAN
FROM mart.consumo
WHERE gramos_calculados IS NOT NULL
UNION ALL
SELECT fecha_inicio, periodo, unidad, tipo_paciente, familia, medicamento,
       'ddd_consumidas'::TEXT, ddd_consumidas,
       NULL::BOOLEAN
FROM mart.consumo
WHERE ddd_consumidas IS NOT NULL
UNION ALL
SELECT fecha_inicio, periodo, unidad, tipo_paciente, familia, medicamento,
       'ddd_100_dias_cama'::TEXT, ddd_100_dias_cama_calculada,
       TRUE
FROM mart.consumo
WHERE ddd_100_dias_cama_calculada IS NOT NULL
  AND densidad_clinica_validada IS DISTINCT FROM FALSE
UNION ALL
SELECT fecha_inicio, periodo, unidad, tipo_paciente, familia, medicamento,
       'ddd_100_dias_cama_no_validada_clinicamente'::TEXT,
       ddd_100_dias_cama_calculada,
       FALSE
FROM mart.consumo
WHERE ddd_100_dias_cama_calculada IS NOT NULL
  AND densidad_clinica_validada IS FALSE
UNION ALL
SELECT fecha_inicio, periodo, unidad, tipo_paciente, familia, medicamento,
       'gasto'::TEXT, gasto_calculado,
       NULL::BOOLEAN
FROM mart.consumo
WHERE gasto_calculado IS NOT NULL;

-- Agregado seguro para los KPI por unidad/período. La densidad se recalcula a
-- partir de numerador y denominador; no suma ni promedia densidades de filas.
CREATE OR REPLACE VIEW mart.consumo_agregado AS
WITH componentes AS (
    SELECT
        c.*,
        c.ddd_consumidas IS NOT NULL
        AND c.dias_cama > 0
        AND c.densidad_clinica_validada IS DISTINCT FROM FALSE AS densidad_valida
    FROM mart.consumo AS c
)
SELECT
    fecha_inicio,
    fecha_fin,
    anio,
    tipo_periodo,
    numero_periodo,
    periodo,
    unidad,
    tipo_paciente,
    SUM(unidades) AS unidades,
    SUM(gramos_calculados) AS gramos_calculados,
    SUM(ddd_consumidas) FILTER (WHERE densidad_valida) AS ddd_consumidas_validas,
    SUM(dias_cama) FILTER (WHERE densidad_valida) AS dias_cama_componentes_validos,
    SUM(ddd_consumidas) FILTER (WHERE densidad_valida)
        / NULLIF(SUM(dias_cama) FILTER (WHERE densidad_valida), 0) * 100
        AS ddd_100_dias_cama,
    SUM(gasto_calculado) AS gasto_calculado,
    COUNT(*) AS hechos_componentes,
    COUNT(*) FILTER (WHERE densidad_valida) AS componentes_densidad_validos
FROM componentes
GROUP BY
    fecha_inicio, fecha_fin, anio, tipo_periodo, numero_periodo, periodo,
    unidad, tipo_paciente;

-- Una fila por incidencia (o una fila de carga sin incidencias), con enlace a
-- la fila raw cuando la incidencia identifica una fila física.
CREATE OR REPLACE VIEW mart.calidad AS
WITH filas_raw_por_carga AS (
    SELECT carga_id, COUNT(*) AS filas_raw
    FROM raw.fila
    GROUP BY carga_id
),
incidencias_por_carga AS (
    SELECT carga_id, COUNT(*) AS incidencias_carga
    FROM audit.incidencia
    GROUP BY carga_id
),
incidencias_por_tipo AS (
    SELECT carga_id, tipo, COUNT(*) AS incidencias_tipo
    FROM audit.incidencia
    GROUP BY carga_id, tipo
)
SELECT
    c.id AS carga_id,
    c.archivo_nombre,
    c.hash_sha256,
    c.fecha_carga,
    c.estado AS estado_carga,
    c.version_etl,
    c.filas_leidas,
    c.filas_validas,
    c.filas_con_error,
    fr.filas_raw,
    ipc.incidencias_carga,
    i.id AS incidencia_id,
    i.tipo AS tipo_incidencia,
    ipt.incidencias_tipo,
    i.columna AS columna_afectada,
    i.valor_original,
    i.descripcion,
    i.origen AS origen_incidencia,
    i.fecha AS fecha_incidencia,
    i.archivo AS archivo_afectado,
    f.pestana_origen AS pestana_afectada,
    i.fila AS fila_afectada,
    f.id AS raw_fila_id,
    f.datos_json AS datos_raw
FROM raw.carga AS c
LEFT JOIN filas_raw_por_carga AS fr ON fr.carga_id = c.id
LEFT JOIN incidencias_por_carga AS ipc ON ipc.carga_id = c.id
LEFT JOIN audit.incidencia AS i ON i.carga_id = c.id
LEFT JOIN incidencias_por_tipo AS ipt
    ON ipt.carga_id = i.carga_id AND ipt.tipo = i.tipo
LEFT JOIN raw.fila AS f
    ON f.carga_id = i.carga_id
   AND f.numero_fila = i.fila
   AND f.archivo_origen IS NOT DISTINCT FROM i.archivo;

-- El rol de aplicación de Metabase hereda solo lectura sobre la capa mart.
-- No se define contraseña en SQL: la autenticación sigue la configuración de
-- infraestructura y no se versionan secretos.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'metabase_reader') THEN
        CREATE ROLE metabase_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'metabase') THEN
        GRANT metabase_reader TO metabase;
        REVOKE ALL PRIVILEGES ON SCHEMA raw, analytics, audit FROM metabase;
        REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA raw, analytics, audit FROM metabase;
    END IF;
END;
$$;

REVOKE ALL PRIVILEGES ON SCHEMA raw, analytics, audit FROM metabase_reader;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA raw, analytics, audit FROM metabase_reader;
GRANT USAGE ON SCHEMA mart TO metabase_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA mart TO metabase_reader;
