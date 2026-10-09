"""ETL del dashboard de consumo de antimicrobianos.

Flujo actual (etapa 1 — ingesta raw):

    TSV -> SHA-256 -> raw.carga -> raw.fila

La transformación a ``analytics.consumo`` y las vistas de Metabase se
implementarán en etapas posteriores.
"""

__version__ = "0.2.0"

# Versión del ETL registrada en raw.carga para trazabilidad del procesamiento.
ETL_VERSION = __version__
