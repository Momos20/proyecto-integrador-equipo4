#!/usr/bin/env python3
"""Bootstrap EXCLUSIVAMENTE LOCAL: catálogo MovieLens verificado + cuentas de prueba.

Usar manualmente con: docker compose --profile setup run --rm local-setup
Mantiene los eventos reales ya registrados en PostgreSQL. No inventa rankings.
"""
from __future__ import annotations
import csv
import hashlib
import io
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import text
from werkzeug.security import generate_password_hash

from app.db import get_engine, _database_url

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "data" / "reference" / "movielens32m"
MIGRATION = ROOT / "database" / "migrations" / "004_cinegraph_accounts_catalog.sql"
MOVIES_MD5 = "0df90835c19151f9d819d0822e190797"
EXPECTED_ROWS = 87585
TEST_USERS = (("cine414", 414), ("cine123", 123), ("cine456", 456))


def check_local_db():
    url = urlsplit(_database_url())
    if url.hostname not in {"db", "localhost", "127.0.0.1"} or os.getenv("CINEGRAPH_LOCAL_SETUP") != "1":
        raise RuntimeError("SEGURIDAD: bootstrap solo para PostgreSQL LOCAL con CINEGRAPH_LOCAL_SETUP=1")


def read_movies():
    pieces = [(REFERENCE / "parts" / f"movies.part{i:02d}.csv").read_bytes() for i in (1, 2, 3)]
    raw = b"".join(pieces)
    checksum = hashlib.md5(raw).hexdigest()
    if checksum != MOVIES_MD5:
        raise RuntimeError("El catálogo MovieLens no coincide con el checksum original; no se importa")
    values = []
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8"), newline=""))
    for row in reader:
        title = row["title"]
        m = re.search(r"\((\d{4})\)$", title)
        year = int(m.group(1)) if m else None
        genres = [] if row["genres"] == "(no genres listed)" else row["genres"].split("|")
        values.append((int(row["movieId"]), title, year, genres))
    if len(values) != EXPECTED_ROWS:
        raise RuntimeError(f"Se esperaban {EXPECTED_ROWS} películas y llegaron {len(values)}")
    return values


def migrate(conn):
    # Split by ';' is safe for the controlled migration file: no procedural SQL.
    sql = "\n".join(line for line in MIGRATION.read_text(encoding="utf-8").splitlines() if not line.strip().startswith("--"))
    for statement in sql.split(";"):
        statement = statement.strip()
        if not statement or statement.upper() in {"BEGIN", "COMMIT"}:
            continue
        conn.exec_driver_sql(statement)


def main():
    check_local_db()
    movies = read_movies()
    engine = get_engine()
    credentials = []
    with engine.begin() as conn:
        migrate(conn)
        raw_connection = conn.connection.driver_connection
        with raw_connection.cursor() as cur:
            cur.execute("CREATE TEMP TABLE _incoming_movies(movie_id bigint, title text, release_year smallint, genres text[]) ON COMMIT DROP")
            with cur.copy("COPY _incoming_movies (movie_id, title, release_year, genres) FROM STDIN") as writer:
                for movie in movies:
                    writer.write_row(movie)
            cur.execute("""
                INSERT INTO movies (movie_id, title, release_year, genres)
                SELECT movie_id,title,release_year,genres FROM _incoming_movies
                ON CONFLICT(movie_id) DO UPDATE SET
                  title=EXCLUDED.title, release_year=EXCLUDED.release_year,
                  genres=EXCLUDED.genres,updated_at=NOW()
            """)
        conn.execute(text("""
            INSERT INTO catalog_imports(dataset_name,movies_md5,verified_rows)
            VALUES ('movielens32m',:checksum,:rows)
            ON CONFLICT (dataset_name) DO UPDATE SET
              movies_md5=EXCLUDED.movies_md5,verified_rows=EXCLUDED.verified_rows,loaded_at=NOW()
        """), {"checksum": MOVIES_MD5, "rows": EXPECTED_ROWS})
        # Eliminamos solo las recomendaciones de prueba; las interacciones reales se conservan.
        conn.execute(text("DELETE FROM recommendations WHERE model_version='baseline-v0'"))
        conn.execute(text("DELETE FROM scoring_runs WHERE model_version='baseline-v0'"))
        conn.execute(text("DELETE FROM model_versions WHERE model_version='baseline-v0'"))
        for username, user_id in TEST_USERS:
            exists = conn.execute(text("SELECT 1 FROM app_users WHERE username=:u"), {"u":username}).scalar()
            if exists:
                continue
            password = secrets.token_urlsafe(14)
            conn.execute(text("""
              INSERT INTO app_users(username,password_hash,movielens_user_id)
              VALUES(:username,:pw,:movie_user)
            """), {"username":username, "pw":generate_password_hash(password), "movie_user":user_id})
            credentials.append((username, password, user_id))
    print(f"OK: {EXPECTED_ROWS:,} películas reales MovieLens 32M importadas y verificadas")
    print("OK: se descartó baseline-v0 del servicio sin borrar las interacciones existentes")
    if credentials:
        print("\nCUENTAS LOCALES CREADAS (GUARDA ESTAS CONTRASEÑAS; NO SE VUELVEN A MOSTRAR):")
        for username, password, user_id in credentials:
            print(f"  {username} | contraseña: {password} | MovieLens userId: {user_id}")
    else:
        print("Cuentas existentes conservadas: cine414, cine123, cine456.")
        print("Para recuperar una contraseña, utilizar el restablecimiento manual documentado.")
    print("La aplicación solo mostrará predicciones A9 cuando se ejecuten y publiquen; no se generaron Top-K ficticios.")


if __name__ == "__main__":
    main()
