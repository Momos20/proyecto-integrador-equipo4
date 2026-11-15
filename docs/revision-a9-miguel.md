# Entrega de Miguel: A9_topk_diario.zip

**Revisión del 15 de noviembre de 2026.** Este documento se basa en el ZIP entregado por Miguel, no en una corrida nueva del modelo.

## Qué llega y qué se comprobó

- Código fuente `src/recomendar.py` (carga de A9, scoring de todos los candidatos conocidos y Top-K) y `src/diario.py` (snapshots diarios y validación). El ZIP incluye 25 archivos Python bajo `src/` en total, además de pruebas.
- Checkpoint `modelo.pt`, `validacion.json` y `curva.csv` idénticos byte a byte a los ya almacenados en `ml/models/A9_sin_id/`. **No duplicar los pesos**.
- Checkpoint inspeccionado usando `torch.load(..., weights_only=True)`: `state_dict` con 17 tensores y 1 963 286 elementos; proyecciones de dimensión 64 y dos capas de GraphSAGE; incluye buffer `atributos_pelicula` con forma `(87585,22)`. Nuevos nodos o dimensiones requieren verificar la reconstrucción de buffers/atributos.
- `resultados/diario/validacion_resumen.csv`: cuatro métodos evaluados durante 362 días de 2022; la tabla coincide con las métricas resumidas en `LEEME.md`. `validacion_comparacion.csv` contiene 12 comparaciones con `significativa=True`, **sin recalcularlas independientemente**.
- `resultados/recomendaciones/ejemplo_top10_2022-06.json`: 382 listas Top-10 para fechas 15 y 16 de junio de 2022; son **resultados históricos** de usuarios activos de MovieLens, no predicciones de hoy. No aparecen recomendaciones del usuario demo 414.
- Se revisó y compiló sintácticamente el código Python. **No se ejecutó GraphSAGE sobre MovieLens**: faltan los Parquet de 32M ratings en el ZIP y el entorno de revisión no tenía `torch_geometric`.

## Validación diaria entregada (2022)

| Método | Recall@10 | NDCG@10 | Recall@20 | NDCG@20 |
|---|---:|---:|---:|---:|
| A9, corte diario | 0.093790 | 0.066280 | 0.128416 | 0.075738 |
| A9, corte semanal | 0.086832 | 0.061105 | 0.119970 | 0.070122 |
| Popularidad 7 días | 0.070443 | 0.055707 | 0.094445 | 0.062114 |
| Popularidad día anterior | 0.060746 | 0.049201 | 0.079901 | 0.054131 |

Estas métricas proceden de los CSV de Miguel, no de una evaluación reproducida en infraestructura del equipo.

## Puntos que impiden activar serving automáticamente

1. **Horizonte predictivo:** Miguel predice interacciones del día `d`, usando ratings **anteriores a `d`**. El protocolo de CineGraph requiere un snapshot diario con **siete días futuros**. Mismo calendario de recálculo no implica mismo target. Requerimos construir objetivos de 7 días sin fuga y validarlos en 2022, manteniendo intacto 2023 si es test final del protocolo.
2. **Usuarios activos:** `--activos` obtiene usuarios que calificaron el **día objetivo**, selección retrospectiva imposible de conocer antes de predecir. Para producción, usar un conjunto de usuarios elegibles conocido al cutoff, nunca los activos futuros.
3. **Etiqueta futura:** `acierto` mira las calificaciones del día objetivo. Miguel documenta que es solo para mostrar en su demostración histórica. **Nunca publicar `acierto` en RDS como feature o resultado online**.
4. **Datos reales:** hacen falta `data/processed/{ratings,movies}.parquet` obtenidos desde MovieLens 32M. MovieLens termina en octubre de 2023. Para scoring en 2026 se necesita incorporar feedback de CineGraph con semántica explícita y actualización del catálogo; si no, se puntuarán características congeladas del histórico.
5. **Nuevas películas y usuarios:** aunque `usar_id=false`, el `state_dict` contiene `atributos_pelicula` de tamaño fijo. La carga de nuevos nodos exige reconstruir/migrar el buffer del catálogo y sus índices. Usuarios sin historial son excluidos por el código actual y requieren fallback.
6. **Persistencia:** `src.recomendar` exporta `userId, movieId, posicion, puntaje, fecha`; el backend espera `user_id, movie_id, rank, score, model_version, cutoff_week, scoring_run_id` en PostgreSQL. Falta un publicador transaccional y registrar una versión real, distinta de `baseline-v0`. No hay que confundir el score (producto punto) con una probabilidad.
7. **Operación:** no hay una prueba end-to-end de A9 contra RDS y Floci con el nuevo paquete. No ejecutar entrenamiento ni publicar tablas automáticamente por copiar los archivos.

## Importación segura del código

Los pesos ya están en `ml/models/A9_sin_id`; se agregó un **importador manual** para conservar el código completo sin otro `modelo.pt`.

Desde tu clon local del repositorio, guarda el archivo recibido en Downloads y ejecuta:

```bash
git checkout main
git pull origin main
python scripts/import_miguel_a9.py ~/Downloads/A9_topk_diario.zip
cd ml/a9_daily
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m tests.test_diario
# Para puntuar MovieLens se requiere preparar data/processed:
# python -m src.datos   (necesita el archivo ml-32m.zip en esta carpeta)
```

El importador copia `src/`, `tests/`, resultados y documentos, omite los pesos duplicados y cambia solo **tres referencias de `src/recomendar.py`**: ruta del checkpoint canónico, carga segura con `weights_only=True` y la ruta del checkpoint reportada en JSON. No ejecuta el código, no toca PostgreSQL y no dispara pipelines. Los archivos importados estarán en `ml/a9_daily/`. Hasta que se haga ese paso local, **el código fuente del ZIP no estará versionado en GitHub**; si se aprueba, se puede commitear por PR sin incluir MovieLens/Parquet.

Si el comando falla, revisar los archivos de origen y sus hashes; no desactivar las verificaciones de integridad.

## Decisión

**A9 es un candidato técnicamente completo para un piloto offline histórico** (ahora tiene código y checkpoint), pero **todavía no es un serving operativo para el horizonte de siete días ni para el feedback live 2026**. Próximo paso: validar la evaluación a 7 días y preparar adaptador de snapshots + publicador a RDS.
