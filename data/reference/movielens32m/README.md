# MovieLens 32M · catálogo verificado para el modelo de Miguel

Los archivos provienen de MovieLens 32M (GroupLens), generados el **13 de octubre de 2023**. Recibidos y verificados el 15 de noviembre de 2026. Las sumas MD5 son **idénticas a las del README oficial** que proporcionó el equipo.

## Archivos versionados en Git

```text
data/reference/movielens32m/
├── README.txt            # Original completo: términos de uso, estructura, cita
├── checksums.txt         # MD5 originales de MovieLens
├── links.csv             # Original, 87.585 filas y 1.950.748 bytes
└── parts/
    ├── movies.part01.csv # Primera parte exacta, líneas 1–30.000
    ├── movies.part02.csv # Líneas 30.001–60.000
    └── movies.part03.csv # Líneas 60.001–87.586
```

`movies.csv` se conserva **sin perder ni una línea** en tres fragmentos concatenables byte a byte, porque el archivo original supera el tamaño recomendado de una sola transferencia al repositorio. Los fragmentos conservan `CRLF` y su concatenación tiene el MD5 oficial: `0df90835c19151f9d819d0822e190797`.

`links.csv` mantiene MD5 `8f033867bcb4e6be8792b21468b4fa6e`.

## Archivos que NO se suben a Git

- `tags.csv`: 72.353.890 bytes y 2.000.072 registros; **validado contra el checksum oficial** (MD5 `963bf4fa4de6b8901868fddd3eb54567`). Es opcional para el GraphSAGE A9 base, que construye el grafo usando ratings y características de movies. Se almacena en el directorio local de datos o S3/Floci, no en la historia Git.
- `ratings.csv`: **no fue adjuntado en esta entrega**. El modelo A9 sí necesita sus interacciones históricas. Si ya existe `ratings_clean.parquet` en el Mac, se reutiliza sin repetir la limpieza.

## Dejar el catálogo listo para A9 sin reprocesar MovieLens completo

Primero actualizar el clon y, si no existe, incorporar el ZIP de Miguel con el importador ya presente:

```bash
git pull origin main
python3 scripts/import_miguel_a9.py ~/Downloads/A9_topk_diario.zip
```

Instalar las dependencias desde `ml/a9_daily/requirements.txt`, incluyendo pandas y pyarrow. Para comprobar la integridad del catálogo **sin dependencias de Machine Learning**:

```bash
python3 scripts/data/prepare_miguel_a9.py --verify-only
```

Para usar el Parquet de ratings limpios ya existente:

```bash
python3 scripts/data/prepare_miguel_a9.py \
  --ratings-parquet "/Users/momos/Downloads/ml-32m/ml32m_cache/ratings_clean.parquet"
```

Genera exactamente:

```text
ml/a9_daily/data/processed/
├── movies.parquet
├── links.parquet
└── ratings.parquet
```

Miguel utiliza `src/datos.py`, que espera esos nombres y `userId, movieId, rating, timestamp` (timestamp Unix en segundos). La preparación solo ajusta nombres y tipos si hace falta; **no redefine features, arquitectura, entrenamiento, candidatos ni objetivo del modelo**.

Si también deseas tags:

```bash
python3 scripts/data/prepare_miguel_a9.py \
  --ratings-parquet ".../ratings_clean.parquet" \
  --tags-csv ".../tags.csv"
```

La inferencia de A9 funciona principalmente con **ratings + movies**; `links` facilita integraciones con TMDB. El modelo de Miguel es nuestra referencia técnica; se conserva su protocolo diario tal como fue entregado. La diferencia respecto al horizonte a siete días descrito previamente sigue documentada para que la decisión metodológica sea explícita.

## Licencia y atribución

El `README.txt` original permite la redistribución con las **mismas condiciones de uso**, exige reconocer a GroupLens y prohíbe el uso comercial o con ingresos sin permiso. Este repositorio es académico; no se atribuye ninguna aprobación de GroupLens.

Cita: Harper, F. M. y Konstan, J. A. (2015). *The MovieLens Datasets: History and Context*. ACM Transactions on Interactive Intelligent Systems, 5(4). https://doi.org/10.1145/2827872
