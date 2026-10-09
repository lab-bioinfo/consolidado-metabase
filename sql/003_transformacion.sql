-- =============================================================================
-- 003_transformacion.sql
-- Etapa de transformación: raw.fila -> audit.transformacion -> analytics.consumo.
--
-- Añade (sin modificar las migraciones ya aplicadas 001/002):
--   1. audit.transformacion  : regla/interpretación aplicada por el ETL sobre
--                              una celda/fila (trazabilidad célula-a-campo).
--   2. Columnas nuevas en analytics.consumo para distinguir valor observado
--      (archivo) vs valor calculado, y medicamento original vs normalizado.
--   3. audit.incidencia.origen : distingue incidencias ETL de las manuales.
--
-- Resultado de una transformación (audit.transformacion.resultado):
--   DIRECTO | NORMALIZADO | CALCULADO | IGNORADO_SUBTOTAL | IGNORADO_METADATA
--   | INVALIDO | PENDIENTE_VALIDACION
-- =============================================================================

-- -----------------------------------------------------------------------------
-- audit.transformacion
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit.transformacion (
    id                  BIGSERIAL   PRIMARY KEY,
    carga_id            BIGINT      REFERENCES raw.carga(id) ON DELETE CASCADE,
    numero_fila         INTEGER     NOT NULL,
    archivo_origen      TEXT,
    pestana_origen      TEXT,
    campo_destino       TEXT        NOT NULL,
    columna_origen      TEXT,
    valor_original      TEXT,
    valor_interpretado  TEXT,
    regla_aplicada      TEXT        NOT NULL,
    resultado           TEXT        NOT NULL,
    fecha               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_transformacion_carga
    ON audit.transformacion (carga_id);
CREATE INDEX IF NOT EXISTS idx_audit_transformacion_fila
    ON audit.transformacion (carga_id, numero_fila);
CREATE INDEX IF NOT EXISTS idx_audit_transformacion_campo
    ON audit.transformacion (campo_destino);

-- -----------------------------------------------------------------------------
-- analytics.consumo: columnas que distinguen observado vs calculado y
-- medicamento original vs normalizado.
-- -----------------------------------------------------------------------------
ALTER TABLE analytics.consumo ADD COLUMN IF NOT EXISTS medicamento_original     TEXT;
ALTER TABLE analytics.consumo ADD COLUMN IF NOT EXISTS medicamento_normalizado  TEXT;
ALTER TABLE analytics.consumo ADD COLUMN IF NOT EXISTS gramos_calculados        NUMERIC;
ALTER TABLE analytics.consumo ADD COLUMN IF NOT EXISTS ddd_archivo              NUMERIC;
ALTER TABLE analytics.consumo ADD COLUMN IF NOT EXISTS ddd_referencia_usada     NUMERIC;
ALTER TABLE analytics.consumo ADD COLUMN IF NOT EXISTS densidad_calculada       NUMERIC;
ALTER TABLE analytics.consumo ADD COLUMN IF NOT EXISTS gasto_archivo            NUMERIC;
ALTER TABLE analytics.consumo ADD COLUMN IF NOT EXISTS gasto_calculado          NUMERIC;
-- Flag: densidad (DDD/100 días-cama) calculable matemáticamente pero NO
-- validada clínicamente (FALSE para UPC_NEO/UPC_PED; NULL en el resto).
ALTER TABLE analytics.consumo ADD COLUMN IF NOT EXISTS densidad_clinica_validada BOOLEAN;

-- -----------------------------------------------------------------------------
-- audit.incidencia: distinguir origen (ETL vs manual).
-- -----------------------------------------------------------------------------
ALTER TABLE audit.incidencia ADD COLUMN IF NOT EXISTS origen TEXT NOT NULL DEFAULT 'ETL';
