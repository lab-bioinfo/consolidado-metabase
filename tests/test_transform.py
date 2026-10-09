"""Tests de la transformación raw -> analytics (sin base de datos).

Se ejecutan con::

    python -m unittest discover -s tests -t .

Cubren: resolución de columnas por (unidad, año, pestaña) sobre datos reales,
parseo numérico conservador, detección de subtotales, cálculos (gramos, gasto,
DDD, densidad), trazabilidad (hecho -> transformación -> valor original) y
determinismo del rebuild.
"""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from etl import config as cfg
from etl import transform


def _raw_rows_from_tsvs() -> list[transform.RawRow]:
    """Carga los 5 TSV reales como objetos ``RawRow`` (solo lectura)."""
    rows: list[transform.RawRow] = []
    carga_id = 0
    for path in cfg.discover_files(cfg.INPUT_DIR):
        carga_id += 1
        header, data = cfg.read_tsv(path)
        for i, r in enumerate(data, start=1):
            cells = {header[j]: (r[j] if j < len(r) else "") for j in range(len(header))}
            rows.append(transform.RawRow(
                carga_id=carga_id,
                numero_fila=i,
                archivo_origen=r[0] if len(r) > 0 else None,
                pestana_origen=r[1] if len(r) > 1 else None,
                cells=cells,
            ))
    return rows


def _build():
    return transform.transform_rows(
        _raw_rows_from_tsvs(), cfg.load_periodos(), cfg.load_aliases())


def _find_hecho(result, unidad, anio, pestana, med_norm):
    for h in result.hechos:
        if (h["unidad"] == unidad and h["anio"] == anio
                and h["pestana_origen"] == pestana
                and h["medicamento_normalizado"] == med_norm):
            return h
    return None


class TestParseNumeric(unittest.TestCase):
    def test_valido(self):
        st, v = transform.parse_numeric("37.5")
        self.assertEqual(st, transform.NUM_VALID)
        self.assertEqual(v, Decimal("37.5"))

    def test_vacio(self):
        st, v = transform.parse_numeric("")
        self.assertEqual(st, transform.NUM_EMPTY)
        self.assertIsNone(v)

    def test_guion(self):
        st, v = transform.parse_numeric("-")
        self.assertEqual(st, transform.NUM_DASH)
        self.assertIsNone(v)

    def test_multipunto_ambiguo(self):
        st, v = transform.parse_numeric("528.169.014.084.507")
        self.assertEqual(st, transform.NUM_AMBIGUOUS)
        self.assertIsNone(v)

    def test_texto_inesperado(self):
        st, v = transform.parse_numeric("abc")
        self.assertEqual(st, transform.NUM_TEXT)
        self.assertIsNone(v)


class TestMultipuntoGeneraIncidencia(unittest.TestCase):
    def test_original_conservado_y_null(self):
        """Un valor multipunto se conserva como original, NULL + incidencia."""
        result = _build()
        # La fila NEO con densidad '31.697.341.513.292.400' (AMIKACINA 2022 T1)
        hecho = _find_hecho(result, "UPC_NEO", 2022, "TRIM1", "AMIKACINA_100_MG")
        self.assertIsNotNone(hecho)
        self.assertIsNone(hecho["densidad_archivo"])
        # transformación INVALIDO conserva el original
        trans = [t for t in result.transformaciones
                 if t["campo_destino"] == "densidad_archivo"
                 and t["carga_id"] == hecho["carga_id"]
                 and t["numero_fila"] == hecho["numero_fila"]]
        self.assertTrue(any(t["resultado"] == transform.RES_INVALIDO for t in trans))
        self.assertTrue(any(t["valor_original"] == "31.697.341.513.292.400" for t in trans))
        # incidencia VALOR_NUMERICO_INVALIDO
        incs = [i for i in result.incidencias
                if i["carga_id"] == hecho["carga_id"]
                and i["fila"] == hecho["numero_fila"]
                and i["tipo"] == transform.INC_VALOR_NUMERICO
                and i["columna"] == "DENSIDAD_DE_CONSUMO"]
        self.assertEqual(len(incs), 1)
        self.assertEqual(incs[0]["valor_original"], "31.697.341.513.292.400")

    def test_gasto_multipunto_en_metadata_genera_incidencia(self):
        """Metadata no es hecho, pero su GASTO inválido queda auditado."""
        result = _build()
        valor = "936.741.616.222.222"
        incs = [i for i in result.incidencias
                if i["tipo"] == transform.INC_VALOR_NUMERICO
                and i["columna"] == "GASTO" and i["valor_original"] == valor]
        self.assertEqual(len(incs), 1)
        self.assertIsNotNone(incs[0]["carga_id"])
        self.assertIsNotNone(incs[0]["fila"])
        trans = [t for t in result.transformaciones
                 if t["campo_destino"] == "gasto_archivo"
                 and t["valor_original"] == valor]
        self.assertTrue(any(t["resultado"] == transform.RES_INVALIDO for t in trans))


