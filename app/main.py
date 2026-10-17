from flask import Flask, jsonify, render_template


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="recommendation-app")

    @app.get("/")
    def index():
        return render_template("index.html")

    return app


app = create_app()
