# Proyecto integrador: predicción temporal de enlaces en MovieLens 32M

Equipo 4: Juan Manuel Agudelo, Juan Camilo Cataño, Carlos Muñoz y Miguel Roldán.

**Pregunta principal.** Dado el grafo bipartito usuario–película hasta la semana t, predecir con qué películas interactuará cada usuario en la semana t+1 (una lista ordenada de candidatas por usuario).

**Pregunta 2.** ¿Cuántas interacciones necesita una película nueva para que la estructura del grafo supere a sus atributos de contenido?

## Estructura

```
ml-32m.zip                            datos originales de GroupLens (no se modifican)
data/processed/                       Parquet generados por src/datos.py (no se versionan)
src/datos.py                          conversión zip → Parquet, carga y semanas
src/grafo.py                          grafo usuario–película e instantáneas semanales (con con_dias=True, también el día de cada arista)
src/modelo.py                         GraphSAGE heterogéneo (PyTorch Geometric)
src/evaluacion.py                     métricas de ranking por semana y por usuario (K = 10, 20, 50)
src/protocolo.py                      partición 2021/2022/2023 y evaluación semana a semana
src/estadistica.py                    Wilcoxon por semana, IC bootstrap por bloques y Holm; ley de potencia y PSI del EDA
src/lineas_base.py                    aleatoria, popularidad (k semanas), ItemKNN y MF-BPR
src/temporal.py                       instantáneas en GPU con decaimiento y atributos semanales
src/entrenamiento.py                  GraphSAGE temporal: entrenamiento, parada temprana y test
src/ablacion.py                       secuencia de la ablación (una cosa a la vez, en validación)
src/hipotesis.py                      contraste de H1 en test: Wilcoxon, IC por bloques y Holm
src/h3.py                             H3: ventaja según el historial (deciles, bootstrap por usuario)
src/tmdb.py                           descarga de metadatos de TMDB (con caché y límite de tasa)
src/frio.py                           protocolo de arranque en frío de películas (candidatas y estratos)
src/h2.py                             H2: métodos evaluados en el protocolo de frío
src/comparadores.py                   comparadores DL (NCF de dos torres, LightGCN, Mult-VAE): validación, test y contraste
src/embeddings.py                     UMAP de las representaciones de películas de A9
src/resultados_a9.py                  página HTML de resultados de A9: recomendaciones de ejemplo y gráficos
src/resultados_a9.html                plantilla de esa página
src/wikipedia.py                      validación externa: visitas semanales de Wikipedia vs. MovieLens y A9
src/diario.py                         horizonte diario: A9 cortado en cualquier día (semanas móviles) y su validación en 2022
src/recomendar.py                     Top-K diario de A9: reconstruye el modelo, prepara las entradas y escribe CSV/JSON
src/dashboard.py                      datos del dashboard del EDA (JSON) y su versión autónoma en un solo HTML
src/dashboard.html                    página del dashboard (la misma que está publicada en claude.ai)
vendor/d3-7.9.0/                      d3.min.js (licencia ISC), incrustado en el HTML autónomo
src/experimento.py                    experimento inicial: baselines, entrenamiento y test
tests/test_modelo.py                  verifica la capa SAGE contra el SAGEConv de PyG
tests/test_evaluacion.py              métricas a mano, corte temporal del grafo y partición
tests/test_estadistica.py             Wilcoxon, bootstrap, Holm, ley de potencia y PSI
tests/test_lineas_base.py             ItemKNN a mano sin fuga, calendario de recálculo, MF-BPR
tests/test_temporal.py                cada atributo semanal a mano, sin fuga; pesos de decaimiento
tests/test_entrenamiento.py           negativos sólo entre películas conocidas; entrenamiento de humo
tests/test_h3.py                      grupos de historial y regla del umbral
tests/test_resultados_a9.py           ranking sin historial ni películas desconocidas; elección de usuarios de ejemplo
tests/test_wikipedia.py               consulta a Wikidata, visitas por semana, coincidencia y exposición (sin red)
tests/test_diario.py                  corte diario a mano y sin fuga, lunes = semana, Top-K sin historial ni películas desconocidas
notebooks/01_eda.ipynb                análisis exploratorio con OSEMN: contrato de datos, exploración, ley de potencia, deriva KS/PSI y decisiones (ya ejecutado)
notebooks/archivo/01_eda_v1.ipynb     EDA anterior, sólo como referencia
notebooks/02_experimento_inicial.ipynb resultados del experimento inicial (ya ejecutado)
notebooks/03_tiempo_en_el_modelo.ipynb protocolo, líneas base, ablación, H1 y H3 (ya ejecutado)
notebooks/04_arranque_en_frio.ipynb   H2: arranque en frío, contenido de TMDB, ablación, semillas y test (ya ejecutado)
notebooks/06_validacion_wikipedia.ipynb validación externa con las visitas de Wikipedia (sin ejecutar; el 05 queda para los comparadores)
resultados/experimento_inicial/       métricas, curva de entrenamiento y registro de la corrida
resultados/protocolo/                 métricas por semana y por usuario de cada corrida (validacion/, test/)
resultados/lineas_base/               registros, resumen y comparación de las líneas base
resultados/graphsage/                 registro, curva, configuración y pesos de cada corrida de la ablación
resultados/ablacion.csv               una fila por corrida: configuración y promedio de cada métrica
resultados/h1_test_*.csv              resumen y comparaciones de H1 en test
resultados/h3/                        deciles, tendencia y resumen de H3 (validación y test)
resultados/dashboard/                 un JSON por fuente del dashboard del EDA y eda_movielens_32m.html (versión autónoma)
resultados/a9/                        resultados_a9.html (página autónoma de resultados de A9)
resultados/wikipedia/                 semanal.csv, ejemplos.csv y cobertura.json de la validación con Wikipedia
resultados/diario/                    validación del horizonte diario (2022): métricas por día y por usuario, resumen y comparación
resultados/recomendaciones/           Top-K de src/recomendar.py (CSV o JSON)
```

