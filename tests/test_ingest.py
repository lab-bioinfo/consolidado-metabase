"""Tests de ingesta raw (sin base de datos real).

Cubren: descubrimiento de ``.TSV`` en Linux (mayúsculas), SHA-256,
idempotencia (rama de omisión), y preservación del archivo original.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from etl import config as cfg
from etl import db
from etl import ingest


class TestDiscoverFiles(unittest.TestCase):
    def test_descubre_TSV_mayuscula_y_minuscula(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "A.TSV").write_text("a\tb\n1\t2\n")
            (p / "b.tsv").write_text("x\ty\n")
            (p / "c.txt").write_text("no\n")
            (p / "D.csv").write_text("no\n")
            names = sorted(f.name for f in cfg.discover_files(p))
            self.assertEqual(names, ["A.TSV", "b.tsv"])

    def test_descubre_los_cinco_consolidados(self):
        files = cfg.discover_files(cfg.INPUT_DIR)
        self.assertEqual(len(files), 5)


class TestSha256(unittest.TestCase):
    def test_deterministico(self):
        p = cfg.INPUT_DIR / "CONSOLIDADO_CIRUGIA_TRIMESTRES_CUATRIMESTRES_4.TSV"
        self.assertEqual(cfg.compute_sha256(p), cfg.compute_sha256(p))

    def test_contenido_distinto_hash_distinto(self):
        with tempfile.TemporaryDirectory() as d:
            a = Path(d) / "a.tsv"
            b = Path(d) / "b.tsv"
            a.write_text("x\n")
            b.write_text("y\n")
            self.assertNotEqual(cfg.compute_sha256(a), cfg.compute_sha256(b))


class TestNoModificaOrigen(unittest.TestCase):
    def test_lectura_y_hash_no_modifican_bytes(self):
        p = cfg.INPUT_DIR / "CONSOLIDADO_UPC_NEO_TRIMESTRES_CUATRIMESTRES_3.TSV"
        before = p.read_bytes()
        cfg.read_tsv(p)
        cfg.compute_sha256(p)
        self.assertEqual(before, p.read_bytes())


class TestRowToJson(unittest.TestCase):
    def test_preserva_columnas_duplicadas(self):
        header = ["A", "B", "A"]
        row = ["1", "2", "3"]
        data = json.loads(ingest._row_to_json(header, row))
        self.assertEqual(data["columnas"], ["A", "B", "A"])
        self.assertEqual(data["valores"], ["1", "2", "3"])


class TestIdempotencia(unittest.TestCase):
    def test_omite_si_hash_ya_existe(self):
        p = cfg.INPUT_DIR / "CONSOLIDADO_CIRUGIA_TRIMESTRES_CUATRIMESTRES_4.TSV"
        with mock.patch.object(db, "hash_exists", return_value=True):
            with mock.patch.object(db, "insert_carga") as minsert:
                res = ingest.load_file(conn=mock.MagicMock(), path=p, version_etl="test")
        self.assertEqual(res.estado, "ya_existente")
        minsert.assert_not_called()

    def test_inserta_y_preserva_trazabilidad(self):
        p = cfg.INPUT_DIR / "CONSOLIDADO_SOLO_TRIMESTRES_CUATRIMESTRES_2.TSV"
        with mock.patch.object(db, "hash_exists", return_value=False), \
             mock.patch.object(db, "insert_carga", return_value=42), \
             mock.patch.object(db, "insert_filas", return_value=168) as mfilas:
            res = ingest.load_file(conn=mock.MagicMock(), path=p, version_etl="test")

        self.assertEqual(res.estado, "cargado")
        self.assertEqual(res.carga_id, 42)
        self.assertEqual(res.filas_leidas, 168)
        self.assertEqual(res.filas_almacenadas, 168)

        fila_rows = mfilas.call_args[0][2]
        self.assertEqual(len(fila_rows), 168)
        # numero_fila 1-based y sin cabecera
        self.assertEqual(fila_rows[0][1], 1)
        self.assertEqual(fila_rows[-1][1], 168)


if __name__ == "__main__":
    unittest.main()
