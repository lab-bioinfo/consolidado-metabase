"""Consultas parametrizadas exclusivamente a mart. Densidad: solo vista agregada."""

from db import fetch

METRICS = {
    "DDD/100 días-cama": "ddd_100_dias_cama",
    "DDD consumidas": "ddd_consumidas",
    "Gramos": "gramos",
    "Unidades": "unidades",
    "Gasto": "gasto",
}

DETAIL_COLUMNS = {
    "ddd_consumidas": "ddd_consumidas",
    "gramos": "gramos_calculados",
    "unidades": "unidades",
    "gasto": "gasto_calculado",
    "ddd_100_dias_cama": "ddd_100_dias_cama_calculada",
}


def filters(unidad=None, familia=None, medicamento=None, anio=None, fecha=None,
            alias="c", long=False):
    """Solo identificadores SQL internos; valores siempre ligados como parámetros."""
    clauses, params = [], []
    for column, value in (("unidad", unidad), ("familia", familia),
                          ("medicamento", medicamento), ("anio", anio),
                          ("fecha_inicio", fecha)):
        if value is not None:
            if column == "anio" and long:
                clauses.append(f"EXTRACT(YEAR FROM {alias}.fecha_inicio) = %s")
            else:
                clauses.append(f"{alias}.{column} = %s")
            params.append(value)
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), tuple(params)


def families():
    return [r["familia"] for r in fetch(
        "SELECT DISTINCT familia FROM mart.consumo WHERE familia IS NOT NULL ORDER BY familia")]


def medicines(familia=None):
    where, args = filters(familia=familia)
    return [r["medicamento"] for r in fetch(
        "SELECT DISTINCT c.medicamento FROM mart.consumo c" + where +
        (" AND " if where else " WHERE ") +
        "c.medicamento IS NOT NULL ORDER BY c.medicamento", args)]


def units(familia=None, medicamento=None):
    where, args = filters(familia=familia, medicamento=medicamento)
    return [r["unidad"] for r in fetch(
        "SELECT DISTINCT c.unidad FROM mart.consumo c" + where +
        (" AND " if where else " WHERE ") + "c.unidad IS NOT NULL ORDER BY c.unidad", args)]


def years(unidad=None, familia=None, medicamento=None):
    where, args = filters(unidad, familia, medicamento)
    return [r["anio"] for r in fetch(
        "SELECT DISTINCT c.anio FROM mart.consumo c" + where +
        (" AND " if where else " WHERE ") + "c.anio IS NOT NULL ORDER BY c.anio DESC", args)]


def periods(unidad=None, familia=None, medicamento=None, anio=None):
    where, args = filters(unidad, familia, medicamento, anio)
    return fetch("SELECT DISTINCT c.fecha_inicio, c.anio, c.tipo_periodo, "
                 "c.numero_periodo, c.periodo FROM mart.consumo c" + where +
                 " ORDER BY c.fecha_inicio DESC, c.tipo_periodo, c.numero_periodo", args)


def evolution(metrica, unidad=None, familia=None, medicamento=None):
    """Serie histórica completa para el ámbito de entidades (año/período no la cortan)."""
    if metrica == "ddd_100_dias_cama":
        if familia or medicamento:
            return []  # no existe agregado por familia/medicamento en mart
        where, args = filters(unidad=unidad, alias="c")
        return fetch("SELECT c.fecha_inicio, c.anio, c.periodo, c.unidad, "
                     "c.ddd_100_dias_cama AS valor FROM mart.consumo_agregado c" + where +
                     (" AND " if where else " WHERE ") +
                     "c.ddd_100_dias_cama IS NOT NULL ORDER BY c.fecha_inicio, c.unidad", args)
    if metrica not in DETAIL_COLUMNS:
        raise ValueError("Métrica desconocida")
    where, args = filters(unidad, familia, medicamento)
    clause = (" AND " if where else " WHERE ")
    return fetch("SELECT c.fecha_inicio, c.periodo, c.unidad, SUM(c.valor) AS valor "
                 "FROM mart.consumo_largo c" + where + clause + "c.metrica = %s "
                 "GROUP BY c.fecha_inicio, c.periodo, c.unidad "
                 "ORDER BY c.fecha_inicio, c.unidad", args + (metrica,))


def comparison(metrica, familia=None, medicamento=None, anio=None, fecha=None):
    """Densidad nunca combinada entre períodos ni entre unidades."""
    if metrica == "ddd_100_dias_cama":
        if familia or medicamento or fecha is None:
            return []
        return fetch("SELECT c.unidad, c.ddd_100_dias_cama AS valor "
                     "FROM mart.consumo_agregado c WHERE c.fecha_inicio = %s "
                     "AND c.ddd_100_dias_cama IS NOT NULL ORDER BY valor DESC", (fecha,))
    if metrica not in DETAIL_COLUMNS:
        raise ValueError("Métrica desconocida")
    where, args = filters(familia=familia, medicamento=medicamento, anio=anio, fecha=fecha,
                          long=True)
    return fetch("SELECT c.unidad, SUM(c.valor) AS valor FROM mart.consumo_largo c" +
                 where + (" AND " if where else " WHERE ") + "c.metrica = %s "
                 "GROUP BY c.unidad ORDER BY valor DESC", args + (metrica,))


def top_ten(metrica, unidad=None, familia=None, medicamento=None, anio=None, fecha=None):
    if metrica == "ddd_100_dias_cama":
        return []  # agregado por medicamento no publicado
    if metrica not in DETAIL_COLUMNS:
        raise ValueError("Métrica desconocida")
    where, args = filters(unidad, familia, medicamento, anio, fecha, long=True)
    return fetch("SELECT c.medicamento, SUM(c.valor) AS valor FROM mart.consumo_largo c" +
                 where + (" AND " if where else " WHERE ") + "c.metrica = %s "
                 "GROUP BY c.medicamento ORDER BY valor DESC NULLS LAST, c.medicamento LIMIT 10",
                 args + (metrica,))


def detail(metrica, unidad=None, familia=None, medicamento=None, anio=None, fecha=None):
    if metrica not in DETAIL_COLUMNS:
        raise ValueError("Métrica desconocida")
    where, args = filters(unidad, familia, medicamento, anio, fecha)
    col = DETAIL_COLUMNS[metrica]
    return fetch("SELECT c.unidad, c.anio, c.periodo, c.fecha_inicio, c.familia, "
                 "c.medicamento, c.tipo_paciente, c." + col + " AS valor, "
                 "c.archivo_origen, c.pestana_origen, c.numero_fila, c.carga_id, "
                 "c.densidad_clinica_validada FROM mart.consumo c" + where +
                 " ORDER BY c.fecha_inicio DESC, c.unidad, c.medicamento, c.numero_fila", args)
