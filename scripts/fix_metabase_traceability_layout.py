"""Ajusta SOLO coordenadas y tamaños de Integridad al grid real de 24 columnas.

Requiere METABASE_API_KEY; no actualiza preguntas, SQL, filtros ni otras pestañas.
La tabla de posiciones se comparte con el publicador para evitar regresiones.
"""

from __future__ import annotations

import copy

from publish_metabase_traceability import CARD_IDS, CARDS, TAB_NAME
from redesign_metabase_dashboard import DASHBOARD_ID, request


def main() -> None:
    before = request("GET", f"/dashboard/{DASHBOARD_ID}")
    if before["name"] != "Consumo de antimicrobianos":
        raise RuntimeError("Dashboard inesperado")
    tab_ids = [t["id"] for t in before["tabs"] if t["name"] == TAB_NAME]
    if len(tab_ids) != 1:
        raise RuntimeError("No se encontró una única pestaña de Integridad")
    tab_id = tab_ids[0]
    current = {c["card_id"]: c for c in before["dashcards"]
               if c["dashboard_tab_id"] == tab_id and c["card_id"] is not None}
    if set(current) != set(CARD_IDS.values()) | {
            c["card_id"] for c in current.values() if c.get("card", {}).get("name") == "Contexto de la fila"
    } or len(current) != len(CARDS):
        raise RuntimeError("Tarjetas de Integridad inesperadas; no aplicar layout")
    positions = {CARD_IDS.get(name, next(
        (c["card_id"] for c in current.values()
         if c.get("card", {}).get("name") == name), None)): geometry
        for name, _, _, _, _, geometry in CARDS}
    if None in positions or len(positions) != len(CARDS):
        raise RuntimeError("No se pudieron asociar posiciones con las tarjetas")
    if any(col < 0 or width <= 0 or col + width > 24 for _, col, width, _ in positions.values()):
        raise RuntimeError("Coordenadas fuera del grid de 24 columnas")

    cards = copy.deepcopy(before["dashcards"])
    for item in cards:
        if item["dashboard_tab_id"] != tab_id:
            continue
        if item["card_id"] is None:
            if not item.get("visualization_settings", {}).get("text"):
                raise RuntimeError("Nota de Integridad inesperada")
            geometry = (13, 0, 24, 2)
        else:
            geometry = positions[item["card_id"]]
        item.update(zip(("row", "col", "size_x", "size_y"), geometry))

    if before["width"] != "full" or cards != before["dashcards"]:
        request("PUT", f"/dashboard/{DASHBOARD_ID}",
                {"width": "full", "dashcards": cards,
                 "tabs": [{k: t[k] for k in ("id", "name", "position")}
                          for t in before["tabs"]],
                 "parameters": before["parameters"]})
    after = request("GET", f"/dashboard/{DASHBOARD_ID}")
    if after["width"] != "full" or after["parameters"] != before["parameters"] or after["tabs"] != before["tabs"]:
        raise RuntimeError("Cambió el ancho, los filtros o las pestañas inesperadamente")
    previous = {c["id"]: c for c in before["dashcards"]}
    if {c["id"] for c in after["dashcards"]} != set(previous):
        raise RuntimeError("Cambió el conjunto de dashcards")
    for item in after["dashcards"]:
        old = previous[item["id"]]
        if item["dashboard_tab_id"] != tab_id:
            expected = tuple(old[k] for k in ("row", "col", "size_x", "size_y"))
        else:
            expected = positions[item["card_id"]] if item["card_id"] is not None else (13, 0, 24, 2)
        if tuple(item[k] for k in ("row", "col", "size_x", "size_y")) != expected:
            raise RuntimeError(f"Geometría no persistida: dashcard {item['id']}")
        for key in ("card_id", "dashboard_tab_id", "parameter_mappings", "visualization_settings", "series"):
            if item.get(key) != old.get(key):
                raise RuntimeError(f"Cambio no autorizado en dashcard {item['id']}: {key}")
    print("Layout persistido: 24 columnas utilizadas en cada fila; preguntas y filtros intactos")


if __name__ == "__main__":
    main()