## Cómo empezar (Windows)

Desde la carpeta del proyecto:

```
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/cu130
pip install -r requirements.txt
pip install pyg_lib -f https://data.pyg.org/whl/torch-2.14.0+cu130.html
python -m src.datos
jupyter notebook notebooks/01_eda.ipynb
```

- `python -m src.datos` lee los CSV directo del zip y escribe los Parquet (~240 MB). Tarda ~1 minuto y usa ~1.4 GB de RAM. Si los Parquet ya están en `data/processed/`, no hace falta repetirlo.
- El notebook de EDA corre en ~2 minutos y llega a ~5.3 GB de RAM.
- La línea de `torch` instala PyTorch con CUDA 13.0 (requiere un driver NVIDIA reciente). Sin GPU, omítela y `requirements.txt` instala la versión CPU.
- `pyg_lib` sólo hace falta para el muestreo de vecindario. Para torch 2.14 no hay `torch_sparse`, y no se necesita.
- Probado en Windows 11 con Python 3.13, PyTorch 2.14.0+cu130, PyTorch Geometric 2.8.1 y pyg_lib 0.9.0 en una RTX 4060 (8 GB): un paso full-batch de GraphSAGE (dimensión 128, 30 M aristas) tarda ~0.2 s y usa ~2.5 GB de GPU.

## Dashboard del EDA

```
python -m src.dashboard           # recalcula los JSON
python -m src.dashboard --html    # arma resultados/dashboard/eda_movielens_32m.html
```

