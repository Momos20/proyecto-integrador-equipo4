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