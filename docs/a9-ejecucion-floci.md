# CineGraph — A9 de Miguel con Floci local (sin AWS Academy)

## Etapa actual: local primero

**No se necesita cuenta ni consola AWS.** CineGraph usa Docker Compose para Flask + PostgreSQL y [Floci](https://github.com/floci-io/floci) para emular Kinesis, Firehose y S3 en el Mac. El cálculo de GraphSAGE **lo ejecuta PyTorch local**; Floci no entrena ni sirve GraphSAGE automáticamente. No se usa SageMaker real. AWS Academy queda para una etapa posterior.

El código A9 y los pesos de Miguel están en GitHub: `ml/a9_daily/src/` y `ml/models/A9_sin_id/modelo.pt`. `scripts/ml/run_a9_floci.py` es solo un **orquestador local**, no modifica ni reentrena A9, y bloquea cualquier endpoint diferente de `localhost:4566`/`127.0.0.1:4566`/`floci:4566` (HTTP). Utiliza credenciales ficticias y el bucket emulado `cinegraph-local-datalake`. El ZIP original de Miguel no necesita volver a subirse.

## 1. Preparar Floci (una vez)

En Mac Terminal, desde el repositorio:

```bash
cd "$HOME/Documents/GitHub/proyecto-integrador-equipo4"
git switch main
git pull --ff-only origin main
# Conservar tu .env si ya existe:
test -f .env || cp .env.example .env
docker compose up -d db app
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci up -d floci
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci run --rm floci-tools bootstrap
```

Comprueba recursos emulados (no AWS real):

```bash
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci run --rm floci-tools status
```

El bucket local de MovieLens será `cinegraph-local-datalake`; `docker-compose.floci.yml` define el volumen `floci_data` para conservar objetos entre reinicios normales. **No uses `docker compose down -v`**, porque borra volúmenes.

## 2. Preparar Python local para Miguel

Desde la raíz del repositorio:

```bash
python3 -m venv .venv-a9
source .venv-a9/bin/activate
python -m pip install --upgrade pip
python -m pip install -r ml/a9_daily/requirements.txt boto3
```

Miguel requiere PyTorch y PyTorch Geometric. En Mac Apple Silicon son instalaciones nativas (sin CUDA). El grafo MovieLens 32M requiere memoria considerable: usar 16 GB de RAM **como referencia inicial, no garantía**; una ejecución puede necesitar más. Si falla instalación de `torch_geometric` o memoria, registra el error y ajustamos el entorno **sin cambiar el modelo**. `.venv-a9/` es local y no debe entrar en Git.

## 3. Cargar primero los ratings a S3 local (opcional, para comprobar datos)

```bash
python scripts/ml/run_a9_floci.py \
  --ratings-local "$HOME/Downloads/ml-32m/ml32m_cache/ratings_clean.parquet" \
  --solo-subir
```

Verifica el SHA-256 del checkpoint de Miguel, comprueba el bucket local y almacena el Parquet con nombre basado en SHA-256, sin subirlo a GitHub ni utilizar AWS externo. Si el mismo objeto existe y coincide, no vuelve a escribirlo.

## 4. Ejecutar pruebas y Top-K con A9 **sin reentrenar**

```bash
python scripts/ml/run_a9_floci.py \
  --ratings-local "$HOME/Downloads/ml-32m/ml32m_cache/ratings_clean.parquet" \
  --fecha 2023-06-15 --usuarios 123 456 --k 10
```

La ejecución hace lo siguiente:

1. Verifica que `modelo.pt` coincide con el SHA-256 de Miguel y que Floci está disponible.
2. Comprueba o sube `ratings_clean.parquet` al **S3 emulado**; vuelve a descargar ese objeto y comprueba su hash.
3. Prepara `ratings.parquet`, `movies.parquet`, `links.parquet` con `scripts/data/prepare_miguel_a9.py` (catálogo ya conservado en GitHub).
4. Ejecuta `python -m tests.test_evaluacion` y `python -m tests.test_diario` del código original de Miguel.
5. Ejecuta `python -m src.recomendar` y publica Top-K JSON y manifiesto de procedencia en el **S3 emulado** bajo `predictions/a9/`.

Si falla una etapa, **no declara una prueba exitosa**. Un archivo histórico `resultados/diario` no equivale a reproducir las métricas. El A9 original tiene **corte diario** y la tarea de predicción del mismo día; no se sustituye silenciosamente por el horizonte de 7 días de CineGraph.

Los Parquet procesados se escriben bajo `ml/a9_daily/data/processed/` y están excluidos de Git. La aplicación aún muestra rankings del baseline de demostración. **Todavía no hay adaptador A9 → PostgreSQL**; será la siguiente etapa después de validar la inferencia.

## 5. Streaming local de feedback (flujo diferente)

Para comprobar el recorrido de una interacción del frontend: sigue [`docs/floci-local.md`](floci-local.md) (`ship` y `verify`). Ese circuito Kinesis → Firehose → S3 Raw es **independiente** de ejecutar el batch de MovieLens A9. No entrenamos ni ejecutamos scoring en cada clic.

## Futuro: AWS Academy

Cuando termine la validación local, se mapeará el almacenamiento emulado a S3 AWS y el cálculo de PyTorch a un entorno de ejecución real. **No hay recursos AWS reales creados ni validados en esta etapa**, y no debe ejecutarse el runner local contra una cuenta AWS.
## Publicación manual en CineGraph sin simulaciones

El runner ahora anota `predicciones_sha256` en el manifiesto. `a9-publish` lee exclusivamente JSON y manifiesto de A9 bajo S3 Floci, verifica el checksum del resultado, del checkpoint y que se ejecutaron las pruebas originales, y guarda posiciones y scores verdaderos en PostgreSQL. El frontend solo los presenta después de iniciar sesión. Sin resultados A9 publicados, aparece un mensaje de ausencia, nunca una predicción falsa. [Guía](cinegraph-login-real-a9.md).


## Datos behavioral de 2026: integración experimental shadow

La inferencia histórica A9 del 15 de junio de 2023 ya se ejecutó y publicó en la aplicación local; esto **no valida nuevas predicciones en 2026**. El preparador `a9-feedback-stage` ahora selecciona solo ratings explícitos previos al corte y conserva las features observacionales aparte. El runner opcional `run_a9_shadow.py` reconstruye el grafo sobre una copia en memoria con usuarios CineGraph remapeados a IDs distintos de MovieLens, sin cambiar el checkpoint original ni publicar rankings nuevos. [Protocolo y comandos](orquestacion-y-shadow-local.md).
