# Proyecto Integrador — Equipo 4

## Predicción de enlaces sobre un grafo bipartito temporal: recomendación dinámica y arranque en frío en MovieLens 32M

Este repositorio contiene el desarrollo del **Proyecto Integrador II de la Maestría en Ciencia de Datos y Analítica**. El objetivo es construir y desplegar en AWS un sistema de recomendación de películas basado en una red neuronal de grafos (**GraphSAGE**), capaz de generar recomendaciones **Top-K actualizadas diariamente** para anticipar interacciones durante los **próximos 7 días**, además de atender escenarios de **arranque en frío**.

La solución se diseña como una plataforma **MLOps end-to-end** con dos flujos complementarios:

- **Histórico/batch:** MovieLens 32M y TMDB → S3 → Glue → Features → SageMaker.
- **Behavioral/streaming:** CineGraph → `clickstream.log` → Kinesis Agent → Kinesis Data Streams → Data Firehose → S3 Raw.

El diseño objetivo prevé **scoring diario**, con reentrenamiento periódico o condicionado; **ningún entrenamiento ni scoring de GraphSAGE se inicia por cada clic**. Por ahora, la aplicación consulta Top-K precalculado desde PostgreSQL.

## Arquitectura objetivo

- **Fuentes históricas:** MovieLens 32M y metadatos de TMDB.
- **Feedback live:** likes, dislikes, ratings, watchlist y eventos de interacción de CineGraph.
- **Data Lake:** Amazon S3 con capas `raw/`, `curated/`, `features/`, `models/` y `predictions/`.
- **Streaming:** Kinesis Agent + Amazon Kinesis Data Streams + Amazon Data Firehose.
- **Procesamiento:** AWS Glue.
- **Orquestación:** Amazon EventBridge + AWS Step Functions.
- **Modelo:** GraphSAGE con PyTorch / PyTorch Geometric. Miguel aportó versiones bajo `ml/models/`.
- **Entrenamiento y evaluación:** Amazon SageMaker AI.
- **Inferencia principal:** scoring batch diario Top-K.
- **Cold start:** GraphSAGE inductivo + contenido; fallback de popularidad cuando la señal sea insuficiente.
- **Persistencia operacional:** Amazon RDS PostgreSQL.
- **Aplicación:** Nginx + Gunicorn + Flask en Amazon EC2.
- **CI/CD:** GitHub Actions + Amazon ECR.
- **Observabilidad:** Amazon CloudWatch.

El diagrama editable se encuentra en:

```text
docs/architecture/arquitectura_aws_cinegraph_kinesis.drawio
```

## Modelos del equipo y estado actual

Miguel entregó los archivos de `A0_base` y `A9_sin_id`, organizados en [`ml/models/`](ml/models/README.md). **A9 contiene un checkpoint `modelo.pt`** y métricas de validación registradas (Recall@20 0.138956; NDCG@20 0.091508 en el paso 1600). **A0 solo tiene su curva**. Se conservaron los archivos originales.

La configuración de A9 señala `atributos_semanales=true` y aún debe comprobarse su compatibilidad con el protocolo diario de siete días. El checkpoint todavía no está conectado a un proceso de scoring, por lo que el Top-10 de demostración que devuelve PostgreSQL corresponde a `PopularityBaseline` (`baseline-v0`) y **no a GraphSAGE A9**.

El workflow CI de GitHub Actions permanece disponible **solo mediante ejecución manual** desde «Run workflow»; un push o PR no lo dispara.

## Diseño temporal

La tarea se formula así:

> Dado el grafo de interacciones usuario–película observado hasta el día `d`, ¿qué películas tienen mayor probabilidad de recibir una interacción del usuario durante los próximos 7 días?

Diseño de trabajo:

```text
Snapshot: diario
Horizonte objetivo: (d, d+7]
Scoring Top-K: diario
Entrenamiento: hasta 2021
Validación: 2022
Test final: 2023
Reentrenamiento: periódico / por condición
```

## Flujo de datos y feedback

```text
                                ┌───────────────┐
                                │   CineGraph   │
                                └───────┬───────┘
                                        │ interacción
                                        ▼
                                     Flask
                              ┌─────────┴─────────┐
                              ▼                   ▼
                      RDS PostgreSQL        clickstream.log
                    user_interactions             │
                                                   ▼
                                             Kinesis Agent
                                                   ▼
                                        Kinesis Data Streams
                                                   ▼
                                          Data Firehose
                                                   ▼
MovieLens + TMDB ───────────────────────────────► S3 Raw
                                                   ▼
                                             Glue Curated
                                                   ▼
                                             Glue Features
                                                   ▼
                                      SageMaker scoring diario
                                                   ▼
                                                Top-K
                                                   ▼
                                                  RDS
                                                   ▼
                                               CineGraph
```

