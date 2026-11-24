#!/usr/bin/env python3
"""Prueba de autenticación Flask con cuenta ficticia y RDS real, sin cambios persistentes.

Ejecutar exclusivamente como stdin de "docker exec -i cinegraph-e4-app python -":
el proceso recupera secretos del rol IAM de EC2 en memoria y simula HTTPS
mediante Flask test_client, sin abrir puertos ni imprimir contraseñas.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_SECRET_ID = "cinegraph-e4-app-db"
DEMO_SECRET_ID = "cinegraph-e4-demo-users"
ACCOUNT_NAME = os.environ.get("CINEGRAPH_SMOKE_USER", "cine414")
EXPECTED_MOVIELENS_ID = {"cine123":123,"cine414":414,"cine456":456}[ACCOUNT_NAME]
BASE_URL = "https://cinegraph.local"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def install_app_runtime_credentials() -> str:
    """Configurar una copia efímera del entorno Flask, sin modificar PID 1."""
    import boto3

    region = os.environ.get("AWS_REGION")
    host = os.environ.get("RDS_ENDPOINT", "")
    require(region == "us-east-1", "REGION_UNEXPECTED")
    require(
        host.startswith("cinegraph-e4-postgres.")
        and host.endswith(".us-east-1.rds.amazonaws.com"),
        "RDS_HOST_UNEXPECTED",
    )
    require(os.environ.get("CINEGRAPH_ENV") == "production", "PRODUCTION_REQUIRED")
    require(os.environ.get("CINEGRAPH_COOKIE_SECURE") == "1", "SECURE_COOKIE_REQUIRED")
    ca_file = Path("/tmp/cinegraph-rds-ca.pem")
    require(ca_file.exists(), "RDS_CA_MISSING")
    session_file = Path("/run/secrets/cinegraph_session_key")
    require(session_file.exists(), "SESSION_KEY_FILE_MISSING")
    session_key = session_file.read_text(encoding="utf-8").strip()
    require(len(session_key) >= 48, "SESSION_KEY_INVALID")

    secrets_client = boto3.client("secretsmanager", region_name=region)
    db = json.loads(
        secrets_client.get_secret_value(SecretId=APP_SECRET_ID)["SecretString"]
    )
    require(isinstance(db, dict), "APP_DB_SECRET_INVALID")
    require(
        db.get("host") == host
        and db.get("username") == "cinegraph_app"
        and db.get("dbname") == "cinegraph"
        and db.get("port") == 5432,
        "APP_DB_SECRET_MISMATCH",
    )
    db_password = db.get("password")
    require(isinstance(db_password, str) and len(db_password) >= 32,
            "APP_DB_PASSWORD_INVALID")
    demo = json.loads(
        secrets_client.get_secret_value(SecretId=DEMO_SECRET_ID)["SecretString"]
    )
    account = demo.get("accounts", {}).get(ACCOUNT_NAME) if isinstance(demo, dict) else None
    require(isinstance(account, dict), "DEMO_ACCOUNT_MISSING")
    require(account.get("movielens_user_id") == EXPECTED_MOVIELENS_ID,
            "DEMO_ACCOUNT_ID_MISMATCH")
    demo_password = account.get("password")
    require(isinstance(demo_password, str) and len(demo_password) >= 24,
            "DEMO_PASSWORD_INVALID")

    # Docker exec no hereda los cambios de entorno hechos por el PID 1 después
    # de crear el contenedor, así que se cargan de nuevo en este proceso efímero.
    os.environ.update(
        DB_HOST=host,
        DB_PORT="5432",
        DB_NAME="cinegraph",
        DB_USER="cinegraph_app",
        DB_PASSWORD=db_password,
        PGSSLMODE="verify-full",
        PGSSLROOTCERT=str(ca_file),
        SECRET_KEY=session_key,
    )
    print("AUTH_TEST_SECRET_ACCESS_OK", flush=True)
    return demo_password


def run_test(demo_password: str) -> None:
    from app.main import app

    require(bool(app.config["SESSION_COOKIE_SECURE"]), "COOKIE_SECURE_DISABLED")
    with app.test_client() as client:
        root = client.get("/", base_url=BASE_URL)
        require(root.status_code == 200 and b"CineGraph" in root.data,
                "FRONTEND_NOT_READY")
        print("AUTH_TEST_FRONTEND_OK")

        css = client.get("/static/css/styles.css", base_url=BASE_URL)
        require(css.status_code == 200, "STATIC_FILES_NOT_READY")
        print("AUTH_TEST_STATIC_OK")

        catalog = client.get("/api/catalog?limit=2", base_url=BASE_URL)
        payload = catalog.get_json()
        require(catalog.status_code == 200 and payload.get("ready")
                and payload.get("count") == 2, "CATALOG_NOT_READY")
        print("AUTH_TEST_CATALOG_OK")

        before = client.get("/api/recommendations", base_url=BASE_URL)
        require(before.status_code == 401, "AUTH_REQUIRED_MISSING")
        print("AUTH_TEST_UNAUTHENTICATED_401_OK")

        csrf_response = client.get("/api/auth/me", base_url=BASE_URL)
        require(csrf_response.status_code == 200, "ME_ENDPOINT_FAILED")
        data = csrf_response.get_json()
        require(data.get("authenticated") is False
                and isinstance(data.get("csrf_token"), str), "ME_GUEST_INVALID")

        login = client.post(
            "/api/auth/login",
            base_url=BASE_URL,
            json={"username": ACCOUNT_NAME, "password": demo_password},
            headers={"X-CSRF-Token": data["csrf_token"]},
        )
        require(login.status_code == 200, "LOGIN_FAILED")
        login_data = login.get_json()
        require(login_data.get("authenticated") is True
                and login_data.get("user", {}).get("username") == ACCOUNT_NAME
                and login_data.get("user", {}).get("movielens_user_id")
                == EXPECTED_MOVIELENS_ID, "LOGIN_IDENTITY_INVALID")
        cookie = login.headers.get("Set-Cookie", "")
        require("Secure" in cookie and "HttpOnly" in cookie,
                "SECURE_COOKIE_MISSING")
        print(f"AUTH_TEST_LOGIN_OK: {ACCOUNT_NAME}; secure cookie")

        me = client.get("/api/auth/me", base_url=BASE_URL)
        require(me.status_code == 200 and me.get_json().get("authenticated"),
                "PERSISTED_SESSION_INVALID")
        print("AUTH_TEST_SESSION_OK")

        watchlist = client.get("/api/watchlist", base_url=BASE_URL)
        require(watchlist.status_code == 200
                and watchlist.get_json().get("user_id") == EXPECTED_MOVIELENS_ID,
                "WATCHLIST_READ_FAILED")
        history = client.get("/api/interactions?limit=2", base_url=BASE_URL)
        require(history.status_code == 200
                and history.get_json().get("user_id") == EXPECTED_MOVIELENS_ID,
                "INTERACTIONS_READ_FAILED")
        print("AUTH_TEST_PRIVATE_READS_OK")

        rec = client.get("/api/recommendations", base_url=BASE_URL)
        if rec.status_code == 404:
            require(rec.get_json().get("error") == "no_recommendations",
                    "RECOMMENDATION_ERROR_UNEXPECTED")
            raise RuntimeError("A9_NOT_PUBLISHED")
        elif rec.status_code == 200:
            verified = rec.get_json()
            require(verified.get("model", {}).get("version") == "a9-miguel-diario"
                    and verified.get("count") == 10
                    and verified.get("user_id") == EXPECTED_MOVIELENS_ID
                    and verified.get("cutoff_date") == "2023-06-15",
                    "RECOMMENDATION_PAYLOAD_UNEXPECTED")
            items = verified["recommendations"]
            require([i["rank"] for i in items] == list(range(1,11)), "INVALID_RANK")
            require(len({i["movie_id"] for i in items}) == 10, "DUPLICATE_MOVIE")
            print("AUTH_TEST_A9_PUBLISHED: GraphSAGE real")
            print(json.dumps({"user":ACCOUNT_NAME,"cutoff":verified["cutoff_date"],"movies":[{"rank":i["rank"],"movie_id":i["movie_id"],"title":i["title"],"poster":bool(i.get("poster_url"))} for i in items]},ensure_ascii=False))
        else:
            raise RuntimeError("RECOMMENDATION_ROUTE_FAILED")

        csrf = login_data.get("csrf_token")
        require(isinstance(csrf, str), "LOGIN_CSRF_MISSING")
        logout = client.post(
            "/api/auth/logout", base_url=BASE_URL,
            headers={"X-CSRF-Token": csrf},
        )
        require(logout.status_code == 200
                and logout.get_json().get("authenticated") is False,
                "LOGOUT_FAILED")
        postlogout = client.get("/api/recommendations", base_url=BASE_URL)
        require(postlogout.status_code == 401, "LOGOUT_SESSION_NOT_CLEARED")
        print("AUTH_TEST_LOGOUT_OK")
    print("CINEGRAPH_AUTH_SMOKE_SUCCESS: sin escrituras a RDS")


def main() -> int:
    stage = "config"
    try:
        stage = "fetch_secrets"
        demo_password = install_app_runtime_credentials()
        stage = "flask_test_client"
        run_test(demo_password)
        return 0
    except Exception as exc:
        # No imprimir exception str ni traceback: podrían incluir información sensible.
        print(f"AUTH_TEST_FAILED: stage={stage} type={type(exc).__name__}",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
