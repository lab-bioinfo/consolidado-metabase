"""MVP Consumo: Streamlit es una segunda capa de lectura de mart."""

import streamlit as st

import queries as q
from components import chart


st.set_page_config(page_title="Consumo | Antimicrobianos", layout="wide", page_icon="📊")
st.markdown("""<style>
 .stApp {background: #f3f6f8; color: #193449;}
 [data-testid="stSidebar"] {background: #e9f1f4;}
 h1,h2,h3 {color: #193449;}
 [data-testid="stMetric"], [data-testid="stPlotlyChart"],
 [data-testid="stDataFrame"] {background: white; border-radius: 12px;
     padding: 12px; border: 1px solid #dce5e9;}
 [data-testid="stAlert"] {border-radius: 9px;}
 </style>""", unsafe_allow_html=True)


def option(label, items, fmt=None):
    return st.sidebar.selectbox(label, [None] + list(items),
                                format_func=lambda v: "Todos" if v is None else
                                (fmt(v) if fmt else str(v)))


def main():
    st.title("Consumo de antimicrobianos")
    st.caption("Datos consolidados · lectura directa de PostgreSQL / mart · sin estimaciones de valores ausentes")
    try:
        familias = q.families()
        with st.sidebar:
            st.subheader("Filtros de Consumo")
        familia = option("Familia ATB", familias)
        medicamento = option("Medicamento", q.medicines(familia))
        unidad = option("Unidad", q.units(familia, medicamento))
        metrica_label = st.sidebar.selectbox("Métrica", list(q.METRICS))
        metrica = q.METRICS[metrica_label]
        anio = option("Año (resumen)", q.years(unidad, familia, medicamento))
        periodos = q.periods(unidad, familia, medicamento, anio)
        periodo = option("Período (resumen)", periodos,
                         lambda p: f"{p['anio']} {p['tipo_periodo']} {p['numero_periodo']} · {p['periodo']}")
        fecha = periodo["fecha_inicio"] if periodo else None

        scope = " · ".join(str(v) for v in (familia or "Todas las familias",
                          medicamento or "Todos los medicamentos", unidad or "Todas las unidades"))
        st.subheader(metrica_label)
        st.caption(f"{scope} · Resumen: {anio or 'todos los años'} / "
                   f"{periodo['periodo'] if periodo else 'todos los períodos'} · "
                   "Evolución: historial completo del ámbito seleccionado")

        density = metrica == "ddd_100_dias_cama"
        if density and (familia or medicamento):
            st.warning("La vista mart.consumo_agregado publica densidad únicamente por unidad y "
                       "período. Quite los filtros de familia y medicamento para verla sin "
                       "recalcular una densidad no publicada.")
            return

        serie = q.evolution(metrica, unidad, familia, medicamento)
        c1, c2 = st.columns([2, 1])
        with c1:
            st.markdown("### Evolución histórica por unidad")
            chart(serie, "fecha_inicio", "valor", "unidad")
        with c2:
            if density:
                st.info("DDD/100 días-cama: solo adultos con componentes válidos, "
                        "desde mart.consumo_agregado. No se suman ni promedian densidades. "
                        "UPC pediátrica/neonatal no figura como densidad validada.")
            else:
                st.info("Las sumas usan únicamente valores no nulos publicados en "
                        "mart.consumo_largo. Ausencia de datos no es consumo cero.")
            if unidad and fecha:
                selected = [r for r in serie if r["unidad"] == unidad and r["fecha_inicio"] == fecha]
                if selected:
                    st.metric(f"{metrica_label} · {unidad} · {periodo['periodo']}",
                              f"{selected[0]['valor']:,.2f}")

        st.markdown("### Comparación por unidad")
        if density and fecha is None:
            st.info("Seleccione un período concreto para comparar densidades entre unidades.")
        else:
            st.caption("Comparación del mismo período entre unidades" if density else
                       "Suma por unidad en el año/período seleccionado; la cobertura histórica puede diferir.")
            chart(q.comparison(metrica, familia, medicamento, anio, fecha),
                  "unidad", "valor", horizontal=True)

        st.markdown("### Top 10 medicamentos")
        if density:
            st.info("No disponible: mart no publica densidad agregada por medicamento. "
                    "Seleccione DDD consumidas, Gramos, Unidades o Gasto para ver el ranking.")
        elif fecha is None:
            st.info("Seleccione un período concreto para el ranking.")
        else:
            chart(q.top_ten(metrica, unidad, familia, medicamento, anio, fecha),
                  "medicamento", "valor", horizontal=True)

        st.markdown("### Detalle trazable")
        if density:
            st.warning("El valor del detalle es de cada presentación; NO es agregable y "
                       "no sustituye la densidad de mart.consumo_agregado. "
                       "La validez clínica por fila se indica explícitamente.")
        rows = q.detail(metrica, unidad, familia, medicamento, anio, fecha)
        st.caption(f"{len(rows)} hechos · origen físico: archivo_origen / pestana_origen / numero_fila / carga_id")
        st.dataframe(rows, width="stretch", hide_index=True)
    except Exception as exc:
        # No mostrar mensajes del driver que pudieran contener datos de conexión.
        st.error("No se pudo consultar PostgreSQL mart. Verifique variables STREAMLIT_DB_*, "
                 "permisos de solo lectura y disponibilidad de las vistas.")
        if isinstance(exc, RuntimeError) and "STREAMLIT_DB_PASSWORD" in str(exc):
            st.info(str(exc))
        st.stop()


if __name__ == "__main__":
    main()
