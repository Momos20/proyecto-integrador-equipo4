from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.db import get_engine
from app.services.catalog_service import KNOWN_TMDB_POSTERS


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


# Leer todo el historial relevante del usuario, no solamente sus últimas 100 interacciones.
# Orden de desempate por interaction_id: add -> remove -> add produce el estado correcto.
WATCHLIST_SQL = text(
    """
    WITH last_action AS (
        SELECT i.movie_id, i.interaction_type, i.event_at, i.interaction_id,
               ROW_NUMBER() OVER (
                   PARTITION BY i.movie_id
                   ORDER BY i.event_at DESC, i.interaction_id DESC
               ) AS rn
        FROM user_interactions i
        WHERE i.user_id = :user_id
          AND i.interaction_type IN ('watchlist', 'watchlist_remove')
    )
    SELECT m.movie_id, m.title, m.release_year, m.genres, m.poster_url
    FROM last_action l
    JOIN movies m ON m.movie_id = l.movie_id
    WHERE l.rn = 1 AND l.interaction_type = 'watchlist'
    ORDER BY l.event_at DESC, l.interaction_id DESC
    LIMIT :limit
    """
)


def get_watchlist(user_id: int, limit: int = 500) -> list[dict[str, Any]]:
    """Último estado de cada película guardada, filtrado por la cuenta autenticada."""
    with get_engine().connect() as connection:
        rows = connection.execute(
            WATCHLIST_SQL, {"user_id": user_id, "limit": limit}
        ).mappings().all()
    return [
        {
            "movie_id": row["movie_id"],
            "title": row["title"],
            "release_year": row["release_year"],
            "genres": list(row["genres"] or []),
            "poster_url": row["poster_url"] or KNOWN_TMDB_POSTERS.get(int(row["movie_id"])),
        }
        for row in rows
    ]