- Sin argumentos, escribe en `resultados/dashboard/` un JSON por cada fuente del dashboard "EDA MovieLens 32M" (https://claude.ai/artifact/9P2BjwQXDfq3e3Z1Lc7juu), con el mismo cálculo del notebook 01. Tarda ~2 minutos y usa ~5 GB de RAM. Si cambia el notebook, hay que cambiar también `src/dashboard.py`.
- El dashboard de claude.ai guarda una copia fija de esos archivos: para actualizarlo, se regeneran y se reemplazan en el dashboard (se le puede pedir a Claude). Es privado hasta que se comparte desde su menú Share.
- Para compartirlo como archivo, `--html` arma en segundos `eda_movielens_32m.html` (~0.7 MB) con la página de `src/dashboard.html`, los JSON y d3 adentro. Se abre con doble clic en cualquier navegador, sin internet ni cuenta, y conserva los gráficos interactivos. Si se cambia la página en `src/dashboard.html`, hay que cambiarla también en el dashboard publicado.

## Protocolo de evaluación

```
python -m tests.test_evaluacion
python -m tests.test_estadistica
python -m src.protocolo
```

- Partición: objetivos de entrenamiento hasta dic-2021, validación = 52 semanas de 2022, test = 40 semanas completas de 2023 (02-ene a 02-oct). El test se mira una vez por configuración final.
- Para la semana w todo se calcula con datos anteriores a w. Los modelos se actualizan cada semana con la instantánea y los atributos de esa semana, con los pesos fijos.
- Métricas por usuario (Recall, Precision, NDCG y HitRate con K = 10, 20, 50, y MRR sobre el ranking completo) y cobertura del catálogo por semana. Se guardan por semana (`*_semanas.csv`) y por usuario (`*_usuarios.parquet`).
- Comparaciones: la unidad es la semana. Wilcoxon bilateral sobre las diferencias semanales, IC al 95 % con bootstrap de bloques móviles (bloques de 4 semanas) y Holm sobre {Recall@20, NDCG@20} × líneas base.

## GraphSAGE temporal: líneas base, ablación, H1 y H3

Pruebas (todas en segundos, sobre un grafo de juguete; cada atributo semanal tiene la suya, sin fuga temporal):

```
python -m tests.test_modelo
python -m tests.test_evaluacion
python -m tests.test_estadistica
python -m tests.test_lineas_base
python -m tests.test_temporal
python -m tests.test_entrenamiento
python -m tests.test_h3
```

Corridas, en orden (tiempos en la RTX 4060):

```
python -m src.lineas_base                                 # validación: aleatoria, popularidad k, ItemKNN, MF-BPR (~1 h)
python -m src.lineas_base --resumen                       # elige la mejor configuración de cada familia
python -m src.ablacion                                    # etapa 3, una cosa a la vez en validación (~2.5 h; retoma si se corta)
python -m src.entrenamiento --nombre A9_sin_id --test     # test 2023, una sola vez (~8 min)
python -m src.lineas_base --test                          # líneas base elegidas, en test (~8 min)
python -m src.hipotesis                                   # H1: Wilcoxon, IC por bloques y Holm
python -m src.h3                                          # H3: deciles de historial, bootstrap por usuario
```

- `src.ablacion` se salta las corridas que ya están en `resultados/ablacion.csv`, así que se puede interrumpir y retomar. Una corrida suelta se lanza con `python -m src.entrenamiento --nombre X --desde Y --cambio clave=valor`.
- Modelo final (A9): GraphSAGE heterogéneo de 2 capas y dimensión 64, **sin embeddings de ID** (totalmente inductivo), con atributos semanales de usuarios y películas, 13 semanas objetivo, dropout 0.1 y 1600 pasos. Para cada semana, los pesos quedan fijos y se recalculan el grafo y los atributos.
- El notebook 03 sólo lee `resultados/`. Para ejecutarlo con el entorno del proyecto: `python -m ipykernel install --sys-prefix --name proyecto-integrador` y elegir ese kernel.

Resultado en test (40 semanas de 2023):

| Método | Recall@20 | NDCG@20 | HitRate@20 | MRR |
|---|---|---|---|---|
| **GraphSAGE (A9)** | **0.140** | **0.087** | **0.313** | 0.111 |
| Popularidad semana anterior | 0.106 | 0.078 | 0.268 | 0.114 |
| MF-BPR (ventana 13, 20 épocas) | 0.073 | 0.045 | 0.183 | 0.063 |
| ItemKNN | 0.037 | 0.030 | 0.140 | 0.054 |
| Popularidad histórica | 0.027 | 0.022 | 0.106 | 0.040 |
| Aleatoria | 0.0003 | 0.0001 | 0.002 | 0.001 |

- **H1 se cumple.** Frente a la popularidad de la semana anterior: Recall@20 +0.034, IC 95 % [0.031, 0.038], 40 de 40 semanas, p de Holm 1.8e-11; NDCG@20 +0.010 [0.007, 0.013], 34 de 40 semanas, p de Holm 8.2e-8. La ventaja no se erosiona a lo largo del año con los pesos fijos. El MRR no mejora.
- **H3 se cumple en parte.** La ventaja crece con la longitud del historial (pendiente positiva en validación y test, p < 1e-4), pero no hay un umbral por debajo del cual la popularidad sea mejor: en el decil más corto (≤ 110 ratings previos) sólo hay empate.
- Detalle, tablas y figuras en `notebooks/03_tiempo_en_el_modelo.ipynb`.

## Resultados de A9 (página HTML)

```
python -m tests.test_resultados_a9
python -m tests.test_wikipedia
python -m src.wikipedia --descargar   # visitas de Wikipedia a data/wikipedia/ (~30 min, retoma si se corta)
python -m src.wikipedia               # validación con Wikipedia a resultados/wikipedia/ (CPU, ~15 min)
python -m src.resultados_a9
```

- Arma `resultados/a9/resultados_a9.html`, un solo archivo que se abre con doble clic, sin internet (d3 va adentro). Corre en CPU en unos minutos.
- Recomendaciones de ejemplo: el top 10 de A9 para 3 usuarios (historial corto, medio y largo: percentiles 10, 50 y 90 entre los que calificaron algo en las 3 semanas) en la primera, la del medio y la última semana de test, con las películas que de verdad calificaron esa semana y la posición que les daba A9. También compara los géneros de su historial con los de su top 20.
- Gráficos: curva de entrenamiento, Recall@20 y NDCG@20 por semana frente a la popularidad de la semana anterior (2022 y 2023), y la comparación en test con las líneas base.
- Validación externa con Wikipedia: MovieLens tiene ratings, no vistas, así que se comparan con las visitas semanales al artículo de cada película en Wikipedia en inglés (buscado en Wikidata por su imdbId). Responde si MovieLens refleja la popularidad real (Spearman semanal entre ratings y visitas) y si A9 expone a los usuarios a lo que está en boga (coincidencia del top 100 de A9 con el top 100 de Wikipedia de cada semana, frente a la popularidad y a Wikipedia de la semana anterior). Es un análisis adicional, después del test: las visitas no entran al modelo. Detalle en `notebooks/06_validacion_wikipedia.ipynb`.
- Lee `resultados/graphsage/A9_sin_id/{modelo.pt,curva.csv,validacion.json}`, `resultados/protocolo/`, `resultados/h1_test_resumen.csv` y `resultados/wikipedia/`. Las recomendaciones usan los pesos de `modelo.pt`, que son los de la corrida de validación (objetivos hasta dic-2021); las métricas de test son las del modelo reentrenado hasta dic-2022, cuyos pesos no se guardan.

## Recomendaciones Top-K con horizonte diario

```
python -m tests.test_diario
python -m src.diario                                                  # validación diaria en 2022 (GPU, ~5 min)
python -m src.recomendar --fecha 2022-06-15 --usuarios 123 456        # Top-10 a resultados/recomendaciones/top10.csv
python -m src.recomendar --fecha 2022-06-15 2022-06-16 --activos --k 10 --salida resultados/recomendaciones/top10.json
```

- **Horizonte.** Para la fecha d (día UTC), A9 ve sólo los ratings anteriores a d y ordena, para cada usuario, las películas que ya existían antes de d y que él no ha calificado. Los aciertos son las que califica el día d.
- **Reconstruir el modelo.** `cargar_a9` (`src/recomendar.py`) arma el `SAGEHeterogeneo` con la configuración de `resultados/graphsage/A9_sin_id/validacion.json` y le carga `modelo.pt` (pesos de la corrida de validación, objetivos hasta la semana del 27-dic-2021). No depende de `resultados/ablacion.csv`.
- **Preparar las entradas.** `GrafoDiario.en_semanas(dia)` (`src/diario.py`) arma la instantánea y los atributos con los ratings anteriores al día, con el mismo código de `src/temporal.py`: usa semanas móviles que terminan el día anterior, así que "la última semana" son los 7 días antes de d, "las últimas 4" los 28 y "semanas desde…" es ⌈días / 7⌉. En un lunes, las entradas son exactamente las de la instantánea semanal (prueba en `tests/test_diario.py`; en los datos, el top 10 de un lunes coincide con el de `src/resultados_a9.py`). A9 no tiene embeddings de ID, así que no hace falta reentrenar.
- **Top-K.** `Recomendador.a9().recomendar(usuarios, fecha, k)` devuelve un DataFrame con `fecha, userId, posicion, movieId, titulo, generos, puntaje, acierto` (`acierto`: el usuario calificó esa película ese día; sólo para mostrar). El comando escribe CSV (una fila por recomendación) o JSON (una entrada por usuario y día, con el modelo y el horizonte), según la extensión de `--salida`. Con `--activos`, recomienda a los usuarios con historia que calificaron algo ese día. Un usuario sin ratings antes de la fecha no recibe recomendaciones (A9 nunca se evaluó con ellos) y se reporta aparte.
- Corre en CPU: cargar datos y modelo tarda ~20 s (pico de ~5 GB de RAM) y el Top-10 de los ~200 usuarios activos de un día, ~5 s. Necesita `data/processed/` y `resultados/graphsage/A9_sin_id/{modelo.pt,validacion.json}`; `--gpu` usa la GPU. Ejemplo: `resultados/recomendaciones/ejemplo_top10_2022-06.json` (activos del 15 y 16-jun-2022).

Validación del horizonte diario (`python -m src.diario`): los días de las 52 semanas de validación (03-ene-2022 a 01-ene-2023; 362 con ratings, ~253 usuarios evaluados por día), con los pesos guardados, que no vieron 2022. "A9 corte semanal" es lo que vería el sistema si sólo se recalcula los lunes (instantánea, candidatas e historial del lunes).

| Método | Recall@10 | NDCG@10 | Recall@20 | NDCG@20 | HitRate@10 |
|---|---|---|---|---|---|
| **A9 corte diario** | **0.094** | **0.066** | **0.128** | **0.076** | **0.168** |
| A9 corte semanal | 0.087 | 0.061 | 0.120 | 0.070 | 0.158 |
| Popularidad 7 días | 0.070 | 0.056 | 0.094 | 0.062 | 0.143 |
| Popularidad día anterior | 0.061 | 0.049 | 0.080 | 0.054 | 0.126 |

- **A9 es compatible con el horizonte diario sin reentrenar.** Con corte diario supera a las tres referencias en las cuatro métricas (Wilcoxon por día, IC con bootstrap de bloques de 7 días, Holm sobre 12 pruebas, p ≤ 4e-27). Frente a la popularidad de los 7 días anteriores: Recall@10 +0.023, IC 95 % [0.022, 0.026], 339 de 362 días; NDCG@10 +0.011 [0.009, 0.012].
- **Hay que recalcular cada día, no sólo los lunes.** El corte diario le gana al semanal en Recall@10 por +0.007 [0.005, 0.009] (243 de 362 días) y en NDCG@10 por +0.005 [0.004, 0.006]. El 62 % de los usuarios que califican un día ya calificaron en los 6 días anteriores; con el corte del lunes, A9 no ve esos ratings y puede recomendar películas que el usuario ya calificó esa semana.
- El test (2023) no se ha mirado con el horizonte diario. Resultados en `resultados/diario/` y en `resultados/ablacion.csv` (etapa `5_diario`; ahí la columna `semanas` cuenta días).

## Experimento inicial

```
python -m tests.test_modelo
python -m src.experimento                              # objetivos de entrenamiento desde 1995
python -m src.experimento --semanas-entrenamiento 52   # sólo las 52 semanas antes de la validación
```

- La configuración (dimensión, capas, pasos, tasa de aprendizaje) está al inicio de `src/experimento.py`.
- Corre en CPU, sin GPU. En la máquina de prueba (2 núcleos, 8 GB de RAM) tardó 24 y 36 minutos, y llegó a ~4.6 GB de RAM.
- Cada corrida escribe `metricas.json`, `curva_entrenamiento.csv` en `resultados/experimento_inicial/<corrida>/`; el notebook 02 las compara.
- Esas dos corridas se hicieron en una máquina Linux sin GPU, con Python 3.13, PyTorch 2.14 y PyTorch Geometric 2.8.1.

Resultado (test, últimas 4 semanas completas): ninguna versión de GraphSAGE estático supera a la popularidad de las últimas 4 semanas (Recall@20 0.053 vs. 0.081; NDCG@20 0.025 vs. 0.063). Detalle en `notebooks/02_experimento_inicial.ipynb`.

## Datos

MovieLens 32M (GroupLens): 32,000,204 ratings de 200,948 usuarios sobre 87,585 películas, de enero de 1995 a octubre de 2023. Licencia sólo para investigación, sin uso comercial. Citar: Harper, F. M., & Konstan, J. A. (2015). The MovieLens Datasets: History and Context. *ACM TiiS*, 5(4). https://doi.org/10.1145/2827872

**TMDB (contenido de películas, para H2).** `python -m src.tmdb` descarga una sola vez (~70 min, retoma si se corta) la sinopsis, palabras clave, director, reparto, idioma, duración y fecha de estreno de cada `tmdbId` de `links.csv` a `data/tmdb/` (no se versiona). La llave se lee de la variable de entorno `TMDB_API_KEY` o de `data/tmdb/llave.txt`. No se guardan `popularity`, `vote_average` ni `vote_count`, que son valores actuales y meterían información del futuro. Cobertura: 86,237 de 87,585 películas, con sinopsis para el 98 % (también para las películas que entran en 2022–2023). *This product uses the TMDB API but is not endorsed or certified by TMDB.*

PyTorch Geometric no trae un cargador para MovieLens 32M: su clase `MovieLens` descarga `ml-latest-small` (610 usuarios) y las otras son `MovieLens100K` y `MovieLens1M` (verificado en PyG 2.8.1). El grafo se construye desde los Parquet de `data/processed/`.

## Estado

- [x] Datos convertidos a Parquet
- [x] EDA con OSEMN: contrato de datos, exploración, ley de potencia de los grados y deriva entre 2021, 2022 y 2023 (KS y PSI, estable); cierra con cada hallazgo y la decisión que tomó el proyecto
- [x] Grafo temporal, protocolo de evaluación y baselines de popularidad
- [x] Experimento inicial con GraphSAGE heterogéneo estático
- [x] Protocolo de evaluación de la propuesta (métricas, partición, pruebas estadísticas)
- [x] Líneas base de la propuesta en validación (`python -m src.lineas_base`, ~45 min en la RTX 4060; `--resumen` para la tabla)
- [x] Tiempo dentro del modelo: ablación en validación (`python -m src.ablacion`); gana A9, GraphSAGE inductivo sin embeddings de ID con atributos semanales
- [x] Test de 2023, una sola vez (`python -m src.entrenamiento --nombre A9_sin_id --test`, `python -m src.lineas_base --test`, `python -m src.hipotesis`): H1 se cumple. GraphSAGE logra Recall@20 0.140 frente a 0.106 de la popularidad de la semana anterior, y NDCG@20 0.087 frente a 0.078 (Wilcoxon por semana con Holm, p < 1e-7)
- [x] H3 (`python -m src.h3`): la ventaja crece con el historial (pendiente > 0 en validación y test, p < 1e-4); no hay umbral donde la popularidad sea mejor, sólo empate en el decil más corto (≤ 110 ratings)
- [x] Notebook 03 con tablas y figuras de las etapas 1 a 4
- [x] Pregunta 2 / H2 (`python -m src.tmdb`, `python -m src.contenido`, `python -m src.h2 --ablacion`, `python -m src.entrenamiento --frio --test --nombre ...`, `python -m src.h2 --comparar test`): en películas sin historial, grafo + contenido (F4) supera a sólo contenido (dos torres) en Recall@20 en test (0.502 vs. 0.473, 3 semillas promediadas, Holm p = 0.010) pero no en NDCG@20 (0.220 vs. 0.226, n. s.); con 5–19 ratings la ventaja del grafo es clara en ambas métricas. Resultados en `resultados/h2/`
- [x] Notebook 04 de H2 con tablas y figuras
- [x] Comparadores DL (`python -m src.comparadores`, `--test`, `--comparar`): en test, A9 supera a Mult-VAE (Recall@20 0.140 vs. 0.118), LightGCN (0.075) y NCF (0.073) en Recall@20 y NDCG@20 (familia de Holm aparte, 6 pruebas, p de Holm ≤ 0.014). Resultados en `resultados/comparadores/`
- [x] Top-K diario de A9 para la demo (`python -m src.recomendar`) y validación del horizonte diario en 2022 (`python -m src.diario`): sin reentrenar, A9 con corte diario supera a la popularidad de 7 días (Recall@10 0.094 vs. 0.070) y al corte sólo los lunes (0.087). Resultados en `resultados/diario/`
- [ ] Notebook 05 de comparadores (tablas, curvas de aprendizaje y UMAP)
- [ ] Repetir sobre A9 los cambios de la ablación que se probaron con embeddings de ID
- [ ] Estadística avanzada que no entró en el EDA: STL de la serie semanal y PCA/k-means de perfiles de usuario
