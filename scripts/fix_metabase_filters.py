"""Corrección acotada de semántica y conexiones; no modifica grilla ni mart.

Requiere METABASE_API_KEY. No ejecuta el rediseño completo.
"""

from __future__ import annotations

import copy

from redesign_metabase_dashboard import DASHBOARD_ID, PARAMS, request


def main() -> None:
    dashboard = request("GET", f"/dashboard/{DASHBOARD_ID}")
    if dashboard["name"] != "Consumo de antimicrobianos" or len(dashboard["dashcards"]) != 16:
        raise RuntimeError("Estado del dashboard inesperado; no se aplica la corrección")

    # Una selección vacía significa Unidades, nunca la suma de magnitudes
    # heterogéneas. Con un field filter presente, el comentario SQL desactiva
    # exclusivamente la condición por defecto en esa línea.
    for card_id in (41, 42, 43):
        card = request("GET", f"/card/{card_id}")
        if card["dataset_query"]["database"] != 3:
            raise RuntimeError(f"Base inesperada en pregunta {card_id}")
        query = copy.deepcopy(card["dataset_query"])
        stage = query["stages"][0]
        old = "[[AND {{metrica}}]]"
        new = "[[AND {{metrica}} --]] AND metrica = 'unidades'"
        if (old not in stage["native"] and new not in stage["native"]) or "FROM mart.consumo_largo" not in stage["native"]:
            raise RuntimeError(f"SQL inesperado en pregunta {card_id}")
        stage["native"] = stage["native"].replace(old, new)
        # La densidad de consumo_largo nunca se agrega con SUM(valor).
        assert "AND metrica IN ('unidades', 'gramos', 'ddd_consumidas', 'gasto')" in stage["native"]
        trial = request("POST", "/dataset", query)
        if trial.get("status") != "completed":
            raise RuntimeError(f"Consulta de prueba fallida en {card_id}: {trial.get('error')}")
        request("PUT", f"/card/{card_id}", {"dataset_query": query})

    # En comparaciones entre unidades el filtro Unidad eliminaría precisamente
    # las otras unidades que se pretende comparar. El resto de conexiones queda
    # intacto. Enviar todos los dashcards y tabs: PUT es una sustitución completa.
    cards = []
    for item in dashboard["dashcards"]:
        card = {key: copy.deepcopy(item[key]) for key in (
            "id", "dashboard_id", "entity_id", "card_id", "dashboard_tab_id",
            "row", "col", "size_x", "size_y", "parameter_mappings", "visualization_settings",
        ) if key in item}
        if card["card_id"] in (42, 48):
            card["parameter_mappings"] = [
                mapping for mapping in card["parameter_mappings"]
                if mapping["parameter_id"] != PARAMS["unidad"]
            ]
        for mapping in card["parameter_mappings"]:
            # Sin card_id Metabase guarda el mapeo pero el endpoint de dashcard
            # ignora el filtro (native_form.params queda vacío).
            mapping["card_id"] = card["card_id"]
        # Restablece la forma homónima de los demás template tags.
        if card["card_id"] == 41:
            for mapping in card["parameter_mappings"]:
                if mapping["parameter_id"] == PARAMS["metrica"]:
                    mapping["target"] = ["dimension", ["template-tag", "metrica"]]
        cards.append(card)
    tabs = [{key: tab[key] for key in ("id", "name", "position")} for tab in dashboard["tabs"]]
    request("PUT", f"/dashboard/{DASHBOARD_ID}", {"dashcards": cards, "tabs": tabs})
    after = request("GET", f"/dashboard/{DASHBOARD_ID}")
    before_layout = sorted((x["card_id"], x["dashboard_tab_id"], x["row"], x["col"], x["size_x"], x["size_y"]) for x in dashboard["dashcards"])
    after_layout = sorted((x["card_id"], x["dashboard_tab_id"], x["row"], x["col"], x["size_x"], x["size_y"]) for x in after["dashcards"])
    if before_layout != after_layout or dashboard["tabs"] != after["tabs"]:
        raise RuntimeError("El layout o las pestañas cambiaron inesperadamente")
    print("Corregidas preguntas 41-43 y mapeos con card_id; Unidad desconectada de 42/48; grilla intacta")


if __name__ == "__main__":
    main()
