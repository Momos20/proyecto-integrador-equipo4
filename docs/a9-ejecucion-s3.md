# CineGraph | Primera inferencia reproducible de A9 desde S3

## Propósito y límites

Ejecutar una **prueba manual** de inferencia Top-K con el **código y los pesos originales de Miguel** (`ml/a9_daily/src/` y `ml/models/A9_sin_id/modelo.pt`). Este flujo no reentrena GraphSAGE, no cambia su arquitectura, no modifica el protocolo temporal diario ni publica recomendaciones en la aplicación o en RDS. La validación diaria original de Miguel se conserva como referencia; una ejecución nueva deberá identificarse como tal.

**Estado:** el repositorio ya contiene A9 y el catálogo MovieLens 32M (`movies.csv` dividido y `links.csv`). Falta poner a disposición en AWS el `ratings_clean.parquet` completo, instalar las dependencias en un entorno de ejecución y correr las pruebas. No se afirma que exista un bucket ni que el scoring haya sucedido.

## Datos y destinos

- Entrada grande: `s3://<BUCKET>/<PREFIJO>/ratings_clean.parquet` (MovieLens 32M); **no subir a GitHub**.
- Catálogo: `data/reference/movielens32m/` **ya disponible en GitHub**, verificado por checksum por `scripts/data/prepare_miguel_a9.py`. No es necesario descargar `movies.csv` a mano.
- Checkpoint original versionado: `ml/models/A9_sin_id/modelo.pt`, verificado por SHA-256 antes de operar.
- Salida propuesta: `s3://<BUCKET>/artifacts/a9/top10_a9_2023-06-15.json` y `top10_a9_2023-06-15.manifest.json` con procedencia, fecha, usuarios y checksum de entrada.

Los archivos Parquet temporales se crean en `ml/a9_daily/data/processed/`, que está excluido del repositorio en `.gitignore`. El script se ejecuta donde esté clonado el repositorio en un **servidor AWS con acceso S3**; no necesita que la Mac permanezca encendida. La Mac sólo interviene si el dataset aún está allí y no se ha transferido a S3.

## Antes de ejecutar

1. Verificar el bucket **existente** y su región. Si no existe, configurarlo en la cuenta del equipo antes de la prueba. No asumir nombre, cuenta ni región.
2. Subir una sola vez el Parquet desde su ubicación actual (o desde donde ya esté almacenado) a la ruta de S3; si se usa AWS CLI desde la Mac, el ejemplo es:

   ```bash
   aws s3 cp "$HOME/Downloads/ml-32m/ml32m_cache/ratings_clean.parquet" \
     "s3://<BUCKET>/datasets/movielens32m/ratings_clean.parquet"
   ```

3. Preparar un entorno Python con RAM suficiente para el grafo completo y las dependencias de `ml/a9_daily/requirements.txt`, además de `boto3`. Como punto de partida, considerar **16 GiB de RAM o más**, sujeto a medición de la ejecución real (no se garantiza que baste para cualquier configuración). Ejemplo en una instancia EC2 o entorno de cómputo AWS compatible:

   ```bash
   git clone https://github.com/Momos20/proyecto-integrador-equipo4.git
   cd proyecto-integrador-equipo4
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r ml/a9_daily/requirements.txt boto3
   ```

4. Usar un **rol IAM** del servidor con permisos S3 de lectura para el objeto de ratings y de escritura para el prefijo de salida. Para comprobar que la salida no existe ya, el script consulta `HeadObject` (en algunas configuraciones requiere `s3:ListBucket`). No guardar access keys en GitHub ni en el código.

## Ejecución manual

Desde la raíz del repositorio, en el entorno Python que tenga PyTorch Geometric:

```bash
python scripts/ml/run_a9_s3.py \
  --ratings-s3 "s3://<BUCKET>/datasets/movielens32m/ratings_clean.parquet" \
  --salida-s3 "s3://<BUCKET>/artifacts/a9/top10_a9_2023-06-15.json" \
  --fecha 2023-06-15 \
  --usuarios 123 456 \
  --k 10
```

El orquestador, distinto del código de Miguel:

1. Verifica el **SHA-256 del checkpoint original** y la existencia del objeto S3.
2. Descarga temporalmente el Parquet desde S3 y prepara `ratings.parquet`, `movies.parquet`, `links.parquet` usando el preparador existente del repositorio.
3. Ejecuta `python -m tests.test_evaluacion` y `python -m tests.test_diario` **del paquete original**.
4. Ejecuta `python -m src.recomendar`, sin modificar el algoritmo GraphSAGE; el corte diario sólo ve ratings anteriores a la fecha UTC indicada.
5. Si hay al menos un Top-K generado, guarda el JSON y un manifiesto de procedencia en S3. Si falla cualquier etapa, no publica recomendaciones.

La salida es un **experimento de inferencia**. No se publica en RDS ni reemplaza los rankings actuales de demostración. La calidad del modelo se debe discutir con las métricas originales de Miguel y con evaluaciones posteriores que utilicen el mismo protocolo; no atribuir las métricas históricas de Miguel a esta ejecución.

## Comprobación

Verificar que existen los dos objetos de salida y que el JSON contiene la clave `recomendaciones`, con un conjunto no vacío de usuarios y Top-K. El manifiesto contiene `checkpoint_sha256`, `ratings_sha256`, fecha, IDs, `k` y confirmación de pruebas.

**Pendiente después de esta etapa:** diseñar un adaptador batch para guardar el Top-K en PostgreSQL/RDS y vincularlo al backend de CineGraph. Eso debe ser una integración distinta; no cambiar `ml/a9_daily/src/recomendar.py` ni el checkpoint para hacerla.