"""Configuración del ETL: rutas del proyecto, carga de ``.env`` y de los
archivos ``config/*.yml``, y funciones puras reutilizables (hash, año,
descubrimiento de archivos, lectura de TSV, detección de subtotales).

Todas las funciones de este módulo son puras o de solo lectura: no modifican
los TSV de ``data/input/``.
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
from pathlib import Path

import yaml

# -----------------------------------------------------------------------------
# Rutas del proyecto (resueltas respecto a la ubicación de este módulo).
# -----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
SQL_DIR = PROJECT_ROOT / "sql"
DATA_DIR = PROJECT_ROOT / "data"
INPUT_DIR = DATA_DIR / "input"

# Nombre canónico por defecto de la base de datos de la aplicación.
DEFAULT_DB_NAME = "antimicrobianos"
DEFAULT_DB_USER = "etl"
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 5432


# -----------------------------------------------------------------------------
# Variables de entorno / .env
# -----------------------------------------------------------------------------
def load_dotenv(path: Path | str = ".env") -> None:
    """Carga variables ``KEY=VALUE`` de ``.env`` si no están ya definidas.

    Parser mínimo y sin dependencias: ignora comentarios y líneas vacías,
    soporta prefijo ``export `` y comillas simples/dobles alrededor del valor.
    """
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] in ("'", '"') and value[-1] == value[0]:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def get_db_config() -> dict:
    """Devuelve la configuración de conexión a PostgreSQL desde el entorno.

    Las credenciales se toman de variables de entorno (p.ej. vía ``.env``).
    No se hardcodea ninguna contraseña.
    """
    password = os.environ.get("POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError(
            "POSTGRES_PASSWORD no está definido. Copie .env.example a .env "
            "o exporte la variable antes de ejecutar el ETL."
        )
    return {
        "host": os.environ.get("POSTGRES_HOST", DEFAULT_HOST),
        "port": int(os.environ.get("POSTGRES_PORT", str(DEFAULT_PORT))),
        "dbname": os.environ.get("POSTGRES_DB", DEFAULT_DB_NAME),
        "user": os.environ.get("POSTGRES_USER", DEFAULT_DB_USER),
        "password": password,
    }


# -----------------------------------------------------------------------------
# Configuración YAML
# -----------------------------------------------------------------------------
def load_yaml(name: str) -> dict:
    """Carga y parsea ``config/<name>``. Lanza error claro si falta el archivo."""
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Falta archivo de configuración: {path}")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_periodos() -> dict:
    return load_yaml("periodos.yml")


def load_aliases() -> dict:
    return load_yaml("aliases.yml")


# -----------------------------------------------------------------------------
# Funciones puras / de solo lectura
# -----------------------------------------------------------------------------
def discover_files(input_dir: Path | str) -> list[Path]:
    """Descubre archivos TSV en ``input_dir`` (sin recursión).

    La coincidencia de extensión es insensible a mayúsculas (``.TSV`` ==
    ``.tsv``) para evitar el bug del script histórico que solo buscaba ``*.tsv``
    en Linux (sistema de archivos sensible a mayúsculas).
    """
    d = Path(input_dir)
    files = [
        p
        for p in d.iterdir()
        if p.is_file() and p.suffix.lower() == ".tsv"
    ]
    return sorted(files)


def compute_sha256(path: Path | str) -> str:
    """Calcula el hash SHA-256 (hex) de los bytes del archivo."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read_tsv(path: Path | str) -> tuple[list[str], list[list[str]]]:
    """Lee un TSV (tabulación) devolviendo ``(header, filas_datos)``.

    Preserva celdas vacías y el texto tal cual. No modifica el archivo.
    """
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter="\t")
        rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:]


def extract_year(archivo_origen: str | None) -> int | None:
    """Extrae el año de ``ARCHIVO_ORIGEN`` (patrón ``DDD_<UNIDAD>_<AÑO>_V2.XLSX``).

    Devuelve el primer grupo de exactamente 4 dígitos no rodeado por dígitos,
    o ``None`` si no puede determinarse (no se inventa).
    """
    if not archivo_origen:
        return None
    m = re.search(r"(?<!\d)(\d{4})(?!\d)", archivo_origen)
    if not m:
        return None
    return int(m.group(1))


def is_subtotal(medicamento: str | None) -> bool:
    """``True`` si el medicamento es una fila de subtotal (``*_TOTAL``)."""
    return bool(medicamento) and medicamento.endswith("_TOTAL")
