"""Publica la pestaña Integridad y trazabilidad en el dashboard existente.

Requiere sql/006_integridad_trazabilidad.sql aplicado y METABASE_API_KEY.
No altera las preguntas ni el layout de las otras pestañas. Reejecutable.
"""

from __future__ import annotations

import copy
from urllib.parse import quote

from redesign_metabase_dashboard import DASHBOARD_ID, DATABASE_ID, request


TAB_NAME = "Integridad y trazabilidad"
FILTER_ID = "e7516a75-e612-4a52-b149-194928241961"


def definition(name: str, sql: str, display: str = "table", filtered: bool = False,
               settings: dict | None = None) -> dict:
    tags = {"raw_fila_id": {"name": "raw_fila_id", "display-name": "ID fila raw",
                             "type": "number", "widget-type": "number", "required": False}}
    return {"name": name, "display": display,
            "dataset_query": {"database": DATABASE_ID, "type": "native",
                              "native": {"query": sql, "template-tags": tags if filtered else {}}},
            "visualization_settings": settings or {}}


# Preguntas ya publicadas; mantener sus IDs evita duplicados durante el rediseño.
CARD_IDS = {
    "Filas origen": 61, "Hechos analíticos": 62, "Subtotales": 63,
    "Metadata": 64, "Sin clasificar": 65, "Destino de las filas": 66,
    "Cobertura por métrica": 67, "Motivos de no disponibilidad": 68,
    "Incidencias principales": 69, "Buscar fila preservada": 70,
    "Interpretaciones de la fila": 71, "Fila original": 72,
}

# Para tarjetas por fila: sin ID no se ejecuta una consulta de miles de filas.
# El filtro opcional se aplica solo a las tarjetas del explorador.
DETAIL = "WHERE 1=0 [[OR raw_fila_id = {{raw_fila_id}}]] "

