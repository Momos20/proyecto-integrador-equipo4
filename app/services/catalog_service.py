"""Catálogo exclusivamente de MovieLens 32M, importado tras verificar checksum.

Los parámetros opcionales usan CAST explícito porque psycopg/PostgreSQL no puede
inferir el tipo de ``:genre IS NULL`` o ``:search IS NULL`` cuando llegan como None.
"""
from __future__ import annotations

from sqlalchemy import text
from app.db import get_engine

OFFICIAL_MOVIES_MD5 = "0df90835c19151f9d819d0822e190797"
# Pósteres TMDB correspondientes a 10 movieId auténticos de MovieLens 32M.
# Son metadatos visuales, NO puntuaciones ni recomendaciones de A9.
KNOWN_TMDB_POSTERS = {
    2571: "https://image.tmdb.org/t/p/w500/f89U3ADr1oiB1s9GkdPOEpXUk5H.jpg",
    2959: "https://image.tmdb.org/t/p/w500/pB8BM7pdSp6B6Ih7QZ4DrQ3PmJK.jpg",
    4993: "https://image.tmdb.org/t/p/w500/6oom5QYQ2yQTMJIbnvbkBL9cHo6.jpg",
    5952: "https://image.tmdb.org/t/p/w500/5VTN0pR8gcqV3EPUHHfMGnJYN9L.jpg",
    7153: "https://image.tmdb.org/t/p/w500/rCzpDGLbOoPwLjy3OAm5NUPOTrC.jpg",
    79132: "https://image.tmdb.org/t/p/w500/oYuLEt3zVCKq57qu2F8dT7NIa6f.jpg",
    58559: "https://image.tmdb.org/t/p/w500/qJ2tW6WMUDux911r6m7haRef0WH.jpg",
    318: "https://image.tmdb.org/t/p/w500/q6y0Go1tsGEsmtFryDOJo3dEmqu.jpg",
    356: "https://image.tmdb.org/t/p/w500/arw2vcBveWOVZr6pxd9XTd1TdQa.jpg",
    296: "https://image.tmdb.org/t/p/w500/d5iIlFn5s0ImszYzBPb8JPIfbXD.jpg",
    # Cuatro películas que aparecen en el Top-10 real de cine123 (corte 2023-06-15).
    # Rutas identificadas públicamente para las obras indicadas, sin inferir imágenes.
    109487: "https://image.tmdb.org/t/p/w500/gEU2QniE6E77NI6lCU6MxlNBvIx.jpg",  # Interstellar (2014)
    50872: "https://image.tmdb.org/t/p/w500/a7hjVvftDqdgqZidGyoDkpXWjtK.jpg",   # Ratatouille (2007)
    68954: "https://image.tmdb.org/t/p/w500/c9QLSX3qEW8FO7UgT2pyfC1LDzb.jpg",   # Up (2009)
    134130: "https://image.tmdb.org/t/p/w500/3ndAx3weG6KDkJIRMCi5vXX6Dyb.jpg", # The Martian (2015)
}
KNOWN_POSTER_IDS = sorted(KNOWN_TMDB_POSTERS)

CATALOG_SQL = text("""
SELECT movie_id, title, release_year, genres, poster_url
FROM movies
WHERE (CAST(:genre AS TEXT) IS NULL OR CAST(:genre AS TEXT) = ANY(genres))
  AND (CAST(:search AS TEXT) IS NULL OR title ILIKE ('%' || CAST(:search AS TEXT) || '%'))
ORDER BY CASE WHEN poster_url IS NOT NULL OR movie_id = ANY(CAST(:poster_ids AS BIGINT[])) THEN 0 ELSE 1 END,
  release_year DESC NULLS LAST, movie_id DESC
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
        movies = conn.execute(CATALOG_SQL, {"limit": limit, "offset": offset, "genre": genre, "search": search, "poster_ids": KNOWN_POSTER_IDS}).mappings().all()
    return {"ready": True, "source": "MovieLens 32M", "count": len(movies), "movies": [
        {"movie_id": r["movie_id"], "title": r["title"], "release_year": r["release_year"],
         "genres": list(r["genres"] or []),
         "poster_url": r["poster_url"] or KNOWN_TMDB_POSTERS.get(int(r["movie_id"]))}
        for r in movies
    ]}
