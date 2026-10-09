"""Aplica por API el rediseño seguro del dashboard de antimicrobianos.

Requiere METABASE_API_KEY y no escribe en PostgreSQL ni en las fuentes mart.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BASE_URL = "http://localhost:3001/api"
DASHBOARD_ID = 2
DATABASE_ID = 3

# Parámetros de dashboard existentes, conservados para no invalidar enlaces.
PARAMS = {
    "unidad": "41bbeb41-276a-4119-8bfa-c34d72315033",
    "familia": "ffb51f19-ea86-4172-af4b-633acb22457f",
    "medicamento": "f647e57f-db40-45f4-af2a-db8980c615d4",
    "anio": "ca1fbe3f-279a-4ec7-9d15-e74393b907e6",
    "periodo": "96a23cc8-c960-46d8-a3fd-f8c48f1cd98f",
    "metrica": "bf28c03e-ecfc-4a41-91aa-52fe339e3d72",
}

FIELDS = {
    "consumo": {"unidad": 1853, "familia": 1855, "medicamento": 1856, "periodo": 1852},
    "agregado": {"unidad": 1886, "periodo": 1885},
    "largo": {"unidad": 1898, "familia": 1900, "medicamento": 1901, "periodo": 1897, "metrica": 1902},
}


def request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    key = os.environ.get("METABASE_API_KEY")
    if not key:
        raise RuntimeError("METABASE_API_KEY no está definida")
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers={"X-API-Key": key, "Content-Type": "application/json"},
    )
    try:
        with urlopen(req) as response:
            body = response.read()
            return json.loads(body or b"null")
    except HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path}: HTTP {error.code}: {detail}") from error


def dimension_tag(name: str, field_id: int, number: bool = False) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "display-name": {"anio": "Año", "metrica": "Métrica"}.get(name, name.capitalize()),
        "type": "dimension",
        "widget-type": "number" if number else "category",
        "dimension": [
            "field",
            {"lib/uuid": str(uuid.uuid4()), "base-type": "type/Integer" if number else "type/Text", "effective-type": "type/Integer" if number else "type/Text"},
            field_id,
        ],
        "required": False,
    }


def number_tag(name: str) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "display-name": "Año",
        "type": "number",
        "widget-type": "number",
        "required": False,
    }


def native_query(sql: str, tags: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "database": DATABASE_ID,
        "lib/type": "mbql/query",
        "stages": [{
            "lib/type": "mbql.stage/native",
            "native": sql,
            "template-tags": tags,
        }],
    }


def card_payload(name: str, description: str, display: str, sql: str, tags: list[dict[str, Any]], settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "display": display,
        "dataset_query": native_query(sql, tags),
        "visualization_settings": settings,
    }


def tags(source: str, names: list[str], include_year: bool = True) -> list[dict[str, Any]]:
    output = [dimension_tag(name, FIELDS[source][name]) for name in names]
    if include_year:
        output.append(number_tag("anio"))
    return output


def mappings(tag_names: list[str], card_id: int) -> list[dict[str, Any]]:
    output = []
    for name in tag_names:
        target_kind = "variable" if name == "anio" else "dimension"
        output.append({
            "card_id": card_id,
            "parameter_id": PARAMS[name],
            "target": [target_kind, ["template-tag", name]],
        })
    return output


def main() -> None:
    dashboard = request("GET", f"/dashboard/{DASHBOARD_ID}")
    if dashboard["name"] != "Consumo de antimicrobianos":
        raise RuntimeError("El dashboard id 2 no coincide con el dashboard esperado")
    dashcard_by_card = {item["card_id"]: item for item in dashboard["dashcards"]}

    # Cada definición usa solo columnas de mart y conserva NULL. Las tarjetas
    # basadas en consumo_largo reciben Métrica; las de densidad no, por seguridad.
    cards = {
        41: card_payload(
            "Evolución histórica del consumo",
            "Métricas aditivas por unidad y período. Seleccione Métrica; la densidad adulta se muestra en la tarjeta segura siguiente.",
            "line",
            """SELECT fecha_inicio, MIN(periodo) AS periodo, unidad, SUM(valor) AS valor
FROM mart.consumo_largo
WHERE 1=1
  AND metrica IN ('unidades', 'gramos', 'ddd_consumidas', 'gasto')
