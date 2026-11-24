#!/usr/bin/env python3
"""Arranque privado de CineGraph en AWS: secretos runtime, TLS estricto y Gunicorn.

Las claves nunca se reciben via CloudShell/SSM, Compose env ni archivos en Git.
Se obtiene password del rol `cinegraph_app` por IAM desde Secrets Manager.
La clave Flask se carga de un fichero raiz 0600 persistente en EBS de EC2.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.request import urlopen

CA_URL = "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"
CA_FILE = Path("/tmp/cinegraph-rds-ca.pem")
SESSION_FILE = Path("/run/secrets/cinegraph_session_key")


def main() -> None:
    import boto3

    region = os.environ["AWS_REGION"]
    host = os.environ["RDS_ENDPOINT"]
    secret_id = os.environ["APP_DB_SECRET_ID"]

    if region != "us-east-1":
        raise RuntimeError("REGION_UNEXPECTED")
    if not (
        host.startswith("cinegraph-e4-postgres.")
        and host.endswith(".us-east-1.rds.amazonaws.com")
    ):
        raise RuntimeError("RDS_ENDPOINT_UNEXPECTED")
    if secret_id != "cinegraph-e4-app-db":
        raise RuntimeError("APP_SECRET_ID_UNEXPECTED")
    if os.environ.get("DATABASE_URL") or os.environ.get("DB_PASSWORD"):
        raise RuntimeError("DB_PASSWORD_ENV_NOT_ALLOWED")
    if os.environ.get("CINEGRAPH_ENV") != "production":
        raise RuntimeError("PRODUCTION_ENV_REQUIRED")
    if os.environ.get("CINEGRAPH_COOKIE_SECURE") != "1":
        raise RuntimeError("HTTPS_COOKIE_REQUIRED")

    # La clave se genera una sola vez en EC2; nunca se imprime ni guarda en Git.
    session_key = SESSION_FILE.read_text(encoding="utf-8").strip()
    if len(session_key) < 48:
        raise RuntimeError("SESSION_KEY_INVALID")

    response = boto3.client("secretsmanager", region_name=region).get_secret_value(
        SecretId=secret_id
    )
    credentials = json.loads(response["SecretString"])
    if not isinstance(credentials, dict) or any(
        credentials.get(field) != value
        for field, value in {
            "username": "cinegraph_app",
            "host": host,
            "dbname": "cinegraph",
            "port": 5432,
        }.items()
    ):
        raise RuntimeError("APP_SECRET_INVALID")
    password = credentials.get("password")
    if not isinstance(password, str) or len(password) < 32:
        raise RuntimeError("APP_PASSWORD_INVALID")

    with urlopen(CA_URL, timeout=30) as remote:
        cert_bundle = remote.read(1024 * 1024)
    if b"-----BEGIN CERTIFICATE-----" not in cert_bundle:
        raise RuntimeError("CA_BUNDLE_INVALID")
    CA_FILE.write_bytes(cert_bundle)
    CA_FILE.chmod(0o600)

    # libpq/psycopg reconoce estas variables. app/db.py construye el DSN
    # usando DB_HOST/DB_USER/DB_PASSWORD; no se guarda en Compose ni docker inspect.
    os.environ.update(
        DB_HOST=host,
        DB_PORT="5432",
        DB_NAME="cinegraph",
        DB_USER="cinegraph_app",
        DB_PASSWORD=password,
        PGSSLMODE="verify-full",
        PGSSLROOTCERT=str(CA_FILE),
        SECRET_KEY=session_key,
    )
    print("CINEGRAPH_WEB_RUNTIME_READY: IAM, TLS y sesión configurados", flush=True)
    os.execvp(
        "gunicorn",
        [
            "gunicorn",
            "--bind", "0.0.0.0:8000",
            "--workers", "2",
            "--access-logfile", "-",
            "--error-logfile", "-",
            "app.main:app",
        ],
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Nunca mostrar SecretString, DSN ni contraseñas en logs/SSM.
        print(f"CINEGRAPH_WEB_START_FAILED: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1)
