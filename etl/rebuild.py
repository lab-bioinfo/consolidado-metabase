"""Rebuild: reconstruye la capa analítica y de auditoría a partir de ``raw``.

Preserva ``raw.carga`` y ``raw.fila`` intactos. Borra y recrea SOLO los datos
derivados (``analytics.consumo``, ``audit.transformacion`` y las incidencias de
origen ETL) dentro de una única transacción PostgreSQL, de modo que un fallo
crítico no deja una reconstrucción parcial.

Determinismo: mismo raw + misma config + misma versión de reglas => mismo
resultado en reconstrucciones sucesivas.
"""

from __future__ import annotations

import logging

from . import config as cfg
from . import db
from . import transform

logger = logging.getLogger("etl")


def run_rebuild(db_cfg: dict) -> transform.TransformResult:
    """Ejecuta el rebuild completo y devuelve el resultado transformado."""
    conn = db.connect(db_cfg)
    try:
        db.apply_migrations(conn)
        filas = db.read_raw_filas(conn)

        raw_rows = [
            transform.RawRow(
                carga_id=f["carga_id"],
                numero_fila=f["numero_fila"],
                archivo_origen=f["archivo_origen"],
                pestana_origen=f["pestana_origen"],
                cells=f["cells"],
            )
            for f in filas
        ]

        periodos_cfg = cfg.load_periodos()
        aliases_cfg = cfg.load_aliases()
        result = transform.transform_rows(raw_rows, periodos_cfg, aliases_cfg)

        # --- transacción atómica: borrar derivados + escribir de nuevo ------
        db.clear_derived(conn)
        n_hechos = db.insert_hechos(conn, result.hechos)
        n_trans = db.insert_transformaciones(conn, result.transformaciones)
        n_inc = db.insert_incidencias(conn, result.incidencias)
        conn.commit()

        result.resumen["insertados_hechos"] = n_hechos
        result.resumen["insertados_transformaciones"] = n_trans
        result.resumen["insertados_incidencias"] = n_inc
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def print_resumen(result: transform.TransformResult) -> None:
    """Imprime un resumen legible del rebuild."""
    r = result.resumen
    print("")
    print("Rebuild completado:")
    print(f"  filas raw leídas            : {r['filas_total']}")
    print(f"  reconocidas como presentación: {r['presentacion']}")
    print(f"  reconocidas como subtotal    : {r['subtotal']}")
    print(f"  metadata (total gasto)       : {r['metadata']}")
    print(f"  no interpretables            : {r['no_interpretable']}")
    print(f"  hechos analytics.consumo     : {r['hechos']} (insertados {r['insertados_hechos']})")
    print(f"  audit.transformacion         : {r['transformaciones']} (insertados {r['insertados_transformaciones']})")
    print(f"  audit.incidencia             : {r['incidencias']} (insertados {r['insertados_incidencias']})")
    print(f"  gramos calculables           : {r['gramos_calculables']}")
    print(f"  ddd_consumidas calculables   : {r['ddd_consumidas_calculables']}")
    print(f"  densidad calculable          : {r['densidad_calculable']}")
    print(f"  gasto calculable             : {r['gasto_calculable']}")
