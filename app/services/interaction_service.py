from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.db import get_engine


INSERT_INTERACTION_SQL = text(
    """
    INSERT INTO user_interactions (
        user_id,
        movie_id,
        interaction_type,
        rating,
        source,
        metadata
    )
    VALUES (
        :user_id,
        :movie_id,
        :interaction_type,
        :rating,
        'cinegraph',
        CAST(:metadata AS JSONB)
    )
    RETURNING
        interaction_id,
        user_id,
        movie_id,
        interaction_type,
        rating,
        source,
        event_at
    """
)

RECENT_INTERACTIONS_SQL = text(
    """
    SELECT
        i.interaction_id,
        i.user_id,
        i.movie_id,
        m.title,
        i.interaction_type,
        i.rating,
        i.source,
        i.event_at
    FROM user_interactions i
    JOIN movies m ON m.movie_id = i.movie_id
    WHERE i.user_id = :user_id
    ORDER BY i.event_at DESC, i.interaction_id DESC
    LIMIT :limit
    """
)


def _serialize(row: Any) -> dict[str, Any]:
    return {
        "interaction_id": row["interaction_id"],
        "user_id": row["user_id"],
        "movie_id": row["movie_id"],
        "title": row.get("title") if hasattr(row, "get") else None,
        "interaction_type": row["interaction_type"],
        "rating": float(row["rating"]) if row["rating"] is not None else None,
        "source": row["source"],
        "event_at": row["event_at"].isoformat(),
    }


def create_interaction(
    *,
    user_id: int,
    movie_id: int,
    interaction_type: str,
    rating: float | None = None,
    metadata: str = "{}",
) -> dict[str, Any]:
    with get_engine().begin() as connection:
        row = connection.execute(
            INSERT_INTERACTION_SQL,
            {
                "user_id": user_id,
                "movie_id": movie_id,
                "interaction_type": interaction_type,
                "rating": rating,
                "metadata": metadata,
            },
        ).mappings().one()

    return _serialize(row)


def get_recent_interactions(user_id: int, limit: int = 20) -> list[dict[str, Any]]:
    with get_engine().connect() as connection:
        rows = connection.execute(
            RECENT_INTERACTIONS_SQL,
            {"user_id": user_id, "limit": limit},
        ).mappings().all()

    return [_serialize(row) for row in rows]
