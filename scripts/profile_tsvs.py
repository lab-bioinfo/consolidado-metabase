#!/usr/bin/env python3
"""Perfil exhaustivo (read-only) de los 5 consolidados TSV.

No modifica los archivos de `data/input/`. Imprime un reporte estructurado
por archivo y una comparación global, para alimentar `docs/data-profile.md`.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

INPUT_DIR = Path("data/input")


def read_rows(path: Path) -> list[list[str]]:
    """Lee el TSV (tab, CRLF) preservando celdas vacías y valores tal cual."""
    with path.open(encoding="ascii", newline="") as fh:
        return list(csv.reader(fh, delimiter="\t"))


def looks_numeric(v: str) -> bool:
    if v == "":
        return False
    # números válidos: enteros o decimales con un solo punto, signo opcional
    return re.fullmatch(r"[+-]?\d+(\.\d+)?", v.strip()) is not None


def classify_number(v: str) -> str:
    v = v.strip()
    if v == "":
        return "EMPTY"
    if looks_numeric(v):
        return "NUM_OK"
    if v in ("-", "—", "–"):
        return "DASH"
    if v.count(".") > 1 or v.count(",") > 1:
        return "MULTI_SEP"
    if "," in v and "." in v:
        return "MIXED_SEP"
    if "," in v:
        return "COMMA"
    if re.fullmatch(r"\d+(\.\d{3})+", v) is not None:
        return "THOUSAND_DOT"
    return "TEXT"


def profile(path: Path) -> dict:
    rows = read_rows(path)
    header = rows[0]
    data = rows[1:]
    ncols = len(header)

    # clasificación de celdas por columna
    col_class: dict[str, Counter] = {}
    for j, col in enumerate(header):
        c = Counter()
        for r in data:
            c[classify_number(r[j]) if j < len(r) else "MISSING_CELL"] += 1
        col_class[col] = c

    # valores únicos de las columnas clave (las que tienen pocos valores)
    def uniques(idx_name: str) -> dict:
        j = header.index(idx_name) if idx_name in header else None
        if j is None:
            return {}
        c = Counter()
        for r in data:
            c[r[j] if j < len(r) else "<MISSING_CELL>"] += 1
        return dict(c.most_common())

    archivo = uniques("ARCHIVO_ORIGEN")
    pestana = uniques("PESTANA_ORIGEN")
    periodo = uniques("PERIODO")
    familia = uniques("FAMILIA_ATB")

    # subtotales: medicamentos terminados en _TOTAL
    jmed = header.index("MEDICAMENTO") if "MEDICAMENTO" in header else None
    subtotales: list[tuple[int, str]] = []
    medicamentos: Counter = Counter()
    if jmed is not None:
        for i, r in enumerate(data):
            m = r[jmed] if jmed < len(r) else ""
            medicamentos[m] += 1
            if m.endswith("_TOTAL"):
                subtotales.append((i + 2, m))  # fila física (header = fila 1)

    # muestras numéricas problemáticas
    problems: list[tuple[int, str, str, str]] = []
    for j, col in enumerate(header):
        for i, r in enumerate(data):
            if j < len(r):
                cls = classify_number(r[j])
                if cls in ("MULTI_SEP", "MIXED_SEP", "COMMA", "TEXT", "THOUSAND_DOT"):
                    problems.append((i + 2, col, r[j], cls))

    # nulos/empty por columna (recuento de celdas vacías)
    empties: dict[str, int] = {}
    for j, col in enumerate(header):
        empties[col] = sum(1 for r in data if j >= len(r) or r[j] == "")

    return {
        "file": path.name,
        "n_data_rows": len(data),
        "n_cols": ncols,
        "header": header,
        "archivo": archivo,
        "pestana": pestana,
        "periodo": periodo,
        "familia": familia,
        "subtotales": subtotales,
        "n_subtotales": len(subtotales),
        "medicamento_count": len(medicamentos),
        "problems": problems,
        "empties": empties,
        "col_class": col_class,
    }


def main() -> int:
    files = sorted(INPUT_DIR.glob("*.TSV"))
    if not files:
        print("No se encontraron archivos .TSV en data/input/")
        return 1

    profiles = [profile(p) for p in files]

    for pr in profiles:
        print("=" * 90)
        print(f"ARCHIVO: {pr['file']}")
        print(f"  filas de datos: {pr['n_data_rows']}  columnas: {pr['n_cols']}")
        print(f"  medicamentos distintos: {pr['medicamento_count']}  "
              f"filas subtotal (_TOTAL): {pr['n_subtotales']}")
        print("  HEADER:")
        for j, c in enumerate(pr["header"]):
            print(f"    [{j:2d}] {c}")
        print("  ARCHIVO_ORIGEN:")
        for k, v in pr["archivo"].items():
            print(f"    {v:4d}  {k}")
        print("  PESTANA_ORIGEN:")
        for k, v in pr["pestana"].items():
            print(f"    {v:4d}  {k}")
        print("  PERIODO:")
        for k, v in pr["periodo"].items():
            print(f"    {v:4d}  {k!r}")
        print("  FAMILIA_ATB:")
        for k, v in pr["familia"].items():
            print(f"    {v:4d}  {k}")
        print("  SUBTOTALES (fila_fisica: medicamento):")
        for fn, m in pr["subtotales"]:
            print(f"    {fn:4d}  {m}")
        print("  CELDAS VACIAS por columna (solo columnas con vacíos):")
        for c, n in sorted(pr["empties"].items(), key=lambda kv: -kv[1]):
            if n:
                print(f"    {n:4d}  {c}")
        print("  CLASIFICACIÓN NUMÉRICA por columna (conteo por clase):")
        for c, cc in pr["col_class"].items():
            nonempty = {k: v for k, v in cc.items() if v}
            if nonempty and set(nonempty) != {"EMPTY"}:
                print(f"    {c}: {dict(nonempty)}")
        if pr["problems"]:
            print("  VALORES NUMÉRICOS PROBLEMÁTICOS:")
            seen = set()
            for fn, col, val, cls in pr["problems"]:
                key = (col, val, cls)
                if key in seen:
                    continue
                seen.add(key)
                print(f"    fila {fn:4d}  col={col}  clase={cls}  valor={val!r}")
        else:
            print("  VALORES NUMÉRICOS PROBLEMÁTICOS: ninguno")

    # comparación global
    print("\n" + "#" * 90)
    print("COMPARACIÓN GLOBAL DE COLUMNAS")
    print("#" * 90)
    allcols: Counter = Counter()
    for pr in profiles:
        for c in pr["header"]:
            allcols[c] += 1
    print("  Columna -> nº de archivos que la contienen:")
    for c, n in allcols.most_common():
        print(f"    {n}  {c}")

    print("\n  Presencia de columnas por archivo (X = presente):")
    headers = sorted(set(allcols.keys()),
                     key=lambda c: (-allcols[c], c))
    print("    " + "".join(f"{h:<24}" for h in headers))
    for pr in profiles:
        row = "".join(f"{'X' if h in pr['header'] else '-':<24}" for h in headers)
        print(f"    {row}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
