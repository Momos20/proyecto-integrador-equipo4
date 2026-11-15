from pathlib import Path
import hashlib


ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "data" / "reference" / "movielens32m"


def test_movies_split_recreates_original_md5():
    parts = [REF / "parts" / f"movies.part{i:02d}.csv" for i in (1,2,3)]
    assert all(f.exists() for f in parts)
    data = b"".join(f.read_bytes() for f in parts)
    assert hashlib.md5(data).hexdigest() == "0df90835c19151f9d819d0822e190797"
    assert data.startswith(b"movieId,title,genres\r\n")
    assert len(data.splitlines()) == 87586


def test_links_file_matches_original():
    data = (REF / "links.csv").read_bytes()
    assert hashlib.md5(data).hexdigest() == "8f033867bcb4e6be8792b21468b4fa6e"
    assert data.startswith(b"movieId,imdbId,tmdbId\r\n")
    assert len(data.splitlines()) == 87586


def test_miguel_ingestion_is_manual_and_keeps_model_unchanged():
    script = (ROOT / "scripts" / "data" / "prepare_miguel_a9.py").read_text()
    assert 'if __name__ == "__main__":' in script
    assert "ratings_clean.parquet" in script
    assert "to_parquet" in script
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "  workflow_dispatch:" in workflow
    assert "  push:" not in workflow
    assert "  pull_request:" not in workflow
