# CineGraph behavioral event schema

Los eventos de comportamiento se escriben como JSON Lines (`.jsonl`), una línea por evento.

## Esquema v1

```json
{
  "schema_version": 1,
  "event_id": "uuid",
  "event_type": "like|dislike|rating|watchlist|view_details",
  "event_source": "http",
  "event_at": "2026-10-17T15:36:33.657157+00:00",
  "request_id": "uuid-or-header",
  "user_id": 414,
  "movie_id": 2959,
  "rating": 4.5,
  "recommendation_id": "414:2026-10-12:2",
  "model_version": "baseline-v0",
  "position": 2,
  "cutoff_date": "2026-10-12",
  "metadata": {
    "surface": "top10"
  }
}
```

## Semántica

- `event_id`: idempotencia y deduplicación en Curated.
- `event_at`: tiempo del evento; debe usarse para la lógica temporal, no el tiempo de ejecución de Glue.
- `user_id`, `movie_id`: permiten integrar behavioral con MovieLens/catálogo.
- `recommendation_id`, `model_version`, `position`: trazabilidad de la recomendación que originó el feedback.
- `rating`: solo aplica cuando `event_type=rating`.
- `cutoff_date`: snapshot/ranking que estaba visible cuando ocurrió el feedback.

## Reglas Curated propuestas

1. Parsear JSON y validar `schema_version`.
2. Rechazar eventos sin `event_id`, `event_type`, `event_at`, `user_id` o `movie_id`.
3. Deduplicar por `event_id`.
4. Validar rating en `[0.5, 5.0]` para eventos `rating`.
5. Particionar salida por `event_date=YYYY-MM-DD` derivado de `event_at`.
6. Enviar inválidos a cuarentena y generar reporte de calidad.

## Relación con PostgreSQL

`user_interactions` es la persistencia operacional de la aplicación. El clickstream es la representación append-only para DataOps/ML. Ambos nacen de la misma interacción, pero tienen responsabilidades diferentes.
