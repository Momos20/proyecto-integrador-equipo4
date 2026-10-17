# Database

Persistencia operacional en PostgreSQL/RDS para la aplicación de recomendaciones.

## Tablas

### `movies`
Catálogo mínimo de películas consumido por la aplicación. Conserva `movie_id` de MovieLens, título, año, géneros y atributos opcionales de TMDB.

### `model_versions`
Registro de versiones del modelo. Permite distinguir modelos `candidate`, `champion`, `archived` o `failed` y asociar métricas y artefactos.

### `scoring_runs`
Auditoría de cada ejecución batch de scoring: versión de modelo, semana de corte, estado, origen/salida y número de usuarios/recomendaciones procesadas.

### `recommendations`
Materialización de los rankings Top-K. La clave lógica es usuario + semana de corte + posición del ranking. Esta tabla es la fuente operacional que consulta Flask; la aplicación no ejecuta GraphSAGE por cada request.

## Vista

`latest_recommendations` expone el ranking correspondiente a la semana más reciente disponible para cada usuario, enriquecido con metadatos de `movies`.

## Inicialización local

`docker compose up --build` monta automáticamente los siguientes archivos en PostgreSQL durante la creación inicial del volumen:

1. `schema/001_init.sql`
2. `schema/002_views.sql`
3. `seeds/001_mock_data.sql`

El seed crea un modelo `baseline-v0` y diez recomendaciones de demostración para el usuario `414`.

> PostgreSQL ejecuta los scripts de `/docker-entrypoint-initdb.d` solo cuando el volumen está vacío. Para reconstruir completamente la base local después de cambiar el esquema:
>
> `docker compose down -v && docker compose up --build`

## Producción

En AWS, PostgreSQL se desplegará sobre Amazon RDS. Los scripts de `schema/` son la definición inicial del esquema; las modificaciones posteriores deben incorporarse como migraciones versionadas en `migrations/`.
