"""La portada invitada no muestra contenido privado después de cerrar sesión."""
from pathlib import Path

from app.main import create_app


ROOT = Path(__file__).resolve().parents[1]


def test_guest_landing_has_a_dedicated_display_mode_and_new_brand():
    app = create_app()
    app.config.update(TESTING=True)
    html = app.test_client().get("/").get_data(as_text=True)
    assert '<html lang="es" class="guest-mode">' in html
    assert "cinegraph-mark.svg" in html
    assert 'class="brand-emblem" aria-hidden="true"' in html
    assert 'class="brand-emblem">C<span>G</span>' not in html
    assert (ROOT / "app/static/img/cinegraph-mark.svg").is_file()


def test_guest_mode_only_shows_hero_and_header():
    css = (ROOT / "app/static/css/styles.css").read_text("utf-8")
    for block in ("#searchResultsSection", "#paraTi", "#catalogo", "#miLista",
                  ".project-note", ".footer", ".skip-link"):
        assert f"html.guest-mode {block}" in css
    js = (ROOT / "app/static/js/app.js").read_text("utf-8")
    assert 'classList.toggle("guest-mode", !state.user)' in js
    assert 'if (!state.user) return;' in js
    assert "clearAuthenticatedViews();" in js
    assert "state.authEpoch += 1;" in js
    assert 'window.history.replaceState(null, "", window.location.pathname + window.location.search)' in js
    assert 'window.scrollTo({ top: 0, behavior: "instant" })' in js


def test_authenticated_catalog_loads_after_login_and_stale_requests_are_discarded():
    js = (ROOT / "app/static/js/app.js").read_text("utf-8")
    assert 'await Promise.all([loadCatalog(), loadRecommendations(), loadWatchlist()]);' in js
    assert 'requestEpoch !== state.authEpoch || !state.user' in js
    assert 'if (!state.user && link.getAttribute("href") !== "#inicio")' in js
    assert 'if (!state.user) { showLogin(); return; }' in js
