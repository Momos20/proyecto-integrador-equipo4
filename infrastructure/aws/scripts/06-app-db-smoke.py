#!/usr/bin/env python3
"""Prueba de solo lectura: contenedor aislado -> Secrets Manager -> RDS como cinegraph_app.

No usa la contraseña maestra ni imprime credenciales. Requiere AWS IAM role
por metadatos de EC2 (IMDSv2 con hop limit 2).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

APP_SECRET_ID = "cinegraph-e4-app-db"
EXPECTED_ACCOUNTS = {"cine414": 414, "cine123": 123, "cine456": 456}
EXPECTED_MD5 = "0df90835c19151f9d819d0822e190797"


def rds_ca():
    bootstrap_path = Path(__file__).with_name("03-bootstrap-rds.py")
    spec = importlib.util.spec_from_file_location("cinegraph_e4_bootstrap", bootstrap_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("RDS_BOOTSTRAP_MISSING")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.get_ca_bundle


def read_app_secret(region: str, host: str) -> dict:
    import boto3

    data = boto3.client("secretsmanager", region_name=region).get_secret_value(
        SecretId=APP_SECRET_ID
    )
    secret = json.loads(data["SecretString"])
    if not isinstance(secret, dict):
        raise RuntimeError("APP_SECRET_NOT_OBJECT")
    if (
        secret.get("host") != host
        or secret.get("username") != "cinegraph_app"
        or secret.get("dbname") != "cinegraph"
        or secret.get("port") != 5432
        or not isinstance(secret.get("password"), str)
        or len(secret["password"]) < 32
    ):
        raise RuntimeError("APP_SECRET_FORMAT_INCORRECT")
    return secret


def audit_connection(conn) -> None:
    with conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        actual_role = conn.execute("SELECT current_user").fetchone()[0]
        if actual_role != "cinegraph_app":
            raise RuntimeError("UNEXPECTED_DB_ROLE")
        tls = conn.execute(
            "SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()"
        ).fetchone()[0]
        if not tls:
            raise RuntimeError("TLS_REQUIRED")
        print("APP_DATABASE_ROLE_OK")
        print("APP_DATABASE_TLS_OK")

        count = conn.execute("SELECT count(*) FROM public.movies").fetchone()[0]
        registry = conn.execute(
            "SELECT movies_md5, verified_rows FROM public.catalog_imports "
            "WHERE dataset_name = 'movielens32m'"
        ).fetchone()
        if count != 87585 or registry != (EXPECTED_MD5, 87585):
            raise RuntimeError("CATALOG_NOT_VERIFIED")
        print("APP_CATALOG_OK: 87585")

        accounts = conn.execute(
            "SELECT username,movielens_user_id,is_active FROM public.app_users "
            "WHERE username = ANY(%s)",
            (list(EXPECTED_ACCOUNTS),),
        ).fetchall()
        if {name: uid for name, uid, active in accounts if active} != EXPECTED_ACCOUNTS:
            raise RuntimeError("DEMO_ACCOUNTS_UNEXPECTED")
        print("APP_DEMO_ACCOUNTS_OK: 3")

        app_can_insert = conn.execute(
            "SELECT has_table_privilege(current_user,'public.user_interactions','INSERT')"
        ).fetchone()[0]
        app_can_update_movies = conn.execute(
            "SELECT has_table_privilege(current_user,'public.movies','UPDATE')"
        ).fetchone()[0]
        if not app_can_insert or app_can_update_movies:
            raise RuntimeError("APP_ROLE_PERMISSIONS_UNSAFE")
        print("APP_PERMISSIONS_OK: INSERT interactions, no UPDATE movies")

    print("APP_DB_SMOKE_SUCCESS: sin escrituras")


def main() -> int:
    stage = "validate_environment"
    try:
        import psycopg

        region = os.environ["AWS_REGION"]
        host = os.environ["RDS_ENDPOINT"]
        secret_id = os.environ["APP_DB_SECRET_ID"]
        if region != "us-east-1":
            raise RuntimeError("REGION_UNEXPECTED")
        if not (host.startswith("cinegraph-e4-postgres.") and
                host.endswith(".us-east-1.rds.amazonaws.com")):
            raise RuntimeError("RDS_HOST_UNEXPECTED")
        if secret_id != APP_SECRET_ID:
            raise RuntimeError("SECRET_ID_UNEXPECTED")
        if os.environ.get("DB_PASSWORD") or os.environ.get("DATABASE_URL"):
            raise RuntimeError("PASSWORD_ENV_UNEXPECTED")

        stage = "read_app_secret"
        secret = read_app_secret(region, host)
        print("APP_SECRET_ACCESS_OK")
        stage = "fetch_rds_trust"
        ca_getter = rds_ca()
        with tempfile.TemporaryDirectory(prefix="cinegraph-smoke-ca-") as temp:
            ca_file = ca_getter(temp)
            stage = "connect_app_role"
            with psycopg.connect(
                host=host,
                port=5432,
                dbname="cinegraph",
                user=secret["username"],
                password=secret["password"],
                sslmode="verify-full",
                sslrootcert=ca_file,
                connect_timeout=10,
                autocommit=True,
                application_name="cinegraph-e4-app-db-smoke",
            ) as connection:
                stage = "audit_database"
                audit_connection(connection)
        return 0
    except Exception as exc:
        # Errores controlados: no registrar DSN, contraseña, SecretString o traceback.
        print(f"APP_DB_SMOKE_FAILED: stage={stage}, error={type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