CARDS = [
    ("Filas origen", "SELECT filas_originales FROM mart.integridad", "scalar", False, {}, (0, 0, 5, 2)),
    ("Hechos analíticos", "SELECT hechos_analiticos FROM mart.integridad", "scalar", False, {}, (0, 5, 5, 2)),
    ("Subtotales", "SELECT subtotales FROM mart.integridad", "scalar", False, {}, (0, 10, 4, 2)),
    ("Metadata", "SELECT metadata FROM mart.integridad", "scalar", False, {}, (0, 14, 5, 2)),
    ("Sin clasificar", "SELECT sin_clasificar FROM mart.integridad", "scalar", False, {}, (0, 19, 5, 2)),
    ("Destino de las filas",
     "SELECT CASE clasificacion WHEN 'HECHO' THEN 'Hecho analítico' "
     "WHEN 'SUBTOTAL' THEN 'Subtotal preservado' WHEN 'METADATA' THEN 'Metadata preservada' "
     "ELSE 'Sin clasificar' END || ' (' || "
     "ROUND(100.0 * filas / NULLIF(SUM(filas) OVER (), 0), 1)::text || '%)' AS \"Destino\", "
     "filas AS \"Filas\" FROM mart.conciliacion ORDER BY orden", "bar", False,
     {"graph.dimensions": ["Destino"], "graph.metrics": ["Filas"],
      "graph.orientation": "horizontal", "graph.show_values": True}, (2, 0, 12, 6)),
    ("Cobertura por métrica",
     "SELECT CASE metrica WHEN 'DDD referencia usada' THEN 'DDD referencia utilizada' "
     "WHEN 'DDD/100 días-cama (calculada)' THEN 'DDD/100 días-cama' ELSE metrica END AS \"Métrica\", "
     "disponibles AS \"Disponibles\", hechos_analiticos AS \"Total\", "
     "no_disponibles AS \"No disponibles\", "
     "porcentaje_disponible::text || '%' AS \"Cobertura\" "
     "FROM mart.cobertura_metricas ORDER BY orden", "table", False, {}, (2, 12, 12, 6)),
    ("Motivos de no disponibilidad",
     "SELECT metrica AS \"Métrica\", CASE resultado_registrado "
     "WHEN 'SIN_RESULTADO_ESPECIFICO' THEN 'No se obtuvo un valor analítico utilizable' "
     "WHEN 'PENDIENTE_VALIDACION' THEN 'Pendiente de validación' "
     "WHEN 'INVALIDO' THEN 'Valor de origen inválido' "
     "ELSE 'Otro resultado registrado' END AS \"Motivo\", "
     "resultado_registrado AS \"Código\", COUNT(*) AS \"Registros afectados\" "
     "FROM mart.no_disponibilidad GROUP BY orden, metrica, resultado_registrado "
     "ORDER BY orden, \"Registros afectados\" DESC", "table", False, {}, (8, 0, 12, 5)),
    ("Incidencias principales",
     "WITH tipos AS (SELECT tipo_incidencia, COUNT(*) AS cantidad "
     "FROM mart.calidad WHERE incidencia_id IS NOT NULL GROUP BY tipo_incidencia), "
     "resumen AS (SELECT 'Total incidencias'::text AS tipo, SUM(cantidad) AS cantidad, 0 AS orden FROM tipos "
     "UNION ALL SELECT tipo_incidencia, cantidad, 1 FROM "
     "(SELECT * FROM tipos ORDER BY cantidad DESC, tipo_incidencia LIMIT 5) principales) "
     "SELECT tipo AS \"Tipo\", cantidad AS \"Incidencias\" FROM resumen "
     "ORDER BY orden, cantidad DESC, tipo", "table", False, {}, (8, 12, 12, 5)),
    ("Buscar fila preservada",
     "SELECT raw_fila_id AS \"ID fila\", archivo_origen AS \"Archivo\", "
     "pestana_origen AS \"Pestaña\", numero_fila AS \"Nº fila\", "
     "medicamento AS \"Medicamento\", clasificacion AS \"Clasificación\" "
     "FROM mart.conciliacion_filas WHERE 1=1 [[AND raw_fila_id = {{raw_fila_id}}]] "
     "ORDER BY raw_fila_id", "table", True, {}, (15, 0, 24, 7)),
    ("Contexto de la fila",
     "SELECT archivo_origen AS \"Archivo\", pestana_origen AS \"Pestaña\", "
     "numero_fila AS \"Nº fila\", medicamento AS \"Medicamento\", "
     "clasificacion AS \"Clasificación\" FROM mart.conciliacion_filas " + DETAIL,
     "table", True, {}, (22, 0, 24, 3)),
    ("Interpretaciones de la fila",
     "SELECT campo_destino AS \"Campo destino\", columna_origen AS \"Columna origen\", "
     "valor_original AS \"Valor original\", valor_interpretado AS \"Valor interpretado\", "
     "regla_aplicada AS \"Regla\", resultado AS \"Resultado\" "
     "FROM mart.trazabilidad " + DETAIL + "ORDER BY transformacion_id",
     "table", True, {}, (25, 0, 24, 7)),
    ("Fila original",
     "SELECT columna_origen AS \"Campo original\", valor_original AS \"Valor original\" "
     "FROM mart.origen_celdas " + DETAIL + "ORDER BY posicion_columna",
     "table", True, {}, (32, 0, 24, 7)),
]

NOTE = ("**Cada fila tiene un destino.** Las filas originales permanecen preservadas. "
        "Una fila puede no convertirse en hecho analítico si es subtotal o metadata. "
        "Un valor conservado en origen puede no utilizarse en una métrica si no se "
        "interpreta con seguridad; NULL no significa cero. Las densidades calculadas "
        "no siempre están validadas clínicamente.\n\n"
        "**Para explorar:** localice una fila en «Buscar fila preservada», copie su "
        "ID al filtro «ID fila raw» y consulte abajo su contexto, interpretaciones "
        "y valores originales. Sin ID seleccionado, esas tres tarjetas quedan vacías.")


