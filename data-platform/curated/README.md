# Curated — CineGraph

Implementación actual **local (Floci emula S3; no AWS Glue real)**: `scripts/data/transform_behavioral_floci.py` valida y normaliza a UTC los eventos v1 recibidos en Raw, deduplica globalmente por `event_id`, particiona por `event_date` y registra filas inválidas/IDs conflictivos en cuarentena. Los archivos de salida son JSONL versionados, acompañados de sumas SHA-256 y conteos de calidad.

Consulta [la guía para ejecutar y verificar la transformación](../../docs/transformacion-behavioral-local.md). Los jobs Glue/Parquet serán una adaptación posterior para AWS Academy, no una parte de esta ejecución local.
