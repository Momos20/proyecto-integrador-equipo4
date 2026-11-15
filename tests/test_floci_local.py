from pathlib import Path


def test_local_aws_emulator_is_opt_in_and_ci_is_manual():
    compose = Path("docker-compose.floci.yml").read_text(encoding="utf-8")
    default_compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    actions = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    manager = Path("scripts/local_aws/manage.py").read_text(encoding="utf-8")

    assert 'profiles: ["floci"]' in compose
    assert "floci/floci:2.5.0" in compose
    assert "floci:" not in default_compose
    assert "workflow_dispatch:" in actions
    assert "  push:" not in actions
    assert "  pull_request:" not in actions
    assert "  schedule:" not in actions
    assert '"KinesisStreamAsSource"' in manager
    assert "SAFETY: only localhost" in manager
    assert 'commands = {"bootstrap": bootstrap, "ship": ship, "verify": verify' in manager


def test_frontend_keeps_fallback_and_preserves_interaction_api():
    js = Path("app/static/js/app.js").read_text(encoding="utf-8")
    css = Path("app/static/css/styles.css").read_text(encoding="utf-8")
    assert "poster_url" in js
    assert "DEMO_POSTERS" in js
    assert "data-action" in js
    assert "/api/interactions" in js
    assert ".editorial-image img, .poster img" in js
    assert "prefers-reduced-motion" in css
