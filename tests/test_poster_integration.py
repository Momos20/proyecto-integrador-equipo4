"""Regresiones del hero y del catálogo con imágenes reales; sin llamar a TMDB."""
from pathlib import Path

from app.services.catalog_service import CATALOG_SQL, KNOWN_TMDB_POSTERS, get_catalog

ROOT = Path(__file__).resolve().parents[1]


def test_hero_has_local_original_image():
    image = ROOT / 'app/static/img/hero-cinegraph.webp'
    data = image.read_bytes()
    assert data[:4] == b'RIFF'
    assert data[8:12] == b'WEBP'
    assert len(data) > 10000
    css = (ROOT / 'app/static/css/styles.css').read_text(encoding='utf-8')
    assert '/static/img/hero-cinegraph.webp' in css
    assert 'background-size:cover' in css or 'background-size: cover' in css


def test_known_real_posters_are_keyed_to_movielens_ids():
    assert len(KNOWN_TMDB_POSTERS) >= 10
    assert KNOWN_TMDB_POSTERS[2571].startswith('https://image.tmdb.org/t/p/w500/')
    assert KNOWN_TMDB_POSTERS[79132].startswith('https://image.tmdb.org/t/p/w500/')
    assert all(isinstance(k, int) and k > 0 for k in KNOWN_TMDB_POSTERS)
    assert all(v.endswith('.jpg') for v in KNOWN_TMDB_POSTERS.values())


def test_catalog_prioritizes_existing_images_without_fake_ranking():
    sql = str(CATALOG_SQL)
    assert 'poster_url IS NOT NULL' in sql
    assert 'release_year DESC' in sql
    assert 'CAST(:genre AS TEXT) IS NULL' in sql
    js = (ROOT / 'app/static/js/app.js').read_text(encoding='utf-8')
    assert 'DEMO_POSTERS' not in js
    assert 'Descubrir mi Top 10' not in js

def test_known_posters_include_first_four_a9_recommendations():
    """Visualización: los Top-K son del modelo, los pósteres son metadatos independientes."""
    for movie_id in (109487, 50872, 68954, 134130):
        assert KNOWN_TMDB_POSTERS[movie_id].startswith("https://image.tmdb.org/t/p/w500/")


def test_a9_api_reuses_real_poster_fallback_without_changing_model(monkeypatch):
    from datetime import date, datetime, timezone
    from app.services import recommendation_service

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, *args, **kwargs):
            return self

        def mappings(self):
            return self

        def all(self):
            return [{
                "user_id": 123, "movie_id": 109487, "title": "Interstellar (2014)",
                "release_year": 2014, "genres": ["Sci-Fi", "IMAX"],
                "poster_url": None, "rank": 1, "score": 2.34567,
                "model_version": "a9-miguel-diario",
                "cutoff_week": date(2023, 6, 15),
                "generated_at": datetime(2026, 11, 15, tzinfo=timezone.utc),
            }]

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(recommendation_service, "get_engine", lambda: FakeEngine())
    result = recommendation_service.get_recommendations(user_id=123, limit=10)
    assert result["model"]["version"] == "a9-miguel-diario"
    assert result["count"] == 1
    assert result["cutoff_date"] == "2023-06-15"
    assert result["recommendations"][0]["poster_url"] == KNOWN_TMDB_POSTERS[109487]
    assert result["recommendations"][0]["rank"] == 1
    assert result["recommendations"][0]["score"] == 2.34567
