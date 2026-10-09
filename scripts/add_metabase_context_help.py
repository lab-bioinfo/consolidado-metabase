"""Agrega ayudas contextuales breves al dashboard de Metabase.

Solo modifica descripciones de preguntas, descripciones de campos sincronizados
en Metabase y el texto de la nota Markdown existente en Integridad. No cambia
consultas, layout, filtros, datos ni vistas SQL.
"""

from __future__ import annotations

import copy

from redesign_metabase_dashboard import DASHBOARD_ID, request


INTEGRITY_NOTE = (
    "Las filas originales permanecen preservadas. Una fila puede no convertirse "
    "en hecho analítico cuando corresponde a un subtotal o metadata. Del mismo "
    "modo, un valor puede conservarse en origen pero no utilizarse en una métrica "
    "cuando no puede interpretarse con seguridad."
)


CARD_DESCRIPTIONS = {
    # Consumo
    41: "Muestra la evolución de métricas aditivas: unidades, gramos, DDD consumidas o gasto. DDD consumidas es la cantidad total estandarizada según la DDD de referencia.",
    40: "DDD/100 días-cama expresa consumo relativo a la actividad hospitalaria y permite comparar períodos o unidades adultas. No afirma validación clínica para pediatría o neonatología.",
    42: "Compara unidades clínicas para la métrica seleccionada. Unidad corresponde al servicio o unidad clínica registrada.",
    43: "Muestra los medicamentos con mayor valor en la métrica seleccionada. Medicamento permite seleccionar un antimicrobiano específico y Familia ATB restringe la lista a una familia antimicrobiana.",
    44: "Detalle trazable de los registros de consumo usados en análisis. Período corresponde al intervalo temporal definido en los consolidados.",
    # Gramos y gasto: ayudan aunque estén en otra pestaña.
    45: "Gramos representa la cantidad física total consumida.",
    46: "Gasto es el costo asociado al consumo según la información disponible. Los valores no disponibles no se reemplazan por cero.",
    47: "Ordena medicamentos por gasto calculado disponible. Un gasto ausente indica que no había datos suficientes para calcularlo con seguridad.",
    48: "Compara el gasto calculado disponible entre unidades clínicas.",
    51: "Detalle de gramos y gasto con referencia al archivo, pestaña y fila de origen.",
    # Integridad y trazabilidad
    61: "Total de filas preservadas desde los archivos fuente.",
    62: "Filas interpretadas como registros de consumo utilizables en análisis.",
    63: "Filas preservadas para validación, pero excluidas de los hechos analíticos para evitar doble conteo.",
    64: "Filas informativas del archivo que no representan un registro de consumo.",
    65: "Filas cuyo rol no pudo determinarse automáticamente.",
    66: "Muestra qué destino tuvo cada fila preservada. Las categorías no son errores: distinguen hechos, subtotales, metadata y filas sin clasificar.",
    67: "Cobertura es el porcentaje de hechos analíticos que disponen de un valor utilizable para cada métrica. No disponibles son registros donde la métrica no puede calcularse o interpretarse con seguridad.",
    68: "Resume por qué una métrica no quedó disponible. PENDIENTE_VALIDACION significa que existe información, pero falta confirmar una regla o referencia antes de usarla en cálculo.",
    69: "Incidencias son situaciones registradas durante la transformación que requieren contexto, validación o seguimiento. VALOR_NUMERICO_INVALIDO conserva el valor original pero no lo convierte; GRAMOS_DIFIEREN o GASTO_DIFIERE indican diferencias entre valor informado y recalculado.",
    70: "Use esta tabla para localizar una fila preservada y copiar su ID al filtro ID fila raw.",
    73: "Muestra una sola vez el archivo, pestaña, número de fila, medicamento y clasificación de la fila seleccionada.",
    71: "Muestra qué ocurrió con cada campo de la fila seleccionada: valor original, valor interpretado, regla aplicada y resultado.",
    72: "Muestra la fila seleccionada tal como venía en el archivo, campo por campo. Los valores fuente se mantienen intactos.",
}