class TestSubtotales(unittest.TestCase):
    def test_subtotal_no_entra_como_hecho(self):
        result = _build()
        # ningún hecho debe tener medicamento terminado en _TOTAL
        self.assertTrue(all(not h["medicamento_normalizado"].endswith("_TOTAL")
                            for h in result.hechos))
        # todo subtotal debe quedar en transformaciones como IGNORADO_SUBTOTAL
        subtotales = [t for t in result.transformaciones
                      if t["resultado"] == transform.RES_IGNORADO_SUBTOTAL]
        self.assertEqual(result.resumen["subtotal"], len(subtotales))
        self.assertEqual(result.resumen["subtotal"], 204)
        self.assertTrue(all(t["regla_aplicada"] == transform.REGLA_SUBTOTAL
                            for t in subtotales))


class TestCalculations(unittest.TestCase):
    def test_gramos(self):
        self.assertEqual(transform.calculate_grams(Decimal("3"), Decimal("0.1")), Decimal("0.3"))
        self.assertIsNone(transform.calculate_grams(None, Decimal("0.1")))
        self.assertIsNone(transform.calculate_grams(Decimal("3"), None))

    def test_ddd_consumidas(self):
        self.assertEqual(transform.calculate_ddd(Decimal("12.4"), Decimal("1")), Decimal("12.4"))
        self.assertIsNone(transform.calculate_ddd(None, Decimal("1")))
        self.assertIsNone(transform.calculate_ddd(Decimal("12.4"), None))
        self.assertIsNone(transform.calculate_ddd(Decimal("12.4"), Decimal("0")))

    def test_densidad(self):
        d = transform.calculate_density(Decimal("0.3"), Decimal("8447"))
        self.assertEqual(d, Decimal("0.3") / Decimal("8447") * 100)
        self.assertIsNone(transform.calculate_density(None, Decimal("8447")))
        self.assertIsNone(transform.calculate_density(Decimal("0.3"), None))
        self.assertIsNone(transform.calculate_density(Decimal("0.3"), Decimal("0")))

    def test_gasto(self):
        self.assertEqual(transform.calculate_gasto(Decimal("10"), Decimal("2.5")), Decimal("25"))
        self.assertIsNone(transform.calculate_gasto(None, Decimal("2.5")))
        self.assertIsNone(transform.calculate_gasto(Decimal("10"), None))


class TestValidacionesGastoYDiasCama(unittest.TestCase):
    def test_gasto_difiere_conserva_observado_y_calculado(self):
        row = transform.RawRow(
            carga_id=9, numero_fila=7, archivo_origen="DDD_PRUEBA_2024_V2.XLSX",
            pestana_origen="TRIM1", cells={
                "FAMILIA_ATB": "PRUEBA", "MEDICAMENTO": "PRUEBA_1G", "PERIODO": "ENE-FEB-MAR",
                "DOSIS_GR": "1", "DDD": "1", "UNIDADES": "2", "GRAMOS": "2",
                "DENSIDAD": "1", "DIAS": "200", "PRECIO": "10", "GASTO": "25",
            })
        periodos = {"unidades": {"PRUEBA": {"tipo_paciente": "ADULTO", "periodos": {"2024": {
            "TRIM1": {"tipo_periodo": "TRIMESTRE", "numero_periodo": 1,
                      "etiqueta": "ENE-FEB-MAR", "inicio": "2024-01-01", "fin": "2024-03-31",
                      "columnas": {"unidades": "UNIDADES", "gramos_archivo": "GRAMOS",
                                   "densidad_archivo": "DENSIDAD", "dias_cama": "DIAS",
                                   "precio": "PRECIO", "gasto": "GASTO"}}}}}}}
        result = transform.transform_rows([row], periodos, {"presentaciones": {}, "subtotales": {}})
        self.assertEqual(result.hechos[0]["gasto_archivo"], Decimal("25"))
        self.assertEqual(result.hechos[0]["gasto_calculado"], Decimal("20"))
        incs = [i for i in result.incidencias if i["tipo"] == transform.INC_GASTO]
        self.assertEqual(len(incs), 1)
        self.assertEqual((incs[0]["carga_id"], incs[0]["fila"]), (9, 7))

    def test_dias_cama_inconsistente_referencia_fila_divergente(self):
        result = _build()
        hecho = _find_hecho(result, "UPC_NEO", 2022, "TRIM1", "CEFAZOLINA_1G")
        self.assertIsNotNone(hecho)
        incs = [i for i in result.incidencias
                if i["tipo"] == transform.INC_DIAS_CAMA
                and i["carga_id"] == hecho["carga_id"]
                and i["fila"] == hecho["numero_fila"]]
        self.assertEqual(len(incs), 1)
        self.assertEqual(incs[0]["valor_original"], "2496")


