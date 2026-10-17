# CineGraph — streaming de interacciones en AWS

## Objetivo

Separar la plataforma operacional de la plataforma analítica siguiendo el patrón usado en los laboratorios SI7002:

- PostgreSQL/RDS conserva el feedback que necesita la aplicación.
- El backend genera un `clickstream.log` append-only.
- Kinesis Agent sigue el log y envía cada evento a Kinesis Data Streams.
- Amazon Data Firehose entrega los eventos a la zona Raw de S3.
- Glue transforma Raw → Curated → Features.
- El scoring de recomendaciones sigue siendo batch diario.

## Flujo

```text
CineGraph → Flask → RDS.user_interactions
                └→ clickstream.log → Kinesis Agent → Kinesis Data Streams
                                                      ↓
                                                  Firehose
                                                      ↓
                                      S3 raw/behavioral/cinegraph/live/
                                                      ↓
                                             Glue Curated
                                                      ↓
                                             Glue Features
                                                      ↓
                                           SageMaker scoring
                                                      ↓
                                            Top-K → RDS
```

## Recursos AWS

### 1. Kinesis Data Streams

Crear un stream:

- Nombre: `cinegraph-clickstream`
- Capacity mode: `On-demand`
- Región: `us-east-1` o la región usada por el equipo

El rol de la instancia EC2 debe poder ejecutar al menos `kinesis:PutRecords`. Si el agente publica métricas, también requiere `cloudwatch:PutMetricData`.

### 2. Amazon Data Firehose

Crear un delivery stream:

- Source: `Amazon Kinesis Data Stream`
- Kinesis stream: `cinegraph-clickstream`
- Destination: `Amazon S3`
- Nombre: `cinegraph-clickstream-to-s3`
- S3 prefix: `raw/behavioral/cinegraph/live/`
- Buffer interval: 60 segundos
- IAM role: `LabRole` cuando aplique en AWS Academy

### 3. EC2 / Docker Compose

La aplicación y el agente comparten el volumen Docker `clickstream_logs`.

```text
app container
/app/logs/clickstream.log
        ↓
clickstream_logs
        ↓
kinesis-agent container
/var/log/cinegraph/clickstream.log
```

La ejecución normal local no inicia el agente. En la instancia EC2 con permisos AWS:

```bash
export AWS_REGION=us-east-1
export KINESIS_STREAM_NAME=cinegraph-clickstream

docker compose --profile aws-streaming up -d --build app kinesis-agent
```

> No se deben guardar access keys en GitHub. En EC2 se debe preferir un IAM instance profile. Si el agente se ejecuta dentro de Docker y usa Instance Metadata Service, la configuración de EC2 debe permitir que el contenedor obtenga las credenciales temporales del rol.

## Verificación end-to-end

1. Abrir CineGraph y cargar el usuario `414`.
2. Dar `Me interesa`, agregar a `Mi lista` o guardar un rating.
3. Confirmar PostgreSQL:

```bash
docker compose exec db psql -U recommender -d recommender -c "
SELECT interaction_id, user_id, movie_id, interaction_type, rating, event_at
FROM user_interactions
ORDER BY event_at DESC
LIMIT 10;"
```

4. Confirmar clickstream:

```bash
docker compose exec app tail -5 /app/logs/clickstream.log
```

5. Confirmar que Kinesis Agent observa el mismo archivo:

```bash
docker compose --profile aws-streaming exec kinesis-agent \
  tail -5 /var/log/cinegraph/clickstream.log
```

6. En Kinesis revisar `IncomingRecords` e `IncomingBytes`.
7. En S3 verificar objetos bajo:

```text
raw/behavioral/cinegraph/live/
```

## Qué NO hace Kinesis

Kinesis no reentrena GraphSAGE y no reemplaza PostgreSQL. Su función es capturar y transportar señales behavioral en near real-time hacia el Data Lake.

El ciclo ML queda separado:

```text
CONTINUO
Usuario → clickstream → Kinesis → Firehose → S3 Raw

DIARIO
EventBridge → Step Functions → Glue → Features → SageMaker scoring → Top-K → RDS

PERIÓDICO
EventBridge / condición → SageMaker Training → evaluación → promoción champion
```
