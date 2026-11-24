#!/usr/bin/env python3
"""Bootstrap exclusivo para RDS de CineGraph E4, sin secretos en consola.

Ejecutar desde EC2 en contenedor efimero con IAM instance profile (LabRole):
  python /workspace/infrastructure/aws/scripts/03-bootstrap-rds.py --plan
  CONFIRM_RDS_IMPORT=YES ... --apply
No usar este script contra la base local ni con una clave en DATABASE_URL.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[3]
MOVIE_PARTS = tuple(
    ROOT / "data" / "reference" / "movielens32m" / "parts" / f"movies.part{i:02d}.csv"
    for i in (1, 2, 3)
)
MOVIES_MD5 = "0df90835c19151f9d819d0822e190797"
EXPECTED_ROWS = 87585
RDS_CA_BUNDLE = "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"
SCHEMA_FILES = (
    "database/schema/001_init.sql",
    "database/schema/002_views.sql",
    "database/schema/003_user_interactions.sql",
    "database/migrations/004_cinegraph_accounts_catalog.sql",
    "database/migrations/005_watchlist_remove.sql",
)


class BootstrapError(Exception):
    """Validacion bloqueante sin revelar secretos."""


def load_movies() -> list[tuple[int, str, int | None, list[str]]]:
    raw = b"".join(part.read_bytes() for part in MOVIE_PARTS)
    if hashlib.md5(raw).hexdigest() != MOVIES_MD5:
        raise BootstrapError("MOVIELENS_MD5_INVALID")
    data: list[tuple[int, str, int | None, list[str]]] = []
    seen: set[int] = set()
    for row in csv.DictReader(io.StringIO(raw.decode("utf-8"), newline="")):
        movie_id = int(row["movieId"])
        if movie_id in seen:
            raise BootstrapError("MOVIELENS_DUPLICATE_MOVIE_ID")
        seen.add(movie_id)
        title = row["title"]
        matched = re.search(r"\((\d{4})\)$", title)
        year = int(matched.group(1)) if matched else None
        genres = [] if row["genres"] == "(no genres listed)" else row["genres"].split("|")
        data.append((movie_id, title, year, genres))
    if len(data) != EXPECTED_ROWS:
        raise BootstrapError("MOVIELENS_ROW_COUNT_INVALID")
    print(f"SOURCE_OK: md5={MOVIES_MD5}, movies={len(data)}")
    return data


def sql_statements(relative_path: str) -> list[str]:
    # Los cinco SQL son fuente controlada, sin bloques procedurales o ; en literales.
    content = (ROOT / relative_path).read_text(encoding="utf-8")
    without_comments = "\n".join(
        line for line in content.splitlines() if not line.lstrip().startswith("--")
    )
    return [
        statement
        for part in without_comments.split(";")
        if (statement := part.strip()) and statement.upper() not in {"BEGIN", "COMMIT"}
    ]


def check_settings() -> tuple[str, str, str]:
    region = os.environ["AWS_REGION"]
    host = os.environ["RDS_ENDPOINT"].strip()
    secret_arn = os.environ["RDS_SECRET_ARN"].strip()
    if not (region == "us-east-1" and host.startswith("cinegraph-e4-postgres.")
            and host.endswith(".us-east-1.rds.amazonaws.com")):
        raise BootstrapError("RDS_ENDPOINT_NOT_APPROVED")
    if not secret_arn.startswith("arn:aws:secretsmanager:us-east-1:"):
        raise BootstrapError("RDS_SECRET_ARN_NOT_APPROVED")
    if os.environ.get("DATABASE_URL") or os.environ.get("DB_PASSWORD"):
        raise BootstrapError("DATABASE_PASSWORD_ENV_NOT_ALLOWED")
    return region, host, secret_arn


def master_credentials(region: str, secret_arn: str) -> tuple[str, str]:
    import boto3

    response = boto3.client("secretsmanager", region_name=region).get_secret_value(
        SecretId=secret_arn
    )
    raw = json.loads(response["SecretString"])
    if raw.get("username") != "cinegraphadmin" or not isinstance(raw.get("password"), str):
        raise BootstrapError("RDS_SECRET_FORMAT_UNEXPECTED")
    if not raw["password"]:
        raise BootstrapError("RDS_SECRET_PASSWORD_MISSING")
    return raw["username"], raw["password"]


def get_ca_bundle(directory: str) -> str:
    certificate = Path(directory) / "global-rds-ca.pem"
    with urlopen(RDS_CA_BUNDLE, timeout=30) as response:
        content = response.read(1024 * 1024)
    if b"-----BEGIN CERTIFICATE-----" not in content:
        raise BootstrapError("RDS_CA_BUNDLE_INVALID")
    certificate.write_bytes(content)
    certificate.chmod(0o600)
    return str(certificate)


def assert_server(conn) -> None:
    version = int(conn.execute("SHOW server_version_num").fetchone()[0])
    if version // 10000 != 16:
        raise BootstrapError("RDS_POSTGRES_VERSION_NOT_16")
    ssl_active = conn.execute(
        "SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()"
    ).fetchone()[0]
    if not ssl_active:
        raise BootstrapError("RDS_TLS_NOT_ACTIVE")
    print("RDS_CONNECTION_OK: PostgreSQL 16, TLS verify-full")


def plan(conn) -> None:
    with conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        movies_exists = conn.execute("SELECT to_regclass('public.movies')").fetchone()[0]
        imports_exists = conn.execute(
            "SELECT to_regclass('public.catalog_imports')"
        ).fetchone()[0]
        count = conn.execute("SELECT count(*) FROM movies").fetchone()[0] if movies_exists else 0
        imports = (
            conn.execute(
                "SELECT verified_rows FROM catalog_imports WHERE dataset_name = 'movielens32m'"
            ).fetchone() if imports_exists else None
        )
        print("PLAN_OK: sin escrituras a RDS")
        print(f"SCHEMA_MOVIES_EXISTS={bool(movies_exists)}")
        print(f"RDS_MOVIES_CURRENT={count}")
        print(f"CATALOG_REGISTRY_ROWS={imports[0] if imports else 0}")
        print(f"TARGET_IMPORT_ROWS={EXPECTED_ROWS}")


def apply(conn, movies: list[tuple[int, str, int | None, list[str]]]) -> None:
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(20261123, 4)")
        for relative_path in SCHEMA_FILES:
            for statement in sql_statements(relative_path):
                conn.execute(statement)
        print("SCHEMA_SQL_APPLIED")
        conn.execute(
            """CREATE TEMP TABLE _cinegraph_incoming_movies(
                 movie_id bigint, title text, release_year smallint, genres text[]
               ) ON COMMIT DROP"""
        )
        with conn.cursor() as cursor:
            with cursor.copy(
                "COPY _cinegraph_incoming_movies (movie_id,title,release_year,genres) FROM STDIN"
            ) as writer:
                for movie in movies:
                    writer.write_row(movie)
        imported = conn.execute(
            "SELECT count(*) FROM _cinegraph_incoming_movies"
        ).fetchone()[0]
        if imported != EXPECTED_ROWS:
            raise BootstrapError("RDS_STAGING_ROW_COUNT_INVALID")
        conn.execute(
            """INSERT INTO movies (movie_id,title,release_year,genres)
               SELECT movie_id,title,release_year,genres FROM _cinegraph_incoming_movies
               ON CONFLICT (movie_id) DO UPDATE SET
                 title = EXCLUDED.title,
                 release_year = EXCLUDED.release_year,
                 genres = EXCLUDED.genres,
                 updated_at = NOW()
               WHERE movies.title IS DISTINCT FROM EXCLUDED.title
                  OR movies.release_year IS DISTINCT FROM EXCLUDED.release_year
                  OR movies.genres IS DISTINCT FROM EXCLUDED.genres"""
        )
        conn.execute(
            """INSERT INTO catalog_imports(dataset_name,movies_md5,verified_rows)
               VALUES ('movielens32m',%s,%s)
               ON CONFLICT (dataset_name) DO UPDATE SET
                 movies_md5=EXCLUDED.movies_md5,
                 verified_rows=EXCLUDED.verified_rows,
                 loaded_at=NOW()""",
            (MOVIES_MD5, EXPECTED_ROWS),
        )
        persisted = conn.execute("SELECT count(*) FROM movies").fetchone()[0]
        if persisted != EXPECTED_ROWS:
            raise BootstrapError("RDS_TOTAL_MOVIES_UNEXPECTED_NO_ROWS_REMOVED")
        registry = conn.execute(
            "SELECT movies_md5, verified_rows FROM catalog_imports WHERE dataset_name='movielens32m'"
        ).fetchone()
        if registry != (MOVIES_MD5, EXPECTED_ROWS):
            raise BootstrapError("RDS_CATALOG_REGISTRY_INVALID")
        print("RDS_APPLY_OK: esquema y 87585 peliculas verificadas, transaccion confirmada al salir")
    print("RDS_COMMIT_OK: 87585 peliculas; sin cuentas ficticias ni predicciones artificiales")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CineGraph RDS seguro")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="Solo lectura")
    mode.add_argument("--apply", action="store_true", help="Escribir schema y catalogo")
    args = parser.parse_args(argv)
    try:
        if args.apply and os.environ.get("CONFIRM_RDS_IMPORT") != "YES":
            raise BootstrapError("CONFIRM_RDS_IMPORT_REQUIRED")
        region, host, arn = check_settings()
        movies = load_movies()
        user, password = master_credentials(region, arn)
        import psycopg

        with tempfile.TemporaryDirectory(prefix="cinegraph-rds-ca-") as ca_dir:
            ca_file = get_ca_bundle(ca_dir)
            with psycopg.connect(
                host=host, port=5432, dbname="cinegraph", user=user,
                password=password, sslmode="verify-full", sslrootcert=ca_file,
                connect_timeout=10, autocommit=True,
                application_name="cinegraph-e4-bootstrap",
            ) as conn:
                assert_server(conn)
                if args.plan:
                    plan(conn)
                else:
                    apply(conn, movies)
        return 0
    except Exception as exc:
        # Nunca mostrar tracebacks/DSN/SecretString: errores detallados pueden
        # revelar credenciales o metadatos sensibles en los logs de SSM.
        if isinstance(exc, BootstrapError):
            print(f"BOOTSTRAP_ERROR: {exc}", file=sys.stderr)
        else:
            print(f"BOOTSTRAP_FAILED: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
