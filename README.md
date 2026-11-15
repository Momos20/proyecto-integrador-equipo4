# Proyecto Integrador — Equipo 4

## Predicción de enlaces sobre un grafo bipartito temporal: recomendación dinámica y arranque en frío en MovieLens 32M

Este repositorio contiene el desarrollo del **Proyecto Integrador II de la Maestría en Ciencia de Datos y Analítica**. El objetivo es construir y desplegar en AWS un sistema de recomendación de películas basado en una red neuronal de grafos (**GraphSAGE**), capaz de generar recomendaciones **Top-K actualizadas diariamente** para anticipar interacciones durante los **próximos 7 días**, además de atender escenarios de **arranque en frío**.

La solución se diseña como una plataforma **MLOps end-to-end** con dos flujos complementarios:

- **Histórico/batch:** MovieLens 32M y TMDB → S3 → Glue → Features → SageMaker.
- **Behavioral/streaming:** CineGraph → `clickstream.log` → Kinesis Agent → Kinesis Data Streams → Data Firehose → S3 Raw.

El diseño objetivo prevé **scoring diario**, con reentrenamiento periódico o condicionado; **ningún entrenamiento ni scoring de GraphSAGE se inicia por cada clic**. Por ahora, la aplicación consulta Top-K precalculado desde PostgreSQL.

## Etapa actual: desarrollo con Floci local

**Primero Floci + Docker en la Mac; AWS Academy después.** No se requiere cuenta, consola ni recursos AWS reales para las pruebas de esta fase. `docker-compose.floci.yml` emula S3, Kinesis y Firehose en `http://127.0.0.1:4566`. GraphSAGE A9 se ejecuta con Python/PyTorch local (Floci no ejecuta por sí mismo el modelo). El batch de A9 y el flujo Kinesis/Firehose son pruebas manuales independientes. [Guía para A9 + Floci](docs/a9-ejecucion-floci.md).

## CineGraph real en Floci local

La interfaz carga **películas originales MovieLens 32M verificadas por MD5**, utiliza inicio de sesión con cuentas locales y muestra recomendaciones únicamente tras publicar una inferencia **GraphSAGE A9 real de Miguel**. El ranking ficticio `baseline-v0` fue retirado; las filas se exploran bajando y desplazándose horizontalmente, sin el botón «Descubrir mi Top 10».

**Primero Docker + Floci local; AWS Academy después.** No usamos cuentas ni consola AWS para esta etapa. [Guía de acceso, catálogo y publicación A9](docs/cinegraph-login-real-a9.md).

El A9 original tiene **horizonte diario**, no una evaluación nueva de siete días.

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

## Datos MovieLens 32M verificados (modelo de Miguel)

El repositorio ya incluye `links.csv` y el catálogo `movies.csv` dividido en tres partes reconstruibles **idénticas al original**. Se conservaron el README y los checksums oficiales. Se verificó `tags.csv` (72 MB), pero se mantiene fuera de Git por tamaño; no es necesario para ejecutar el núcleo de GraphSAGE A9. El archivo de ratings **no fue incluido** en la última entrega: reutilizaremos el `ratings_clean.parquet` existente en el equipo.

La [guía de datos para A9](data/reference/movielens32m/README.md) incluye el comando `python scripts/data/prepare_miguel_a9.py --ratings-parquet RUTA`, que produce la estructura `ml/a9_daily/data/processed/` que espera Miguel **sin reentrenar ni modificar el protocolo del modelo**. Todo el flujo es manual y GitHub Actions sigue desactivado automáticamente.

## Modelos del equipo y estado actual

Miguel entregó los archivos de `A0_base` y `A9_sin_id`, organizados en [`ml/models/`](ml/models/README.md). **A9 contiene un checkpoint `modelo.pt`** y métricas de validación registradas (Recall@20 0.138956; NDCG@20 0.091508 en el paso 1600). **A0 solo tiene su curva**. Se conservaron los archivos originales.

