#!/usr/bin/env python3
"""Provisionar identidad SQL y credenciales demo exclusivas de CineGraph AWS.

Requiere EC2 con IAM instance profile, el secreto RDS y conexion PostgreSQL TLS.
No imprime contraseñas; todas se generan y custodian en AWS Secrets Manager.
No forma parte del bootstrap local ni se ejecuta desde el frontend.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

APP_ROLE = "cinegraph_app"
APP_SECRET_NAME = "cinegraph-e4-app-db"
DEMO_SECRET_NAME = "cinegraph-e4-demo-users"
DEMO_USERS = {"cine414": 414, "cine123": 123, "cine456": 456}
TABLES_READ = (
    "movies",
    "catalog_imports",
    "app_users",
    "model_versions",
    "scoring_runs",
    "recommendations",
    "user_interactions",
)


def bootstrap_module():
    location = Path(__file__).with_name("03-bootstrap-rds.py")
    spec = importlib.util.spec_from_file_location("cinegraph_e4_bootstrap", location)
    if spec is None or spec.loader is None:
        raise RuntimeError("BOOTSTRAP_NOT_FOUND")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def secret_value(manager, name: str, create_payload):
    """Conservar secretos existentes; nunca rotarlos implicitamente."""
    try:
        result = manager.get_secret_value(SecretId=name)
        value = json.loads(result["SecretString"])
        state = "EXISTING"
    except manager.exceptions.ResourceNotFoundException:
        value = create_payload()
        manager.create_secret(
            Name=name,
            Description="CineGraph Equipo 4 - credenciales generadas en EC2, no en GitHub",
            SecretString=json.dumps(value, separators=(",", ":")),
            Tags=[
                {"Key": "Project", "Value": "CineGraph"},
                {"Key": "Team", "Value": "E4"},
                {"Key": "Environment", "Value": "lab"},
            ],
        )
        state = "CREATED"
    if not isinstance(value, dict):
        raise RuntimeError("SECRET_FORMAT_INVALID")
    print(f"SECRET_{name.upper().replace('-', '_')}_{state}")
    return value


def app_credentials(host: str):
    return {
        "username": APP_ROLE,
        "password": secrets.token_urlsafe(36),
        "host": host,
        "port": 5432,
        "dbname": "cinegraph",
    }


def demo_credentials():
    return {
        "accounts": {
            name: {"password": secrets.token_urlsafe(24), "movielens_user_id": uid}
            for name, uid in DEMO_USERS.items()
        }
    }


def validate_app_payload(obj, host):
    if (
        obj.get("username") != APP_ROLE
        or obj.get("host") != host
        or obj.get("dbname") != "cinegraph"
        or obj.get("port") != 5432
        or not isinstance(obj.get("password"), str)
        or len(obj["password"]) < 32
    ):
        raise RuntimeError("APP_SECRET_INVALID")


def validate_demo_payload(obj):
    accounts = obj.get("accounts")
    if not isinstance(accounts, dict) or set(accounts) != set(DEMO_USERS):
        raise RuntimeError("DEMO_SECRET_INVALID")
    for name, movie_user in DEMO_USERS.items():
        entry = accounts.get(name)
        if (
            not isinstance(entry, dict)
            or entry.get("movielens_user_id") != movie_user
            or not isinstance(entry.get("password"), str)
            or len(entry["password"]) < 24
        ):
            raise RuntimeError("DEMO_SECRET_INVALID")


def verify_catalog(conn):
    required = (*TABLES_READ, "app_users")
    for name in set(required):
        if not conn.execute("SELECT to_regclass(%s)", ("public." + name,)).fetchone()[0]:
            raise RuntimeError("REQUIRED_SQL_TABLE_MISSING")
    count = conn.execute("SELECT count(*) FROM public.movies").fetchone()[0]
    registry = conn.execute(
        "SELECT movies_md5, verified_rows FROM public.catalog_imports "
        "WHERE dataset_name='movielens32m'"
    ).fetchone()
    if count != 87585 or registry != ("0df90835c19151f9d819d0822e190797", 87585):
        raise RuntimeError("CATALOG_NOT_VERIFIED")
    print("CATALOG_VERIFIED: 87585")


def grant_app_rights(conn, db_password: str, credentials):
    from psycopg import sql
    from werkzeug.security import check_password_hash, generate_password_hash

    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(20261123, 5)")
        verify_catalog(conn)
        role = conn.execute(
            "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole "
            "FROM pg_roles WHERE rolname=%s", (APP_ROLE,)
        ).fetchone()
        if role is None:
            # La contraseña solo viaja del secreto a PostgreSQL; nunca a un comando SSM.
            conn.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(APP_ROLE), sql.Literal(db_password)
                )
            )
        elif role != (True, False, False, False):
            raise RuntimeError("EXISTING_APP_ROLE_UNSAFE")
        conn.execute("GRANT CONNECT ON DATABASE cinegraph TO cinegraph_app")
        conn.execute("GRANT USAGE ON SCHEMA public TO cinegraph_app")
        for table in TABLES_READ:
            conn.execute(
                sql.SQL("GRANT SELECT ON TABLE public.{} TO cinegraph_app").format(
                    sql.Identifier(table)
                )
            )
        conn.execute("GRANT INSERT ON TABLE public.user_interactions TO cinegraph_app")
        conn.execute(
            "GRANT USAGE ON SEQUENCE public.user_interactions_interaction_id_seq "
            "TO cinegraph_app"
        )
        for name, movie_user in DEMO_USERS.items():
            existing = conn.execute(
                "SELECT movielens_user_id, password_hash FROM public.app_users "
                "WHERE lower(username)=lower(%s)", (name,)
            ).fetchone()
            plain = credentials["accounts"][name]["password"]
            if existing:
                if existing[0] != movie_user or not check_password_hash(existing[1], plain):
                    raise RuntimeError("EXISTING_DEMO_ACCOUNT_SECRET_MISMATCH")
            else:
                conn.execute(
                    "INSERT INTO public.app_users(username,password_hash,movielens_user_id) "
                    "VALUES (%s,%s,%s)",
                    (name, generate_password_hash(plain), movie_user),
                )
        accounts = conn.execute(
            "SELECT username, movielens_user_id FROM public.app_users "
            "WHERE username = ANY(%s)", (list(DEMO_USERS),)
        ).fetchall()
        if {name: uid for name, uid in accounts} != DEMO_USERS:
            raise RuntimeError("APP_ACCOUNTS_VERIFICATION_FAILED")
    print("RDS_SQL_COMMIT_OK: cinegraph_app y 3 cuentas demo")


def verify_app_login(psycopg, host: str, ca: str, pwd: str):
    with psycopg.connect(
        host=host,
        port=5432,
        dbname="cinegraph",
        user=APP_ROLE,
        password=pwd,
        sslmode="verify-full",
        sslrootcert=ca,
        connect_timeout=10,
        autocommit=True,
        application_name="cinegraph-e4-app-role-check",
    ) as conn:
        count = conn.execute("SELECT count(*) FROM public.movies").fetchone()[0]
        users = conn.execute("SELECT count(*) FROM public.app_users").fetchone()[0]
        can_insert = conn.execute(
            "SELECT has_table_privilege(current_user,'public.user_interactions','INSERT')"
        ).fetchone()[0]
        can_update = conn.execute(
            "SELECT has_table_privilege(current_user,'public.movies','UPDATE')"
        ).fetchone()[0]
        if count != 87585 or users < 3 or not can_insert or can_update:
            raise RuntimeError("APP_ROLE_PRIVILEGE_CHECK_FAILED")
    print("APP_SQL_LOGIN_OK: TLS verify-full, lectura de catalogo y rol sin UPDATE en movies")


def main() -> int:
    parser = argparse.ArgumentParser(description="CineGraph - credenciales AWS")
    parser.add_argument("--apply", action="store_true", required=True)
    args = parser.parse_args()
    stage = "preflight"
    try:
        if not args.apply or os.environ.get("CONFIRM_APP_CREDENTIALS") != "YES":
            raise RuntimeError("APPLY_CONFIRMATION_REQUIRED")
        import boto3
        import psycopg

        bootstrap = bootstrap_module()
        region, host, master_secret = bootstrap.check_settings()
        stage = "rds_master"
        master_user, master_pwd = bootstrap.master_credentials(region, master_secret)
        with tempfile.TemporaryDirectory(prefix="cinegraph-rds-roles-") as tmp:
            ca_path = bootstrap.get_ca_bundle(tmp)
            with psycopg.connect(
                host=host,
                port=5432,
                dbname="cinegraph",
                user=master_user,
                password=master_pwd,
                sslmode="verify-full",
                sslrootcert=ca_path,
                autocommit=True,
                connect_timeout=10,
                application_name="cinegraph-e4-role-bootstrap",
            ) as admin:
                bootstrap.assert_server(admin)
                stage = "rds_preflight"
                verify_catalog(admin)
                # Crear primero ambos secretos: un error de IAM deja PostgreSQL intacto.
                manager = boto3.client("secretsmanager", region_name=region)
                stage = "app_db_secret"
                app = secret_value(
                    manager, APP_SECRET_NAME, lambda: app_credentials(host)
                )
                validate_app_payload(app, host)
                stage = "demo_users_secret"
                demos = secret_value(
                    manager, DEMO_SECRET_NAME, demo_credentials
                )
                validate_demo_payload(demos)
                stage = "rds_role_and_accounts"
                grant_app_rights(admin, app["password"], demos)
            stage = "verify_app_login"
            verify_app_login(psycopg, host, ca_path, app["password"])
        print("AWS_APP_IDENTITIES_READY: credenciales solo en Secrets Manager")
        return 0
    except Exception as exc:
        # Nunca imprimir SecretString, DSN, contraseñas ni traceback.
        from botocore.exceptions import ClientError
        code = exc.response.get("Error", {}).get("Code", "") if isinstance(exc, ClientError) else ""
        safe_code = code if code in {
            "AccessDeniedException", "ResourceExistsException",
            "InvalidRequestException", "LimitExceededException",
            "DecryptionFailure", "InternalServiceError"
        } else type(exc).__name__
        print(f"APP_IDENTITIES_FAILED: stage={stage} code={safe_code}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
