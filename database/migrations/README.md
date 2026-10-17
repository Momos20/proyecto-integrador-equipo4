# Migrations

A partir del esquema inicial, cada cambio estructural a PostgreSQL debe agregarse como una migración incremental y no modificarse retroactivamente en producción.

Convención sugerida:

`YYYYMMDD_HHMM_descripcion.sql`

Ejemplo:

`20261020_2100_add_recommendation_source.sql`

Durante la fase MVP, `database/schema/001_init.sql` representa la línea base de una instalación nueva.
