# CineGraph — Ruta definitiva AWS Academy

**Equipo 4 · Universidad EAFIT · noviembre de 2026**

Esta guía reúne los pasos operativos que condujeron al despliegue verificado. Se consolidan los preflight y las confirmaciones en una sola secuencia; no repetir recursos ya creados. El historial Git conserva la evolución de la implementación. Los dos diagramas originales permanecen intactos; la versión adaptada es [arquitectura AWS Academy EC2](../../docs/architecture/arquitectura_aws_academy_ec2.drawio).

## Estado actual

| Componente | Evidencia |
|---|---|
| Web HTTPS, Flask/Gunicorn/Caddy | HTTP 200, TLS válido, navegador cine414 |
| RDS PostgreSQL 16.15 privado | 87.585 películas; 30 recomendaciones reales |
| Kinesis / Firehose / S3 | 5 eventos reales entregados |
| Glue | 5 válidos, 0 duplicados, 0 inválidos |
| GraphSAGE A9 | 32.000.204 ratings; 16 pruebas OK; 34 s; Top-10 para 123, 414 y 456 |
| Step Functions integral | SUCCEEDED; encendido y apagado EC2 automáticos |
| EventBridge | ETL diario configurado, deshabilitado; disparo no probado |
| CloudWatch | Alarmas configuradas |
| Pósteres y validación de tres cuentas | Script preparado; resultado pendiente |

## Ruta operativa consolidada

Los comandos de instalación se usan al reconstruir el entorno, no como reinicio obligatorio. Los scripts actuales están versionados. Para otra cuenta, ajustar IDs, región y recursos; los scripts de este laboratorio tienen guardas explícitas. No almacenar secretos en Git.

### 1. Infraestructura y web

