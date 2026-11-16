"""Regresiones del bootstrap Docker local: sin Docker ni PostgreSQL reales."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_local_setup_exposes_app_on_pythonpath():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    setup = compose.split("  local-setup:", 1)[1].split("\n  kinesis-agent:", 1)[0]
    assert "PYTHONPATH: /app" in setup
    assert "bootstrap.py" in setup
    assert "CINEGRAPH_LOCAL_SETUP:" in setup


def test_bootstrap_sql_insert_disambiguated():
    bootstrap = (ROOT / "scripts/local_setup/bootstrap.py").read_text(encoding="utf-8")
    # PostgreSQL necesita WHERE para desambiguar ON CONFLICT tras INSERT SELECT.
    assert "FROM _incoming_movies\n                WHERE TRUE\n                ON CONFLICT" in bootstrap
    assert "DELETE FROM user_interactions" not in bootstrap
    assert "DELETE FROM recommendations WHERE model_version='baseline-v0'" in bootstrap
