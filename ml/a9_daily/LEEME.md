# Top-K de GraphSAGE A9 con horizonte diario

Código para reemplazar el Top-10 de demostración con las recomendaciones reales de A9
(GraphSAGE heterogéneo de 2 capas, dimensión 64, sin embeddings de ID).

## Qué trae

```
src/recomendar.py                           punto de entrada: reconstruye A9, prepara las entradas y genera el Top-K
src/diario.py                               corte del grafo en cualquier día (horizonte diario) y su validación
src/                                        el resto del código del proyecto (recomendar.py usa 13 de estos módulos)
resultados/graphsage/A9_sin_id/modelo.pt    pesos de A9
resultados/graphsage/A9_sin_id/validacion.json  configuración de A9 (la lee recomendar.py)
resultados/diario/                          validación del horizonte diario en 2022 (resumen y comparación)
resultados/recomendaciones/ejemplo_top10_2022-06.json  ejemplo de salida
tests/test_diario.py                        pruebas del corte diario y del Top-K (no necesitan los datos)
README.md                                   README completo del proyecto
requirements.txt
```

No trae los datos de MovieLens 32M: la licencia de GroupLens no permite redistribuirlos.

## Instalación (Windows; probado con Python 3.13)

Desde esta carpeta:

```
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/cu130
pip install -r requirements.txt
python -m tests.test_diario
```

- Sin GPU NVIDIA, omite la línea de `torch`: `requirements.txt` instala la versión para CPU, que alcanza.
- Datos: descarga `ml-32m.zip` de https://grouplens.org/datasets/movielens/32m/, déjalo en esta carpeta y corre `python -m src.datos`, que escribe `data/processed/` en ~1 minuto. Si ya tienes los Parquet del proyecto, copia `data/processed/` aquí.

## Uso

Como comando (escribe CSV o JSON según la extensión de `--salida`):

```
python -m src.recomendar --fecha 2023-06-15 --usuarios 123 456 --k 10
python -m src.recomendar --fecha 2023-06-15 2023-06-16 --activos --k 10 --salida resultados/recomendaciones/top10.json
```

- `--usuarios`: userId de MovieLens. `--activos`: los usuarios que calificaron algo ese día.
- Sin `--salida`, escribe `resultados/recomendaciones/top<k>.csv`. `--gpu` usa la GPU.
- En CPU tarda ~20 s en cargar (pico de ~5 GB de RAM) y unos segundos por fecha.

Como función, desde Python en esta carpeta:

```python
from src.recomendar import Recomendador
r = Recomendador.a9()                                 # carga datos y modelo una vez
tabla = r.recomendar([123, 456], "2023-06-15", k=10)  # pandas DataFrame
```

Columnas: `fecha, userId, posicion, movieId, titulo, generos, puntaje, acierto`.
`acierto` dice si el usuario calificó esa película ese mismo día; sirve para mostrar en la
demo, no entra al modelo. El JSON trae una entrada por usuario y fecha, con su lista de
recomendaciones (ver el ejemplo en `resultados/recomendaciones/`).

## Qué significa "horizonte diario"

- Para la fecha d (día UTC), A9 usa sólo los ratings anteriores a d y recomienda para lo
  que el usuario califica el día d.
- Recomienda sólo películas que ya existían antes de d y que el usuario no ha calificado.
- Un usuario sin ningún rating antes de d no recibe recomendaciones (se avisa aparte).
- Los datos llegan hasta el 13-oct-2023; para fechas posteriores se usan todos los datos.
- Los pesos son los de la corrida de validación de A9 (entrenada con datos hasta dic-2021).
  Como A9 no tiene embeddings de ID, sirven para cualquier fecha sin reentrenar.

## Compatibilidad con el horizonte diario

Validado en los 362 días de 2022 con ratings (~253 usuarios evaluados por día):

| Método | Recall@10 | NDCG@10 | Recall@20 | NDCG@20 |
|---|---|---|---|---|
| A9 recalculado cada día | 0.094 | 0.066 | 0.128 | 0.076 |
| A9 recalculado sólo los lunes | 0.087 | 0.061 | 0.120 | 0.070 |
| Popularidad de los 7 días anteriores | 0.070 | 0.056 | 0.094 | 0.062 |
| Popularidad del día anterior | 0.061 | 0.049 | 0.080 | 0.054 |

Todas las diferencias son significativas (Wilcoxon por día con Holm, p < 1e-26). Hay que
recalcular cada día, no sólo los lunes.

Estos números no se comparan con los del informe (Recall@20 0.140 por semana): predecir un
día es más difícil que predecir una semana, porque hay menos películas por acertar y lo
más popular ya se calificó en los días anteriores. A la popularidad le pasa lo mismo, y la
ventaja de A9 sobre ella se mantiene.

## Licencia de los datos

MovieLens 32M es sólo para investigación, sin uso comercial. Citar: Harper, F. M., &
Konstan, J. A. (2015). The MovieLens Datasets: History and Context. ACM TiiS, 5(4).
