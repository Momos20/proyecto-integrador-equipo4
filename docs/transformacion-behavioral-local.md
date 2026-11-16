# CineGraph — Raw → Curated → Features con Floci (local)

Este job transforma **únicamente eventos que hayan recorrido de verdad** CineGraph → Flask → Kinesis → Firehose → S3 Raw. No genera registros de ejemplo, no altera el log original, no consulta AWS real, no entrena GraphSAGE A9 y no modifica PostgreSQL.

## Ejecución en Mac

Desde la raíz del repositorio, con Floci en ejecución y al menos un evento verificado mediante `floci-tools verify`:

```bash
git pull --ff-only origin main
# Opcional: envía interacciones nuevas, si las hay:
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci run --rm floci-tools ship
# Transforma todos los eventos realmente entregados a S3:
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci run --rm --build behavioral-transform
# Verifica que la versión publicada existe y coincide con sus sumas SHA-256:
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci run --rm behavioral-transform verify
```

El script lee del bucket local `cinegraph-local-datalake`; **el primer run puede tardar más si hay muchos eventos**. No hace falta reiniciar la aplicación, ejecutar el modelo A9 o eliminar volúmenes. Nunca uses `docker compose down -v` para este trabajo.

## Arquitectura implementada

| Zona | Prefijo de S3 emulado | Formato | Contenido |
|---|---|---|---|
| Raw (entrada) | `raw/behavioral/cinegraph/live/` | JSONL de Firehose | Eventos originales sin modificar |
| Curated (salida) | `curated/behavioral/cinegraph/snapshots/<hash>/event_date=YYYY-MM-DD/events.jsonl` | JSONL | Eventos v1 válidos, normalizados a UTC y deduplicados globalmente por `event_id` |
| Calidad | `curated/behavioral/cinegraph/snapshots/<hash>/quality.json` | JSON | Conteos de entradas, errores, duplicados y filas válidas |
| Cuarentena | `curated/behavioral/cinegraph/snapshots/<hash>/quarantine.jsonl` | JSONL | Origen, línea, razón y SHA-256 de entradas inválidas o ID en conflicto (sin replicar texto sin validar) |
| Features por película | `features/behavioral/cinegraph/snapshots/<hash>/user_movie_daily.jsonl` | JSONL | Día UTC, usuario, película, conteos por acción, media de ratings y señales de atribución A9 |
| Features por usuario | `features/behavioral/cinegraph/snapshots/<hash>/user_daily.jsonl` | JSONL | Día UTC, usuario, número de películas distintas, interacciones y ratings |
| Manifiesto | `curated/behavioral/cinegraph/latest.json` | JSON | Snapshot vigente, métricas de calidad, rutas de salidas y sumas SHA-256 |

El job **reconstruye un snapshot completo** de todos los objetos Raw en cada ejecución; no utiliza un cursor que pudiera recontar duplicados. Dos ejecuciones sobre el mismo Raw producen la misma huella y las mismas rutas. Cuando llegan eventos nuevos, crea otra versión inmutable y actualiza el manifiesto `latest.json` **solo después de escribir todas sus salidas**. Los consumidores futuros deben resolver las rutas a partir de ese manifiesto, no listar todos los snapshots históricos mezclados.

**Semántica de features:** `n_watchlist` es el número de eventos *añadido a lista*, no el estado vigente de una lista; `n_rating` y `avg_rating` describen calificaciones emitidas. `a9_feedback_events` cuenta interacciones registradas en la interfaz de A9 según `model_version`, no aciertos ni evaluaciones. Todos los timestamps y particiones son UTC, sin consultar eventos futuros para las observaciones de ese día.

**Límite metodológico:** estas features son datos de comportamiento observacional para análisis y futuras iteraciones. No son aún los tensores de entrada de Miguel ni un pipeline de entrenamiento de GraphSAGE; el checkpoint A9 está intacto y su corte de evaluación es histórico (2023), mientras que el feedback nuevo es de 2026. Incorporar feedback requiere un diseño temporal y una evaluación nueva; nunca mezclar esos eventos retrospectivamente con cortes de 2023.

**Tecnología:** Python estándar + boto3 (sin pandas ni Spark), JSONL con particiones y checksums. En AWS Academy se podrá adaptar a Glue/Parquet con la misma semántica; **todavía no es Glue real ni parquet**.

## Comprobación reproducible

```bash
python -m pytest -q tests/test_behavioral_transform.py
```

Las pruebas utilizan un S3 simulado en memoria y verifican deduplicación, datos corruptos, filtros de seguridad, agregación, repetición idempotente, integridad y UTC; no necesitan AWS ni credenciales.

## Uso en el orquestador y preparación para A9

Este ETL ahora forma parte de un flujo controlado de seis etapas: envío, verificación Raw, transformación, verificación Curated/Features, staging de feedback previo al corte UTC y verificación de snapshot shadow. No se alteran las tablas PostgreSQL ni los tensores originales A9. [Guía](orquestacion-y-shadow-local.md).
