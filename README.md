# Dashboard de consumo de antimicrobianos

Solución **Python ETL + PostgreSQL + Metabase** para consolidar, preservar y
analizar el consumo de antimicrobianos de distintas unidades clínicas.

```text
TSV consolidados  ->  Python ETL  ->  PostgreSQL (raw)  ->  (analytics)  ->  Metabase
```

Estado actual: infraestructura + ingesta `raw` idempotente + **transformación
trazable** a `analytics.consumo` y capa de vistas `mart` de solo lectura para
Metabase. El dashboard local **Consumo de antimicrobianos** está rediseñado
como consulta para decisiones; la estructura, fuentes y limitaciones están en
[`docs/metabase-redesign.md`](docs/metabase-redesign.md).

---

## Objetivo

Leer los 5 consolidados TSV sin modificarlos, preservar cada fila con
trazabilidad (archivo, pestaña, número de fila, carga), deduplicar por
SHA-256, y dejar una base limpia y reproducible para el modelo analítico.

Principio rector: **Python prepara y valida, PostgreSQL conserva y organiza,
Metabase visualiza.**

---

## Requisitos

- Python 3.11+ con las dependencias de `requirements.txt`
  (`PyYAML`, `click`, `psycopg2-binary`).
- Docker y Docker Compose (para PostgreSQL y Metabase).
- Los TSV originales en `data/input/` (no se modifican jamás).

---

## Instalación de dependencias

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

---

## Levantar la infraestructura (PostgreSQL + Metabase)

1. Copiar la plantilla de entorno y ajustar si hace falta:

   ```bash
   cp .env.example .env
   ```

2. Levantar los servicios:

   ```bash
   docker compose up -d
   ```

   - PostgreSQL: expuesto en `${POSTGRES_PORT}` (por defecto `5432`).
   - Metabase: expuesto en `${MB_PORT}` (por defecto `3000`).
   - Metabase usa **PostgreSQL** para su propia base de aplicación (NO H2):
     la base `metabase` se crea automáticamente en el primer arranque
     (ver `sql/docker/init-metabase-db.sh`).

3. Verificar estado:

   ```bash
   docker compose ps
   ```

Los datos de PostgreSQL persisten en el volumen `pgdata`.

---

## Ejecutar el ETL (ingesta raw)

Aplicar el esquema y cargar los consolidados:

```bash
python -m etl load data/input/
```

Esto:

1. descubre los archivos `.TSV` (mayúsculas/minúsculas);
2. calcula el SHA-256 de cada archivo;
3. omite los archivos ya cargados (idempotente);
4. registra cada carga en `raw.carga`;
5. inserta cada fila en `raw.fila` (preservación lossless en JSONB);
6. imprime un resumen.

Solo aplicar las migraciones SQL (sin cargar):

```bash
python -m etl init-db
```

Volver a ejecutar `load` sobre los mismos archivos **no duplica** datos:
el hash SHA-256 actúa como clave de idempotencia.

---

## Ejecutar la transformación (rebuild)

Transforma `raw.fila` → `analytics.consumo` con trazabilidad completa
(`audit.transformacion` + `audit.incidencia`):

```bash
python -m etl rebuild
```

Esto:

1. lee `raw.fila` (preservando `raw.carga`/`raw.fila`);
2. interpreta cada fila guiado EXCLUSIVAMENTE por `config/periodos.yml` y
   `config/aliases.yml`;
3. calcula gramos, DDD consumidas, densidad y gasto (solo cuando todos los
   insumos son válidos; ausente → `NULL`, nunca `0`);
4. registra cada interpretación en `audit.transformacion` y cada
   problema/ambigüedad en `audit.incidencia`;
5. en una **única transacción**, borra y recrea los datos derivados
   (`analytics.consumo`, `audit.transformacion`, incidencias de origen ETL).

Es **determinista e idempotente**: ejecutarlo dos veces produce el mismo
contenido analítico y deja `raw` intacto.

---

## Ejecutar los tests

```bash
python -m unittest discover -s tests -t .
```

Los tests no requieren base de datos y cubren: descubrimiento de `.TSV`,
SHA-256/idempotencia, extracción de año, preservación del archivo original,
cobertura/consistencia de la configuración contra los datos reales, y la
transformación (resolución de columnas por unidad/año/pestaña, parseo numérico,
subtotales, cálculos, trazabilidad y determinismo).

---

## Conectarse a Metabase

- URL: `http://localhost:<MB_PORT>` (por defecto `http://localhost:3000`).
- En la configuración local comprobada el puerto publicado es `3001`:
  `http://localhost:3001`.
- En el primer acceso Metabase pide crear el usuario administrador.
- Para la base analítica, configurar la conexión con el rol de aplicación
  `metabase`: hereda el perfil `metabase_reader`, con `SELECT` solo sobre las
  vistas `mart` (sin permisos sobre `raw`, `analytics` ni `audit`).

### Dashboard

Nombre actual: **Consumo de antimicrobianos**, con cuatro pestañas: **Consumo**,
**Gramos y gasto**, **Calidad** e **Integridad y trazabilidad**. Consulte las
fuentes, validaciones y límites en [`docs/metabase-redesign.md`](docs/metabase-redesign.md)
y [`docs/metabase-integridad-trazabilidad.md`](docs/metabase-integridad-trazabilidad.md).
La paleta visual, el tema claro por cuenta y sus limitaciones de Metabase OSS
se documentan en [`docs/metabase-visual.md`](docs/metabase-visual.md).

