"""Presentación: ningún cálculo de métricas clínicas aquí."""

import plotly.express as px
import streamlit as st


def chart(rows, x, y, color=None, horizontal=False):
    if not rows:
        st.info("Sin valores disponibles para este ámbito y métrica (NULL no equivale a cero).")
        return
    if horizontal:
        fig = px.bar(rows, x=y, y=x, orientation="h", color=color,
                     color_discrete_sequence=["#087f8c", "#225a84"])
        fig.update_layout(yaxis={"categoryorder": "total ascending"})
    else:
        fig = px.line(rows, x=x, y=y, color=color, markers=True,
                      color_discrete_sequence=["#087f8c", "#225a84", "#e0a62c", "#467890", "#53a7a0"])
    fig.update_layout(height=410, paper_bgcolor="white", plot_bgcolor="white",
                      font_color="#193449", margin=dict(l=20, r=20, t=25, b=20),
                      xaxis_title=None, yaxis_title=None, legend_title_text="Unidad")
    fig.update_yaxes(gridcolor="#edf1f5" if not horizontal else None)
    st.plotly_chart(fig, width="stretch")
