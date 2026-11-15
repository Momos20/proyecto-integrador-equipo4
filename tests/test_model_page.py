from app.main import create_app


def test_home_is_cinematic_and_shows_only_the_selected_model():
    app = create_app()
    app.config.update(TESTING=True)
    response = app.test_client().get("/")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "CineGraph" in page
    assert 'class="cinema-hero"' in page
    assert "Historias que se quedan" in page
    assert "A9_sin_id" in page
    assert "A0_base" not in page
    assert "Recall@10 0,0938" in page
    assert "NDCG@10 0,0663" in page
    assert "horizonte de 7 días" in page
    assert "Top-10 actual es de demostración" in page
    assert "Netflix" not in page
    for element_id in ("recommendationForm", "userId", "movieGrid", "resultsSection",
                       "loadingSection", "emptyState", "demoButton", "emptyDemoButton",
                       "servingNotice", "movieFilter"):
        assert f'id="{element_id}"' in page


def test_home_keeps_interaction_actions_in_client_script():
    js = __import__("pathlib").Path("app/static/js/app.js").read_text(encoding="utf-8")
    for action in ('data-action="like"', 'data-action="dislike"',
                   'data-action="watchlist"', 'data-action="rating"'):
        assert action in js
    assert 'fetch("/api/interactions"' in js
    assert 'fetch(`/api/recommendations/' in js
