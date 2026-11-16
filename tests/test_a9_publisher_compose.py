"""Verifica que la publicación manual A9 pueda importar los módulos de Flask.
El contenedor usa python /app/scripts/ml/publish_a9_local.py, por lo que la
raíz /app debe estar presente en PYTHONPATH (sin instalar el proyecto).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_a9_publisher_python_path_is_explicit():
    compose = (ROOT / "docker-compose.floci.yml").read_text(encoding="utf-8")
    publisher = compose.split("  a9-publish:", 1)[1].split("\nvolumes:", 1)[0]
    assert "PYTHONPATH: /app" in publisher
    assert 'CINEGRAPH_LOCAL_SETUP: "1"' in publisher
    assert "/app/scripts/ml/publish_a9_local.py" in publisher
    assert "floci:" in publisher
