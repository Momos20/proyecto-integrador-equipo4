# CineGraph — cuentas locales, catálogo verificado y recomendaciones A9

## Qué se cambió

- Acceso con cuenta y contraseña; Flask mantiene una sesión firmada con cookie HttpOnly/SameSite.
- Las rutas de recomendaciones e interacciones consultan **solo el ID MovieLens de la cuenta autenticada**. No se aceptan búsquedas arbitrarias de ID ni acciones de otra cuenta.
- El catálogo se importa desde los fragmentos originales MovieLens 32M del repositorio, **verificados por MD5**, en PostgreSQL. No se listan películas hasta que el registro de importación acreditada esté presente.
- El frontend muestra filas horizontales al desplazarse, sin botón «Descubrir mi Top 10» ni pósteres/rankings hardcodeados. Si falta un póster TMDB, aparece el título real con fondo tipográfico (no se inventa una portada).
- Se retira el seed `baseline-v0` de nuevos volúmenes. El bootstrap también retira sus recomendaciones y registros de modelo anteriores **sin eliminar interacciones reales** de `user_interactions`.
- La API solo muestra recomendaciones cuando se hayan publicado resultados del `src.recomendar` A9 original, acompañados de un manifiesto de inferencia validado. Si todavía no hay predicciones, comunica la ausencia sin inventar resultados.

## 1. Actualizar y levantar la app (Mac)

```bash
cd "$HOME/Documents/GitHub/proyecto-integrador-equipo4"
git pull --ff-only origin main
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci up -d --build db app floci
```

**No ejecutar `docker compose down -v`**, porque borraría datos persistentes. El bootstrap aplica la migración al volumen PostgreSQL ya existente.

## 2. Importar catálogo original + crear cuentas locales

```bash
docker compose --profile setup run --rm local-setup
```

Este comando verifica e importa **87.585** películas de MovieLens. Las credenciales locales se crean solo la primera vez; copia las contraseñas que se mostrarán en tu Terminal. Las contraseñas **no se guardan ni se publican en GitHub**. Las cuentas de prueba son:

| Usuario de acceso | MovieLens userId |
|---|---:|
| `cine414` | 414 |
| `cine123` | 123 |
| `cine456` | 456 |

Son perfiles del laboratorio, **no identidades reales** de los autores de los ratings anónimos de MovieLens. Si vuelves a ejecutar el bootstrap, conserva las cuentas y los hashes existentes. Para restablecer una contraseña local:

```bash
docker compose --profile setup run --rm local-setup /app/scripts/local_setup/reset_password.py cine414
```

Reemplaza `cine414` por `cine123` o `cine456` cuando corresponda. Nunca expongas esta configuración de pruebas a Internet o a AWS Academy.

## 3. Abrir la aplicación

Abrir http://localhost:8000. El catálogo aparece en estanterías horizontales. Inicia sesión con `cine414`, `cine123` o `cine456`. La navegación **Para ti** se carga automáticamente para la cuenta autenticada y no presenta resultados de `baseline-v0`.

Comprueba API sin iniciar sesión:

```bash
curl -i http://localhost:8000/api/recommendations
curl -s 'http://localhost:8000/api/catalog?limit=2'
```

La primera debe devolver HTTP 401. La segunda debe devolver 2 películas del catálogo **verificado** (después del bootstrap). El login se realiza en la pantalla; no es necesario pasar el ID MovieLens en la URL.

## 4. Producir Top-K reales de Miguel (requisito para «Tu selección»)

Floci y Docker **no ejecutan** GraphSAGE automáticamente. Los resultados reales aparecen después de:

1. Verificar el Parquet `~/Downloads/ml-32m/ml32m_cache/ratings_clean.parquet` (o indicar su ubicación correcta).
2. Preparar entorno Python local con dependencias `ml/a9_daily/requirements.txt` y `boto3`. En macOS Apple Silicon, PyTorch/PyG necesitan ruedas compatibles con tu versión de Python. No entrenar de nuevo.
3. Ejecutar el comando MANUAL (desde la raíz del repositorio):

```bash
python3 scripts/ml/run_a9_floci.py \
  --ratings-local "$HOME/Downloads/ml-32m/ml32m_cache/ratings_clean.parquet" \
  --fecha 2023-06-15 --usuarios 414 123 456 --k 10
```

Este proceso verifica el checkpoint SHA-256, carga el Parquet a **S3 local Floci**, ejecuta las pruebas del paquete de Miguel, genera rankings mediante su modelo original y guarda JSON/manifiesto bajo `predictions/a9/` en Floci. Puede exigir bastante RAM. Si un usuario no tenía historial en esa fecha, **no recibirá recomendaciones**; esto forma parte del protocolo original de Miguel.

4. **Publicar manualmente** la última inferencia ya validada a PostgreSQL:

```bash
docker compose -f docker-compose.yml -f docker-compose.floci.yml \
  --profile floci run --rm a9-publish
```

El publicador lee exclusivamente JSON+manifiesto bajo `predictions/a9/` en el S3 local y verifica que sean del GraphSAGE original con pruebas aprobadas. Persiste las posiciones y scores de Miguel sin recalcularlos ni inventarlos. El frontend **no ejecuta inferencia** cada vez que alguien entra.

**Nota temporal:** el experimento original de A9 tiene horizonte diario. No se debe afirmar que la ejecución equivale al horizonte de 7 días de la arquitectura objetivo.

## 5. Pruebas de flujo de clics

Las acciones «Me gusta», «Mi lista» y las calificaciones se guardan en PostgreSQL por la cuenta autenticada, y generan `clickstream.log`. Luego se sigue utilizando el laboratorio ya existente:

```bash
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci run --rm floci-tools ship
docker compose -f docker-compose.yml -f docker-compose.floci.yml --profile floci run --rm floci-tools verify
```

No se necesita una consola AWS. La migración a AWS Academy será posterior. Floci es almacenamiento/streaming emulado, **no SageMaker ni una ejecución mágica del modelo**.


## Búsqueda de películas desde el encabezado

El botón con lupa en la barra superior abre un campo de búsqueda estilo Netflix. Al introducir **al menos dos caracteres**, el frontend consulta `GET /api/catalog?search=...` con una espera breve de 320 ms y muestra una cuadrícula de hasta 48 películas reales de MovieLens 32M. Se admiten fragmentos del título y años que formen parte del título. Los resultados no son inferencias ni recomendaciones de A9; proceden exclusivamente del catálogo verificado y respetan las imágenes disponibles. Las acciones de «Me gusta», «Mi lista» y calificar continúan vinculadas a la sesión.

También puedes abrir el buscador pulsando `/` fuera de cualquier campo y cerrarlo con `Escape`. En teléfonos aparece debajo de la barra de navegación. Si todavía no se importó el catálogo, la búsqueda muestra una advertencia en lugar de resultados ficticios.
