#!/usr/bin/env python3
"""Enriquece pósteres reales de MovieLens con TMDB, sólo en PostgreSQL local.

No inventa recomendaciones, no usa AWS y no altera GraphSAGE A9. Cada movieId
se vincula con su tmdbId oficial de links.csv (checksum MD5 verificado).

Ejecutar: docker compose --profile setup run --rm poster-enrich
Requiere TMDB_READ_TOKEN o TMDB_API_KEY en el entorno (no en Git).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
import json

from sqlalchemy import text
from app.db import get_engine, _database_url

ROOT = Path(__file__).resolve().parents[2]
LINKS = ROOT / "data/reference/movielens32m/links.csv"
LINKS_MD5 = "8f033867bcb4e6be8792b21468b4fa6e"
POSTER_RE = re.compile(r"^/[A-Za-z0-9_-]{12,}\.(?:jpg|jpeg|png|webp)$", re.I)
GENRES = (None, "Action", "Sci-Fi", "Drama", "Comedy")


def require_local_database() -> None:
    """No permitir ejecuciones en RDS ni bases de datos no locales."""
    db = urlsplit(_database_url())
    if os.getenv("CINEGRAPH_LOCAL_SETUP") != "1" or db.hostname not in {"db", "localhost", "127.0.0.1"}:
        raise RuntimeError("Sólo PostgreSQL local con CINEGRAPH_LOCAL_SETUP=1")


def load_movie_tmdb_links() -> dict[int, int]:
    content = LINKS.read_bytes()
    if hashlib.md5(content).hexdigest() != LINKS_MD5:
        raise RuntimeError("links.csv no coincide con el checksum MD5 de MovieLens 32M")
    links = {}
    for row in csv.DictReader(content.decode("utf-8-sig").splitlines()):
        movie, tmdb = row["movieId"], row.get("tmdbId", "")
        if movie.isdigit() and tmdb and tmdb.isdigit():
            links[int(movie)] = int(tmdb)
    return links


def fetch_poster(tmdb_id: int, *, bearer: str, api_key: str) -> str | None:
    endpoint = f"https://api.themoviedb.org/3/movie/{tmdb_id}"
    if bearer:
        req = urllib.request.Request(
            endpoint + "?language=es-ES",
            headers={"Authorization": "Bearer " + bearer, "Accept": "application/json", "User-Agent": "CineGraph-Academic-Local/1.0"},
        )
    else:
        params = urllib.parse.urlencode({"language": "es-ES", "api_key": api_key})
        req = urllib.request.Request(
            endpoint + "?" + params,
            headers={"Accept": "application/json", "User-Agent": "CineGraph-Academic-Local/1.0"},
        )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
                payload = json.load(res)
            poster_path = payload.get("poster_path")
            if not isinstance(poster_path, str) or not POSTER_RE.fullmatch(poster_path):
                return None
            return "https://image.tmdb.org/t/p/w500" + poster_path
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410):
                return None
            if exc.code in (401, 403):
                raise RuntimeError("TMDB rechazó la credencial: revisa TMDB_READ_TOKEN o TMDB_API_KEY") from None
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise RuntimeError(f"TMDB devolvió HTTP {exc.code} para la película {tmdb_id}") from exc
            wait = min(10, max(1, int(exc.headers.get("Retry-After", "2"))))
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == 2:
                raise RuntimeError(f"Sin conexión con TMDB para película {tmdb_id}") from exc
            time.sleep(2)
    return None


def choose_movie_ids(conn, limit: int) -> list[int]:
    """Primero cubrir exactamente las estanterías que se muestran en CineGraph."""
    candidates: list[int] = []
    seen: set[int] = set()
    per_genre = max(20, min(45, limit // len(GENRES) + 6))
    for genre in GENRES:
        rows = conn.execute(text("""
            SELECT movie_id FROM movies
            WHERE poster_url IS NULL OR poster_url = ''
            ORDER BY release_year DESC NULLS LAST, movie_id DESC
            LIMIT :limit
        """), {"limit": per_genre}) if genre is None else conn.execute(text("""
            SELECT movie_id FROM movies
            WHERE (:genre = ANY(genres)) AND (poster_url IS NULL OR poster_url = '')
            ORDER BY release_year DESC NULLS LAST, movie_id DESC
            LIMIT :limit
        """), {"genre": genre, "limit": per_genre})
        # Python entra sólo en la primera rama cuando genre=None.
        for row in rows:
            movie_id = int(row.movie_id)
            if movie_id not in seen:
                seen.add(movie_id)
                candidates.append(movie_id)
                if len(candidates) >= limit:
                    return candidates
    return candidates


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=120, help="Máximo de películas nuevas a consultar (1-500)")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 500:
        parser.error("--limit debe estar entre 1 y 500")
    require_local_database()
    bearer = os.getenv("TMDB_READ_TOKEN", "").strip()
    api_key = os.getenv("TMDB_API_KEY", "").strip()
    if not bearer and not api_key:
        raise SystemExit("Falta TMDB_READ_TOKEN o TMDB_API_KEY. Consulta docs/posters-tmdb-local.md; nunca guardes la clave en GitHub.")
    links = load_movie_tmdb_links()
    engine = get_engine()
    with engine.connect() as conn:
        movie_ids = choose_movie_ids(conn, args.limit)
    matched = 0
    absent = 0
    for index, movie_id in enumerate(movie_ids, start=1):
        tmdb_id = links.get(movie_id)
        if tmdb_id is None:
            absent += 1
            continue
        try:
            poster_url = fetch_poster(tmdb_id, bearer=bearer, api_key=api_key)
        except RuntimeError as exc:
            print(f"Aviso: {exc}", flush=True)
            if "credencial" in str(exc):
                raise
            continue
        if poster_url:
            with engine.begin() as conn:
                conn.execute(text("""
                    UPDATE movies SET poster_url=:poster_url, updated_at=NOW()
                    WHERE movie_id=:movie_id AND (poster_url IS NULL OR poster_url='')
                """), {"movie_id": movie_id, "poster_url": poster_url})
            matched += 1
        else:
            absent += 1
        if index % 20 == 0:
            print(f"Procesadas {index}/{len(movie_ids)} · pósteres guardados {matched}", flush=True)
        time.sleep(0.3)
    print(f"TERMINADO: {matched} pósteres auténticos TMDB guardados; {absent} sin póster disponible.")
    print("La cobertura crece al repetir la ejecución. Ninguna recomendación ni checkpoint A9 fue modificado.")


if __name__ == "__main__":
    main()