class TestConfigReal(unittest.TestCase):
    def test_cirugia_trim4_2023_desplazamiento(self):
        result = _build()
        h = _find_hecho(result, "CIRUGIA", 2023, "TRIM4", "AMIKACINA_100_MG")
        self.assertIsNotNone(h)
        # gramos desde GRAMOS, dias_cama desde TOTAL_GRAMOS (desplazamiento)
        self.assertEqual(h["gramos_archivo"], Decimal("0.3"))
        self.assertEqual(h["dias_cama"], Decimal("8447"))
        self.assertEqual(h["unidades"], Decimal("3"))
        # transformación de dias_cama debe ser NORMALIZADO y usar TOTAL_GRAMOS
        trans = [t for t in result.transformaciones
                 if t["campo_destino"] == "dias_cama"
                 and t["carga_id"] == h["carga_id"] and t["numero_fila"] == h["numero_fila"]]
        self.assertTrue(any(t["columna_origen"] == "TOTAL_GRAMOS"
                            and t["resultado"] == transform.RES_NORMALIZADO for t in trans))

    def test_upc_neo_2022_unidades_total_fa(self):
        result = _build()
        h = _find_hecho(result, "UPC_NEO", 2022, "TRIM1", "AMIKACINA_100_MG")
        self.assertIsNotNone(h)
        self.assertEqual(h["unidades"], Decimal("124"))
        self.assertEqual(h["gramos_archivo"], Decimal("12.4"))
        trans = [t for t in result.transformaciones
                 if t["campo_destino"] == "unidades"
                 and t["carga_id"] == h["carga_id"] and t["numero_fila"] == h["numero_fila"]]
        self.assertTrue(any(t["columna_origen"] == "TOTAL_FA" for t in trans))

    def test_medicina_2023_trim3_unidades_consumo_julio(self):
        result = _build()
        h = _find_hecho(result, "MEDICINA", 2023, "TRIM3", "AMIKACINA_100_MG")
        self.assertIsNotNone(h)
        self.assertEqual(h["unidades"], Decimal("3"))
        trans = [t for t in result.transformaciones
                 if t["campo_destino"] == "unidades"
                 and t["carga_id"] == h["carga_id"] and t["numero_fila"] == h["numero_fila"]]
        self.assertTrue(any(t["columna_origen"] == "CONSUMO_JULIO" for t in trans))

    def test_upc_ped_unidades_total_fa(self):
        result = _build()
        h = _find_hecho(result, "UPC_PED", 2022, "TRIM1", "AMIKACINA_100_MG")
        self.assertIsNotNone(h)
        self.assertEqual(h["unidades"], Decimal("29"))
        trans = [t for t in result.transformaciones
                 if t["campo_destino"] == "unidades"
                 and t["carga_id"] == h["carga_id"] and t["numero_fila"] == h["numero_fila"]]
        self.assertTrue(any(t["columna_origen"] == "TOTAL_FA" for t in trans))


class TestTraceability(unittest.TestCase):
    def test_hecho_recupera_valor_original(self):
        """analytics.consumo -> audit.transformacion -> raw.fila recupera el original."""
        result = _build()
        h = _find_hecho(result, "UPC_NEO", 2022, "TRIM1", "AMIKACINA_100_MG")
        self.assertIsNotNone(h)
        # localizar la fila raw correspondiente
        raw = next(r for r in _raw_rows_from_tsvs()
                   if r.carga_id == h["carga_id"] and r.numero_fila == h["numero_fila"])
        self.assertEqual(raw.cells["MEDICAMENTO"], h["medicamento_original"])
        # la transformación de medicamento conserva el original
        trans = [t for t in result.transformaciones
                 if t["campo_destino"] == "medicamento_normalizado"
                 and t["carga_id"] == h["carga_id"] and t["numero_fila"] == h["numero_fila"]]
        self.assertEqual(len(trans), 1)
        self.assertEqual(trans[0]["valor_original"], raw.cells["MEDICAMENTO"])
        # y para gramos_archivo: original == TOTAL_GR del raw
        trans_g = [t for t in result.transformaciones
                   if t["campo_destino"] == "gramos_archivo"
                   and t["carga_id"] == h["carga_id"] and t["numero_fila"] == h["numero_fila"]]
        self.assertEqual(trans_g[0]["valor_original"], raw.cells["TOTAL_GR"])


class TestDeterminismo(unittest.TestCase):
    def test_rebuild_determinista(self):
        result1 = _build()
        result2 = _build()
        self.assertEqual(result1.resumen, result2.resumen)
        self.assertEqual(result1.hechos, result2.hechos)
        self.assertEqual(result1.transformaciones, result2.transformaciones)
        self.assertEqual(result1.incidencias, result2.incidencias)


if __name__ == "__main__":
    unittest.main()
