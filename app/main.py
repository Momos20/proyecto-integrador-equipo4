"""CineGraph Flask: solo sesiones locales salvo configuración explícita de producción."""
import os
import secrets
import time
from datetime import timedelta
from pathlib import Path

from flask import Flask, jsonify
from app.routes.api import api_bp
from app.routes.web import web_bp


def _secret_key():
    supplied = os.getenv("SECRET_KEY", "")
    if supplied and len(supplied) >= 32 and supplied not in {"change-me", "dev-only-secret"}:
        return supplied
    if os.getenv("CINEGRAPH_ENV") == "production":
        raise RuntimeError("SECRET_KEY seguro es obligatorio en producción")
    # Los trabajadores de Gunicorn comparten una clave local persistente,
    # aunque el .env de laboratorio siga usando el valor de ejemplo.
    default_path = "/app/session-secrets/secret_key" if Path("/app/session-secrets").is_dir() else str(Path.home() / ".cache/cinegraph/session_key")
    path = Path(os.getenv("CINEGRAPH_SECRET_PATH", default_path))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            for _ in range(40):
                value = path.read_text(encoding="utf-8").strip()
                if value:
                    return value
                time.sleep(0.05)
            raise RuntimeError("No se pudo leer una clave de sesión local válida")
        else:
            value = secrets.token_urlsafe(48)
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                out.write(value)
            return value
    except OSError as exc:
        raise RuntimeError("No se pudo obtener la clave persistente para sesiones. Comprueba el volumen local.") from exc


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=_secret_key(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("CINEGRAPH_COOKIE_SECURE") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(days=1),
        MAX_CONTENT_LENGTH=16 * 1024,
    )
    app.register_blueprint(api_bp)
    app.register_blueprint(web_bp)

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="cinegraph")

    return app


app = create_app()
