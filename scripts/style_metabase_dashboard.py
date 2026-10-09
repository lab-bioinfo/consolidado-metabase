"""Paleta visual del dashboard existente; solo modifica visualization_settings.

Requiere METABASE_API_KEY. No modifica SQL, fuentes, filtros ni posiciones.
"""

from __future__ import annotations

import copy

from redesign_metabase_dashboard import DASHBOARD_ID, request


# Colores suficientemente contrastados sobre blanco; misma unidad = mismo color.
UNIT_COLORS = {
    "CIRUGIA": "#376E9E",
    "MEDICINA": "#528DB5",
    "UPC_CV": "#4A8494",
    "UPC_NEO": "#7699AC",
    "UPC_PED": "#7985AD",
}
GRAM_COLORS = {
    "CIRUGIA": "#307C8A", "MEDICINA": "#418E9A", "UPC_CV": "#427AA0",
    "UPC_NEO": "#6499A1", "UPC_PED": "#6685A1",
}
COST_COLORS = {
    "CIRUGIA": "#285D7C", "MEDICINA": "#316E88", "UPC_CV": "#226B71",
    "UPC_NEO": "#507589", "UPC_PED": "#4C637F",
}
BLUE = "#477FA9"
TEAL = "#3E8290"
DEEP_TEAL = "#286679"
SLATE = "#637D90"
AMBER = "#AC791D"
RED = "#B45B5A"

# El mapa por unidad deja distinguibles las series de los gráficos temporales.
# Para las preguntas de barra simple se usa el nombre de la única métrica.
CHARTS = {
    41: ("line", {**UNIT_COLORS, "valor": BLUE}),
    40: ("line", {**UNIT_COLORS, "ddd_100_dias_cama": BLUE}),
    42: ("bar", {"valor": BLUE}),
    43: ("bar", {"valor": BLUE}),
    45: ("line", {**GRAM_COLORS, "gramos": TEAL}),
    46: ("line", {**COST_COLORS, "gasto": DEEP_TEAL}),
    47: ("bar", {"gasto": DEEP_TEAL}),
    48: ("bar", {"gasto": DEEP_TEAL}),
    # Ambas barras mezclan niveles de severidad: un único color neutral evita
    # atribuirles una severidad incorrecta a todas sus filas.
    55: ("bar", {"total_incidencias": SLATE}),
    60: ("bar", {"total_incidencias": SLATE}),
}

# Colores de cifras, no umbrales: los conteos válidos son >= 0. La severidad
# se aplica a indicadores de tipos explícitos, no a conteos mixtos.
KPI_COLORS = {
    56: SLATE, 57: SLATE, 58: SLATE, 59: AMBER,
    49: AMBER, 52: RED, 53: RED, 54: RED,
}


def main() -> None:
    before = request("GET", f"/dashboard/{DASHBOARD_ID}")
    if before["name"] != "Consumo de antimicrobianos" or len(before["dashcards"]) != 22:
        raise RuntimeError("Dashboard o número de tarjetas inesperado; no se aplica estilo")
    ids = {item["card_id"] for item in before["dashcards"] if item["card_id"] is not None}
    if not (set(CHARTS) | set(KPI_COLORS)).issubset(ids):
        raise RuntimeError("Faltan preguntas esperadas; no se aplica estilo")

    originals = {card_id: request("GET", f"/card/{card_id}") for card_id in ids}
    if any(originals[i]["display"] != display for i, (display, _) in CHARTS.items()):
        raise RuntimeError("Cambió un tipo de gráfico; no se aplica estilo")
    if any(originals[i]["display"] != "scalar" for i in KPI_COLORS):
        raise RuntimeError("Cambió un KPI; no se aplica estilo")

    for card_id in sorted(set(CHARTS) | set(KPI_COLORS)):
        original = originals[card_id]
        settings = copy.deepcopy(original["visualization_settings"])
        if card_id in CHARTS:
            display, colors = CHARTS[card_id]
            settings["graph.colors"] = colors
            # En líneas con múltiples puntos las etiquetas se superponen.
            if display == "line":
                settings["graph.show_values"] = False
        else:
            settings["scalar.segments"] = [{"min": 0, "max": None,
                                            "color": KPI_COLORS[card_id],
                                            "label": "Conteo"}]
        if settings == original["visualization_settings"]:
            continue
        request("PUT", f"/card/{card_id}", {"visualization_settings": settings})
        saved = request("GET", f"/card/{card_id}")
        if saved["visualization_settings"] != settings:
            raise RuntimeError(f"Metabase no conservó el estilo de pregunta {card_id}")
        if saved["dataset_query"] != original["dataset_query"] or saved["display"] != original["display"]:
            raise RuntimeError(f"Cambió la fuente o visualización de pregunta {card_id}")

    after = request("GET", f"/dashboard/{DASHBOARD_ID}")
    def signature(dashboard: dict) -> tuple:
        cards = [
            (item["id"], item["card_id"], item["dashboard_tab_id"],
             item["row"], item["col"], item["size_x"], item["size_y"],
             item["parameter_mappings"])
            for item in dashboard["dashcards"]
        ]
        return (dashboard["parameters"], dashboard["tabs"], sorted(cards, key=lambda x: x[0]))

    if signature(before) != signature(after):
        raise RuntimeError("El layout, pestañas o filtros cambiaron inesperadamente")
    print("Estilo guardado en 10 gráficos y 8 KPI; dashboard, filtros y consultas intactos")


if __name__ == "__main__":
    main()