## MVP local funcional

El repositorio incluye serving operacional y captura de feedback:

```text
Usuario → CineGraph → Flask API → PostgreSQL → Top-K
                     └→ clickstream.log
```

Las interacciones quedan persistidas en `user_interactions` y, simultáneamente, se escriben como eventos JSONL enriquecidos con trazabilidad del ranking (`model_version`, `position`, `cutoff_date`, etc.).

### Endpoints

- `GET /health`: liveness de la aplicación.
- `GET /api/ready`: readiness de la aplicación y PostgreSQL.
- `GET /api/recommendations/<user_id>`: devuelve el ranking más reciente del usuario.
- `POST /api/interactions`: registra feedback del usuario.
- `GET /api/interactions/<user_id>`: consulta feedback reciente.

El usuario de demostración cargado por el seed local es `414`.

## Pruebas de AWS en local con Floci

Se añadió un laboratorio optativo con [Floci 2.5.0](https://github.com/floci-io/floci), que emula Kinesis, Data Firehose y S3 y permite verificar la ruta del clickstream antes de desplegar recursos AWS reales. **No se inicia con el Compose normal ni dispara pipelines**. Guía paso a paso: [docs/floci-local.md](docs/floci-local.md).

```bash
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci up -d floci
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci run --rm floci-tools bootstrap
# Genera una interaccion desde la pagina (http://localhost:8000)
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci run --rm floci-tools ship
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci run --rm floci-tools verify
```

El publicador de laboratorio es **manual**; el Kinesis Agent de EC2 no se modifica. Glue/SageMaker scoring diario siguen pendientes de implementación y datos de Miguel.

## Streaming en AWS

La ejecución local normal no requiere Kinesis. En EC2, después de crear el stream y otorgar permisos al rol de instancia, se activa el perfil:

```bash
export AWS_REGION=us-east-1
export KINESIS_STREAM_NAME=cinegraph-clickstream

docker compose --profile aws-streaming up -d --build app kinesis-agent
```

Configuración detallada:

```text
docs/aws-streaming-setup.md
docs/data/clickstream_schema.md
```

## Estructura del repositorio

```text
.
├── app/                    # Aplicación Flask, API, servicios y experiencia web
├── data-platform/          # Ingesta, curated, features, publish y orquestación
├── ml/                     # Modelos A0/A9, training, evaluación, inferencia y cold start
├── database/               # Esquema, migraciones y seeds de PostgreSQL
├── infrastructure/         # AWS, Kinesis, Step Functions y Docker
├── monitoring/             # CloudWatch, drift y métricas operativas
├── tests/                  # Pruebas automatizadas e integración con PostgreSQL
├── scripts/                # Utilidades reproducibles
├── docs/architecture/      # Documentación de arquitectura
└── .github/workflows/      # CI/CD
```

## Desarrollo local

```bash
cp .env.example .env
docker compose up -d --build
```

Luego abrir:

```text
http://localhost:8000
```

Para ver el clickstream generado localmente:

```bash
docker compose exec app tail -5 /app/logs/clickstream.log
```

Para desarrollo Python fuera de Docker:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
flask --app app.main run --debug
```

## Ramas

- `main`: versión estable y demostrable.
- `develop`: integración del equipo.
- `feature/*`: trabajo por funcionalidad.

Los cambios relevantes deben llegar a `main` mediante Pull Request.

## Estado del proyecto

MVP Flask + PostgreSQL con feedback operacional funcional. El backend produce clickstream JSONL y el repositorio incluye configuración de Kinesis Agent. Se recibieron los modelos de Miguel y se organizaron en `ml/models/`; el checkpoint A9 aún necesita su código de inferencia y el proceso de generación de Top-K antes de sustituir el seed de demostración. El despliegue de recursos AWS y el pipeline `Raw → Curated → Features → scoring diario` siguen pendientes.

## Equipo 4

- Juan Manuel Agudelo
- Juan Camilo Cataño
- Carlos Muñoz
- Miguel Roldán

## Datos y reproducibilidad

Este es un proyecto académico. Los archivos originales de MovieLens no se redistribuirán desde este repositorio; se documentarán las instrucciones para obtener los datos y reproducir el pipeline completo.
