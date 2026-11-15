#!/usr/bin/env python3
"""Restablece una contraseña de cuenta de prueba local (nunca AWS)."""
import os
import secrets
import sys
from urllib.parse import urlsplit
from sqlalchemy import text
from werkzeug.security import generate_password_hash
from app.db import get_engine, _database_url

ALLOWED = {"cine414", "cine123", "cine456"}


def main():
    if len(sys.argv)!=2 or sys.argv[1] not in ALLOWED:
        raise SystemExit("Uso: python reset_password.py cine414|cine123|cine456")
    db = urlsplit(_database_url())
    if os.getenv("CINEGRAPH_LOCAL_SETUP") != "1" or db.hostname not in {"db", "127.0.0.1", "localhost"}:
        raise SystemExit("Sólo se permite restablecer cuentas de prueba en PostgreSQL local")
    password=secrets.token_urlsafe(14)
    with get_engine().begin() as conn:
        result = conn.execute(text("UPDATE app_users SET password_hash=:pwd WHERE username=:user"),
          {"pwd":generate_password_hash(password),"user":sys.argv[1]})
        if not result.rowcount: raise SystemExit("Cuenta aún no creada. Ejecuta local-setup.")
    print(f"{sys.argv[1]} | nueva contraseña: {password}")

if __name__=="__main__": main()
