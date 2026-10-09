"""Tests de configuración y reglas puras del ETL.

Se ejecutan con::

    python -m unittest discover -s tests -t .

Son también compatibles con pytest (no requieren base de datos).
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from etl import config as cfg


def _unidad_anio(archivo_origen: str) -> tuple[str | None, int | None]:
    m = re.match(r"^DDD_(.+)_(\d{4})_V2\.XLSX$", archivo_origen)
    if not m:
        return None, None
    return m.group(1), int(m.group(2))


def _bloques():
    """Itera ``(nombre_archivo, header, archivo_origen, pestana, filas)``
    por cada bloque real (archivo × ARCHIVO_ORIGEN × PESTANA_ORIGEN)."""
    for path in cfg.discover_files(cfg.INPUT_DIR):
        header, rows = cfg.read_tsv(path)
        idx_archivo = header.index("ARCHIVO_ORIGEN")
        idx_pestana = header.index("PESTANA_ORIGEN")
        groups: dict[tuple[str, str], list[list[str]]] = {}
        for r in rows:
            groups.setdefault((r[idx_archivo], r[idx_pestana]), []).append(r)
        for (archivo, pestana), grp in sorted(groups.items()):
            yield path.name, header, archivo, pestana, grp


class TestPeriodosConfigCobertura(unittest.TestCase):
    def test_todo_bloque_real_tiene_config(self):
        periodos = cfg.load_periodos()["unidades"]
        for name, header, archivo, pestana, _grp in _bloques():
            unidad, anio = _unidad_anio(archivo)
            self.assertIsNotNone(unidad, f"no se pudo derivar unidad de {archivo!r}")
            self.assertIn(
                unidad, periodos,
                f"unidad {unidad!r} sin config (archivo {name})",
            )
            self.assertIn(
                str(anio), periodos[unidad]["periodos"],
                f"{unidad} {anio} sin config",
            )
            self.assertIn(
                pestana, periodos[unidad]["periodos"][str(anio)],
                f"{unidad} {anio} {pestana} sin config",
            )

    def test_columnas_existen_y_estan_pobladas(self):
        """Cada columna referenciada en la config existe en el header y tiene
        al menos una celda no vacía en ese bloque (valida el desplazamiento de
        CIRUGIA TRIM4 2023 y los casos especiales)."""
        periodos = cfg.load_periodos()["unidades"]
        for name, header, archivo, pestana, grp in _bloques():
            unidad, anio = _unidad_anio(archivo)
            bloque = periodos[unidad]["periodos"][str(anio)][pestana]
            cols = bloque["columnas"]
            idx = {c: i for i, c in enumerate(header)}

            def nonempty(col: str | None) -> bool:
                if col is None:
                    return False
                j = idx[col]
                return any(j < len(r) and r[j] != "" for r in grp)

            if cols.get("unidades"):
                self.assertTrue(
                    nonempty(cols["unidades"]),
                    f"{unidad} {anio} {pestana}: unidades={cols['unidades']} vacía",
                )
            for c in cols.get("unidades_mensuales", []) or []:
                self.assertTrue(
                    nonempty(c),
                    f"{unidad} {anio} {pestana}: unidades_mensuales {c} vacía",
                )
            for key in ("gramos_archivo", "densidad_archivo", "dias_cama"):
                col = cols.get(key)
                if col is None:
                    continue
                self.assertIn(
                    col, idx,
                    f"{unidad} {anio} {pestana}: columna {key}={col} no existe en {name}",
                )
                self.assertTrue(
                    nonempty(col),
                    f"{unidad} {anio} {pestana}: {key}={col} vacía en {name}",
                )
            for key in ("precio", "gasto"):
                col = cols.get(key)
                if col is None:
                    continue
                self.assertIn(
                    col, idx,
                    f"{unidad} {anio} {pestana}: columna {key}={col} no existe en {name}",
                )
                self.assertTrue(
                    nonempty(col),
                    f"{unidad} {anio} {pestana}: {key}={col} vacía en {name}",
                )

    def test_anomalia_cirugia_trim4_2023(self):
        """El desplazamiento de CIRUGIA TRIM4 2023 debe estar mapeado."""
        bloque = (
            cfg.load_periodos()["unidades"]["CIRUGIA"]["periodos"]["2023"]["TRIM4"]
        )
        cols = bloque["columnas"]
        self.assertEqual(cols["gramos_archivo"], "GRAMOS")
        self.assertEqual(cols["densidad_archivo"], "DDD2")
        self.assertEqual(cols["dias_cama"], "TOTAL_GRAMOS")

    def test_anomalia_upc_ped_cuatrim4(self):
        """CUATRIM4 de UPC_PED se interpreta como cuatrimestre 3."""
        bloque = (
            cfg.load_periodos()["unidades"]["UPC_PED"]["periodos"]["2024"]["CUATRIM4"]
        )
        self.assertEqual(bloque["tipo_periodo"], "CUATRIMESTRE")
        self.assertEqual(bloque["numero_periodo"], 3)

    def test_upc_neo_2022_unidades_en_total_fa(self):
        bloque = (
            cfg.load_periodos()["unidades"]["UPC_NEO"]["periodos"]["2022"]["TRIM1"]
        )
        self.assertEqual(bloque["columnas"]["unidades"], "TOTAL_FA")


class TestAliasesConfig(unittest.TestCase):
    def test_alias_presentes_en_datos(self):
        """Cada clave y valor canónico de alias aparece en los datos reales."""
        medicamentos: set[str] = set()
        for path in cfg.discover_files(cfg.INPUT_DIR):
            header, rows = cfg.read_tsv(path)
            im = header.index("MEDICAMENTO")
            for r in rows:
                medicamentos.add(r[im])

        aliases = cfg.load_aliases()
        for key, canonical in aliases["presentaciones"].items():
            self.assertIn(key, medicamentos, f"alias {key!r} no aparece en los datos")
            self.assertIn(
                canonical, medicamentos,
                f"canónico {canonical!r} de {key!r} no aparece en los datos",
            )
        for key, canonical in aliases["subtotales"].items():
            self.assertIn(key, medicamentos, f"subtotal alias {key!r} no aparece")


class TestReglasPuras(unittest.TestCase):
    def test_extract_year(self):
        self.assertEqual(cfg.extract_year("DDD_MEDICINA_2023_V2.XLSX"), 2023)
        self.assertEqual(cfg.extract_year("DDD_UPC_CV_2024_V2.XLSX"), 2024)
        self.assertEqual(cfg.extract_year("DDD_UPC_PED_2022_V2.XLSX"), 2022)
        self.assertIsNone(cfg.extract_year("SIN_ANIO.XLSX"))
        self.assertIsNone(cfg.extract_year(None))
        self.assertIsNone(cfg.extract_year(""))

    def test_is_subtotal(self):
        self.assertTrue(cfg.is_subtotal("AMIKACINA_TOTAL"))
        self.assertTrue(cfg.is_subtotal("VANCOMICINA_EV_TOTAL"))
        self.assertFalse(cfg.is_subtotal("AMIKACINA_100_MG"))
        self.assertFalse(cfg.is_subtotal(""))


if __name__ == "__main__":
    unittest.main()
