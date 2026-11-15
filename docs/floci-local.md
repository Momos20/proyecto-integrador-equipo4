# Laboratorio CineGraph con Floci (AWS local)

Este laboratorio permite comprobar el flujo de feedback **Flask → PostgreSQL + clickstream.log → Kinesis Data Streams → Data Firehose → S3 Raw**, sin crear recursos en AWS real. **Floci es opcional** y no altera `docker compose up -d --build` habitual.

Basado en [Floci 2.5.0](https://github.com/floci-io/floci) (licencia MIT). Requiere Docker Desktop con Compose v2 y conexión para descargar la imagen inicial. Usa un endpoint local fijo y credenciales ficticias. No subas credenciales AWS reales.

## 1. Arrancar aplicación y emulador

Desde la raíz del repositorio, en tu Mac:

```bash
test -f .env || cp .env.example .env  # Conserva tu archivo .env si ya existe
docker compose up -d --build db app
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci up -d floci
```

La aplicación se abre en **http://localhost:8000** y el emulador escucha exclusivamente en **http://127.0.0.1:4566**. La configuración usa un volumen `floci_data` para que los recursos sobrevivan a reinicios normales.

> Para Mac Apple Silicon no se necesita compilar Floci ni clonar su repositorio; la imagen Docker oficial es multi-arquitectura.

## 2. Crear recursos locales, manualmente

```bash
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci \
  run --rm floci-tools bootstrap
```

Esto crea únicamente dentro del emulador:

- bucket `cinegraph-local-datalake`
- stream `cinegraph-clickstream`
- Firehose `cinegraph-clickstream-to-s3`, con Kinesis como origen y `raw/behavioral/cinegraph/live/` como destino

El script es reejecutable sin duplicar recursos. El rol ARN usado es ficticio y nunca se usan las credenciales de tu cuenta AWS. Floci incluye un ajuste **solo local** `FLOCI_SERVICES_FIREHOSE_FLUSH_RECORD_COUNT=1` para facilitar la entrega de pocos eventos. No trasladar ese ajuste a AWS.

## 3. Generar interacciones reales del frontend

En **http://localhost:8000**: usuario `414`, «Descubrir», después «Me interesa» o «Mi lista» en una película.

Comprobar que el backend guardó el evento antes de publicarlo:

```bash
docker compose exec app tail -3 /app/logs/clickstream.log
```

## 4. Enviar los eventos pendientes y verificar el recorrido

```bash
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci \
  run --rm floci-tools ship

docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci \
  run --rm floci-tools verify
```

`ship` envía las líneas JSONL completas pendientes mediante `kinesis:PutRecord`. Guarda un cursor de lectura en `floci_ship_state` para no reenviar sistemáticamente todo el log; en caso de fallo entre la publicación y el cursor, la garantía es **at least once** y las transformaciones posteriores deben deduplicar por `event_id`.

`verify` **lee realmente los objetos S3** creados por Firehose y busca el `event_id` de la última interacción enviada. Si no lo encuentra, falla y muestra el problema; no da la prueba por exitosa solo porque Kinesis aceptó una solicitud.

Para consultar el estado sin activar trabajos:

```bash
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci \
  run --rm floci-tools status
```

## 5. Detener sin perder datos

```bash
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci stop floci
```

**No utilices `down -v`** salvo que quieras borrar deliberadamente los volúmenes de PostgreSQL, Floci, clickstream y cursores.

## Qué se está probando y qué todavía no

| Etapa | Se ejecuta de verdad en local | Estado |
|---|---|---|
| Frontend + API Flask + PostgreSQL | Sí (Docker) | Implementado |
| Registro JSONL en `clickstream.log` | Sí (Flask) | Implementado |
| Envío JSONL a Kinesis emulado | Sí, con el comando `ship` | Implementado |
| Kinesis → Firehose → S3 emulados | Floci implementa consumidor y entrega; probar con `verify` | Preparado para prueba |
| MovieLens/TMDB → S3 Raw | Cargas batch separadas | Pendiente |
| Glue Raw → Curated → Features | Floci gestiona catálogo/jobs, **no ejecuta PySpark** | Pendiente: script local o AWS |
| SageMaker GraphSAGE A9_sin_id → Top-K | Requiere inferencia y mapeos de Miguel | Pendiente |
| EventBridge / Step Functions (scoring diario) | No se crea ningún disparador | Pendiente |

**Diferencia intencional respecto del despliegue real:** en AWS el diagrama utiliza un Kinesis Agent que sigue el log continuamente. Para este laboratorio, el agente se sustituye por un pequeño publicador **manual** compatible con el API de Kinesis de Floci. Esto evita exponer accidentalmente los eventos a AWS real. El `kinesis-agent` y su configuración productiva quedan intactos.

La existencia del emulador o un evento nuevo **no ejecutan entrenamiento, scoring, Glue, Step Functions ni GitHub Actions**. Los workflows del repositorio siguen en `workflow_dispatch` (manual).

## 6. MovieLens 32M y GraphSAGE A9 (laboratorio ML local separado)

El mismo bucket emulado `cinegraph-local-datalake` puede almacenar el Parquet de MovieLens y las predicciones de A9. No hay que usar Amazon S3 real ni una consola AWS. Floci **solo simula S3**; las pruebas y la inferencia se ejecutan con PyTorch en la Mac, preservando el checkpoint y el código de Miguel. **No hay reentrenamiento**.

Guía: [`docs/a9-ejecucion-floci.md`](a9-ejecucion-floci.md). Script: `scripts/ml/run_a9_floci.py`. Las salidas quedan bajo `predictions/a9/` en el S3 local, mientras que Kinesis/Firehose publica eventos bajo `raw/behavioral/cinegraph/live/`. Son dos circuitos diferentes; ninguno arranca automáticamente al hacer clic.

No utilizar `scripts/ml/run_a9_s3.py`: era una preparación prematura para AWS real y fue retirada para evitar confusiones en esta fase.
