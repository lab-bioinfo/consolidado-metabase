"""Transformación raw.fila -> interpretación trazable -> analytics.consumo.

Principios:

- No modifica ``data/input/`` ni ``raw``. Construye una capa analítica encima.
- Cada hecho analítico referencia su fila origen (carga_id, numero_fila,
  archivo_origen, pestana_origen).
- Cada interpretación relevante queda en ``audit.transformacion``; cada
  problema/ambigüedad queda en ``audit.incidencia``.
- Reglas dirigidas EXCLUSIVAMENTE por ``config/periodos.yml`` y
  ``config/aliases.yml`` (sin nombres de columna dispersos en el código).
- Deterministita: mismo raw + misma config + misma versión => mismo resultado.

El módulo expone funciones puras (testeables sin base de datos) y una función
de orquestación ``transform_rows`` que devuelve todo el material derivado sin
tocar la base de datos.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

# -----------------------------------------------------------------------------
# Estados de parseo numérico (explícito y conservador).
# -----------------------------------------------------------------------------
# VALID     -> número válido (entero o decimal con un solo punto).
# EMPTY     -> celda vacía (ausencia de dato; NULL, no 0).
# DASH      -> guion '-'/'—'/'–' (marcador de ausencia; NULL, sin incidencia).
# AMBIGUOUS -> múltiples puntos o comas (p.ej. "528.169.014.084.507"); no se
#              convierte; NULL + incidencia VALOR_NUMERICO_INVALIDO.
# TEXT      -> texto inesperado; NULL + incidencia VALOR_NUMERICO_INVALIDO.
NUM_VALID = "VALID"
NUM_EMPTY = "EMPTY"
NUM_DASH = "DASH"
NUM_AMBIGUOUS = "AMBIGUOUS"
NUM_TEXT = "TEXT"

_NUM_RE = re.compile(r"[+-]?\d+(\.\d+)?")

# Resultados de una transformación.
RES_DIRECTO = "DIRECTO"
RES_NORMALIZADO = "NORMALIZADO"
RES_CALCULADO = "CALCULADO"
RES_IGNORADO_SUBTOTAL = "IGNORADO_SUBTOTAL"
RES_IGNORADO_METADATA = "IGNORADO_METADATA"
RES_INVALIDO = "INVALIDO"
RES_PENDIENTE_VALIDACION = "PENDIENTE_VALIDACION"

# Reglas aplicadas (audit.transformacion.regla_aplicada).
REGLA_SUBTOTAL = "detectar_subtotal"
REGLA_METADATA = "detectar_metadata"
REGLA_MEDICAMENTO = "normalizar_medicamento"
REGLA_UNIDADES = "resolver_unidades"
REGLA_GRAMOS_ARCHIVO = "copiar_gramos_archivo"
REGLA_GRAMOS_CALC = "calcular_gramos"
REGLA_DDD_ARCHIVO = "copiar_ddd_archivo"
REGLA_DOSIS = "copiar_dosis_gr"
REGLA_DDD_USADA = "resolver_ddd_referencia"
REGLA_DDD_CONSUMIDAS = "calcular_ddd_consumidas"
REGLA_DENSIDAD_ARCHIVO = "copiar_densidad_archivo"
REGLA_DENSIDAD_CALC = "calcular_densidad"
REGLA_DIAS_CAMA = "resolver_dias_cama"
REGLA_PRECIO = "resolver_precio"
REGLA_GASTO_ARCHIVO = "copiar_gasto_archivo"
REGLA_GASTO_CALC = "calcular_gasto"
REGLA_PERIODO = "normalizar_periodo"

# Tipos de incidencia.
INC_VALOR_NUMERICO = "VALOR_NUMERICO_INVALIDO"
INC_PERIODO = "PERIODO_NORMALIZADO"
INC_DDD = "DDD_INCONSISTENTE"
INC_DOSIS = "DOSIS_PENDIENTE_VALIDACION"
INC_GRAMOS = "GRAMOS_DIFIEREN"
INC_DENSIDAD = "DENSIDAD_DIFIERE"
INC_SUBTOTAL = "SUBTOTAL_DIFIERE"
INC_DIAS_CAMA = "DIAS_CAMA_INCONSISTENTE"
INC_ALIAS = "ALIAS_PENDIENTE"
INC_COLUMNA = "COLUMNA_NO_INTERPRETADA"
INC_METRICA_PED = "METRICA_PEDIATRICA_NO_VALIDADA"
INC_GASTO = "GASTO_DIFIERE"

# Tolerancias técnicas (solo decimales) para comparaciones archivo vs cálculo.
# Son valores técnicos conservadores; la tolerancia "clínica" definitiva sigue
# pendiente de validación humana (CONTEXT.md §28 #9).
TOL_GRAMOS = Decimal("1e-6")      # absoluta (gramos)
TOL_GASTO = Decimal("1e-6")       # absoluta (gasto)
TOL_DENSIDAD_REL = Decimal("1e-6")  # relativa (densidad adimensional)

# Columnas estructurales siempre interpretadas (no son "no interpretadas").
_COLUMNAS_ESTRUCTURALES = {
    "ARCHIVO_ORIGEN",
    "PESTANA_ORIGEN",
    "PERIODO",
    "FAMILIA_ATB",
    "MEDICAMENTO",
    "DOSIS_GR",
    "DDD",
    "DIAS_CAMA_OCUPADOS",
}

_ARCHIVO_RE = re.compile(r"^DDD_(.+)_(\d{4})_V2\.XLSX$")


# -----------------------------------------------------------------------------
# Funciones puras
# -----------------------------------------------------------------------------
def parse_numeric(value: str | None) -> tuple[str, Decimal | None]:
    """Parseo numérico conservador. Devuelve ``(estado, valor)``.

    Nunca convierte silenciosamente un valor ambiguo. Ver ``NUM_*`` arriba.
    """
    if value is None:
        return (NUM_EMPTY, None)
    v = value.strip()
    if v == "":
        return (NUM_EMPTY, None)
    if v in ("-", "\u2014", "\u2013"):
        return (NUM_DASH, None)
    if _NUM_RE.fullmatch(v):
        try:
            return (NUM_VALID, Decimal(v))
        except InvalidOperation:
            return (NUM_AMBIGUOUS, None)
    if v.count(".") > 1 or v.count(",") > 1:
        return (NUM_AMBIGUOUS, None)
    if "," in v:
        return (NUM_AMBIGUOUS, None)
    return (NUM_TEXT, None)


def resolve_unidad(archivo_origen: str | None) -> str | None:
    """Extrae la clave de unidad desde ``ARCHIVO_ORIGEN``."""
    if not archivo_origen:
        return None
    m = _ARCHIVO_RE.match(archivo_origen)
    return m.group(1) if m else None


def extract_year_value(archivo_origen: str | None) -> int | None:
    """Extrae el año desde ``ARCHIVO_ORIGEN``."""
    if not archivo_origen:
        return None
    m = _ARCHIVO_RE.match(archivo_origen)
    return int(m.group(2)) if m else None


def normalize_medicamento(medicamento: str, presentaciones: dict[str, str]) -> tuple[str, bool]:
    """Aplica alias estructural de presentación. Devuelve ``(normalizado, aplicado)``."""
    canonico = presentaciones.get(medicamento)
    if canonico is not None:
        return canonico, True
    return medicamento, False


def normalize_subtotal(medicamento: str, subtotales: dict[str, str]) -> str:
    """Aplica alias de subtotal (p.ej. ``CLINDAMICINA_EV_TOTAL`` -> ``CLINDAMICINA_TOTAL``)."""
    return subtotales.get(medicamento, medicamento)


def classify_row(cells: dict[str, str]) -> str:
    """Clasifica una fila en PRESENTACION | SUBTOTAL | METADATA."""
    familia = cells.get("FAMILIA_ATB", "")
    medicamento = cells.get("MEDICAMENTO", "")
    if medicamento.endswith("_TOTAL"):
        return "SUBTOTAL"
    if familia == "" and medicamento == "":
        return "METADATA"
    return "PRESENTACION"


def calculate_grams(unidades: Decimal | None, dosis_gr: Decimal | None) -> Decimal | None:
    """``gramos = unidades × dosis_gr``. Entrada faltante -> ``None`` (nunca 0)."""
    if unidades is None or dosis_gr is None:
        return None
    return unidades * dosis_gr


def calculate_ddd(gramos: Decimal | None, ddd_ref: Decimal | None) -> Decimal | None:
    """``ddd_consumidas = gramos / ddd_referencia``. Entrada faltante -> ``None``."""
    if gramos is None or ddd_ref is None or ddd_ref == 0:
        return None
    return gramos / ddd_ref


def calculate_density(ddd_consumidas: Decimal | None, dias_cama: Decimal | None) -> Decimal | None:
    """``densidad = ddd_consumidas / dias_cama × 100``. Entrada faltante -> ``None``."""
    if ddd_consumidas is None or dias_cama is None or dias_cama == 0:
        return None
    return ddd_consumidas / dias_cama * 100


def calculate_gasto(unidades: Decimal | None, precio: Decimal | None) -> Decimal | None:
    """``gasto = unidades × precio_unitario``. Entrada faltante -> ``None``."""
    if unidades is None or precio is None:
        return None
    return unidades * precio


def _fmt(d: Decimal | None) -> str | None:
    return None if d is None else format(d, "f")


# -----------------------------------------------------------------------------
# Estructuras de resultado
# -----------------------------------------------------------------------------
@dataclass
class RawRow:
    carga_id: int
    numero_fila: int
    archivo_origen: str | None
    pestana_origen: str | None
    cells: dict[str, str]


@dataclass
class TransformResult:
    hechos: list[dict] = field(default_factory=list)
    transformaciones: list[dict] = field(default_factory=list)
    incidencias: list[dict] = field(default_factory=list)
    resumen: dict = field(default_factory=dict)


# -----------------------------------------------------------------------------
# Orquestación pura
# -----------------------------------------------------------------------------
def _block_for(periodos_cfg: dict, row: RawRow) -> dict | None:
    unidad = resolve_unidad(row.archivo_origen)
    anio = extract_year_value(row.archivo_origen)
    if unidad is None or anio is None:
        return None
    unidades_cfg = periodos_cfg.get("unidades", {})
    ucfg = unidades_cfg.get(unidad)
    if not ucfg:
        return None
    pcfg = ucfg.get("periodos", {}).get(str(anio), {})
    block = pcfg.get(row.pestana_origen)
    if block is None:
        return None
    return {
        "unidad": unidad,
        "anio": anio,
        "block": block,
        "ucfg": ucfg,
    }


def _cell(cells: dict[str, str], column: str | None) -> str | None:
    if column is None:
        return None
    return cells.get(column)


def _t(carga_id, numero_fila, archivo, pestana, campo, columna, valor_orig,
       valor_interp, regla, resultado) -> dict:
    return {
        "carga_id": carga_id,
        "numero_fila": numero_fila,
        "archivo_origen": archivo,
        "pestana_origen": pestana,
        "campo_destino": campo,
        "columna_origen": columna,
        "valor_original": valor_orig,
        "valor_interpretado": valor_interp,
        "regla_aplicada": regla,
        "resultado": resultado,
    }


def _i(carga_id, fila, archivo, columna, valor_original, tipo, descripcion,
       origen="ETL") -> dict:
    return {
        "carga_id": carga_id,
        "archivo": archivo,
        "fila": fila,
        "columna": columna,
        "valor_original": valor_original,
        "tipo": tipo,
        "descripcion": descripcion,
        "origen": origen,
    }


def _resolver_numerico(row, cells, column, campo, regla, result):
    """Resuelve una celda numérica: valor, transformación e incidencia."""
    raw = _cell(cells, column)
    status, valor = parse_numeric(raw)
    if status == NUM_VALID:
        result.transformaciones.append(
            _t(row.carga_id, row.numero_fila, row.archivo_origen, row.pestana_origen,
               campo, column, raw, _fmt(valor), regla, RES_DIRECTO)
        )
        return valor
    if status in (NUM_EMPTY, NUM_DASH):
        return None
    # AMBIGUOUS / TEXT -> NULL + incidencia
    result.transformaciones.append(
        _t(row.carga_id, row.numero_fila, row.archivo_origen, row.pestana_origen,
           campo, column, raw, None, regla, RES_INVALIDO)
    )
    result.incidencias.append(
        _i(row.carga_id, row.numero_fila, row.archivo_origen, column, raw,
           INC_VALOR_NUMERICO,
           f"Valor numérico no interpretable en columna {column!r} ({status}).")
    )
    return None


def _resolver_unidades(row, cells, block, result):
    """Resuelve unidades (columna única o suma de mensuales)."""
    cols = block["columnas"]
    if block.get("granularidad") == "mensual":
        mensuales = cols.get("unidades_mensuales") or []
        valores: list[Decimal] = []
        partes: list[str] = []
        todos_vacios = True
        for col in mensuales:
            raw = _cell(cells, col)
            status, valor = parse_numeric(raw)
            if status == NUM_VALID:
                valores.append(valor)
                todos_vacios = False
            elif status in (NUM_AMBIGUOUS, NUM_TEXT):
                # una celda mensual no válida invalida el total mensual
                result.transformaciones.append(
                    _t(row.carga_id, row.numero_fila, row.archivo_origen, row.pestana_origen,
                       "unidades", col, raw, None, REGLA_UNIDADES, RES_INVALIDO)
                )
                result.incidencias.append(
                    _i(row.carga_id, row.numero_fila, row.archivo_origen, col, raw,
                       INC_VALOR_NUMERICO,
                       f"Valor numérico no interpretable en columna {col!r} ({status}).")
                )
                return None
            # EMPTY / DASH: se ignora (no suma)
            partes.append(f"{col}={raw if raw else ''}")
        if todos_vacios:
            return None
        suma = sum(valores, Decimal(0))
        result.transformaciones.append(
            _t(row.carga_id, row.numero_fila, row.archivo_origen, row.pestana_origen,
               "unidades", " + ".join(mensuales), " + ".join(partes), _fmt(suma),
               REGLA_UNIDADES, RES_CALCULADO)
        )
        return suma
    col = cols.get("unidades")
    return _resolver_numerico(row, cells, col, "unidades", REGLA_UNIDADES, result)


def transform_rows(raw_rows: list[RawRow], periodos_cfg: dict,
                   aliases_cfg: dict) -> TransformResult:
    """Construye todo el material derivado (determinista, sin base de datos)."""
    result = TransformResult()
    presentaciones_alias = aliases_cfg.get("presentaciones", {})
    subtotales_alias = aliases_cfg.get("subtotales", {})
    unidades_cfg = periodos_cfg.get("unidades", {})

    # --- 1) clasificación y resolución de bloque ----------------------------
    registros = []  # lista de dicts con clasificación + bloque
    for row in raw_rows:
        clase = classify_row(row.cells)
        bloque = _block_for(periodos_cfg, row)
        registros.append({"row": row, "clase": clase, "bloque": bloque})

    # bases de subtotal (sustancias con fila _TOTAL) para agrupar V5
    subtotal_bases: set[str] = set()
    for reg in registros:
        if reg["clase"] == "SUBTOTAL":
            med_norm = normalize_subtotal(reg["row"].cells.get("MEDICAMENTO", ""), subtotales_alias)
            base = _subtotal_base(med_norm)
            if base:
                subtotal_bases.add(base)

    # --- 2) mapa global DDD conflictivo por medicamento normalizado ---------
    ddd_por_medicamento: dict[str, set[str]] = {}
    for reg in registros:
        if reg["clase"] != "PRESENTACION":
            continue
        row = reg["row"]
        med = row.cells.get("MEDICAMENTO", "")
        med_norm, _ = normalize_medicamento(med, presentaciones_alias)
        ddd_raw = row.cells.get("DDD", "")
        if ddd_raw.strip() == "":
            continue
        ddd_por_medicamento.setdefault(med_norm, set()).add(ddd_raw.strip())

    # --- 3) construir hechos -------------------------------------------------
    presentaciones_por_grupo: dict[tuple, list[dict]] = {}  # (bloque_key, base_subtotal) -> hechos
    dias_cama_por_bloque: dict[tuple, list[tuple[RawRow, str, str, Decimal]]] = {}
    subtotales_registrados: list[dict] = []

    for reg in registros:
        row = reg["row"]
        clase = reg["clase"]
        bloque = reg["bloque"]
        cells = row.cells

        if clase == "SUBTOTAL":
            med_norm = normalize_subtotal(cells.get("MEDICAMENTO", ""), subtotales_alias)
            result.transformaciones.append(
                _t(row.carga_id, row.numero_fila, row.archivo_origen, row.pestana_origen,
                   "medicamento", "MEDICAMENTO", cells.get("MEDICAMENTO"), med_norm,
                   REGLA_SUBTOTAL, RES_IGNORADO_SUBTOTAL)
            )
            subtotales_registrados.append({
                "row": row, "bloque": bloque, "med_norm": med_norm,
                "med_original": cells.get("MEDICAMENTO", ""),
            })
            continue

        if clase == "METADATA":
            # Las filas de total de gasto no son hechos, pero su único valor
            # numérico relevante debe validarse y conservar su trazabilidad.
            _resolver_numerico(
                row, cells, "GASTO", "gasto_archivo", REGLA_GASTO_ARCHIVO, result)
            result.transformaciones.append(
                _t(row.carga_id, row.numero_fila, row.archivo_origen, row.pestana_origen,
                   "gasto", "GASTO", cells.get("GASTO"), None,
                   REGLA_METADATA, RES_IGNORADO_METADATA)
            )
            continue

        # clase == PRESENTACION
        if bloque is None:
            # fila no interpretable (sin configuración): se conserva en raw y se marca
            result.incidencias.append(
                _i(row.carga_id, row.numero_fila, row.archivo_origen, "MEDICAMENTO",
                   cells.get("MEDICAMENTO"), INC_COLUMNA,
                   "Fila sin configuración de bloque (unidad/año/pestaña) interpretable.")
            )
            continue

        unidad = bloque["unidad"]
        anio = bloque["anio"]
        block = bloque["block"]
        ucfg = bloque["ucfg"]
        cols = block["columnas"]
        clave_bloque = (unidad, str(anio), row.pestana_origen)

        tipo_paciente = ucfg.get("tipo_paciente")
        tipo_periodo = block.get("tipo_periodo")
        numero_periodo = block.get("numero_periodo")
        periodo_etiqueta = block.get("etiqueta")
        fecha_inicio = block.get("inicio")
        fecha_fin = block.get("fin")

        med_original = cells.get("MEDICAMENTO", "")
        med_norm, alias_aplicado = normalize_medicamento(med_original, presentaciones_alias)

        # transformación de medicamento
        result.transformaciones.append(
            _t(row.carga_id, row.numero_fila, row.archivo_origen, row.pestana_origen,
               "medicamento_normalizado", "MEDICAMENTO", med_original, med_norm,
               REGLA_MEDICAMENTO, RES_NORMALIZADO if alias_aplicado else RES_DIRECTO)
        )

        # período: detección de normalización (variante o vacío)
        periodo_observado = cells.get("PERIODO", "")
        etiquetas_observadas = block.get("etiquetas_observadas", [])
        if periodo_observado != periodo_etiqueta:
            result.transformaciones.append(
                _t(row.carga_id, row.numero_fila, row.archivo_origen, row.pestana_origen,
                   "periodo_etiqueta", "PERIODO", periodo_observado, periodo_etiqueta,
                   REGLA_PERIODO, RES_NORMALIZADO)
            )
            result.incidencias.append(
                _i(row.carga_id, row.numero_fila, row.archivo_origen, "PERIODO",
                   periodo_observado, INC_PERIODO,
                   f"Período normalizado {periodo_observado!r} -> {periodo_etiqueta!r} "
                   f"(según PESTANA_ORIGEN {row.pestana_origen!r}).")
            )

        # dosis
        dosis_gr = _resolver_numerico(row, cells, "DOSIS_GR", "dosis_gr", REGLA_DOSIS, result)

        # unidades
        unidades = _resolver_unidades(row, cells, block, result)

        # gramos
        gramos_archivo = _resolver_numerico(
            row, cells, cols.get("gramos_archivo"), "gramos_archivo", REGLA_GRAMOS_ARCHIVO, result)
        gramos_calc = calculate_grams(unidades, dosis_gr)
        if gramos_calc is not None:
            result.transformaciones.append(
                _t(row.carga_id, row.numero_fila, row.archivo_origen, row.pestana_origen,
                   "gramos_calculados", None, None, _fmt(gramos_calc),
                   REGLA_GRAMOS_CALC, RES_CALCULADO)
            )

        # DDD
        ddd_archivo = _resolver_numerico(row, cells, "DDD", "ddd_archivo", REGLA_DDD_ARCHIVO, result)
        ddd_set = ddd_por_medicamento.get(med_norm, set())
        if med_norm in ddd_por_medicamento and len(ddd_set) > 1:
            ddd_usada = None
            result.transformaciones.append(
                _t(row.carga_id, row.numero_fila, row.archivo_origen, row.pestana_origen,
                   "ddd_referencia_usada", "DDD", _fmt(ddd_archivo), None,
                   REGLA_DDD_USADA, RES_PENDIENTE_VALIDACION)
            )
        else:
            ddd_usada = ddd_archivo
            result.transformaciones.append(
                _t(row.carga_id, row.numero_fila, row.archivo_origen, row.pestana_origen,
                   "ddd_referencia_usada", "DDD", _fmt(ddd_archivo), _fmt(ddd_usada),
                   REGLA_DDD_USADA, RES_DIRECTO)
            )

        # ddd consumidas
        ddd_consumidas = calculate_ddd(gramos_calc, ddd_usada)
        if ddd_consumidas is not None:
            result.transformaciones.append(
                _t(row.carga_id, row.numero_fila, row.archivo_origen, row.pestana_origen,
                   "ddd_consumidas", None, None, _fmt(ddd_consumidas),
                   REGLA_DDD_CONSUMIDAS, RES_CALCULADO)
            )

        # densidad archivo
        densidad_archivo = _resolver_numerico(
            row, cells, cols.get("densidad_archivo"), "densidad_archivo",
            REGLA_DENSIDAD_ARCHIVO, result)

        # días-cama (puede venir de columna alternativa por desplazamiento)
        dias_cama_col = cols.get("dias_cama")
        dias_cama_raw = _cell(cells, dias_cama_col)
        status_dc, dias_cama = parse_numeric(dias_cama_raw)
        if status_dc == NUM_VALID:
            # NORMALIZADO cuando la columna no es la estándar (desplazamiento
            # documentado en config, p.ej. CIRUGIA TRIM4 usa TOTAL_GRAMOS).
            resultado_dc = RES_DIRECTO if dias_cama_col == "DIAS_CAMA_OCUPADOS" else RES_NORMALIZADO
            result.transformaciones.append(
                _t(row.carga_id, row.numero_fila, row.archivo_origen, row.pestana_origen,
                   "dias_cama", dias_cama_col, dias_cama_raw, _fmt(dias_cama),
                   REGLA_DIAS_CAMA, resultado_dc)
            )
            dias_cama_por_bloque.setdefault(clave_bloque, []).append(
                (row, dias_cama_col, dias_cama_raw, dias_cama)
            )
        elif status_dc in (NUM_AMBIGUOUS, NUM_TEXT):
            result.transformaciones.append(
                _t(row.carga_id, row.numero_fila, row.archivo_origen, row.pestana_origen,
                   "dias_cama", dias_cama_col, dias_cama_raw, None,
                   REGLA_DIAS_CAMA, RES_INVALIDO)
            )
            result.incidencias.append(
                _i(row.carga_id, row.numero_fila, row.archivo_origen, dias_cama_col,
                   dias_cama_raw, INC_VALOR_NUMERICO,
                   f"Valor numérico no interpretable en columna {dias_cama_col!r}.")
            )
            dias_cama = None

        # densidad calculada
        densidad_calc = calculate_density(ddd_consumidas, dias_cama)
        if densidad_calc is not None:
            result.transformaciones.append(
                _t(row.carga_id, row.numero_fila, row.archivo_origen, row.pestana_origen,
                   "densidad_calculada", None, None, _fmt(densidad_calc),
                   REGLA_DENSIDAD_CALC, RES_CALCULADO)
            )

        # precio y gasto (solo bloques que traen esas columnas)
        precio = _resolver_numerico(row, cells, cols.get("precio"), "precio_unitario", REGLA_PRECIO, result)
        gasto_archivo = _resolver_numerico(row, cells, cols.get("gasto"), "gasto_archivo", REGLA_GASTO_ARCHIVO, result)
        gasto_calc = calculate_gasto(unidades, precio)
        if gasto_calc is not None:
            result.transformaciones.append(
                _t(row.carga_id, row.numero_fila, row.archivo_origen, row.pestana_origen,
                   "gasto_calculado", None, None, _fmt(gasto_calc),
                   REGLA_GASTO_CALC, RES_CALCULADO)
            )

        # Validación V3 (gramos archivo vs cálculo)
        gramos_difieren = False
        if gramos_archivo is not None and gramos_calc is not None:
            diff = abs(gramos_archivo - gramos_calc)
            if diff > TOL_GRAMOS:
                gramos_difieren = True
                result.incidencias.append(
                    _i(row.carga_id, row.numero_fila, row.archivo_origen, cols.get("gramos_archivo"),
                       _fmt(gramos_archivo), INC_GRAMOS,
                       f"Gramos archivo {_fmt(gramos_archivo)} difiere de unidades×dosis "
                       f"{_fmt(gramos_calc)} (diferencia {_fmt(diff)}).")
                )

        # Validación de gasto observado vs calculado. Conserva ambos valores:
        # la discrepancia solo queda explícita en auditoría.
        if gasto_archivo is not None and gasto_calc is not None:
            diff = abs(gasto_archivo - gasto_calc)
            if diff > TOL_GASTO:
                result.incidencias.append(
                    _i(row.carga_id, row.numero_fila, row.archivo_origen, cols.get("gasto"),
                       _fmt(gasto_archivo), INC_GASTO,
                       f"Gasto archivo {_fmt(gasto_archivo)} difiere de unidades×precio "
                       f"{_fmt(gasto_calc)} (diferencia {_fmt(diff)}).")
                )

        # Validación V4 (densidad archivo vs cálculo) solo si DDD fiable y
        # gramos_calculados fiables (sin discrepancia V3).
        if (densidad_archivo is not None and densidad_calc is not None
                and ddd_usada is not None and not gramos_difieren):
            diff = abs(densidad_archivo - densidad_calc)
            umbral = TOL_DENSIDAD_REL * max(Decimal(1), abs(densidad_archivo))
            if diff > umbral:
                result.incidencias.append(
                    _i(row.carga_id, row.numero_fila, row.archivo_origen, cols.get("densidad_archivo"),
                       _fmt(densidad_archivo), INC_DENSIDAD,
                       f"Densidad archivo {_fmt(densidad_archivo)} difiere de la calculada "
                       f"{_fmt(densidad_calc)} (diferencia {_fmt(diff)}).")
                )

        # Flag clínico pediátrico/neonatal
        densidad_clinica = None
        if unidad in ("UPC_NEO", "UPC_PED"):
            densidad_clinica = False

        hecho = {
            "unidad": unidad,
            "tipo_paciente": tipo_paciente,
            "anio": anio,
            "tipo_periodo": tipo_periodo,
            "numero_periodo": numero_periodo,
            "periodo_etiqueta": periodo_etiqueta,
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
            "familia": cells.get("FAMILIA_ATB"),
            "medicamento": med_norm,
            "presentacion": med_norm,
            "medicamento_original": med_original,
            "medicamento_normalizado": med_norm,
            "dosis_gr": dosis_gr,
            "unidades": unidades,
            "gramos": gramos_calc,
            "gramos_archivo": gramos_archivo,
            "gramos_calculados": gramos_calc,
            "ddd_archivo": ddd_archivo,
            "ddd_referencia": ddd_usada,
            "ddd_referencia_usada": ddd_usada,
            "ddd_consumidas": ddd_consumidas,
            "densidad_archivo": densidad_archivo,
            "densidad_calculada": densidad_calc,
            "ddd_100_dias_cama": densidad_calc,
            "dias_cama": dias_cama,
            "precio_unitario": precio,
            "gasto": gasto_calc,
            "gasto_archivo": gasto_archivo,
            "gasto_calculado": gasto_calc,
            "densidad_clinica_validada": densidad_clinica,
            "archivo_origen": row.archivo_origen,
            "pestana_origen": row.pestana_origen,
            "numero_fila": row.numero_fila,
            "carga_id": row.carga_id,
        }
        result.hechos.append(hecho)

        # agrupar para V5 (por base de sustancia con subtotal)
        base_presentacion = _presentacion_base(med_norm, subtotal_bases)
        if base_presentacion is not None:
            presentaciones_por_grupo.setdefault((clave_bloque, base_presentacion), []).append(hecho)

    # --- 4) columnas no interpretadas (una incidencia por columna+bloque) -----
    _registrar_columnas_no_interpretadas(registros, result)

    # --- 5) V6: días-cama inconsistentes por bloque --------------------------
    for clave_bloque, observaciones in dias_cama_por_bloque.items():
        valores = Counter(valor for _, _, _, valor in observaciones)
        if len(valores) > 1:
            unidad, anio, pestana = clave_bloque
            frecuencia_maxima = max(valores.values())
            valores_referencia = {
                valor for valor, frecuencia in valores.items() if frecuencia == frecuencia_maxima
            }
            # Si no hay una moda inequívoca, cada fila forma parte de la
            # inconsistencia; siempre se conserva la fila concreta de origen.
            divergentes = (
                observaciones if len(valores_referencia) > 1 else
                [o for o in observaciones if o[3] not in valores_referencia]
            )
            valores_texto = sorted(_fmt(valor) for valor in valores)
            for row, columna, raw, valor in divergentes:
                result.incidencias.append(
                    _i(row.carga_id, row.numero_fila, row.archivo_origen, columna, raw,
                       INC_DIAS_CAMA,
                       f"Días-cama {_fmt(valor)} divergente en bloque {unidad} {anio} {pestana}; "
                       f"valores observados: {valores_texto}.")
                )

    # --- 6) V5: subtotales vs suma de presentaciones -------------------------
    for sub in subtotales_registrados:
        bloque = sub["bloque"]
        if bloque is None:
            continue
        unidad = bloque["unidad"]; anio = bloque["anio"]
        clave_bloque = (unidad, str(anio), sub["row"].pestana_origen)
        base = _subtotal_base(sub["med_norm"])
        if base is None:
            continue
        cols = bloque["block"]["columnas"]
        gramos_col = cols.get("gramos_archivo")
        gramos_raw = _cell(sub["row"].cells, gramos_col)
        status, subtotal_gramos = parse_numeric(gramos_raw)
        if status != NUM_VALID:
            continue
        hechos_grupo = presentaciones_por_grupo.get((clave_bloque, base), [])
        if not hechos_grupo:
            continue
        suma = sum((h["gramos_archivo"] or Decimal(0)) for h in hechos_grupo if h["gramos_archivo"] is not None)
        diff = abs(suma - subtotal_gramos)
        if diff > TOL_GRAMOS:
            result.incidencias.append(
                _i(sub["row"].carga_id, sub["row"].numero_fila, sub["row"].archivo_origen,
                   gramos_col, gramos_raw, INC_SUBTOTAL,
                   f"Subtotal {sub['med_norm']} ({_fmt(subtotal_gramos)}) difiere de la suma "
                   f"de presentaciones ({_fmt(suma)}), diferencia {_fmt(diff)}.")
            )

    # --- 7) DDD inconsistente (una incidencia por medicamento) ---------------
    for med_norm, valores in sorted(ddd_por_medicamento.items()):
        if len(valores) > 1:
            # referencia a una fila representativa
            rep = next((r for r in registros
                        if r["clase"] == "PRESENTACION"
                        and normalize_medicamento(r["row"].cells.get("MEDICAMENTO", ""),
                                                  presentaciones_alias)[0] == med_norm), None)
            result.incidencias.append(
                _i(rep["row"].carga_id if rep else None,
                   rep["row"].numero_fila if rep else None,
                   rep["row"].archivo_origen if rep else None,
                   "DDD", None, INC_DDD,
                   f"DDD conflictivo para {med_norm!r}: valores {sorted(valores)}. "
                   f"ddd_referencia_usada=NULL (pendiente validación clínica); no se homogeniza.")
            )

    # --- 8) DOSIS pendiente de validación (AMPICILINA/SULBACTAM_1.5G) ---------
    dosis_pendiente = {"AMPICILINA/SULBACTAM_1.5G"}
    for reg in registros:
        if reg["clase"] != "PRESENTACION":
            continue
        med = reg["row"].cells.get("MEDICAMENTO", "")
        med_norm, _ = normalize_medicamento(med, presentaciones_alias)
        if med_norm in dosis_pendiente:
            result.incidencias.append(
                _i(reg["row"].carga_id, reg["row"].numero_fila, reg["row"].archivo_origen,
                   "DOSIS_GR", reg["row"].cells.get("DOSIS_GR"), INC_DOSIS,
                   f"DOSIS_GR del archivo ({reg['row'].cells.get('DOSIS_GR')}) difiere del "
                   f"gramaje del nombre de {med_norm!r} (1.5G). Pendiente validación clínica.")
            )
            break  # una única incidencia representativa

    # --- 9) métrica pediátrica/neonatal --------------------------------------
    for unidad_ in ("UPC_NEO", "UPC_PED"):
        rep = next((r for r in registros
                    if r["clase"] == "PRESENTACION" and r["bloque"] is not None
                    and r["bloque"]["unidad"] == unidad_), None)
        if rep is not None:
            result.incidencias.append(
                _i(rep["row"].carga_id, None, rep["row"].archivo_origen, "DENSIDAD_DE_CONSUMO",
                   None, INC_METRICA_PED,
                   f"DDD/100 días-cama calculable matemáticamente para {unidad_} pero "
                   f"NO validada clínicamente en población pediátrica/neonatal.")
            )

    # --- 10) resumen ----------------------------------------------------------
    n_presentacion = sum(1 for r in registros if r["clase"] == "PRESENTACION")
    n_subtotal = sum(1 for r in registros if r["clase"] == "SUBTOTAL")
    n_metadata = sum(1 for r in registros if r["clase"] == "METADATA")
    n_no_interp = sum(1 for r in registros if r["clase"] == "PRESENTACION" and r["bloque"] is None)
    result.resumen = {
        "filas_total": len(raw_rows),
        "presentacion": n_presentacion,
        "subtotal": n_subtotal,
        "metadata": n_metadata,
        "no_interpretable": n_no_interp,
        "hechos": len(result.hechos),
        "transformaciones": len(result.transformaciones),
        "incidencias": len(result.incidencias),
        "gramos_calculables": sum(1 for h in result.hechos if h["gramos_calculados"] is not None),
        "ddd_consumidas_calculables": sum(1 for h in result.hechos if h["ddd_consumidas"] is not None),
        "densidad_calculable": sum(1 for h in result.hechos if h["densidad_calculada"] is not None),
        "gasto_calculable": sum(1 for h in result.hechos if h["gasto_calculado"] is not None),
    }
    return result


def _subtotal_base(med_norm: str) -> str | None:
    """Devuelve la base (prefijo de sustancia) de un subtotal normalizado, o None."""
    if not med_norm.endswith("_TOTAL"):
        return None
    return med_norm[: -len("_TOTAL")]


def _presentacion_base(med_norm: str, bases: set[str]) -> str | None:
    """Devuelve la base de sustancia de una presentación si pertenece a un grupo
    de subtotal conocido (prefijo ``base_``), o ``None``."""
    for b in bases:
        if med_norm.startswith(b + "_"):
            return b
    return None


def _registrar_columnas_no_interpretadas(registros: list[dict], result: TransformResult) -> None:
    """Registra columnas con dato no consumido (COLUMNA_NO_INTERPRETADA).

    Se emite UNA incidencia por (columna, bloque) para no saturar el audit; el
    detalle de anomalías ya está en config/periodos.yml y docs/data-profile.md.
    """
    vistos: set[tuple] = set()
    for reg in registros:
        if reg["clase"] != "PRESENTACION" or reg["bloque"] is None:
            continue
        row = reg["row"]
        block = reg["bloque"]["block"]
        cols = block["columnas"]
        consumidas = set(_COLUMNAS_ESTRUCTURALES)
        if cols.get("unidades"):
            consumidas.add(cols["unidades"])
        for c in (cols.get("unidades_mensuales") or []):
            consumidas.add(c)
        for k in ("gramos_archivo", "densidad_archivo", "dias_cama", "precio", "gasto"):
            if cols.get(k):
                consumidas.add(cols[k])
        for column, value in row.cells.items():
            if column in consumidas or value.strip() == "":
                continue
            clave = (row.archivo_origen, row.pestana_origen, column)
            if clave in vistos:
                continue
            vistos.add(clave)
            result.incidencias.append(
                _i(row.carga_id, row.numero_fila, row.archivo_origen, column, value,
                   INC_COLUMNA,
                   f"Columna {column!r} con dato no interpretado por la configuración "
                   f"(bloque {row.pestana_origen!r}).")
            )
