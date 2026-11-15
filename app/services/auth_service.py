"""Cuentas locales separadas de los ID anónimos de MovieLens.

Nunca se interpreta un ID enviado por el navegador como identidad autenticada.
"""
from __future__ import annotations

import hmac
import secrets
from functools import wraps

from flask import g, jsonify, request, session
from sqlalchemy import text
from werkzeug.security import check_password_hash

from app.db import get_engine

ACCOUNT_SQL = text("""
SELECT account_id, username, movielens_user_id
FROM app_users WHERE account_id = :account_id AND is_active = TRUE
""")
LOGIN_SQL = text("""
SELECT account_id, username, movielens_user_id, password_hash
FROM app_users WHERE lower(username) = lower(:username) AND is_active = TRUE
""")


def get_account():
    account_id = session.get("account_id")
    if not isinstance(account_id, int) or account_id < 1:
        return None
    with get_engine().connect() as conn:
        row = conn.execute(ACCOUNT_SQL, {"account_id": account_id}).mappings().first()
    return dict(row) if row else None


def verify_credentials(username: str, password: str):
    if not username or not password:
        return None
    with get_engine().connect() as conn:
        row = conn.execute(LOGIN_SQL, {"username": username}).mappings().first()
    if not row or not check_password_hash(row["password_hash"], password):
        return None
    return {key: row[key] for key in ("account_id", "username", "movielens_user_id")}


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def requires_csrf():
    supplied = request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf_token", "")
    return bool(supplied and expected and hmac.compare_digest(supplied, expected))


def start_session(account):
    session.clear()
    session["account_id"] = int(account["account_id"])
    session.permanent = True
    return csrf_token()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        account = get_account()
        if not account:
            return jsonify(error="authentication_required", message="Inicia sesión para continuar."), 401
        g.account = account
        return view(*args, **kwargs)
    return wrapped
