# CineGraph — orquestación local y feedback para A9 sin fuga temporal

**Estado:** implementación local con Docker y Floci. **No usa AWS real ni AWS Glue/Step Functions**, no cambia el modelo de Miguel y no publica resultados experimentales de 2026 en el CineGraph que ya funciona con el corte histórico del 15 de junio de 2023.

## 1. Qué hace la orquestación

Una sola orden ejecuta seis etapas estrictamente secuenciales:

1. `floci-tools ship`: envía los eventos aún pendientes al Kinesis emulado.
2. `floci-tools verify`: comprueba realmente la entrega del último evento al S3 Raw de Floci.
3. `behavioral-transform run`: genera snapshots JSONL Curated y Features desde Raw, con deduplicación global por `event_id`, cuarentena y métricas de calidad.
4. `behavioral-transform verify`: vuelve a descargar las salidas y verifica sus SHA-256.
5. `a9-feedback-stage run`: lee el manifiesto Curated, vuelve a verificar los datos, aplica un **corte diario UTC estricto** y prepara datasets especiales para futuras inferencias A9 en una carpeta separada de S3.
6. `a9-feedback-stage verify`: comprueba manifiesto y SHA-256 de todas las salidas para ML.

Se detiene inmediatamente si alguna etapa termina con código distinto de cero; ninguna etapa posterior arranca. Cada ejecución guarda en `artifacts/pipeline-runs/<fecha>-<id>/` el `summary.json` (estado, tiempos, salida, código de retorno, etapa fallida) y un log por etapa. `artifacts/` está ignorada por Git. No se modifican los volúmenes de PostgreSQL ni Floci.

Desde la raíz del repositorio, en la Terminal del Mac:

```bash
git pull --ff-only origin main
# El cutoff determina qué eventos ENTRAN: solo los anteriores al 17-nov-2026 00:00 UTC
python3 scripts/local_aws/orchestrate_local.py --cutoff 2026-11-17
```

Si deseas consultar el plan sin ejecutar nada:

```bash
python3 scripts/local_aws/orchestrate_local.py --cutoff 2026-11-17 --dry-run
```

Si omites `--cutoff`, se elige **el día siguiente en UTC** a la fecha de ejecución. Es recomendable pasar una fecha explícita para un experimento reproducible. El orquestador usa `--build` cuando necesita construir las imágenes y Floci debe estar disponible en Docker. Si falla una etapa, revisa su log en la ruta que imprime el script antes de reintentar.

**La orquestación no ejecuta entrenamiento ni scoring y no está programada como tarea recurrente.** Es una ejecución local controlada, iniciada por la persona desde la Terminal.

## 2. Qué se entrega a ML y qué NO

Las interacciones registradas hoy tienen `event_at` en **2026**, mientras el histórico de MovieLens y la prueba validada de A9 finalizan en **2023**. Además, `cine123`, `cine414` y `cine456` son cuentas de prueba propias de CineGraph que *usan números* de perfiles MovieLens para mostrar rankings históricos, **no son necesariamente esos participantes reales**. Por ello está prohibido concatenar feedback con el historial usando directamente los `user_id` numéricos coincidentes.

El preparador publica solo en **S3 local** bajo:

```text
features/behavioral/cinegraph/a9-shadow/
  snapshots/<snapshot_curated>/cutoff_date=<AAAA-MM-DD>/
    ratings_candidates.jsonl
    user_daily_context.jsonl
    user_movie_daily_context.jsonl
    manifest.json
  latest.json
```

- **`ratings_candidates.jsonl`**: solo eventos con `event_type=rating`, puntuación explícita 0.5–5.0 en pasos de 0.5, y `event_at` estrictamente anterior al inicio del día UTC del corte. Si un usuario califica la misma película varias veces, conserva la más reciente anterior al corte. Cada fila lleva `user_namespace="cinegraph-local"`, `movie_namespace="movielens32m"`, `source_event_id`, `event_at` y `timestamp` Unix. No se imputan ratings a partir de likes, dislikes, watchlist ni vistas.
- **`user_daily_context.jsonl` / `user_movie_daily_context.jsonl`**: agregados observacionales obtenidos de las Features verificadas, también filtrados por `event_date < cutoff`. Se conservan aparte: **el A9 original NO recibe directamente columnas como `n_like` o `n_watchlist`**.
- **Manifiesto**: checksum de cada salida, snapshot Curated de origen, cutoff, números de eventos incluidos y excluidos, y bloqueo explícito a la fusión de identidades.

Los archivos de snapshots son **inmutables**: si otra ejecución intenta publicar bytes diferentes bajo la misma versión/corte, se detiene con error. El puntero `latest.json` solo se actualiza después de que los archivos y su manifiesto estén guardados. Las salidas son experimentales y **nunca se publican en `predictions/a9/` ni en PostgreSQL**.

## 3. Inferencia futura opcional (shadow, manual)

**Solo si el manifiesto informa `rating_candidate_edges > 0`**: el nuevo ejecutor opcional puede probar estas calificaciones con el checkpoint A9 original, sin reentrenar y sin afectar las recomendaciones ya publicadas. Se utiliza el entorno Python `.venv-a9` del Mac que ya tiene PyTorch/PyG, Pandas, PyArrow y boto3, y los Parquet del histórico preparados en `ml/a9_daily/data/processed/` durante la inferencia original.

```bash
source .venv-a9/bin/activate
python scripts/ml/run_a9_shadow.py --cutoff 2026-11-17 --k 10
```

Controles de este runner:

1. Verifica el manifiesto y los hashes shadow directamente contra Floci; comprueba el SHA-256 del checkpoint A9 auténtico y la existencia del catálogo MovieLens original.
2. Filtra también el histórico MovieLens a `timestamp < cutoff 00:00:00 UTC` para impedir fuga retrospectiva.
3. Asigna a las cuentas CineGraph **IDs internos nuevos mayores que cualquier `userId` histórico**; por ejemplo, `cine123` nunca se mezcla con el `userId=123` de MovieLens. La tabla de correspondencia queda únicamente en el manifiesto local del experimento.
4. Acepta solo películas MovieLens existentes y calificaciones explícitas válidas, sin duplicar usuario-película ni usar eventos del día objetivo.
5. Ejecuta `GrafoTemporal` y `Recomendador` de Miguel en CPU con el checkpoint original A9. Los resultados y checksums quedan exclusivamente bajo `artifacts/a9-shadow/` (ignorado por Git), con estado `research_only_not_published`.

**Advertencias científicas:** esto es una **prueba exploratoria fuera del periodo validado**. No existe evidencia nueva de desempeño para 2026, ni evaluación del horizonte de siete días; tampoco valida que basten unas pocas calificaciones nuevas para generalizar. El modelo puede fallar por memoria, por falta de ratings elegibles o por incompatibilidad con nuevos nodos; **si falla no se activará ninguna publicación automática ni se alterarán los rankings de 2023**. Para convertirlo en serving productivo se requerirá un protocolo evaluable en datos futuros, manejo formal de cold-start y revisión por Miguel.

## 4. Pruebas y comprobaciones

Las pruebas offline se ejecutan, desde la raíz del repo, con `pytest` cuando esté instalado:

```bash
python -m pytest -q tests/test_local_orchestrator_shadow.py
```

Cubren orden/fail-fast de orquestación, separación de identidades, cortes estrictos, selección de calificaciones, deduplicación de ratings por usuario-película, lectura/verificación de hashes, snapshots inmutables y bloqueo de rutas que no sean Floci local. El script completo requiere el Mac y Floci para probar la integración end-to-end.