"""Contrato de filtros SQL y protección frente a agregaciones indebidas."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path("streamlit")))
import queries as q


class QueryTests(unittest.TestCase):
    def test_medicines_linked_to_family(self):
        with patch.object(q, "fetch", return_value=[{"medicamento": "AMIKACINA_100_MG"}]) as fetch:
            self.assertEqual(q.medicines("AMINOGLICOSIDOS"), ["AMIKACINA_100_MG"])
            sql, args = fetch.call_args.args
            self.assertIn("c.familia = %s", sql)
            self.assertEqual(args, ("AMINOGLICOSIDOS",))

    def test_density_never_sums_detail_values(self):
        with patch.object(q, "fetch", return_value=[]) as fetch:
            q.evolution("ddd_100_dias_cama", "MEDICINA")
            self.assertIn("mart.consumo_agregado", fetch.call_args.args[0])
            self.assertNotIn("SUM(", fetch.call_args.args[0])
            self.assertEqual(fetch.call_args.args[1], ("MEDICINA",))
            q.comparison("ddd_100_dias_cama", fecha="2024-09-01")
            self.assertIn("mart.consumo_agregado", fetch.call_args.args[0])
        with patch.object(q, "fetch") as fetch:
            self.assertEqual(q.evolution("ddd_100_dias_cama", familia="AMINOGLICOSIDOS"), [])
            self.assertEqual(q.comparison("ddd_100_dias_cama", fecha=None), [])
            self.assertEqual(q.top_ten("ddd_100_dias_cama"), [])
            fetch.assert_not_called()

    def test_metric_specific_queries_and_traceability(self):
        with patch.object(q, "fetch", return_value=[]) as fetch:
            q.evolution("gramos", unidad="MEDICINA")
            self.assertIn("c.metrica = %s", fetch.call_args.args[0])
            self.assertEqual(fetch.call_args.args[1], ("MEDICINA", "gramos"))
            q.top_ten("gasto", unidad="MEDICINA", fecha="2024-09-01")
            self.assertEqual(fetch.call_args.args[1], ("MEDICINA", "2024-09-01", "gasto"))
            q.detail("gasto", unidad="MEDICINA")
            sql, args = fetch.call_args.args
            self.assertIn("c.gasto_calculado AS valor", sql)
            for name in ("archivo_origen", "pestana_origen", "numero_fila", "carga_id"):
                self.assertIn(name, sql)
            self.assertEqual(args, ("MEDICINA",))

    def test_long_view_year_comes_from_date_not_nonexistent_column(self):
        with patch.object(q, "fetch", return_value=[]) as fetch:
            q.comparison("gramos", anio=2024)
            sql, args = fetch.call_args.args
            self.assertIn("EXTRACT(YEAR FROM c.fecha_inicio) = %s", sql)
            self.assertNotIn("c.anio", sql)
            self.assertEqual(args, (2024, "gramos"))
            q.top_ten("gasto", anio=2024)
            self.assertIn("EXTRACT(YEAR FROM c.fecha_inicio) = %s", fetch.call_args.args[0])

    def test_invalid_metric_rejected(self):
        with self.assertRaises(ValueError):
            q.detail("invalid")
        with self.assertRaises(ValueError):
            q.evolution("invalid")


if __name__ == "__main__":
    unittest.main()
