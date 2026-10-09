"""Publica exclusivamente la pestaña Calidad del dashboard local por API.

Requiere METABASE_API_KEY. Ejecutar después de sql/005_calidad_integridad.sql.
Las consultas de prueba se ejecutan antes de publicar cada pregunta.
"""

from __future__ import annotations

import copy
from urllib.parse import quote

from redesign_metabase_dashboard import DASHBOARD_ID, DATABASE_ID, request


SEVERITY = """CASE
  WHEN tipo_incidencia = 'PERIODO_NORMALIZADO' THEN 'Información'
  WHEN tipo_incidencia IN ('COLUMNA_NO_INTERPRETADA',
       'METRICA_PEDIATRICA_NO_VALIDADA', 'DOSIS_PENDIENTE_VALIDACION')
       THEN 'Advertencia'
  WHEN tipo_incidencia IN ('VALOR_NUMERICO_INVALIDO', 'GRAMOS_DIFIEREN',
       'GASTO_DIFIERE', 'DDD_INCONSISTENTE', 'DIAS_CAMA_INCONSISTENTE',
       'SUBTOTAL_DIFIERE') THEN 'Inconsistencia'
  ELSE 'Sin clasificar'
END"""

NOTE = ("## Calidad e integridad de datos\n\n"
        "Las incidencias no implican pérdida de datos. Los 1.228 registros "
        "originales se conservan en raw; los valores ambiguos o no utilizados "
        "permanecen trazables y no se descartan silenciosamente.")


def question(name: str, sql: str, display: str = "scalar",
             settings: dict | None = None) -> dict:
    return {
        "name": name,
        "display": display,
        "dataset_query": {"database": DATABASE_ID, "type": "native",
                          "native": {"query": sql, "template-tags": {}}},
        "visualization_settings": settings or {},
    }