[[AND {{metrica}} --]] AND metrica = 'unidades'
[[AND {{unidad}}]]
[[AND {{familia}}]]
[[AND {{medicamento}}]]
[[AND EXTRACT(YEAR FROM fecha_inicio) = {{anio}}]]
[[AND {{periodo}}]]
GROUP BY fecha_inicio, unidad
ORDER BY fecha_inicio, unidad""",
            tags("largo", ["metrica", "unidad", "familia", "medicamento", "periodo"]),
            {"graph.dimensions": ["fecha_inicio", "unidad"], "graph.metrics": ["valor"], "graph.x_axis.title_text": "Período", "graph.y_axis.title_text": "Consumo"},
        ),
        40: card_payload(
            "Evolución DDD/100 días-cama (adultos)",
            "Densidad adulta segura: recalculada desde DDD consumidas y días-cama en mart.consumo_agregado. No incluye UPC pediátrica/neonatal.",
            "line",
            """SELECT fecha_inicio, MIN(periodo) AS periodo, unidad,
       SUM(ddd_consumidas_validas) / NULLIF(SUM(dias_cama_componentes_validos), 0) * 100 AS ddd_100_dias_cama
FROM mart.consumo_agregado
WHERE ddd_100_dias_cama IS NOT NULL
[[AND {{unidad}}]]
[[AND anio = {{anio}}]]
[[AND {{periodo}}]]
GROUP BY fecha_inicio, unidad
ORDER BY fecha_inicio, unidad""",
            tags("agregado", ["unidad", "periodo"]),
            {"graph.dimensions": ["fecha_inicio", "unidad"], "graph.metrics": ["ddd_100_dias_cama"], "graph.x_axis.title_text": "Período", "graph.y_axis.title_text": "DDD/100 días-cama"},
        ),
        42: card_payload(
            "Comparación por unidad",
            "Comparación descendente para métricas aditivas; no presenta densidad pediátrica/neonatal como equivalente clínica.",
            "bar",
            """SELECT unidad, SUM(valor) AS valor
FROM mart.consumo_largo
WHERE 1=1
  AND metrica IN ('unidades', 'gramos', 'ddd_consumidas', 'gasto')
[[AND {{metrica}} --]] AND metrica = 'unidades'
[[AND {{unidad}}]]
[[AND {{familia}}]]
[[AND {{medicamento}}]]
[[AND EXTRACT(YEAR FROM fecha_inicio) = {{anio}}]]
[[AND {{periodo}}]]
GROUP BY unidad
ORDER BY valor DESC, unidad""",
            tags("largo", ["metrica", "unidad", "familia", "medicamento", "periodo"]),
            {"graph.dimensions": ["unidad"], "graph.metrics": ["valor"], "graph.x_axis.title_text": "Unidad", "graph.y_axis.title_text": "Consumo"},
        ),
        43: card_payload(
            "Top medicamentos del período",
            "Top 10 descendente para una única métrica aditiva seleccionada; no mezcla métricas.",
            "bar",
            """SELECT medicamento, SUM(valor) AS valor
FROM mart.consumo_largo
WHERE 1=1
  AND metrica IN ('unidades', 'gramos', 'ddd_consumidas', 'gasto')
[[AND {{metrica}} --]] AND metrica = 'unidades'
[[AND {{unidad}}]]
[[AND {{familia}}]]
[[AND {{medicamento}}]]
[[AND EXTRACT(YEAR FROM fecha_inicio) = {{anio}}]]
[[AND {{periodo}}]]
GROUP BY medicamento
ORDER BY valor DESC, medicamento
LIMIT 10""",
            tags("largo", ["metrica", "unidad", "familia", "medicamento", "periodo"]),
            {"graph.dimensions": ["medicamento"], "graph.metrics": ["valor"], "graph.x_axis.title_text": "Medicamento", "graph.y_axis.title_text": "Consumo"},
        ),
        44: card_payload(
            "Detalle y trazabilidad de consumo",
            "Hechos trazables sin subtotales ni JSON raw; los NULL se conservan visibles.",
            "table",
            """SELECT periodo, fecha_inicio, unidad, familia, medicamento, unidades,
       gramos_calculados AS gramos, ddd_consumidas,
       ddd_100_dias_cama_calculada AS ddd_100_dias_cama,
       gasto_calculado AS gasto, archivo_origen, pestana_origen, numero_fila
FROM mart.consumo
WHERE 1=1
[[AND {{unidad}}]]
[[AND {{familia}}]]
[[AND {{medicamento}}]]
[[AND anio = {{anio}}]]
[[AND {{periodo}}]]
ORDER BY fecha_inicio DESC, unidad, medicamento""",
            tags("consumo", ["unidad", "familia", "medicamento", "periodo"]),
            {},
        ),
        45: card_payload("Evolución de gramos", "Suma de gramos calculados por período y unidad.", "line", """SELECT fecha_inicio, MIN(periodo) AS periodo, unidad, SUM(gramos_calculados) AS gramos
