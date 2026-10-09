"""Ingesta raw de los consolidados TSV.

Carga cada archivo en ``raw.carga`` + ``raw.fila`` preservando cada fila tal
cual (lossless), con trazabilidad (archivo, pestaña, número de fila, carga) y
deduplicación por SHA-256 (idempotencia).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import ETL_VERSION
from . import config as cfg
from . import db

logger = logging.getLogger("etl")


@dataclass
class FileResult:
    """Resultado de la carga de un único archivo."""

    archivo_nombre: str
    sha256: str
    estado: str  # "cargado" | "ya_existente" | "error"
    filas_leidas: int = 0
    filas_almacenadas: int = 0
    carga_id: int | None = None
    error: str | None = None


def _row_to_json(header: list[str], row: list[str]) -> str:
    """Serializa la fila de forma lossless (columnas + valores por posición).

    Se conserva el orden y los nombres duplicados de columna (p.ej. las dos
    ``UCI/UTI_PED`` de UPC_PED) que un dict por nombre perdería.
    """
    return json.dumps({"columnas": header, "valores": row}, ensure_ascii=False)


def load_file(
    conn,
    path: Path,
    version_etl: str,
    sha256: str | None = None,
) -> FileResult:
    """Carga un archivo en raw si su hash no fue cargado antes."""
    sha256 = sha256 or cfg.compute_sha256(path)

    if db.hash_exists(conn, sha256):
        logger.info("Ya cargado (hash %s...): %s", sha256[:12], path.name)
        return FileResult(path.name, sha256, "ya_existente")

    header, rows = cfg.read_tsv(path)

    idx_archivo = header.index("ARCHIVO_ORIGEN") if "ARCHIVO_ORIGEN" in header else None
    idx_pestana = header.index("PESTANA_ORIGEN") if "PESTANA_ORIGEN" in header else None

    carga_id = db.insert_carga(conn, path.name, sha256, len(rows), version_etl)

    fila_rows: list[tuple[int, int, str | None, str | None, str]] = []
    for i, row in enumerate(rows, start=1):  # numero_fila 1-based, sin cabecera
        archivo_origen = row[idx_archivo] if idx_archivo is not None and idx_archivo < len(row) else None
        pestana_origen = row[idx_pestana] if idx_pestana is not None and idx_pestana < len(row) else None
        datos_json = _row_to_json(header, row)
        fila_rows.append((carga_id, i, archivo_origen, pestana_origen, datos_json))

    db.insert_filas(conn, carga_id, fila_rows)
    conn.commit()

    logger.info("Cargado %s: %d filas en raw", path.name, len(fila_rows))
    return FileResult(path.name, sha256, "cargado", len(rows), len(fila_rows), carga_id)


def load_all(input_dir: Path | str, db_cfg: dict) -> list[FileResult]:
    """Carga todos los TSV de ``input_dir`` y devuelve el resumen por archivo."""
    files = cfg.discover_files(input_dir)
    if not files:
        logger.warning("No se encontraron archivos .TSV en %s", input_dir)
        return []

    results: list[FileResult] = []
    conn = db.connect(db_cfg)
    try:
        db.apply_migrations(conn)
        for path in files:
            try:
                results.append(load_file(conn, path, ETL_VERSION))
            except Exception as exc:  # no detener el resto de archivos
                conn.rollback()
                logger.error("Error cargando %s: %s", path.name, exc)
                results.append(
                    FileResult(path.name, "", "error", error=str(exc))
                )
    finally:
        conn.close()

    return results