El código original de Miguel `A9_topk_diario` está en [`ml/a9_daily/`](ml/a9_daily/), con pruebas y métricas históricas. Los pesos están en `ml/models/A9_sin_id/modelo.pt`, sin modificación. Se dispone del ejecutor local `scripts/ml/run_a9_floci.py` y del publicador `scripts/ml/publish_a9_local.py`, pero **todavía no afirmamos que el scoring se haya ejecutado en el Mac ni que existan recomendaciones personales publicadas**. La aplicación no sustituye la ausencia de A9 con `baseline-v0` ni otros rankings ficticios.

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
- `GET /api/catalog`: películas del catálogo MovieLens 32M original verificado.
- `GET /api/auth/me`, `POST /api/auth/login`, `POST /api/auth/logout`: sesión local.
- `GET /api/recommendations`: ranking A9 únicamente de la cuenta autenticada, si ya existe.
- `POST /api/interactions`: feedback de la cuenta autenticada con CSRF.
- `GET /api/interactions`: feedback reciente de la cuenta autenticada.

Los usuarios de laboratorio `cine414`, `cine123`, `cine456` se crean con contraseñas aleatorias mediante el bootstrap; no son identidades reales de los participantes de MovieLens.

## Pruebas de AWS en local con Floci

Se añadió un laboratorio optativo con [Floci 2.5.0](https://github.com/floci-io/floci), que emula Kinesis, Data Firehose y S3 y permite verificar la ruta del clickstream antes de desplegar recursos AWS reales. **No se inicia con el Compose normal ni dispara pipelines**. Guía paso a paso: [docs/floci-local.md](docs/floci-local.md).

```bash
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci up -d floci
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci run --rm floci-tools bootstrap
# Genera una interaccion desde la pagina (http://localhost:8000)
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci run --rm floci-tools ship
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci run --rm floci-tools verify
```

La publicación de eventos a Kinesis/Firehose y la de rankings A9 a PostgreSQL son **manuales y separadas**. El Kinesis Agent de EC2 sigue intacto. Glue/SageMaker reales son objetivos posteriores para AWS Academy.

### Prueba local de A9 con MovieLens 32M

La aplicación y el almacenamiento/streaming emulados se ejecutan en Docker/Floci; la inferencia de Miguel se ejecuta con PyTorch local, manteniendo sus pesos y protocolo diario. Una vez arrancado Floci y su bucket emulado, con las dependencias instaladas:

```bash
python scripts/ml/run_a9_floci.py \
  --ratings-local "$HOME/Downloads/ml-32m/ml32m_cache/ratings_clean.parquet" \
  --solo-subir
# Después, para ejecutar pruebas originales e inferencia real:
python scripts/ml/run_a9_floci.py \
  --ratings-local "$HOME/Downloads/ml-32m/ml32m_cache/ratings_clean.parquet" \
  --fecha 2023-06-15 --usuarios 123 456 --k 10
```

Detalles y requisitos: [`docs/a9-ejecucion-floci.md`](docs/a9-ejecucion-floci.md). Los ratings y resultados Top-K se almacenan en **S3 local de Floci**, no en GitHub ni en AWS real. Las recomendaciones aún no alimentan PostgreSQL; la conexión A9 → app es una fase posterior.

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

Después de iniciar la aplicación, ejecuta **una sola vez** `docker compose --profile setup run --rm local-setup`. El bootstrap importa 87.585 películas auténticas, aplica la migración de cuentas y retira el seed anterior sin borrar interacciones. Guarda las claves que se mostrarán en Terminal. [Pasos completos](docs/cinegraph-login-real-a9.md).


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

Actualmente solo se mantiene `main` en el repositorio remoto, por decisión del equipo. No se crean ramas adicionales ni ejecuciones automáticas para el laboratorio local.

## Estado del proyecto

MVP Flask + PostgreSQL con feedback operacional funcional. El backend produce clickstream JSONL y el repositorio incluye configuración de Kinesis Agent. El catálogo original y las cuentas locales están preparados mediante un bootstrap manual. El frontend no muestra predicciones ficticias y la API solo consulta A9 publicado con manifiesto verificable. **La ejecución de GraphSAGE A9 sobre MovieLens 32M y la publicación resultante todavía requieren ejecución en el Mac del equipo.** Se conservan los pesos y el protocolo de Miguel. Floci es la fase actual; AWS Academy vendrá después.

## Equipo 4

- Juan Manuel Agudelo
- Juan Camilo Cataño
- Carlos Muñoz
- Miguel Roldán

## Datos y reproducibilidad

Este es un proyecto académico. Los archivos originales de MovieLens no se redistribuirán desde este repositorio; se documentarán las instrucciones para obtener los datos y reproducir el pipeline completo.
