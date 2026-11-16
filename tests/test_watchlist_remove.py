"""Regression: Mi lista permite añadir, retirar y volver a añadir sin perder el historial."""
from datetime import datetime, timezone
from pathlib import Path

from app.main import create_app
from app.routes import api
from app.services import auth_service, interaction_service


ROOT = Path(__file__).resolve().parents[1]


def test_watchlist_sql_uses_latest_add_or_remove_for_each_movie():
    sql = str(interaction_service.WATCHLIST_SQL)
    assert "ROW_NUMBER() OVER" in sql
    assert "PARTITION BY i.movie_id" in sql
    assert "i.event_at DESC, i.interaction_id DESC" in sql
    assert "i.interaction_type IN ('watchlist', 'watchlist_remove')" in sql
    assert "l.rn = 1 AND l.interaction_type = 'watchlist'" in sql
    assert "i.user_id = :user_id" in sql


def test_database_schema_and_safe_migration_accept_remove():
    schema = (ROOT / "database/schema/003_user_interactions.sql").read_text("utf-8")
    migration = (ROOT / "database/migrations/005_watchlist_remove.sql").read_text("utf-8")
    for code in (schema, migration):
        assert "'watchlist_remove'" in code
        assert "ix_user_interactions_watchlist_latest" in code
    assert "DROP TABLE" not in migration
    assert "TRUNCATE" not in migration
    assert "DELETE FROM" not in migration


def test_authenticated_watchlist_and_remove_event(monkeypatch):
    account = {"account_id": 414, "username": "cine414", "movielens_user_id": 414}
    monkeypatch.setattr(api, "verify_credentials",
                        lambda username, password: account if username == "cine414" and password == "test" else None)
    monkeypatch.setattr(api, "get_account",
                        lambda: account if auth_service.session.get("account_id") == 414 else None)
    monkeypatch.setattr(auth_service, "get_account",
                        lambda: account if auth_service.session.get("account_id") == 414 else None)
    inserted = []
    events = []

    def save(**kwargs):
        inserted.append(kwargs)
        return {"interaction_id": len(inserted), "user_id": kwargs["user_id"],
                "movie_id": kwargs["movie_id"], "interaction_type": kwargs["interaction_type"],
                "rating": kwargs["rating"], "source": "cinegraph",
                "event_at": datetime(2026, 11, 16, tzinfo=timezone.utc).isoformat()}

    def emit(**kwargs):
        events.append(kwargs)
        return {"event_id": f"event-{len(events)}", "event_at": "2026-11-16T01:00:00+00:00"}

    monkeypatch.setattr(api, "create_interaction", save)
    monkeypatch.setattr(api, "emit_interaction_event", emit)
    monkeypatch.setattr(api, "get_watchlist", lambda user_id, limit: [
        {"movie_id": 109487, "title": "Interstellar (2014)", "release_year": 2014,
         "genres": ["Sci-Fi"], "poster_url": None}
    ] if user_id == 414 else [])

    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    assert client.get("/api/watchlist").status_code == 401
    csrf = client.get("/api/auth/me").get_json()["csrf_token"]
    login = client.post("/api/auth/login",
                        json={"username": "cine414", "password": "test"},
                        headers={"X-CSRF-Token": csrf})
    assert login.status_code == 200
    token = login.get_json()["csrf_token"]
    response = client.get("/api/watchlist?limit=500")
    assert response.status_code == 200
    assert response.get_json()["user_id"] == 414
    assert response.get_json()["movies"][0]["movie_id"] == 109487
    assert client.get("/api/watchlist?limit=1001").status_code == 400
    assert client.post("/api/interactions",
                       json={"movie_id": 109487, "interaction_type": "watchlist_remove"}).status_code == 403

    for action in ("watchlist", "watchlist_remove", "watchlist"):
        response = client.post("/api/interactions",
                               json={"movie_id": 109487, "interaction_type": action,
                                     "metadata": {"surface": "watchlist"}},
                               headers={"X-CSRF-Token": token})
        assert response.status_code == 201
        assert response.get_json()["interaction"]["interaction_type"] == action
        assert response.get_json()["stream_event"]["logged"] is True
    assert [i["interaction_type"] for i in inserted] == ["watchlist", "watchlist_remove", "watchlist"]
    assert [e["interaction_type"] for e in events] == ["watchlist", "watchlist_remove", "watchlist"]
    assert all(i["user_id"] == 414 for i in inserted)
    assert client.post("/api/interactions",
                       json={"movie_id": 109487, "interaction_type": "watchlist_remove", "user_id": 123},
                       headers={"X-CSRF-Token": token}).status_code == 403
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": token}).status_code == 200
    assert client.get("/api/watchlist").status_code == 401


def test_watchlist_frontend_buttons_toggle_and_refresh_across_views():
    js = (ROOT / "app/static/js/app.js").read_text("utf-8")
    assert 'request("/api/watchlist?limit=1000")' in js
    assert 'state.watchlistIds = new Set(movies.map(movie => Number(movie.movie_id)))' in js
    assert 'button.dataset.action = saved ? "watchlist_remove" : "watchlist"' in js
    assert 'surface === "watchlist" ? "− Quitar" : "✓ En mi lista"' in js
    assert 'if (action === "watchlist" || action === "watchlist_remove")' in js
    assert 'await loadWatchlist();' in js
    assert 'state.watchlistIds.clear();' in js
    assert 'sequence !== watchlistRequestSequence' in js


def test_curated_counts_remove_without_changing_a9_rating_candidates():
    import importlib.util
    import json
    import uuid

    # El ETL se carga desde la carpeta usada por Docker en el laboratorio.
    import sys
    path = ROOT / "scripts/data/transform_behavioral_floci.py"
    spec = importlib.util.spec_from_file_location("transform_behavioral_floci", path)
    pipeline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipeline)

    def event(kind):
        return {"schema_version": 1, "event_id": str(uuid.uuid4()),
                "event_type": kind, "event_at": "2026-11-16T01:00:00+00:00",
                "user_id": 414, "movie_id": 109487, "rating": None}
    assert pipeline.normalize_event(event("watchlist_remove"))["event_type"] == "watchlist_remove"

    class Body:
        def __init__(self, blob):
            self.blob = blob
        def read(self, size=None):
            return self.blob if size is None else self.blob[:size]

    class S3:
        def list_objects_v2(self, **kwargs):
            return {"Contents": [{"Key": pipeline.RAW_PREFIX + "data"}], "IsTruncated": False}
        def get_object(self, **kwargs):
            return {"Body": Body(pipeline.jsonl_bytes([event("watchlist"), event("watchlist_remove")]))}

    snapshot, outputs = pipeline.build_snapshot(S3())
    feature = next(blob for key, blob in outputs.items() if key.endswith("user_movie_daily.jsonl"))
    rows = [json.loads(line) for line in feature.splitlines()]
    assert rows[0]["n_watchlist"] == 1
    assert rows[0]["n_watchlist_remove"] == 1
    assert rows[0]["n_rating"] == 0
