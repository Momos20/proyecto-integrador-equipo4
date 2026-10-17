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
    payload = response.get_json()["interaction"]
    assert payload["user_id"] == 414
    assert payload["movie_id"] == 2571
    assert payload["interaction_type"] == "like"
    assert payload["rating"] is None


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
