# CineGraph — Plataforma de datos en AWS

## Arquitectura operativa

```text
CineGraph → Flask → RDS (interacciones)
                └→ clickstream.log
                     → Kinesis Agent
                     → Kinesis Data Streams
                     → Amazon Data Firehose
                     → S3 Raw
                     → AWS Glue → Curated / Features

MovieLens 32M + checkpoint A9 en S3
                     → EC2 GraphSAGE
                     → S3 Top-K → RDS → CineGraph
```

La rama de eventos de 2026 y la inferencia histórica de A9 son independientes. Step Functions orquesta ambas etapas sin introducir los eventos nuevos en el experimento histórico.

## Recursos desplegados

| Servicio | Recurso |
|---|---|
| Kinesis Data Streams | cinegraph-e4-clickstream, 1 shard |
| Firehose | cinegraph-e4-firehose |
| S3 | cinegraph-e4-datalake-023914826547-us-east-1 |
| Glue | cinegraph_e4 / cinegraph-e4-behavioral-etl |
| Step Functions | cinegraph-e4-behavioral / cinegraph-e4-a9-replay |
| EventBridge | cinegraph-e4-behavioral-daily, deshabilitado |
| CloudWatch | Alarmas de entrega y ejecución |

## Resultados verificados

Cinco eventos válidos entregados a Raw; cero duplicados e inválidos. Glue produjo un snapshot Curated/Features con agregados por usuario y usuario-película. El workflow integral ejecutó Glue, encendió EC2, reprodujo la inferencia A9, almacenó resultados, detuvo EC2 y verificó la publicación en RDS.

EventBridge está configurado; el disparo programado no se ha validado. El modelo no se reentrena con el feedback actual. Consultar la [ruta operativa definitiva](../infrastructure/aws/README.md) y el [esquema de eventos](data/clickstream_schema.md).
