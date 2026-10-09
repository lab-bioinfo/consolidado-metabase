"""Interfaz de línea de comandos del ETL.

Uso principal::

    python -m etl load data/input/
    python -m etl init-db
"""

from __future__ import annotations

import logging
from pathlib import Path

import click

from . import config as cfg
from . import db
from . import ingest
from . import rebuild as rebuild_mod

logger = logging.getLogger("etl")


def _setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="[%(levelname)s] %(message)s",
    )


def _print_summary(results: list[ingest.FileResult]) -> None:
    cargados = [r for r in results if r.estado == "cargado"]
    ya = [r for r in results if r.estado == "ya_existente"]
    errores = [r for r in results if r.estado == "error"]

    total_filas = sum(r.filas_almacenadas for r in cargados)
    click.echo("")
    click.echo("Resumen de carga:")
    click.echo(f"  archivos descubiertos : {len(results)}")
    click.echo(f"  cargados              : {len(cargados)}")
    click.echo(f"  ya existentes         : {len(ya)}")
    click.echo(f"  con error             : {len(errores)}")
    click.echo(f"  filas raw insertadas  : {total_filas}")

    if ya:
        for r in ya:
            click.echo(f"  [omitido] {r.archivo_nombre} (hash {r.sha256[:12]}...)")
    if errores:
        for r in errores:
            click.echo(f"  [error] {r.archivo_nombre}: {r.error}")


@click.group()
def main() -> None:
    """ETL del dashboard de consumo de antimicrobianos."""


@main.command()
@click.argument(
    "input_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option("--verbose", "-v", is_flag=True, help="Mostrar logs en nivel DEBUG.")
def load(input_dir: Path, verbose: bool) -> None:
    """Carga los TSV de INPUT_DIR en raw (idempotente por SHA-256)."""
    _setup_logging(verbose)
    cfg.load_dotenv()
    db_cfg = cfg.get_db_config()
    logger.info("Descubriendo archivos .TSV en %s", input_dir)
    results = ingest.load_all(input_dir, db_cfg)
    _print_summary(results)


@main.command("init-db")
def init_db() -> None:
    """Aplica las migraciones SQL (esquemas y tablas)."""
    _setup_logging()
    cfg.load_dotenv()
    db_cfg = cfg.get_db_config()
    conn = db.connect(db_cfg)
    try:
        applied = db.apply_migrations(conn)
        for name in applied:
            click.echo(f"Aplicado: {name}")
    finally:
        conn.close()


@main.command()
@click.option("--verbose", "-v", is_flag=True, help="Mostrar logs en nivel DEBUG.")
def rebuild(verbose: bool) -> None:
    """Reconstruye analytics.consumo y audit desde raw (transaccional).

    Preserva raw.carga/raw.fila. Borra y recrea analytics.consumo,
    audit.transformacion y las incidencias de origen ETL.
    """
    _setup_logging(verbose)
    cfg.load_dotenv()
    db_cfg = cfg.get_db_config()
    logger.info("Iniciando rebuild (raw -> analytics + audit)...")
    result = rebuild_mod.run_rebuild(db_cfg)
    rebuild_mod.print_resumen(result)


if __name__ == "__main__":
    main()
