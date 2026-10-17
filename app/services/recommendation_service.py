from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.db import get_engine


RECOMMENDATIONS_SQL = text(
    """
    SELECT
        user_id,
        movie_id,
        title,
        release_year,
        genres,
        poster_url,
        rank,
        score,
        model_version,
        cutoff_week,
        generated_at
    FROM latest_recommendations
    WHERE user_id = :user_id
    ORDER BY rank ASC
    LIMIT :limit
    """
)

MODEL_SQL = text(
    """
    SELECT
        model_version,
        model_name,
        status,
        recall_at_k,
        ndcg_at_k,
        mrr
    FROM model_versions
    WHERE model_version = :model_version
    """
)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def get_recommendations(user_id: int, limit: int = 10) -> dict[str, Any] | None:
    with get_engine().connect() as connection:
        rows = connection.execute(
            RECOMMENDATIONS_SQL,
            {"user_id": user_id, "limit": limit},
        ).mappings().all()

        if not rows:
            return None

        model_row = connection.execute(
            MODEL_SQL,
            {"model_version": rows[0]["model_version"]},
        ).mappings().first()

    recommendations = [
        {
            "movie_id": row["movie_id"],
            "title": row["title"],
            "release_year": row["release_year"],
            "genres": list(row["genres"] or []),
            "poster_url": row["poster_url"],
            "rank": row["rank"],
            "score": round(float(row["score"]), 6),
        }
        for row in rows
    ]

    model = None
    if model_row:
        model = {
            "version": model_row["model_version"],
            "name": model_row["model_name"],
            "status": model_row["status"],
            "metrics": {
                "recall_at_k": model_row["recall_at_k"],
                "ndcg_at_k": model_row["ndcg_at_k"],
                "mrr": model_row["mrr"],
            },
        }

    return {
        "user_id": user_id,
        "count": len(recommendations),
        "cutoff_week": _iso(rows[0]["cutoff_week"]),
        "generated_at": _iso(rows[0]["generated_at"]),
        "model": model,
        "recommendations": recommendations,
    }
