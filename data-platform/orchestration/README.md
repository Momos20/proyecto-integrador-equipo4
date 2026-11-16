# Orchestration — CineGraph (Floci local)

Proceso manual unificado **fail-fast** implementado por `scripts/local_aws/orchestrate_local.py`: `ship → verify Raw → transform → verify Curated/Features → stage shadow → verify shadow`. Guarda summary JSON, logs y códigos de retorno bajo `artifacts/pipeline-runs/`. El pipeline no se programa solo, no ejecuta scoring ni toca datos originales de A9; EventBridge, Glue y Step Functions reales quedan para AWS Academy.

```bash
python3 scripts/local_aws/orchestrate_local.py --cutoff 2026-11-17
```

[Guía de ejecución, temporalidad y staging para futuras inferencias](../../docs/orquestacion-y-shadow-local.md).
