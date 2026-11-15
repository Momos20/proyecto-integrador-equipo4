# Integración de A9 de Miguel en CineGraph

## Alcance y autoría

Este directorio contiene la implementación original **A9_topk_diario** entregada por Miguel, preparada para incorporarse al repositorio `Momos20/proyecto-integrador-equipo4` mediante el importador ya versionado `scripts/import_miguel_a9.py`. Es la implementación de referencia para recomendaciones Top-K. **No se cambió la arquitectura GraphSAGE, los hiperparámetros, la selección de candidatos, la lógica de fechas ni el protocolo de evaluación diario.**

### Integridad

- ZIP de origen: `A9_topk_diario(1).zip` (mismo contenido que el nombre original esperado por el importador).
- 40 archivos dentro del ZIP; **37 incorporados** y 3 artefactos del modelo original no duplicados (`modelo.pt`, `validacion.json`, `curva.csv`).
- 36 de 37 archivos incorporados son exactamente iguales byte a byte a la entrega de Miguel.
- El único archivo adaptado es `src/recomendar.py`, con **tres sustituciones estrictamente de integración**. Ver `ADAPTACION_RECOMENDAR.patch`.
- Checkpoint canónico de Miguel: `ml/models/A9_sin_id/modelo.pt`. SHA-256 esperado: `8c9aa61fb7e8d3ed3a6476fe759f9861283387bc6561ea5aa03595ab516a2358`.
- Todas las rutas, hashes originales y hashes de los archivos preparados figuran en `MANIFEST_SHA256.json`.
- Los CSV de validación se incorporan como evidencia original de Miguel, no como mediciones reproducidas por CineGraph.

### Tres ajustes en `src/recomendar.py`

1. `CARPETA_A9` apunta al checkpoint canónico `ml/models/A9_sin_id/` en lugar de duplicarlo.
2. La carga del checkpoint usa `torch.load(..., weights_only=True)` (se validó que el archivo es un `OrderedDict` de tensores).
3. El JSON de salida indica la ruta del checkpoint relativa al repositorio, no al directorio de Miguel.

**No se reentrenó ni se alteró `modelo.pt`.**

## Protocolo de referencia (Miguel)

Para la fecha `d` (UTC) se usan exclusivamente las calificaciones con fecha anterior a `d`; se puntúan películas que ya existían antes de `d` y que el usuario no ha calificado. Los usuarios sin historial previo no reciben recomendaciones. El comportamiento original de A9 es **horizonte diario**, no el horizonte de 7 días que se había planteado para CineGraph. No mezclar métricas ni declarar que el experimento de 7 días ya fue realizado.

Resultados diarios entregados por Miguel (362 días evaluables de 2022): A9 diario Recall@10 = 0,0938 y NDCG@10 = 0,0663; popularidad de 7 días Recall@10 = 0,0704 y NDCG@10 = 0,0557. Son valores de su registro original, **no una reproducción aquí**. Consultar `resultados/diario/` para todos los resultados y `LEEME.md` para la descripción de la implementación.

## Pruebas y ejemplo local

Desde la raíz del repositorio, con Python y dependencias instaladas:

```bash
python3 scripts/data/prepare_miguel_a9.py --ratings-parquet "$HOME/Downloads/ml-32m/ml32m_cache/ratings_clean.parquet"
cd ml/a9_daily
python3 -m pip install -r requirements.txt
python3 -m tests.test_evaluacion
python3 -m tests.test_diario
python3 -m src.recomendar --fecha 2023-06-15 --usuarios 123 456 --k 10 --salida resultados/recomendaciones/prueba_a9.json
```

El archivo `ratings_clean.parquet` permanece local; los Parquet se escriben en `ml/a9_daily/data/processed/` y **no** se versionan ni se suben. El catálogo `movies.parquet` y `links.parquet` se reconstruye desde la referencia ya versionada en `data/reference/movielens32m`.

## Verificaciones efectuadas en este paquete

- Lectura segura del ZIP y verificación SHA-256 del checkpoint: **aprobada**.
- Importación local por `scripts/import_miguel_a9.py`: **37 archivos importados**.
- Concordancia byte a byte: **36/37 sin cambios; una adaptación con 3 líneas**.
- `python -m compileall` sobre 28 archivos Python: **aprobada**.
- `torch.load(modelo.pt, weights_only=True, map_location="cpu")`: **aprobada**; 17 claves.
- Pruebas `tests.test_evaluacion` y `tests.test_diario`: **pendientes** en este entorno porque falta `torch_geometric`.
- Ejecución de Top-K sobre MovieLens 32M real: **pendiente** porque no se dispone del Parquet local de la Mac en este entorno; también falta `pyarrow`.
- GitHub Actions: **no ejecutado**. No se modifican los workflows.

## Ejecución con Floci en la etapa actual

Primero probamos en local con Docker + Floci, **sin cuenta AWS**. El orquestador independiente [`scripts/ml/run_a9_floci.py`](../../scripts/ml/run_a9_floci.py) carga los ratings al S3 emulado, verifica checkpoint y Parquet, ejecuta las pruebas originales y el `src.recomendar` de Miguel, y guarda Top-K y manifiesto en S3 local. Guía: [`docs/a9-ejecucion-floci.md`](../../docs/a9-ejecucion-floci.md). Ni el checkpoint ni los archivos `src/` de Miguel se modifican.
