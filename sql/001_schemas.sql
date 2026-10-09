-- =============================================================================
-- 001_schemas.sql
-- Esquemas lógicos del modelo MVP: raw, analytics, audit.
-- Idempotente: se puede re-ejecutar sin error.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS audit;
