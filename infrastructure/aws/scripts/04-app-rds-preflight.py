#!/usr/bin/env python3
"""Diagnóstico de solo lectura para cuentas SQL y secretos de CineGraph AWS.

No crea roles, contraseñas, usuarios, recursos de AWS ni modifica PostgreSQL.
Se ejecuta desde EC2, sin imprimir SecretString, con IAM LabRole.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SECRET_APP_NAME = "cinegraph-e4-app-db"
SECRET_DEMO_NAME = "cinegraph-e4-demo-users"
ROLE_APP = "cinegraph_app"
DEMO_NAMES = ("cine414", "cine123", "cine456")


def load_bootstrap():
    location = Path(__file__).with_name("03-bootstrap-rds.py")
    spec = importlib.util.spec_from_file_location("cinegraph_e4_rds_bootstrap", location)
    if spec is None or spec.loader is None:
        raise RuntimeError("BOOTSTRAP_MODULE_MISSING")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def secret_exists(sm, name: str) -> bool:
    try:
        sm.describe_secret(SecretId=name)
        return True
    except sm.exceptions.ResourceNotFoundException:
        return False


def audit(conn) -> None:
    with conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        role = conn.execute(
            "SELECT rolcanlogin FROM pg_roles WHERE rolname = %s", (ROLE_APP,)
        ).fetchone()
        required = (
            "movies", "catalog_imports", "app_users",
            "model_versions", "scoring_runs", "recommendations", "user_interactions"
        )
        for table in required:
            exists = conn.execute(
                "SELECT to_regclass(%s)", ("public." + table,)
            ).fetchone()[0]
            if exists is None:
                raise RuntimeError("REQUIRED_TABLE_MISSING_" + table.upper())
        names = conn.execute(
            "SELECT username FROM app_users WHERE username = ANY(%s) ORDER BY username",
            (list(DEMO_NAMES),)
        ).fetchall()
        account_names = {row[0] for row in names}
        catalog_count = conn.execute("SELECT count(*) FROM movies").fetchone()[0]
        registry = conn.execute(
            "SELECT verified_rows FROM catalog_imports WHERE dataset_name='movielens32m'"
        ).fetchone()
        if catalog_count != 87585 or registry is None or registry[0] != 87585:
            raise RuntimeError("CATALOG_NOT_READY")
        print("CATALOG_READY: 87585")
        print(f"APP_ROLE_EXISTS={bool(role)}")
        print(f"APP_ROLE_CAN_LOGIN={bool(role and role[0])}")
        print(f"DEMO_ACCOUNTS_PRESENT={','.join(sorted(account_names)) or 'none'}")
        if role:
            can_read = conn.execute(
                "SELECT has_table_privilege(%s, 'public.movies', 'SELECT')",
                (ROLE_APP,)
            ).fetchone()[0]
            can_write_interactions = conn.execute(
                "SELECT has_table_privilege(%s, 'public.user_interactions', 'INSERT')",
                (ROLE_APP,)
            ).fetchone()[0]
            print(f"APP_ROLE_MOVIES_READ={bool(can_read)}")
            print(f"APP_ROLE_INTERACTIONS_INSERT={bool(can_write_interactions)}")
    print("RDS_AUDIT_READ_ONLY_OK")


def main() -> int:
    try:
        import boto3
        import psycopg

        bootstrap = load_bootstrap()
        region, host, secret_arn = bootstrap.check_settings()
        sm = boto3.client("secretsmanager", region_name=region)
        # DescribeSecret consulta SOLO metadatos, nunca SecretString.
        print(f"APP_DB_SECRET_EXISTS={secret_exists(sm, SECRET_APP_NAME)}")
        print(f"DEMO_USERS_SECRET_EXISTS={secret_exists(sm, SECRET_DEMO_NAME)}")
        username, password = bootstrap.master_credentials(region, secret_arn)
        import tempfile

        with tempfile.TemporaryDirectory(prefix="cinegraph-rds-audit-") as path:
            ca_file = bootstrap.get_ca_bundle(path)
            with psycopg.connect(
                host=host, port=5432, dbname="cinegraph",
                user=username, password=password,
                sslmode="verify-full", sslrootcert=ca_file,
                connect_timeout=10, autocommit=True,
                application_name="cinegraph-e4-app-preflight",
            ) as conn:
                bootstrap.assert_server(conn)
                audit(conn)
        return 0
    except Exception as exc:
        # No se imprimen detalles del proveedor: podrían incluir credenciales.
        print(f"APP_PREFLIGHT_FAILED: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
