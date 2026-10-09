-- =============================================================================
-- 002_tables.sql
-- Tablas mínimas del MVP.
--
--   raw.carga          : una fila por archivo procesado (idempotencia por hash).
--   raw.fila           : una fila por fila física del TSV (preservación lossless).
--   analytics.consumo  : modelo analítico común (se poblará en etapa posterior).
--   audit.incidencia   : registro de problemas y normalizaciones.
--
-- Trazabilidad: raw.fila conserva archivo_origen, pestana_origen, numero_fila,
-- carga_id; analytics.consumo replica esas claves para cada hecho.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- raw.carga
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.carga (
    id              BIGSERIAL PRIMARY KEY,
    archivo_nombre  TEXT        NOT NULL,
    hash_sha256     TEXT        NOT NULL UNIQUE,
    fecha_carga     TIMESTAMPTZ NOT NULL DEFAULT now(),
    estado          TEXT        NOT NULL DEFAULT 'cargado',
    filas_leidas    INTEGER     NOT NULL DEFAULT 0,
    filas_validas   INTEGER     NOT NULL DEFAULT 0,
    filas_con_error INTEGER     NOT NULL DEFAULT 0,
    version_etl     TEXT        NOT NULL
);

-- -----------------------------------------------------------------------------
-- raw.fila
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.fila (
    id             BIGSERIAL   PRIMARY KEY,
    carga_id       BIGINT      NOT NULL REFERENCES raw.carga(id) ON DELETE CASCADE,
    numero_fila    INTEGER     NOT NULL,
    archivo_origen TEXT,
    pestana_origen TEXT,
    datos_json     JSONB       NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_fila_carga_id ON raw.fila (carga_id);
CREATE INDEX IF NOT EXISTS idx_raw_fila_origen ON raw.fila (archivo_origen, pestana_origen);

-- -----------------------------------------------------------------------------
-- analytics.consumo
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analytics.consumo (
    id                BIGSERIAL PRIMARY KEY,

    unidad            TEXT,
    tipo_paciente     TEXT,

    anio              INTEGER,
    tipo_periodo      TEXT,
    numero_periodo    INTEGER,
    periodo_etiqueta  TEXT,
    fecha_inicio      DATE,
    fecha_fin         DATE,

    familia           TEXT,
    medicamento       TEXT,
    presentacion      TEXT,

    dosis_gr          NUMERIC,
    unidades          NUMERIC,
    gramos            NUMERIC,

    ddd_referencia    NUMERIC,
    ddd_consumidas    NUMERIC,
    ddd_100_dias_cama NUMERIC,

    dias_cama         NUMERIC,

    precio_unitario   NUMERIC,
    gasto             NUMERIC,

    gramos_archivo    NUMERIC,
    densidad_archivo  NUMERIC,

    -- trazabilidad
    archivo_origen    TEXT,
    pestana_origen    TEXT,
    numero_fila       INTEGER,
    carga_id          BIGINT REFERENCES raw.carga(id)
);

CREATE INDEX IF NOT EXISTS idx_analytics_consumo_unidad
    ON analytics.consumo (unidad, anio, tipo_periodo, numero_periodo);

-- -----------------------------------------------------------------------------
-- audit.incidencia
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit.incidencia (
    id             BIGSERIAL   PRIMARY KEY,
    carga_id       BIGINT      REFERENCES raw.carga(id) ON DELETE SET NULL,
    archivo        TEXT,
    fila           INTEGER,
    columna        TEXT,
    valor_original TEXT,
    tipo           TEXT        NOT NULL,
    descripcion    TEXT,
    fecha          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_incidencia_tipo ON audit.incidencia (tipo);
CREATE INDEX IF NOT EXISTS idx_audit_incidencia_carga ON audit.incidencia (carga_id);