FIELD_DESCRIPTIONS = {
    # Filtros y campos frecuentes de consumo.
    1853: "Servicio o unidad clínica.",
    1886: "Servicio o unidad clínica.",
    1898: "Servicio o unidad clínica.",
    1855: "Familia antimicrobiana. Al filtrar por familia se restringen los medicamentos disponibles.",
    1900: "Familia antimicrobiana. Al filtrar por familia se restringen los medicamentos disponibles.",
    1856: "Antimicrobiano específico registrado para análisis.",
    1901: "Antimicrobiano específico registrado para análisis.",
    1852: "Intervalo temporal definido en los consolidados.",
    1885: "Intervalo temporal definido en los consolidados.",
    1897: "Intervalo temporal definido en los consolidados.",
    1860: "Número de presentaciones o unidades registradas.",
    1888: "Número de presentaciones o unidades registradas.",
    1861: "Cantidad física total consumida, calculada desde unidades y dosis cuando hay información suficiente.",
    1889: "Cantidad física total consumida, calculada desde unidades y dosis cuando hay información suficiente.",
    1862: "Valor de DDD considerado válido para realizar los cálculos analíticos.",
    1863: "Cantidad total estandarizada según la DDD de referencia.",
    1890: "Cantidad total estandarizada usada para recalcular densidad cuando corresponde.",
    1865: "Indicador de intensidad de consumo normalizado por días-cama. No debe sumarse ni promediarse directamente.",
    1892: "Indicador de intensidad de consumo normalizado por días-cama, recalculado para agregaciones adultas.",
    1866: "Precio unitario disponible para calcular gasto cuando puede interpretarse con seguridad.",
    1867: "Costo asociado al consumo según precio y unidades disponibles.",
    1893: "Costo asociado al consumo según precio y unidades disponibles.",
    1902: "Nombre de la métrica seleccionable: unidades, gramos, DDD consumidas o gasto.",
    1903: "Valor de la métrica seleccionada. Los valores no disponibles no se convierten a cero.",
    # Integridad y trazabilidad.
    2014: "Métrica evaluada para medir cobertura analítica.",
    2016: "Hechos analíticos que tienen un valor utilizable para la métrica.",
    2017: "Registros donde la métrica no puede calcularse o interpretarse con seguridad.",
    2018: "Porcentaje de hechos analíticos que disponen de un valor utilizable para esta métrica.",
    2020: "Destino asignado a la fila preservada: hecho, subtotal, metadata o sin clasificar.",
    2023: "Identificador interno de la fila preservada, usado para revisar su trazabilidad.",
    2030: "Destino asignado a la fila preservada: hecho, subtotal, metadata o sin clasificar.",
    2032: "Métrica que no quedó disponible para un registro.",
    2039: "Código interno del resultado registrado para explicar la no disponibilidad.",
    2042: "Valor fuente conservado tal como venía en el archivo.",
    2057: "Identificador interno de la fila preservada, usado para revisar su trazabilidad.",
    2063: "Destino asignado a la fila preservada: hecho, subtotal, metadata o sin clasificar.",
    1834: "Tipo de incidencia registrado durante la transformación. VALOR_NUMERICO_INVALIDO conserva el valor original pero no puede convertirlo con seguridad; GRAMOS_DIFIEREN y GASTO_DIFIERE marcan diferencias entre valores informados y recalculados.",
}


def main() -> None:
    before = request("GET", f"/dashboard/{DASHBOARD_ID}")
    before_cards = {c["id"]: copy.deepcopy(c) for c in before["dashcards"]}
    before_params = copy.deepcopy(before["parameters"])
    before_tabs = copy.deepcopy(before["tabs"])
    before_width = before["width"]

    for card_id, description in CARD_DESCRIPTIONS.items():
        card = request("GET", f"/card/{card_id}")
        if card.get("description") == description:
            continue
        original_query = copy.deepcopy(card["dataset_query"])
        original_display = card["display"]
        request("PUT", f"/card/{card_id}", {"description": description})
        saved = request("GET", f"/card/{card_id}")
        if saved["dataset_query"] != original_query or saved["display"] != original_display:
            raise RuntimeError(f"Cambió consulta o visualización de la tarjeta {card_id}")

    for field_id, description in FIELD_DESCRIPTIONS.items():
        field = request("GET", f"/field/{field_id}")
        if field.get("description") == description:
            continue
        request("PUT", f"/field/{field_id}", {"description": description})
        saved = request("GET", f"/field/{field_id}")
        if saved.get("description") != description:
            raise RuntimeError(f"Metabase no guardó la descripción del campo {field_id}")

    current = request("GET", f"/dashboard/{DASHBOARD_ID}")
    note = next((c for c in current["dashcards"]
                 if c["dashboard_tab_id"] == 7 and c["card_id"] is None), None)
    if not note:
        raise RuntimeError("No se encontró la nota Markdown de Integridad")
    cards = copy.deepcopy(current["dashcards"])
    for item in cards:
        if item["id"] == note["id"]:
            item["visualization_settings"] = {"text": INTEGRITY_NOTE}
    if cards != current["dashcards"]:
        request("PUT", f"/dashboard/{DASHBOARD_ID}", {
            "dashcards": cards,
            "tabs": [{k: t[k] for k in ("id", "name", "position")} for t in current["tabs"]],
            "parameters": current["parameters"],
            "width": current["width"],
        })

    after = request("GET", f"/dashboard/{DASHBOARD_ID}")
    if after["parameters"] != before_params or after["tabs"] != before_tabs or after["width"] != before_width:
        raise RuntimeError("Cambió filtro, pestaña o ancho del dashboard")
    if {c["id"] for c in after["dashcards"]} != set(before_cards):
        raise RuntimeError("Cambió el conjunto de dashcards")
    for item in after["dashcards"]:
        old = before_cards[item["id"]]
        for key in ("card_id", "dashboard_tab_id", "row", "col", "size_x", "size_y", "parameter_mappings", "series"):
            if item.get(key) != old.get(key):
                raise RuntimeError(f"Cambio no autorizado en dashcard {item['id']}: {key}")
    print(f"Descripciones guardadas: {len(CARD_DESCRIPTIONS)} tarjetas, {len(FIELD_DESCRIPTIONS)} campos y nota Markdown existente")


if __name__ == "__main__":
    main()
