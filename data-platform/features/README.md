# Features — CineGraph

Implementación actual **local (Floci emula S3)**: el job manual `behavioral-transform` genera `user_movie_daily.jsonl` y `user_daily.jsonl` a partir de eventos Curated válidos y deduplicados. Incluye conteos por tipo de interacción, números de películas distintas, ratings medios y trazabilidad A9, con cortes por día UTC y checksums por versión.

Estos agregados **no son los tensores del GraphSAGE A9 de Miguel** ni modifican sus pesos o ranking. Consulta [la guía de transformación](../../docs/transformacion-behavioral-local.md). Las features del grafo y los jobs de Glue reales quedan para otra fase.


## Feedback para inferencia futura (shadow)

`a9-feedback-stage` guarda bajo `features/behavioral/cinegraph/a9-shadow/` un snapshot con ratings explícitos estrictamente anteriores al cutoff UTC, las features contextuales filtradas y manifiesto SHA-256. Los usuarios locales están separados por el namespace `cinegraph-local` y el ensayo manual `run_a9_shadow.py` les asigna IDs nuevos sin colisión con MovieLens. Ni los likes ni watchlist se convierten en ratings. [Guía](../../docs/orquestacion-y-shadow-local.md).
