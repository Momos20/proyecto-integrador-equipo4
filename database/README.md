# Persistencia operacional de CineGraph

PostgreSQL local (Docker) se conservará como base para evolucionar después a Amazon RDS.

## Tablas

- `movies`: **catálogo original MovieLens 32M**, 87.585 películas importadas tras validar MD5. Incluye campos opcionales TMDB para enriquecimiento posterior.
- `catalog_imports`: prueba de origen y cantidad de filas. Sin esta marca válida, el frontend no muestra supuestos datos del catálogo.
- `app_users`: cuentas de la aplicación con contraseña hasheada y mapeo **uno a uno** a los ID anónimos de MovieLens; el login nunca verifica directamente la identidad de los autores reales de MovieLens.
- `user_interactions`: acciones originales de la aplicación (se preservan aunque se retiren datos simulados).
- `model_versions`, `scoring_runs`, `recommendations`: estado y resultados de inferencia batch, no una ejecución por petición web.

## Esquema y migraciones

Los scripts `schema/001_init.sql`, `002_views.sql`, `003_user_interactions.sql` inicializan nuevos volúmenes PostgreSQL. **No se ejecuta el seed baseline-v0**.

Las bases existentes NO ejecutan init scripts de nuevo. Se utiliza la migración aditiva `migrations/004_cinegraph_accounts_catalog.sql` a través del **bootstrap local manual**:

```bash
docker compose --profile setup run --rm local-setup
```

El bootstrap verifica MD5 y filas, importa películas y crea `cine414`, `cine123`, `cine456` con contraseñas aleatorias que solo se muestran en Terminal. También elimina `baseline-v0` y sus rankings de prueba de la base local, sin borrar `user_interactions`.

**No utilizar `docker compose down -v`**: se perderían datos reales registrados. Los cambios son idempotentes.

## Publicación real de GraphSAGE A9

`POST /api/interactions` usa exclusivamente la cuenta autenticada y guarda el evento en PostgreSQL, seguido de clickstream JSONL. `GET /api/recommendations` devuelve únicamente resultados de `a9-miguel-diario` con scoring exitoso y versión champion. La tabla puede estar vacía hasta una ejecución A9 real.

Después de generar predicciones con `scripts/ml/run_a9_floci.py` en S3 local Floci, se pueden importar manualmente a la base con `a9-publish`, que verifica el manifiesto, checkpoint y scores, sin retocar el modelo.

[Guía completa de login y publicación](../docs/cinegraph-login-real-a9.md).
