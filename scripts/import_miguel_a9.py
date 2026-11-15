#!/usr/bin/env python3
"""Stage Miguel's A9 ZIP without executing its Python modules or launching pipelines.

Keeps existing ml/models/A9_sin_id/modelo.pt canonical (no binary duplication).
Requires the original A9_topk_diario.zip in the local filesystem.
"""
from __future__ import annotations

import argparse
import hashlib
import stat
import zipfile
from pathlib import Path, PurePosixPath

ARCHIVE_ROOT = "A9_topk_diario"
MODEL_REL = PurePosixPath("resultados/graphsage/A9_sin_id/modelo.pt")
EXPECTED_SHA256 = "8c9aa61fb7e8d3ed3a6476fe759f9861283387bc6561ea5aa03595ab516a2358"
ALLOWED_TOP = {"src", "tests", "resultados"}
ALLOWED_RESULTS = {"diario", "recomendaciones"}
ALLOWED_EXTENSIONS = {".py", ".md", ".txt", ".csv", ".json", ".html"}


def import_zip(zip_path: Path, repo_root: Path) -> tuple[int, Path]:
    repo_root = repo_root.resolve()
    dest = repo_root / "ml" / "a9_daily"
    model = repo_root / "ml" / "models" / "A9_sin_id" / "modelo.pt"
    if not model.is_file():
        raise RuntimeError(f"Existing Git model not found: {model}")
    if hashlib.sha256(model.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise RuntimeError("Canonical A9 checkpoint does not match Miguel's archived version")

    with zipfile.ZipFile(zip_path) as archive:
        entries = {PurePosixPath(info.filename): info for info in archive.infolist() if not info.is_dir()}
        expected = PurePosixPath(ARCHIVE_ROOT) / MODEL_REL
        if expected not in entries:
            raise RuntimeError("A9 checkpoint is missing from the uploaded zip")
        if hashlib.sha256(archive.read(entries[expected])).hexdigest() != EXPECTED_SHA256:
            raise RuntimeError("A9 checkpoint in ZIP differs from model already in GitHub")

        outputs = []
        for member, info in entries.items():
            if not member.parts or member.parts[0] != ARCHIVE_ROOT:
                raise RuntimeError(f"Unexpected archive path: {member}")
            rel = PurePosixPath(*member.parts[1:])
            if rel == MODEL_REL or (len(rel.parts) >= 2 and rel.parts[:2] == ("resultados", "graphsage")):
                continue  # the original model, validation.json and curve are already versioned
            if any(part in ("", ".", "..") for part in rel.parts) or rel.is_absolute():
                raise RuntimeError(f"Unsafe path: {member}")
            if rel.parts[0] in ALLOWED_TOP:
                if rel.parts[0] == "resultados" and (len(rel.parts) < 2 or rel.parts[1] not in ALLOWED_RESULTS):
                    continue
            elif str(rel) not in ("README.md", "LEEME.md", "requirements.txt"):
                raise RuntimeError(f"Unexpected file: {rel}")
            if rel.suffix not in ALLOWED_EXTENSIONS:
                raise RuntimeError(f"Unexpected file type: {rel}")
            if stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK:
                raise RuntimeError("Symbolic links are not allowed")
            target = (dest / Path(*rel.parts)).resolve()
            if not target.is_relative_to(dest.resolve()):
                raise RuntimeError(f"Path escapes destination: {rel}")
            data = archive.read(info)
            if rel == PurePosixPath("src/recomendar.py"):
                source = data.decode("utf-8")
                substitutions = {
                    'CARPETA_A9 = datos.RAIZ / "resultados" / "graphsage" / "A9_sin_id"':
                        'CARPETA_A9 = datos.RAIZ.parent / "models" / "A9_sin_id"',
                    'modelo.load_state_dict(torch.load(carpeta / "modelo.pt", map_location=diario.dispositivo))':
                        'modelo.load_state_dict(torch.load(carpeta / "modelo.pt", map_location=diario.dispositivo, weights_only=True))',
                    '(CARPETA_A9 / "modelo.pt").relative_to(datos.RAIZ).as_posix()':
                        '(CARPETA_A9 / "modelo.pt").relative_to(datos.RAIZ.parent.parent).as_posix()',
                }
                for old, new in substitutions.items():
                    if source.count(old) != 1:
                        raise RuntimeError(f"Unexpected source layout; cannot safely adapt: {old}")
                    source = source.replace(old, new)
                data = source.encode("utf-8")
            outputs.append((target, data))

    for target, data in outputs:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return len(outputs), dest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip", type=Path, help="Path to A9_topk_diario.zip received from Miguel")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    count, dest = import_zip(args.zip, args.repo_root)
    print(f"Staged {count} files at {dest}")
    print("Reuses existing ml/models/A9_sin_id weights. No jobs were started.")
    print("After installing requirements: cd ml/a9_daily && python -m tests.test_diario")
    print("WARNING: source code currently evaluates SAME-DAY targets, not our 7-day horizon.")


if __name__ == "__main__":
    main()