## Segunda presentación: Streamlit (solo Consumo)

La app local `streamlit/app.py` consulta directamente **solo** `mart.consumo`,
`mart.consumo_largo` y `mart.consumo_agregado` de PostgreSQL, sin API de Metabase.
No altera la infraestructura ni las reglas ETL. Instalar adicionalmente:

```bash
pip install -r streamlit/requirements.txt
```

Exportar variables de conexión del **rol de lectura** (no usar `POSTGRES_USER`
ni `POSTGRES_PASSWORD` del ETL). El rol de login `metabase` existente hereda
`metabase_reader` y puede consultar las vistas `mart` en la base analítica.
En la instalación local creada con Docker Compose, use la contraseña configurada
para `METABASE_DB_USER` en su `.env` privado (no publicarla). Ejemplo:

```bash
export STREAMLIT_DB_HOST=localhost
export STREAMLIT_DB_PORT=5433  # sustituir por POSTGRES_PORT de su .env
export STREAMLIT_DB_NAME=antimicrobianos
export STREAMLIT_DB_USER=metabase
export STREAMLIT_DB_PASSWORD='su_contraseña_de_lector'
streamlit run streamlit/app.py
```

Se abre normalmente en `http://localhost:8501`. La pestaña Consumo ofrece
familia → medicamento dependiente, unidad, métrica, año y período. Año/período
limitan resumen, comparación, top 10 y detalle; la serie histórica muestra
todos los años de las entidades seleccionadas. El ranking requiere período;
medicamento equivale a la etiqueta de presentación publicada en `mart`.
DDD/100 días-cama procede exclusivamente de `mart.consumo_agregado`
(unidad-período, adultos elegibles); al filtrar familia o medicamento no se
muestra densidad porque no existe agregado publicado a ese grano. Para comparar
densidades se debe seleccionar un período. El detalle de densidad por
presentación es **no agregable** y distingue validez clínica; UPC pediátrica/
neonatal no se presenta como densidad validada. Las demás métricas se filtran
por nombre en `mart.consumo_largo`; los NULL no se convierten a cero.

Tests de consultas (sin infraestructura):

```bash
python -m unittest tests.test_streamlit_queries
```

## Vistas disponibles para Metabase

- `mart.consumo`: detalle analítico trazable, con valores calculados y valores
  observados del archivo separados; conserva los `NULL` de origen.
- `mart.consumo_largo`: métricas no nulas en formato largo. La densidad de UPC
  pediátrica/neonatal se etiqueta como
  `ddd_100_dias_cama_no_validada_clinicamente`.
- `mart.consumo_agregado`: KPI por unidad y período; recalcula densidad como
  `SUM(ddd_consumidas) / SUM(dias_cama) * 100` solo con componentes válidos.
- `mart.calidad`: cargas e incidencias por tipo, con enlace a la fila `raw` y
  su JSON original cuando existe una fila afectada.

---

## Estructura del proyecto

```text
dashboard/
├── config/
│   ├── periodos.yml       # mapeo de columnas por (unidad, año, pestaña)
│   └── aliases.yml        # alias de presentación (solo evidencia estructural)
├── etl/
│   ├── __init__.py        # versión del ETL
│   ├── __main__.py        # python -m etl
│   ├── config.py          # rutas, .env, config YAML y funciones puras
│   ├── db.py              # acceso a PostgreSQL (raw + analytics + audit)
│   ├── ingest.py          # ingesta raw idempotente
│   ├── transform.py       # interpretación trazable (funciones puras)
│   ├── rebuild.py         # orquestación transaccional del rebuild
│   └── cli.py             # comandos load / init-db / rebuild
├── sql/
│   ├── 001_schemas.sql    # esquemas raw, analytics, audit
│   ├── 002_tables.sql     # raw.carga, raw.fila, analytics.consumo, audit.incidencia
│   ├── 003_transformacion.sql  # audit.transformacion + columnas observado/calculado
│   ├── 004_mart_views.sql # vistas mart + permisos de lectura para Metabase
│   └── docker/            # init script (BD interna de Metabase)
├── tests/                 # tests (stdlib unittest)
├── data/
│   └── input/             # TSV originales (solo lectura)
├── docs/                  # perfil de datos y decisiones
├── docker-compose.yml
├── .env.example
└── requirements.txt
```

### Esquema de datos (etapa actual)

- `raw.carga`: una fila por archivo procesado (con `hash_sha256` único).
- `raw.fila`: una fila por fila física del TSV (`datos_json` lossless +
  `archivo_origen`, `pestana_origen`, `numero_fila`, `carga_id`).
- `analytics.consumo`: modelo analítico común. Distingue valor observado
  (`*_archivo`) de valor calculado (`*_calculados`), medicamento original vs
  normalizado, y DDD del archivo vs DDD usado como referencia.
- `audit.transformacion`: una fila por interpretación aplicada (campo destino,
  columna origen, valor original → interpretado, regla, resultado).
- `audit.incidencia`: problemas y normalizaciones (con `origen` ETL vs manual).

---

## Qué NO está implementado todavía

- Resolución de decisiones clínicas pendientes (DDD definitivas, AWaRe,
  métricas pediátricas/neonatales, alias clínicos y números corruptos).
- Resolución de decisiones clínicas pendientes (DDD definitivas, AWaRe,
  métricas pediátricas/neonatales, alias clínicos, recuperación de números
  corruptos).
