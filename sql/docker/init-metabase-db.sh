#!/bin/sh
# =============================================================================
# Init script del contenedor postgres (se ejecuta UNA vez, al crear el volumen).
#
# Crea el rol y la base de datos que Metabase usa como almacenamiento de su
# propia aplicación (MB_DB_*). Idempotente por si el volumen se reutiliza.
# =============================================================================
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${METABASE_DB_USER}') THEN
            CREATE ROLE ${METABASE_DB_USER} WITH LOGIN PASSWORD '${METABASE_DB_PASSWORD}';
        END IF;
    END
    \$\$;
EOSQL

if [ "$(psql -tAc "SELECT 1 FROM pg_database WHERE datname='${METABASE_DB_NAME}'" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB")" = "1" ]; then
    echo "Base de datos '${METABASE_DB_NAME}' ya existe; se omite su creación."
else
    createdb --username "$POSTGRES_USER" --owner "$METABASE_DB_USER" "$METABASE_DB_NAME"
    echo "Base de datos '${METABASE_DB_NAME}' creada (owner: ${METABASE_DB_USER})."
fi
