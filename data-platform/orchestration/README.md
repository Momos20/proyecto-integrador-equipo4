# Orchestration — CineGraph (Floci local)

Proceso manual unificado **fail-fast** implementado por `scripts/local_aws/orchestrate_local.py`: `ship → verify Raw → transform → verify Curated/Features → stage shadow → verify shadow`. Guarda summary JSON, logs y códigos de retorno bajo `artifacts/pipeline-runs/`. El pipeline no se programa solo, no ejecuta scoring ni toca datos originales de A9; EventBridge, Glue y Step Functions reales quedan para AWS Academy.

```bash
python3 scripts/local_aws/orchestrate_local.py --cutoff 2026-11-17
```

[Guía de ejecución, temporalidad y staging para futuras inferencias](../../docs/orquestacion-y-shadow-local.md).

## Experimento A9 comparativo con feedback real

Script manual `scripts/ml/compare_a9_feedback.py`: mismo usuario, mismo corte UTC, checkpoint original y catálogo MovieLens; se compara una calificación real con las dos primeras del mismo usuario. Guarda métricas descriptivas de coincidencia y desplazamiento del Top 10; no inventa ground truth ni publica resultados en la app. La inferencia real se ejecuta en el Mac y los resultados quedan en `artifacts/a9-feedback-comparison/`.

```bash
source .venv-a9/bin/activate
python scripts/ml/compare_a9_feedback.py --cutoff 2026-11-17 --k 10
```

[Protocolo, métricas, límites y pruebas](../../docs/comparacion-controlada-a9.md).