FROM mart.consumo
WHERE gramos_calculados IS NOT NULL
[[AND {{unidad}}]] [[AND {{familia}}]] [[AND {{medicamento}}]]
[[AND anio = {{anio}}]] [[AND {{periodo}}]]
GROUP BY fecha_inicio, unidad ORDER BY fecha_inicio, unidad""", tags("consumo", ["unidad", "familia", "medicamento", "periodo"]), {"graph.dimensions": ["fecha_inicio", "unidad"], "graph.metrics": ["gramos"], "graph.x_axis.title_text": "Período", "graph.y_axis.title_text": "Gramos"}),
        46: card_payload("Evolución de gasto", "Suma de gasto calculado por período y unidad; NULL no se reemplaza por cero.", "line", """SELECT fecha_inicio, MIN(periodo) AS periodo, unidad, SUM(gasto_calculado) AS gasto
FROM mart.consumo
WHERE gasto_calculado IS NOT NULL
[[AND {{unidad}}]] [[AND {{familia}}]] [[AND {{medicamento}}]]
[[AND anio = {{anio}}]] [[AND {{periodo}}]]
GROUP BY fecha_inicio, unidad ORDER BY fecha_inicio, unidad""", tags("consumo", ["unidad", "familia", "medicamento", "periodo"]), {"graph.dimensions": ["fecha_inicio", "unidad"], "graph.metrics": ["gasto"], "graph.x_axis.title_text": "Período", "graph.y_axis.title_text": "Gasto"}),
        47: card_payload("Top 10 medicamentos por gasto", "Top 10 descendente por suma de gasto calculado.", "bar", """SELECT medicamento, SUM(gasto_calculado) AS gasto
FROM mart.consumo WHERE gasto_calculado IS NOT NULL
[[AND {{unidad}}]] [[AND {{familia}}]] [[AND {{medicamento}}]]
[[AND anio = {{anio}}]] [[AND {{periodo}}]]
GROUP BY medicamento ORDER BY gasto DESC, medicamento LIMIT 10""", tags("consumo", ["unidad", "familia", "medicamento", "periodo"]), {"graph.dimensions": ["medicamento"], "graph.metrics": ["gasto"], "graph.x_axis.title_text": "Medicamento", "graph.y_axis.title_text": "Gasto"}),
        48: card_payload("Comparación de gasto por unidad", "Suma de gasto calculado por unidad, en orden descendente.", "bar", """SELECT unidad, SUM(gasto_calculado) AS gasto
FROM mart.consumo WHERE gasto_calculado IS NOT NULL
[[AND {{unidad}}]] [[AND {{familia}}]] [[AND {{medicamento}}]]
[[AND anio = {{anio}}]] [[AND {{periodo}}]]
GROUP BY unidad ORDER BY gasto DESC, unidad""", tags("consumo", ["unidad", "familia", "medicamento", "periodo"]), {"graph.dimensions": ["unidad"], "graph.metrics": ["gasto"], "graph.x_axis.title_text": "Unidad", "graph.y_axis.title_text": "Gasto"}),
        51: card_payload("Detalle trazable de gramos y gasto", "Detalle trazable de valores calculados; no expone JSON raw.", "table", """SELECT periodo, fecha_inicio, unidad, familia, medicamento,
       gramos_calculados AS gramos, gasto_calculado AS gasto,
       archivo_origen, pestana_origen, numero_fila
FROM mart.consumo WHERE 1=1
[[AND {{unidad}}]] [[AND {{familia}}]] [[AND {{medicamento}}]]
[[AND anio = {{anio}}]] [[AND {{periodo}}]]
ORDER BY fecha_inicio DESC, unidad, medicamento""", tags("consumo", ["unidad", "familia", "medicamento", "periodo"]), {}),
        49: card_payload("Incidencias totales", "Conteo de incidencias no nulas.", "scalar", "SELECT COUNT(incidencia_id) AS total_incidencias FROM mart.calidad WHERE incidencia_id IS NOT NULL", [], {"scalar.field": "total_incidencias"}),
        52: card_payload("Valores numéricos inválidos", "Conteo de incidencias VALOR_NUMERICO_INVALIDO.", "scalar", "SELECT COUNT(incidencia_id) AS total FROM mart.calidad WHERE tipo_incidencia = 'VALOR_NUMERICO_INVALIDO'", [], {"scalar.field": "total"}),
        53: card_payload("Diferencias de gramos", "Conteo de incidencias GRAMOS_DIFIEREN.", "scalar", "SELECT COUNT(incidencia_id) AS total FROM mart.calidad WHERE tipo_incidencia = 'GRAMOS_DIFIEREN'", [], {"scalar.field": "total"}),
        54: card_payload("Diferencias de gasto", "Conteo de incidencias GASTO_DIFIERE.", "scalar", "SELECT COUNT(incidencia_id) AS total FROM mart.calidad WHERE tipo_incidencia = 'GASTO_DIFIERE'", [], {"scalar.field": "total"}),
        55: card_payload("Incidencias por tipo", "Todos los tipos de incidencia, ordenados de mayor a menor.", "bar", """SELECT tipo_incidencia, COUNT(incidencia_id) AS total_incidencias
