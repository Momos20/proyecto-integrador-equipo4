# Data Platform — CineGraph

Flujo actual **manual local**: Kinesis/Firehose de Floci deja JSONL de interacciones reales en S3 Raw; `behavioral-transform` realiza validación y deduplicación para Curated, construye agregados diarios para Features y publica un manifiesto verificable por SHA-256. No entrena ni recalcula GraphSAGE.

[Ejecutar transformación Raw → Curated → Features](../docs/transformacion-behavioral-local.md).

La futura plataforma AWS de Glue (ETL) y SageMaker (ML) no se confunde con la emulación local.
