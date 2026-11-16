# Experimento controlado de sensibilidad al feedback — GraphSAGE A9

**Estado:** código implementado y 13 pruebas unitarias superadas. **La inferencia comparativa completa debe ejecutarse en el Mac donde están MovieLens 32M, PyTorch y Floci; no se han calculado valores empíricos de coincidencia de rankings todavía.** El experimento no publica recomendaciones en CineGraph ni utiliza AWS real.

## Objetivo

Medir cuánto **cambia el ranking**, no si mejora su calidad, cuando el mismo usuario CineGraph aporta una segunda calificación explícita. El experimento evita un comparador sin historial, porque A9 no genera recomendaciones para usuarios sin ratings previos.

## Condiciones controladas

Se comparan dos escenarios con **la misma fecha de corte UTC** (ejemplo: `2026-11-17 00:00 UTC`), el **mismo `user_id` lógico**, el mismo `shadow_graph_user_id` disjunto del histórico MovieLens, el mismo catálogo, los mismos pesos originales del checkpoint A9 y el mismo `k=10`:

- **A:** histórico MovieLens antes del corte + la **primera** calificación explícita del usuario CineGraph.
- **B:** el mismo histórico y la misma primera calificación + la **segunda** calificación explícita del **mismo usuario**.

Ambas calificaciones se leen del snapshot verificado en Floci (`a9-feedback-stage`), se ordenan por `(event_at, source_event_id, movie_id)` y se validan con reglas de identidad, rating, catálogo y temporalidad. Si no existe un usuario con dos calificaciones explícitas válidas, el script **falla**: no rellena datos ni fabrica un comparador. Si hay varios usuarios elegibles debe pasarse `--user-id`.

### Métricas descriptivas

- **Overlap@10** = películas presentes en ambos listados / 10.
- **Jaccard** = tamaño de la intersección de películas / tamaño de la unión.
- **Altas/bajas del Top 10** = películas que entran o salen al incluir la segunda calificación.
- **Desplazamiento absoluto medio de posición** para películas que aparecen en ambos rankings.
- **Variación absoluta media del score** entre películas compartidas. El score es un producto punto de embeddings, **no una probabilidad**.

Estas métricas miden sensibilidad del ranking. **No miden Recall, NDCG, exactitud ni desempeño prospectivo**, porque no se dispone de un conjunto de verdad futura 2026 para evaluar relevancia. La tarea académica de horizonte de 7 días sigue pendiente de validación independiente.

## Ejecución en Mac

Desde la raíz del repositorio, con Floci funcionando y después de haber ejecutado la orquestación para el mismo corte:

```bash
cd "$HOME/Documents/GitHub/proyecto-integrador-equipo4"
git pull --ff-only origin main
source .venv-a9/bin/activate
python scripts/ml/compare_a9_feedback.py --cutoff 2026-11-17 --k 10
```

Si existen varios usuarios elegibles, usar `--user-id 123` (ejemplo; solo si el manifest indica ese usuario). El script lee el Parquet histórico ya preparado en `ml/a9_daily/data/processed/`, verifica SHA-256 del checkpoint original, verifica el snapshot de Floci y reconstruye **dos grafos en secuencia** para limitar RAM. Puede usar varios GB de memoria. No modificar los pesos, los Parquet originales, ni `predictions/a9/` de producción.

## Salidas

Se escribe un directorio versionado e ignorado por Git bajo:

```text
artifacts/a9-feedback-comparison/<snapshot>-<cutoff>/<timestamp>/
  one_rating_topk.jsonl
  two_ratings_topk.jsonl
  comparison.json
  manifest.json
```

`comparison.json` tendrá los **resultados empíricos** tras ejecutar el comando en el Mac. `manifest.json` conserva los IDs de eventos usados, el hash del modelo, el corte UTC, el snapshot de origen, el mapeo seguro de usuario, el número de ratings históricos y SHA-256 de cada salida.

## Regla AWS / local

La arquitectura objetivo utiliza **S3, Kinesis Data Streams, Data Firehose, AWS Glue, SageMaker AI, RDS y EC2**. En el laboratorio las llamadas S3/Kinesis/Firehose fueron verificadas contra **Floci**, con Flask/PostgreSQL en Docker y A9 ejecutado en el Mac. **No describir ese laboratorio como un despliegue real en AWS Academy**. Para el informe, distinguir siempre estado comprobado y servicio AWS previsto.

## Reproducción de pruebas de código

```bash
python -m pytest -q tests/test_compare_a9_feedback.py
```

Prueban la selección cronológica, el usuario único, error ante pocos datos, duplicados, cálculo independiente de métricas, rankings inválidos y ausencia de publicación a producción; no requieren procesar 32 millones de ratings.