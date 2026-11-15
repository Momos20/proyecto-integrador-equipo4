"""Catálogo exclusivamente de MovieLens 32M, importado tras verificar checksum."""
from __future__ import annotations

from sqlalchemy import text
from app.db import get_engine

OFFICIAL_MOVIES_MD5 = "0df90835c19151f9d819d0822e190797"
CATALOG_SQL = text("""
SELECT movie_id, title, release_year, genres, poster_url
FROM movies
WHERE (:genre IS NULL OR :genre = ANY(genres))
  AND (:search IS NULL OR title ILIKE ('%' || :search || '%'))
ORDER BY release_year DESC NULLS LAST, movie_id DESC
LIMIT :limit OFFSET :offset
""")
READY_SQL = text("""
SELECT verified_rows FROM catalog_imports
WHERE dataset_name = 'movielens32m' AND movies_md5 = :checksum
""")


def get_catalog(*, limit=24, offset=0, genre=None, search=None):
    with get_engine().connect() as conn:
        row = conn.execute(READY_SQL, {"checksum": OFFICIAL_MOVIES_MD5}).mappings().first()
        if not row or int(row["verified_rows"]) != 87585:
            return {"ready": False, "source": "MovieLens 32M", "movies": [], "count": 0}
        movies = conn.execute(CATALOG_SQL, {"limit": limit, "offset": offset, "genre": genre, "search": search}).mappings().all()
    return {"ready": True, "source": "MovieLens 32M", "count": len(movies), "movies": [
        {"movie_id": r["movie_id"], "title": r["title"], "release_year": r["release_year"],
         "genres": list(r["genres"] or []), "poster_url": r["poster_url"]}
        for r in movies
    ]}
