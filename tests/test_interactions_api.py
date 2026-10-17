import json

from app.main import create_app


def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_create_like_interaction():
    response = client().post(
        "/api/interactions",
        json={
            "user_id": 414,
            "movie_id": 2571,
            "interaction_type": "like",
        },
    )

    assert response.status_code == 201
    body = response.get_json()
    payload = body["interaction"]
    assert payload["user_id"] == 414
    assert payload["movie_id"] == 2571
    assert payload["interaction_type"] == "like"
    assert payload["rating"] is None
    assert body["stream_event"]["logged"] is True


def test_create_rating_interaction():
    response = client().post(
        "/api/interactions",
        json={
            "user_id": 414,
            "movie_id": 79132,
            "interaction_type": "rating",
            "rating": 4.5,
        },
    )

    assert response.status_code == 201
    payload = response.get_json()["interaction"]
    assert payload["interaction_type"] == "rating"
    assert payload["rating"] == 4.5


def test_interaction_writes_enriched_clickstream(monkeypatch, tmp_path):
    log_path = tmp_path / "clickstream.log"
    monkeypatch.setenv("CLICKSTREAM_LOG_PATH", str(log_path))

    response = client().post(
        "/api/interactions",
        json={
            "user_id": 414,
            "movie_id": 2959,
            "interaction_type": "rating",
            "rating": 4.5,
            "metadata": {
                "recommendation_id": "414:2026-10-12:2",
                "model_version": "baseline-v0",
                "position": 2,
                "cutoff_date": "2026-10-12",
                "surface": "top10",
            },
        },
        headers={"X-Request-ID": "test-request-001"},
    )

    assert response.status_code == 201
    event = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert event["schema_version"] == 1
    assert event["event_type"] == "rating"
    assert event["user_id"] == 414
    assert event["movie_id"] == 2959
    assert event["rating"] == 4.5
    assert event["model_version"] == "baseline-v0"
    assert event["position"] == 2
    assert event["request_id"] == "test-request-001"


def test_reject_invalid_rating():
    response = client().post(
        "/api/interactions",
        json={
            "user_id": 414,
            "movie_id": 2571,
            "interaction_type": "rating",
            "rating": 6,
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_rating"


def test_recent_interactions_returns_saved_feedback():
    c = client()
    c.post(
        "/api/interactions",
        json={
            "user_id": 414,
            "movie_id": 2959,
            "interaction_type": "watchlist",
        },
    )

    response = c.get("/api/interactions/414?limit=20")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["user_id"] == 414
    assert payload["count"] >= 1
    assert any(item["movie_id"] == 2959 for item in payload["interactions"])
