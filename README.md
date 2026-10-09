# Dashboard de consumo de antimicrobianos

Proyecto para consolidar y visualizar información de consumo de antimicrobianos a partir de archivos TSV.

La solución utiliza:

- **Python** para la ingesta y transformación de datos.
- **PostgreSQL** para almacenar información original, datos analíticos y trazabilidad.
- **Metabase** como dashboard principal.
- **Streamlit** como interfaz complementaria de consulta, en desarrollo.

Flujo general:

```text
TSV
 ↓
ETL en Python
 ↓
PostgreSQL
 ↓
Vistas analíticas
 ↓
Metabase / Streamlit
```

El objetivo es poder analizar el consumo sin perder la relación con los archivos originales y manteniendo visibles los problemas o datos que no pudieron interpretarse correctamente.

---

## Requisitos

Necesitas:

- Python 3.11 o superior
- Docker
- Docker Compose
- Git
- Los archivos TSV originales

---

## Instalación

### 1. Clonar el repositorio

```bash
git clone https://github.com/lab-bioinfo/consolidado-metabase.git
cd consolidado-metabase
```

### 2. Crear el entorno de Python

```bash
python -m venv .venv
source .venv/bin/activate
```

Instalar las dependencias:

```bash
pip install -r requirements.txt
```

### 3. Configurar las variables de entorno

Crear el archivo local `.env` a partir de la plantilla:

```bash
cp .env.example .env
```

Luego ajustar los valores del archivo `.env` si es necesario.

Este archivo contiene configuración local y credenciales, por lo que no debe subirse al repositorio.

---

## Levantar PostgreSQL y Metabase

Ejecutar:

```bash
docker compose up -d
```

Comprobar que los servicios estén funcionando:

```bash
docker compose ps
```

Esto levanta PostgreSQL y Metabase utilizando la configuración definida en `.env`.

Los datos de PostgreSQL quedan almacenados en un volumen de Docker, por lo que no se pierden al detener los contenedores.

---

## Cargar los datos

Los archivos TSV originales deben colocarse en:

```text
data/input/
```

Por ejemplo:

```text
data/input/
├── CONSOLIDADO_CIRUGIA_...
├── CONSOLIDADO_MEDICINA_...
├── CONSOLIDADO_SOLO_TRI_...
├── CONSOLIDADO_UPC_NEO_...
└── CONSOLIDADO_UPC_PED_...
```

Los archivos se utilizan como fuente de datos y no son modificados por el ETL.

### 1. Cargar los archivos

```bash
python -m etl load data/input/
```

Este comando:

- busca los archivos TSV disponibles;
- registra los archivos y sus filas originales;
- evita cargar dos veces exactamente el mismo archivo;
- conserva la información necesaria para rastrear cada dato hasta su origen.

### 2. Construir la capa analítica

Después de cargar los archivos:

```bash
python -m etl rebuild
```

Este comando interpreta los datos almacenados y reconstruye las tablas analíticas y de auditoría.

Por lo tanto, cuando se agreguen nuevos archivos, el flujo habitual es:

```bash
python -m etl load data/input/
python -m etl rebuild
```

---

## Abrir Metabase

Con los contenedores funcionando, Metabase estará disponible en el puerto configurado en `.env`.

Por ejemplo:

```text
http://localhost:3001
```

El dashboard principal está organizado en cuatro áreas:

- **Consumo**
- **Gramos y gasto**
- **Calidad**
- **Integridad y trazabilidad**

Metabase consulta vistas de solo lectura desde PostgreSQL.

Además de mostrar los resultados, el dashboard permite revisar la calidad de los datos y rastrear cómo una fila del archivo original llegó a la capa analítica.

---

## Streamlit

El proyecto incluye también una interfaz complementaria desarrollada en Streamlit.

Primero instalar sus dependencias:

```bash
pip install -r streamlit/requirements.txt
```

Luego configurar la conexión a PostgreSQL:

```bash
export STREAMLIT_DB_HOST=localhost
export STREAMLIT_DB_PORT=5433
export STREAMLIT_DB_NAME=antimicrobianos
export STREAMLIT_DB_USER=metabase
export STREAMLIT_DB_PASSWORD='...'
```

Ejecutar:

```bash
streamlit run streamlit/app.py
```

La aplicación normalmente estará disponible en:

```text
http://localhost:8501
```

Streamlit consulta las mismas vistas analíticas utilizadas por Metabase y no modifica los datos.

---

## Tests

Para ejecutar los tests:

```bash
python -m unittest discover -s tests -t .
```

Actualmente los tests cubren principalmente:

- descubrimiento y carga de archivos;
- reglas de configuración;
- transformación de datos;
- consultas utilizadas por Streamlit.

---

## Estructura del proyecto

```text
dashboard/
├── config/       # reglas y mapeos utilizados por el ETL
├── data/input/   # archivos TSV originales
├── etl/          # ingesta y transformación
├── scripts/      # automatización y configuración de Metabase
├── sql/          # esquemas, tablas y vistas
├── streamlit/    # interfaz complementaria
├── tests/        # tests
├── docker-compose.yml
├── .env.example
└── requirements.txt
```

---

## Cómo se manejan los datos

La información pasa por distintas capas:

```text
raw
 ↓
analytics
 ↓
mart
```

### `raw`

Conserva los datos tal como fueron recibidos desde los archivos originales.

### `analytics`

Contiene la información interpretada, normalizada y preparada para análisis.

### `mart`

Publica las vistas que utilizan Metabase y Streamlit.

También existe una capa de auditoría que registra transformaciones e incidencias.

Esto permite distinguir entre:

- lo que venía originalmente en el archivo;
- lo que pudo interpretarse;
- lo que fue calculado;
- y los casos que necesitan revisión.

---

## Consideraciones actuales

Algunos elementos todavía requieren validación de dominio, especialmente:

- referencias DDD;
- métricas pediátricas y neonatales;
- algunos alias clínicos;
- valores de origen corruptos o inconsistentes.

Cuando un valor no puede calcularse de forma segura, el sistema prefiere conservarlo como `NULL` o registrar una incidencia en lugar de asumir un resultado.

---

## Inicio rápido

Para levantar el proyecto desde cero:

```bash
git clone https://github.com/lab-bioinfo/consolidado-metabase.git
cd consolidado-metabase

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env

docker compose up -d

# Copiar los archivos TSV en data/input/

python -m etl load data/input/
python -m etl rebuild
```

Luego abrir Metabase en el puerto configurado en `.env`.