def main() -> None:
    before = request("GET", f"/dashboard/{DASHBOARD_ID}")
    tabs = {tab["name"]: tab["id"] for tab in before["tabs"]}
    if before["name"] != "Consumo de antimicrobianos" or set(tabs) != {
        "Consumo", "Gramos y gasto", "Calidad"
    }:
        raise RuntimeError("Dashboard o pestañas inesperadas")
    quality = tabs["Calidad"]
    existing = {item["card_id"]: item for item in before["dashcards"]
                if item["dashboard_tab_id"] == quality}
    if set(existing) not in ({49, 50, 52, 53, 54, 55},
                             {49, 50, 52, 53, 54, 55, 56, 57, 58, 59, 60, None}):
        raise RuntimeError(f"Tarjetas de Calidad inesperadas: {set(existing)}")

    definitions = [
        ("Filas originales", "SELECT filas_originales FROM mart.integridad", "scalar", {}),
        ("Hechos analíticos", "SELECT hechos_analiticos FROM mart.integridad", "scalar", {}),
        ("Subtotales y metadata", "SELECT subtotales_y_metadata FROM mart.integridad", "scalar", {}),
        ("Sin clasificar", "SELECT sin_clasificar FROM mart.integridad", "scalar", {}),
        ("Incidencias por severidad", f"""SELECT severidad, COUNT(*) AS total_incidencias
FROM (SELECT {SEVERITY} AS severidad FROM mart.calidad
      WHERE incidencia_id IS NOT NULL) AS i
GROUP BY severidad ORDER BY total_incidencias DESC, severidad""", "bar",
         {"graph.dimensions": ["severidad"], "graph.metrics": ["total_incidencias"],
          "graph.x_axis.title_text": "Severidad", "graph.y_axis.title_text": "Incidencias",
          "graph.show_values": True}),
    ]
    updates = {
        49: question("Incidencias totales", "SELECT COUNT(*) AS total FROM mart.calidad WHERE incidencia_id IS NOT NULL"),
        52: question("Valores numéricos inválidos", "SELECT COUNT(*) AS total FROM mart.calidad WHERE tipo_incidencia = 'VALOR_NUMERICO_INVALIDO'"),
        53: question("Gramos difieren", "SELECT COUNT(*) AS total FROM mart.calidad WHERE tipo_incidencia = 'GRAMOS_DIFIEREN'"),
        54: question("Gasto difiere", "SELECT COUNT(*) AS total FROM mart.calidad WHERE tipo_incidencia = 'GASTO_DIFIERE'"),
        55: question("Incidencias por tipo", f"""SELECT tipo_incidencia, {SEVERITY} AS severidad,
       COUNT(*) AS total_incidencias
FROM mart.calidad WHERE incidencia_id IS NOT NULL
GROUP BY tipo_incidencia ORDER BY total_incidencias DESC, tipo_incidencia""", "bar",
                     {"graph.dimensions": ["tipo_incidencia"],
                      "graph.metrics": ["total_incidencias"],
                      "graph.x_axis.title_text": "Incidencias",
                      "graph.y_axis.title_text": "Tipo de incidencia",
                      "graph.show_values": True, "graph.orientation": "horizontal"}),
        50: question("Detalle de incidencias", f"""SELECT {SEVERITY} AS severidad, tipo_incidencia,
       archivo_afectado, pestana_afectada, fila_afectada,
       columna_afectada, valor_original, descripcion
FROM mart.calidad WHERE incidencia_id IS NOT NULL
ORDER BY tipo_incidencia, archivo_afectado, fila_afectada""", "table"),
    }
    # Validar SQL y datos antes de efectuar cualquier PUT/POST.
    for payload in list(updates.values()) + [question(*definition) for definition in definitions]:
        result = request("POST", "/dataset", payload["dataset_query"])
        if result.get("status") != "completed":
            raise RuntimeError(f"Consulta fallida: {payload['name']}: {result.get('error')}")

    for card_id, payload in updates.items():
        request("PUT", f"/card/{card_id}", payload)
    created = []
    for definition in definitions:
        name = definition[0]
        # Reusar preguntas creadas por una ejecución interrumpida antes del PUT.
        candidate = next((x["card_id"] for x in existing.values()
                          if x.get("card") and x["card"].get("name") == name), None)
        if candidate is None:
            hits = request("GET", "/search?q=" + quote(name) + "&models=card")["data"]
            candidate = next((hit["id"] for hit in hits
                              if hit.get("name") == name and
                              request("GET", f"/card/{hit['id']}")["dataset_query"]["database"] == DATABASE_ID), None)
        payload = question(*definition)
        if candidate is None:
            card = request("POST", "/card", payload)
            candidate = card["id"]
        else:
            request("PUT", f"/card/{candidate}", payload)
        created.append(candidate)

    next_id = [-1]

    def dashcard(card_id: int | None, row: int, col: int, width: int, height: int,
                 text: str | None = None) -> dict:
        item = existing.get(card_id)
        if not item:
            fresh_id = next_id[0]
            next_id[0] -= 1
        data = {key: copy.deepcopy(item[key]) for key in (
            "id", "dashboard_id", "entity_id", "card_id", "dashboard_tab_id",
            "row", "col", "size_x", "size_y", "parameter_mappings",
            "visualization_settings", "series"
        ) if item and key in item} if item else {
            "id": fresh_id, "card_id": card_id, "dashboard_tab_id": quality,
            "parameter_mappings": [], "visualization_settings": {}, "series": [],
        }
        data.update(row=row, col=col, size_x=width, size_y=height)
        if text is not None:
            data["visualization_settings"] = {"text": text}
        return data

    new_cards = []
    for i, card_id in enumerate(created[:4]):
        new_cards.append(dashcard(card_id, 0, i * 3, 3, 2))
    for i, card_id in enumerate((49, 52, 53, 54)):
        new_cards.append(dashcard(card_id, 2, i * 3, 3, 2))
    new_cards += [dashcard(55, 4, 0, 8, 5),
                  dashcard(created[4], 4, 8, 4, 5),
                  dashcard(None, 9, 0, 12, 2, NOTE),
                  dashcard(50, 11, 0, 12, 7)]
    # PUT reemplaza todos los dashcards; copiar íntegramente las otras pestañas.
    unchanged = [copy.deepcopy(item) for item in before["dashcards"]
                 if item["dashboard_tab_id"] != quality]
    request("PUT", f"/dashboard/{DASHBOARD_ID}", {
        "dashcards": unchanged + new_cards,
        "tabs": [{k: tab[k] for k in ("id", "name", "position")}
                 for tab in before["tabs"]],
    })
    after = request("GET", f"/dashboard/{DASHBOARD_ID}")
    def signature(item: dict) -> tuple:
        return tuple(item.get(k) for k in ("id", "card_id", "dashboard_tab_id", "row", "col", "size_x", "size_y"))
    assert sorted(map(signature, unchanged), key=str) == sorted(
        (signature(item) for item in after["dashcards"] if item["dashboard_tab_id"] != quality), key=str)
    assert len([x for x in after["dashcards"] if x["dashboard_tab_id"] == quality]) == 12
    print("Calidad publicada; nuevos IDs:", created, "tarjetas de Calidad: 12")


if __name__ == "__main__":
    main()