FROM mart.calidad WHERE incidencia_id IS NOT NULL
GROUP BY tipo_incidencia ORDER BY total_incidencias DESC, tipo_incidencia""", [], {"graph.dimensions": ["tipo_incidencia"], "graph.metrics": ["total_incidencias"], "graph.x_axis.title_text": "Tipo", "graph.y_axis.title_text": "Incidencias"}),
        50: card_payload("Detalle de incidencias", "Detalle trazable sin JSON raw como contenido principal.", "table", """SELECT tipo_incidencia, archivo_afectado, pestana_afectada, fila_afectada,
       columna_afectada, valor_original, descripcion
FROM mart.calidad WHERE incidencia_id IS NOT NULL
ORDER BY tipo_incidencia, archivo_afectado, fila_afectada""", [], {}),
    }

    # Ejecutar las consultas antes de guardar evita publicar sintaxis inválida.
    for card_id, payload in cards.items():
        request("POST", "/dataset", payload["dataset_query"])
        request("PUT", f"/card/{card_id}", payload)

    parameters = [
        {"id": PARAMS["unidad"], "name": "Unidad", "slug": "unidad", "type": "category"},
        {"id": PARAMS["familia"], "name": "Familia ATB", "slug": "familia", "type": "category"},
        {"id": PARAMS["medicamento"], "name": "Medicamento", "slug": "medicamento", "type": "category"},
        {"id": PARAMS["metrica"], "name": "Métrica", "slug": "metrica", "type": "category"},
        {"id": PARAMS["anio"], "name": "Año", "slug": "anio", "type": "number"},
        {"id": PARAMS["periodo"], "name": "Período", "slug": "periodo", "type": "category"},
    ]
    request("PUT", f"/dashboard/{DASHBOARD_ID}", {
        "name": "Consumo de antimicrobianos",
        "description": "Consulta para decisiones. Las métricas aditivas y la densidad adulta usan fuentes separadas para preservar agregaciones correctas.",
        "parameters": parameters,
        "width": "full",
    })

    layouts = {
        41: (4, 0, 0, 12, 5, ["metrica", "unidad", "familia", "medicamento", "anio", "periodo"]),
        40: (4, 5, 0, 12, 4, ["unidad", "anio", "periodo"]),
        42: (4, 9, 0, 6, 4, ["metrica", "familia", "medicamento", "anio", "periodo"]),
        43: (4, 9, 6, 6, 4, ["metrica", "unidad", "familia", "medicamento", "anio", "periodo"]),
        44: (4, 13, 0, 12, 6, ["unidad", "familia", "medicamento", "anio", "periodo"]),
        45: (5, 0, 0, 6, 4, ["unidad", "familia", "medicamento", "anio", "periodo"]),
        46: (5, 0, 6, 6, 4, ["unidad", "familia", "medicamento", "anio", "periodo"]),
        47: (5, 4, 0, 6, 4, ["unidad", "familia", "medicamento", "anio", "periodo"]),
        48: (5, 4, 6, 6, 4, ["familia", "medicamento", "anio", "periodo"]),
        51: (5, 8, 0, 12, 6, ["unidad", "familia", "medicamento", "anio", "periodo"]),
        49: (6, 0, 0, 3, 2, []), 52: (6, 0, 3, 3, 2, []), 53: (6, 0, 6, 3, 2, []), 54: (6, 0, 9, 3, 2, []),
        55: (6, 2, 0, 12, 4, []), 50: (6, 6, 0, 12, 6, []),
    }
    # Metabase actualiza el conjunto de tarjetas del dashboard mediante un único
    # PUT. Se preservan los 16 dashcards existentes y solo cambia su geometría
    # y sus conexiones de filtro.
    dashboard_cards = []
    for card_id, (tab, row, col, width, height, filter_names) in layouts.items():
        dashcard = dashcard_by_card[card_id]
        dashboard_cards.append({
            "id": dashcard["id"],
            "dashboard_id": DASHBOARD_ID,
            "entity_id": dashcard["entity_id"],
            "card_id": card_id,
            "dashboard_tab_id": tab,
            "row": row,
            "col": col,
            "size_x": width,
            "size_y": height,
            "parameter_mappings": mappings(filter_names, card_id),
            "visualization_settings": {},
            "series": [],
        })
    request("PUT", f"/dashboard/{DASHBOARD_ID}", {
        "dashcards": dashboard_cards,
        "tabs": [
            {"id": tab["id"], "name": tab["name"], "position": tab["position"]}
            for tab in dashboard["tabs"]
        ],
    })
    print("Rediseño aplicado y consultas validadas por /api/dataset.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