La guía detallada de infraestructura previamente validada se conserva en el commit [34d8f32](https://github.com/Momos20/proyecto-integrador-equipo4/blob/34d8f32a3f35ecf2d571cf6af8c73e302721f15e/infrastructure/aws/README.md) como referencia histórica; utilizar sus comandos definitivos de CloudFormation y SSM, no los intentos de diagnóstico. La secuencia es:

1. Foundation: `cloudformation/01-foundation.yaml` (bucket privado y grupos de seguridad).
2. Red RDS: `scripts/02-db-network.sh --plan` y, tras comprobarlo, `CONFIRM_LAB_DEPLOY=YES bash infrastructure/aws/scripts/02-db-network.sh --apply`.
3. RDS: `cloudformation/03-rds-postgres.yaml` (PostgreSQL 16.15, db.t3.micro, 20 GiB gp3 cifrado, privado).
4. Web: `cloudformation/04-web-ec2.yaml` (t3.small, SSM, Docker). Instalar Git, Compose y Buildx según el procedimiento validado; clonar el repo y construir la imagen Flask.
5. Aplicar esquema y catálogo con `03-bootstrap-rds.py` mediante SSM y credenciales administradas; crear rol limitado y cuentas con `05-provision-app-identities.py`; verificar con `06-app-db-smoke.py`.
6. Lanzar web con `08-launch-web.sh`; verificar `09-auth-smoke.py`.
7. Validar DNS y Caddy; desplegar `05-web-https-ingress.yaml` (80/443); arrancar `compose.https.yaml` con CINEGRAPH_HOST correspondiente a la IP pública vigente. Confirmar HTTPS sin desactivar TLS. RDS y 8000 no se exponen.

### 2. Streaming y transformación

Desde CloudShell:

```bash
cd ~/cinegraph-aws
git pull --ff-only origin main
bash infrastructure/aws/scripts/10-pipeline-preflight.sh
bash infrastructure/aws/scripts/11-streaming-glue.sh
bash infrastructure/aws/scripts/12-ingest-behavioral.sh
bash infrastructure/aws/scripts/13-glue-behavioral.sh
```

Generar interacciones reales desde la aplicación antes de validar el flujo. Kinesis Agent recoge JSONL, Kinesis Data Streams entrega a Firehose, Firehose escribe GZIP en S3 Raw; Glue valida, deduplica y genera snapshots Curated/Features. El snapshot comprobado contiene 5 eventos válidos, 1 fila user_daily y 1 user_movie_daily.

### 3. Inferencia y publicación inicial

SageMaker Processing es la arquitectura objetivo, pero CreateProcessingJob fue denegado por Pvoclabs2. Se usa exclusivamente EC2 t3.large autorizado (8 GiB RAM, 2 vCPU, swap de 12 GiB). No se modificó IAM.

```bash
bash infrastructure/aws/scripts/14-a9-assets.sh
bash infrastructure/aws/scripts/17-a9-ec2.sh
```

El worker descarga MovieLens por HTTPS con certifi, verifica datos, convierte ratings, ejecuta pruebas e inferencia. Consultar el CommandId SSM que imprime el script hasta Success. La versión actual incorpora las correcciones definitivas de dependencias y TLS. No repetir el despliegue si ya existen resultados válidos. `18-publish-a9.sh` está fijado al run histórico exitoso del equipo (no es un publicador genérico de runs nuevos).

```bash
bash infrastructure/aws/scripts/18-publish-a9.sh
```

Valida hashes, detiene el worker y publica las 30 filas en RDS con transacción. La aplicación lee solo rankings reales del modelo champion.

### 4. Orquestación

```bash
bash infrastructure/aws/scripts/16-orchestration.sh
bash infrastructure/aws/scripts/19-full-workflow.sh
```

El primer script verifica ETL y configura EventBridge y CloudWatch. El segundo reutiliza el worker y el dataset preparados en la ejecución histórica exitosa: Glue → encender EC2 → inferencia → S3 → apagar EC2 → verificar/publicar ranking RDS → smoke test. No requiere volver a descargar MovieLens. Ejecutar solamente con el worker detenido y sin otra ejecución activa. No programa scoring recurrente de datos históricos.

### 5. Validación final y evidencias

```bash
bash infrastructure/aws/scripts/20-final-validation.sh
```

Prueba las tres cuentas y consolida evidencias en S3. Si existe el secreto `cinegraph-e4-tmdb` con `read_token`, enriquece pósteres de las películas recomendadas; si falta, omite esa operación. Nunca incluir token o contraseñas en Git. La ejecución de este paso todavía no se ha confirmado.

## Evidencias verificadas y limitaciones

- HTTPS: Caddy, TLS 1.3 y certificado validado; web t3.small y RDS privado. URL observada: https://cinegraph-e4.3-84-177-220.sslip.io (IP efímera).
- Glue run `jr_30cd3798b8dfa90bf758758b9074374757b1ce49a3ef9f67de10bb609a5da04c`, SUCCEEDED; snapshot `3249895e35672b0848231d08`.
- A9: SSM `33357d81-885a-4bad-9009-a8abd24c2bc0`, Success. 32.000.204 ratings, 16 pruebas, 34 s, 30 recomendaciones. Fecha histórica 2023-06-15; 0 de 3 usuarios con acierto ese día, no una evaluación global.
- Checkpoint SHA256 `8c9aa61fb7e8d3ed3a6476fe759f9861283387bc6561ea5aa03595ab516a2358`.
- Dataset `datasets/movielens32m/ratings_67920bb4da2cb8c2.parquet`; predicciones `predictions/a9/2023-06-15/ec2-20261124031146/top10.json` y manifiesto bajo el mismo prefijo. Bucket `cinegraph-e4-datalake-023914826547-us-east-1`.
- Publicación SSM `c51eba8e-4913-42d2-8844-574017e9dd4c`: A9_RDS_PUBLISHED, run_id=1; AUTH_TEST_A9_PUBLISHED; navegador cine414 verificado.
- Step Functions behavioral `manual-20261124030320` SUCCEEDED; integral `manual-20261124031918` SUCCEEDED, A9_FULL_WORKFLOW_VERIFIED. Worker detenido automáticamente.
- EventBridge permanece deshabilitado, disparo programado no verificado. CloudWatch alarmas básicas, sin notificación comprobada. No hay reentrenamiento periódico ni feedback 2026 incorporado al modelo. Pósteres y capturas de cine123/cine456 pendientes.

Los recursos web y RDS deben mantenerse disponibles para la demo, sujetos a vigencia del laboratorio. El worker detenido conserva EBS, que puede generar cargos.
