from pathlib import Path
from app.main import create_app


def test_netflix_like_home_has_no_fake_ranking_or_button():
    app=create_app();app.config.update(TESTING=True)
    r=app.test_client().get("/")
    assert r.status_code==200
    page=r.get_data(as_text=True)
    for fragment in ('id="loginForm"','id="personalRail"','id="catalogShelves"','id="watchlistRail"','id="loginModal"'):
        assert fragment in page
    assert "Descubrir mi Top 10" not in page
    assert "Modo demostración" not in page
    assert "Top-10 de demostración" not in page
    assert "image.tmdb.org/t/p/w500/" not in page


def test_client_consults_only_current_account_and_real_catalog():
    js=Path("app/static/js/app.js").read_text("utf-8")
    assert '/api/recommendations?limit=10' in js
    assert '/api/auth/me' in js
    assert '/api/catalog?' in js
    assert '/api/interactions' in js
    assert 'DEMO_POSTERS' not in js
    assert 'CINEGRAPH_DEMO_USER' not in js


def test_hero_remains_home_and_empty_sections_are_hidden():
    app = create_app()
    app.config.update(TESTING=True)
    page = app.test_client().get("/").get_data(as_text=True)
    assert 'class="hero" id="inicio"' in page
    assert "Una historia más." in page
    for section in ("paraTi", "catalogo", "miLista"):
        assert f'id="{section}" hidden' in page
    assert 'class="project-note" aria-label="Información del proyecto" hidden' in page


def test_frontend_reveals_only_shelves_with_real_records():
    js = Path("app/static/js/app.js").read_text(encoding="utf-8")
    assert '$("catalogo").hidden = loaded === 0' in js
    assert '$("paraTi").hidden = false' in js
    assert '$("miLista").hidden = false' in js
    assert '$("paraTi").hidden = true' in js
    assert '$("miLista").hidden = true' in js
    assert 'window.scrollTo({ top: 0, behavior: "smooth" })' in js


def test_optional_catalog_filters_have_explicit_postgres_types():
    from app.services.catalog_service import CATALOG_SQL
    sql = str(CATALOG_SQL)
    # psycopg envía None como tipo desconocido: ':genre IS NULL' falla con 42P18.
    for field in ("genre", "search"):
        assert f"CAST(:{field} AS TEXT) IS NULL" in sql
        assert f":{field} IS NULL" not in sql
    assert "CAST(:genre AS TEXT) = ANY(genres)" in sql
    assert "CAST(:search AS TEXT)" in sql


def test_header_has_netflix_style_movie_search():
    app = create_app()
    app.config.update(TESTING=True)
    html = app.test_client().get("/").get_data(as_text=True)
    for fragment in ('id="searchToggle"', 'id="searchPanel" hidden',
                     'id="movieSearchInput"', 'id="searchResultsSection" hidden',
                     'id="searchResultsGrid"', 'id="searchStatus"'):
        assert fragment in html
    assert 'aria-label="Buscar películas"' in html
    assert 'Descubrir mi Top 10' not in html


def test_movie_search_calls_only_real_catalog_endpoint():
    js = Path("app/static/js/app.js").read_text(encoding="utf-8")
    assert 'new URLSearchParams({ search: query, limit: "48" })' in js
    assert 'request(`/api/catalog?${params}`' in js
    assert 'movieCard(movie, { surface: "search" })' in js
    assert "new AbortController()" in js
    assert 'searchGeneration' in js
    assert 'id="movieSearchInput"' not in js
    assert 'DEMO_POSTERS' not in js


def test_search_api_uses_real_catalog_filter(monkeypatch):
    from app.routes import api
    recorded = {}
    def fake_catalog(**kwargs):
        recorded.update(kwargs)
        return {"ready": True, "source": "MovieLens 32M", "count": 0, "movies": []}
    monkeypatch.setattr(api, "get_catalog", fake_catalog)
    app = create_app()
    app.config.update(TESTING=True)
    response = app.test_client().get("/api/catalog?search=Matrix&limit=48")
    assert response.status_code == 200
    assert response.get_json()["source"] == "MovieLens 32M"
    assert recorded["search"] == "Matrix"
    assert recorded["limit"] == 48
    assert app.test_client().get("/api/catalog?search=" + "x" * 101).status_code == 400
