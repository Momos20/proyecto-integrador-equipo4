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

## Estado del proyecto

Arquitectura objetivo definida. El repositorio se encuentra en la etapa inicial de estructuración e implementación.

## Equipo 4

- Juan Manuel Agudelo
- Juan Camilo Cataño
- Carlos Muñoz
- Miguel Roldán

## Datos y reproducibilidad

Este es un proyecto académico. Los archivos originales de MovieLens no se redistribuirán desde este repositorio; se documentarán las instrucciones para obtener los datos y reproducir el pipeline completo.
