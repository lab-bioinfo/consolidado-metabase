"""Capa de acceso a PostgreSQL (psycopg2).

Solo contiene operaciones de la etapa de ingesta raw: aplicar migraciones,
verificar idempotencia por hash, insertar cargas y filas. Sin lógica de negocio.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

from .config import SQL_DIR

_MIGRATION_GLOB = "*.sql"


def connect(cfg: dict) -> psycopg2.extensions.connection:
    """Abre una conexión usando la configuración devuelta por ``get_db_config``."""
    return psycopg2.connect(
        host=cfg["host"],
        port=cfg["port"],
        dbname=cfg["dbname"],
        user=cfg["user"],
        password=cfg["password"],
    )


def apply_migrations(conn: psycopg2.extensions.connection) -> list[str]:
    """Aplica ``sql/*.sql`` en orden (idempotente) y hace commit.

    Devuelve la lista de archivos aplicados.
    """
    files = sorted(Path(SQL_DIR).glob(_MIGRATION_GLOB))
    applied: list[str] = []
    with conn.cursor() as cur:
        for f in files:
            sql = f.read_text(encoding="utf-8")
            cur.execute(sql)
            applied.append(f.name)
    conn.commit()
    return applied


def hash_exists(conn: psycopg2.extensions.connection, sha256: str) -> bool:
    """``True`` si ya existe una carga con ese SHA-256 (idempotencia)."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM raw.carga WHERE hash_sha256 = %s", (sha256,))
        return cur.fetchone() is not None


def insert_carga(
    conn: psycopg2.extensions.connection,
    archivo_nombre: str,
    sha256: str,
    filas_leidas: int,
    version_etl: str,
    estado: str = "cargado",
) -> int:
    """Inserta una fila en ``raw.carga`` y devuelve su ``id`` (sin commit)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw.carga
                (archivo_nombre, hash_sha256, filas_leidas, filas_validas,
                 filas_con_error, version_etl, estado)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (archivo_nombre, sha256, filas_leidas, filas_leidas, 0, version_etl, estado),
        )
        return cur.fetchone()[0]


def insert_filas(
    conn: psycopg2.extensions.connection,
    carga_id: int,
    fila_rows: list[tuple[int, int, str | None, str | None, str]],
) -> int:
    """Inserta filas en ``raw.fila`` y devuelve la cantidad insertada (sin commit).

    ``fila_rows`` es una lista de tuplas:
    ``(carga_id, numero_fila, archivo_origen, pestana_origen, datos_json_str)``.
    """
    if not fila_rows:
        return 0
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO raw.fila
                (carga_id, numero_fila, archivo_origen, pestana_origen, datos_json)
            VALUES %s
            """,
            fila_rows,
            template="(%s, %s, %s, %s, %s::jsonb)",
        )
        return cur.rowcount


# -----------------------------------------------------------------------------
# Transformación / rebuild (raw -> analytics + audit)
# -----------------------------------------------------------------------------
def read_raw_filas(conn: psycopg2.extensions.connection) -> list[dict]:
    """Lee ``raw.fila`` como lista de dicts con ``cells`` (columna -> valor).

    ``datos_json`` se guardó como ``{columnas: [...], valores: [...]}``; aquí se
    reconstruye un dict (primera ocurrencia por nombre, suficiente porque las
    columnas mapeadas por la configuración no están duplicadas). El JSONB
    original permanece intacto en ``raw.fila``.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT carga_id, numero_fila, archivo_origen, pestana_origen, datos_json
            FROM raw.fila
            ORDER BY carga_id, numero_fila
            """
        )
        filas = []
        for carga_id, numero_fila, archivo, pestana, datos in cur.fetchall():
            if isinstance(datos, str):
                datos = json.loads(datos)
            columnas = datos.get("columnas", [])
            valores = datos.get("valores", [])
            cells: dict[str, str] = {}
            for i, col in enumerate(columnas):
                if col in cells:
                    continue  # conserva la primera ocurrencia
                cells[col] = valores[i] if i < len(valores) else ""
            filas.append({
                "carga_id": carga_id,
                "numero_fila": numero_fila,
                "archivo_origen": archivo,
                "pestana_origen": pestana,
                "cells": cells,
            })
        return filas


def clear_derived(conn: psycopg2.extensions.connection) -> None:
    """Borra solo los datos derivados (no toca raw) antes de un rebuild."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM analytics.consumo")
        cur.execute("DELETE FROM audit.transformacion")
        cur.execute("DELETE FROM audit.incidencia WHERE origen = 'ETL'")


_CONSUMO_COLUMNS = [
    "unidad", "tipo_paciente", "anio", "tipo_periodo", "numero_periodo",
    "periodo_etiqueta", "fecha_inicio", "fecha_fin", "familia", "medicamento",
    "presentacion", "medicamento_original", "medicamento_normalizado",
    "dosis_gr", "unidades", "gramos", "gramos_archivo", "gramos_calculados",
    "ddd_archivo", "ddd_referencia", "ddd_referencia_usada", "ddd_consumidas",
    "densidad_archivo", "densidad_calculada", "ddd_100_dias_cama", "dias_cama",
    "precio_unitario", "gasto", "gasto_archivo", "gasto_calculado",
    "densidad_clinica_validada", "archivo_origen", "pestana_origen",
    "numero_fila", "carga_id",
]


def insert_hechos(conn: psycopg2.extensions.connection, hechos: list[dict]) -> int:
    if not hechos:
        return 0
    cols = ", ".join(_CONSUMO_COLUMNS)
    rows = [tuple(h.get(c) for c in _CONSUMO_COLUMNS) for h in hechos]
    template = "(" + ", ".join(["%s"] * len(_CONSUMO_COLUMNS)) + ")"
    with conn.cursor() as cur:
        execute_values(cur, f"INSERT INTO analytics.consumo ({cols}) VALUES %s",
                       rows, template=template)
        return len(rows)


_TRANS_COLUMNS = [
    "carga_id", "numero_fila", "archivo_origen", "pestana_origen",
    "campo_destino", "columna_origen", "valor_original", "valor_interpretado",
    "regla_aplicada", "resultado",
]


def insert_transformaciones(conn: psycopg2.extensions.connection,
                            transformaciones: list[dict]) -> int:
    if not transformaciones:
        return 0
    cols = ", ".join(_TRANS_COLUMNS)
    rows = [tuple(t.get(c) for c in _TRANS_COLUMNS) for t in transformaciones]
    template = "(" + ", ".join(["%s"] * len(_TRANS_COLUMNS)) + ")"
    with conn.cursor() as cur:
        execute_values(cur, f"INSERT INTO audit.transformacion ({cols}) VALUES %s",
                       rows, template=template)
        return len(rows)


_INC_COLUMNS = [
    "carga_id", "archivo", "fila", "columna", "valor_original", "tipo",
    "descripcion", "origen",
]


def insert_incidencias(conn: psycopg2.extensions.connection,
                       incidencias: list[dict]) -> int:
    if not incidencias:
        return 0
    cols = ", ".join(_INC_COLUMNS)
    rows = [tuple(i.get(c) for c in _INC_COLUMNS) for i in incidencias]
    template = "(" + ", ".join(["%s"] * len(_INC_COLUMNS)) + ")"
    with conn.cursor() as cur:
        execute_values(cur, f"INSERT INTO audit.incidencia ({cols}) VALUES %s",
                       rows, template=template)
        return len(rows)
