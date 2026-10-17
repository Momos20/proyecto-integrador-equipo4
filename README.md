# Proyecto Integrador — Equipo 4

## Predicción de enlaces sobre un grafo bipartito temporal: recomendación semanal y arranque en frío en MovieLens 32M

Este repositorio contiene el desarrollo del **Proyecto Integrador II de la Maestría en Ciencia de Datos y Analítica**. El objetivo es construir y desplegar en AWS un sistema de recomendación de películas basado en una red neuronal de grafos (**GraphSAGE**), capaz de generar recomendaciones **Top-K para la semana siguiente** y atender escenarios de **arranque en frío**.

La solución se diseña como una plataforma **MLOps end-to-end**: ingesta y almacenamiento en Amazon S3, transformación de datos con AWS Glue, orquestación con EventBridge y Step Functions, entrenamiento y scoring con Amazon SageMaker AI, publicación de recomendaciones en PostgreSQL sobre Amazon RDS y consumo mediante una aplicación Flask desplegada en EC2.

## Arquitectura objetivo

- **Fuentes:** MovieLens 32M y metadatos de TMDB.
- **Data Lake:** Amazon S3 con capas `raw/`, `curated/`, `features/`, `models/` y `predictions/`.
- **Procesamiento:** AWS Glue.
- **Orquestación:** Amazon EventBridge + AWS Step Functions.
- **Modelo:** GraphSAGE con PyTorch / PyTorch Geometric.
- **Entrenamiento y evaluación:** Amazon SageMaker AI.
- **Inferencia principal:** SageMaker Batch Transform para scoring semanal Top-K.
- **Cold start:** endpoint serverless de SageMaker, sujeto a disponibilidad en AWS Academy Learner Lab.
- **Persistencia operacional:** Amazon RDS PostgreSQL.
- **Aplicación:** Nginx + Gunicorn + Flask en Amazon EC2.
- **CI/CD:** GitHub Actions + Amazon ECR.
- **Observabilidad:** Amazon CloudWatch.

## Flujo principal

```text
MovieLens + TMDB
      ↓
Amazon S3
raw → curated → features
      ↓
SageMaker Training Job
      ↓
Evaluación / Experimentos
      ↓
Modelo GraphSAGE versionado
      ↓
SageMaker Batch Transform
      ↓
Top-K semanal
      ↓
Amazon RDS PostgreSQL
      ↓
Flask / EC2
      ↓
Usuario
```

## MVP local funcional

El repositorio ya incluye una primera versión end-to-end del serving operacional:

```text
Usuario → CineGraph (Flask/Jinja/JS) → API Flask → PostgreSQL → Top-K
```

La interfaz **CineGraph** presenta un diseño oscuro/cinematográfico, tarjetas de recomendación, metadata del modelo y manejo visual de estados de carga y usuarios sin ranking.

### Endpoints

- `GET /health`: liveness de la aplicación.
- `GET /api/ready`: readiness de la aplicación y PostgreSQL.
- `GET /api/recommendations/<user_id>`: devuelve el ranking más reciente del usuario.
- `GET /api/recommendations/<user_id>?limit=3`: permite limitar el Top-K entre 1 y 50.

El usuario de demostración cargado por el seed local es `414`.

## Estructura del repositorio

```text
.
├── app/                    # Aplicación Flask, API, servicios y experiencia web
├── data-platform/          # Ingesta, curated, features, publish y orquestación
├── ml/                     # Training, evaluación, inferencia y cold start
├── database/               # Esquema, migraciones y seeds de PostgreSQL
├── infrastructure/         # AWS, Step Functions y Docker
├── monitoring/             # CloudWatch, drift y métricas operativas
├── tests/                  # Pruebas automatizadas e integración con PostgreSQL
├── scripts/                # Utilidades reproducibles
├── docs/architecture/      # Documentación de arquitectura
└── .github/workflows/      # CI/CD
```

## Desarrollo local

La forma más sencilla de probar el MVP completo es con Docker:

```bash
cp .env.example .env
docker compose down -v
docker compose up --build
```

Luego abrir:

```text
http://localhost:8000
```

La base de datos se inicializa automáticamente con el esquema y las recomendaciones mock del usuario `414`.

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

Arquitectura objetivo definida, persistencia operacional implementada y MVP Flask + PostgreSQL funcional. La siguiente etapa es construir el pipeline de datos `MovieLens/TMDB → S3 Raw → Glue Curated → Features` y posteriormente sustituir el seed mock por las predicciones batch del modelo.

## Equipo 4

- Juan Manuel Agudelo
- Juan Camilo Cataño
- Carlos Muñoz
- Miguel Roldán

## Datos y reproducibilidad

Este es un proyecto académico. Los archivos originales de MovieLens no se redistribuirán desde este repositorio; se documentarán las instrucciones para obtener los datos y reproducir el pipeline completo.
