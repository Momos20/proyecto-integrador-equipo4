# Features — CineGraph

Implementación actual **local (Floci emula S3)**: el job manual `behavioral-transform` genera `user_movie_daily.jsonl` y `user_daily.jsonl` a partir de eventos Curated válidos y deduplicados. Incluye conteos por tipo de interacción, números de películas distintas, ratings medios y trazabilidad A9, con cortes por día UTC y checksums por versión.

Estos agregados **no son los tensores del GraphSAGE A9 de Miguel** ni modifican sus pesos o ranking. Consulta [la guía de transformación](../../docs/transformacion-behavioral-local.md). Las features del grafo y los jobs de Glue reales quedan para otra fase.
