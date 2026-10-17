from app.main import create_app


def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_recommendations_returns_ranked_top_10():
    response = client().get("/api/recommendations/414")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["user_id"] == 414
    assert payload["count"] == 10
    assert payload["model"]["version"] == "baseline-v0"
    assert [item["rank"] for item in payload["recommendations"]] == list(range(1, 11))
    assert payload["recommendations"][0]["title"] == "The Matrix"


def test_recommendations_respects_limit():
    response = client().get("/api/recommendations/414?limit=3")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["count"] == 3
    assert len(payload["recommendations"]) == 3


def test_recommendations_returns_404_for_unknown_user():
    response = client().get("/api/recommendations/999999999")

    assert response.status_code == 404
    assert response.get_json()["error"] == "no_recommendations"


def test_recommendations_rejects_invalid_limit():
    response = client().get("/api/recommendations/414?limit=100")

    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_limit"


def test_homepage_renders_cinegraph_ui():
    response = client().get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "CineGraph" in body
    assert "Descubrir mi Top 10" in body


def test_readiness_checks_database():
    response = client().get("/api/ready")

    assert response.status_code == 200
    assert response.get_json()["database"] == "ok"