def main() -> None:
    before = request("GET", f"/dashboard/{DASHBOARD_ID}")
    if before["name"] != "Consumo de antimicrobianos":
        raise RuntimeError("Dashboard inesperado")
    if not {"Consumo", "Gramos y gasto", "Calidad"}.issubset(
            {t["name"] for t in before["tabs"]}):
        raise RuntimeError("Faltan pestañas anteriores")

    # Probar cada consulta antes de publicar; además verifica el rol de lectura.
    for name, sql, display, filtered, settings, _ in CARDS:
        payload = definition(name, sql, display, filtered, settings)
        result = request("POST", "/dataset", payload["dataset_query"])
        if result.get("status") != "completed":
            raise RuntimeError(f"Consulta fallida {name}: {result.get('error')}")

    tab = next((t for t in before["tabs"] if t["name"] == TAB_NAME), None)
    if tab is None:
        request("PUT", f"/dashboard/{DASHBOARD_ID}", {
            "tabs": [{k: t[k] for k in ("id", "name", "position")} for t in before["tabs"]]
                    + [{"id": -1, "name": TAB_NAME, "position": len(before["tabs"])}],
            "dashcards": before["dashcards"],
        })
    current = request("GET", f"/dashboard/{DASHBOARD_ID}")
    tab_id = next(t["id"] for t in current["tabs"] if t["name"] == TAB_NAME)
    existing = {d["card_id"]: d for d in current["dashcards"]
                if d["dashboard_tab_id"] == tab_id and d["card_id"] is not None}
    if not set(CARD_IDS.values()).issubset(existing):
        raise RuntimeError("Faltan preguntas existentes de Integridad; no modificar otras pestañas")
    cards = []
    next_temp_id = -1
    for name, sql, display, filtered, settings, (row, col, width, height) in CARDS:
        payload = definition(name, sql, display, filtered, settings)
        item = existing.get(CARD_IDS[name]) if name in CARD_IDS else next(
            (d for d in existing.values() if d.get("card", {}).get("name") == name), None)
        if item:
            card_id = item["card_id"]
            request("PUT", f"/card/{card_id}", payload)
        else:
            hits = request("GET", "/search?q=" + quote(name) + "&models=card")["data"]
            card_id = next((hit["id"] for hit in hits if hit.get("name") == name and
                            request("GET", f"/card/{hit['id']}")["dataset_query"]["database"] == DATABASE_ID), None)
            if card_id is None:
                card_id = request("POST", "/card", payload)["id"]
            else:
                request("PUT", f"/card/{card_id}", payload)
        mappings = ([{"parameter_id": FILTER_ID,
                      "target": ["variable", ["template-tag", "raw_fila_id"]],
                      "card_id": card_id}] if filtered else [])
        cards.append({"id": item["id"] if item else next_temp_id,
                      "card_id": card_id, "dashboard_tab_id": tab_id,
                      "row": row, "col": col, "size_x": width, "size_y": height,
                      "parameter_mappings": mappings, "visualization_settings": {}, "series": []})
        if not item:
            next_temp_id -= 1
    note = next((d for d in current["dashcards"] if d["dashboard_tab_id"] == tab_id
                 and d["card_id"] is None), None)
    cards.insert(9, {"id": note["id"] if note else next_temp_id, "card_id": None,
                     "dashboard_tab_id": tab_id, "row": 13, "col": 0,
                     "size_x": 24, "size_y": 2, "parameter_mappings": [],
                     "visualization_settings": {"text": NOTE}, "series": []})
    params = copy.deepcopy(current["parameters"])
    if not any(p["id"] == FILTER_ID for p in params):
        params.append({"id": FILTER_ID, "name": "ID fila raw", "slug": "raw_fila_id",
                       "type": "number", "sectionId": "number", "isMultiSelect": False})
    unchanged = [copy.deepcopy(d) for d in current["dashcards"] if d["dashboard_tab_id"] != tab_id]
    request("PUT", f"/dashboard/{DASHBOARD_ID}", {
        "dashcards": unchanged + cards,
        "tabs": [{k: t[k] for k in ("id", "name", "position")} for t in current["tabs"]],
        "parameters": params,
    })
    after = request("GET", f"/dashboard/{DASHBOARD_ID}")
    assert len([d for d in after["dashcards"] if d["dashboard_tab_id"] == tab_id]) == len(CARDS) + 1
    for old in unchanged:
        new = next(d for d in after["dashcards"] if d["id"] == old["id"])
        assert all(new.get(k) == old.get(k) for k in
                   ("card_id", "dashboard_tab_id", "row", "col", "size_x", "size_y", "parameter_mappings"))
    print(f"Pestaña {TAB_NAME} (id {tab_id}); {len(CARDS)} preguntas y nota; otras pestañas intactas")


if __name__ == "__main__":
    main()
