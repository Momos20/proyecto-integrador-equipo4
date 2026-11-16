"""Solo rankings persistidos tras una inferencia A9 real y publicada.

La tabla baseline-v0 histórica no se consulta ni se presenta como una predicción.
"""
from __future__ import annotations
from typing import Any
from sqlalchemy import text
from app.db import get_engine
from app.services.catalog_service import KNOWN_TMDB_POSTERS

A9_VERSION = "a9-miguel-diario"
RECOMMENDATIONS_SQL = text("""
SELECT r.user_id, r.movie_id, m.title, m.release_year, m.genres, m.poster_url,
       r.rank, r.score, r.model_version, r.cutoff_week, r.generated_at
FROM recommendations r
JOIN movies m ON m.movie_id = r.movie_id
JOIN model_versions mv ON mv.model_version = r.model_version
JOIN scoring_runs sr ON sr.scoring_run_id = r.scoring_run_id
WHERE r.user_id = :user_id
  AND r.model_version = :model_version
  AND mv.status = 'champion'
  AND sr.status = 'succeeded'
  AND r.cutoff_week = (
    SELECT MAX(r2.cutoff_week)
    FROM recommendations r2
    JOIN scoring_runs sr2 ON sr2.scoring_run_id = r2.scoring_run_id
    WHERE r2.user_id = :user_id AND r2.model_version = :model_version
      AND sr2.status = 'succeeded'
  )
ORDER BY r.rank ASC
LIMIT :limit
""")


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def get_recommendations(user_id: int, limit: int = 10) -> dict[str, Any] | None:
    with get_engine().connect() as connection:
        rows = connection.execute(RECOMMENDATIONS_SQL, {
            "user_id": user_id, "limit": limit, "model_version": A9_VERSION
        }).mappings().all()
    if not rows:
        return None
    return {
        "user_id": user_id,
        "count": len(rows),
        "cutoff_date": _iso(rows[0]["cutoff_week"]),
        "generated_at": _iso(rows[0]["generated_at"]),
        "model": {"version": A9_VERSION, "name": "GraphSAGE A9 de Miguel", "protocolo": "diario UTC"},
        "recommendations": [{
            "movie_id": row["movie_id"], "title": row["title"],
            "release_year": row["release_year"], "genres": list(row["genres"] or []),
            "poster_url": row["poster_url"] or KNOWN_TMDB_POSTERS.get(int(row["movie_id"])),
            "rank": row["rank"],
            "score": round(float(row["score"]), 6),
        } for row in rows],
    }
