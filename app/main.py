import os

from flask import Flask, jsonify

from app.routes.api import api_bp
from app.routes.web import web_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-only-secret")

    app.register_blueprint(api_bp)
    app.register_blueprint(web_bp)

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="recommendation-app")

    return app


app = create_app()
