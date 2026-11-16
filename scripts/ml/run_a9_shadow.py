#!/usr/bin/env python3
"""Inferencia opcional y EXPLORATORIA de A9 con nuevos ratings CineGraph.

Nunca reentrena ni publica en PostgreSQL/`predictions/a9/`. Lee las features
shadow validadas en Floci, remapea usuarios CineGraph a IDs nuevos disjuntos,
filtra el pasado estricto en UTC y ejecuta el código A9 de Miguel sin editarlo.

Solo son aristas rating explícitas; NO se convierten like/watchlist en ratings.
Los resultados de 2026 son una prueba de compatibilidad, NO métricas validadas.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
A9_ROOT = ROOT / "ml" / "a9_daily"
ARTIFACTS = ROOT / "artifacts" / "a9-shadow"
EXPECTED_MODEL_SHA256 = "8c9aa61fb7e8d3ed3a6476fe759f9861283387bc6561ea5aa03595ab516a2358"
MODEL = ROOT / "ml" / "models" / "A9_sin_id" / "modelo.pt"
PROCESSED = A9_ROOT / "data" / "processed"
sys.path.insert(0, str(ROOT / "scripts" / "data"))
import stage_a9_feedback_floci as stage  # noqa: E402 - cargado desde carpeta local controlada


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def assign_shadow_ids(local_user_ids: list[int], largest_movielens_user: int) -> dict[int, int]:
    """Jamás confundir los numerales cine123/123 con identidades MovieLens 123.

    IDs estrictamente mayores al máximo histórico y estables por orden local.
    No modifica ninguna tabla fuente ni usuario real.
    """
    if not isinstance(largest_movielens_user, int) or largest_movielens_user < 1:
        raise ValueError("max_user_id histórico inválido")
    distinct = sorted(set(local_user_ids))
    if any(type(uid) is not int or uid <= 0 for uid in distinct):
        raise ValueError("user_id local inválido")
    if largest_movielens_user + len(distinct) >= 2**31:
        raise OverflowError("Demasiados usuarios para IDs int32 del grafo A9")
    return {uid: largest_movielens_user + i + 1 for i, uid in enumerate(distinct)}


def validate_candidate_rows(rows: list[dict], cutoff: date, allowed_movies: set[int]) -> list[dict]:
    """Validaciones no eludibles antes de añadir aristas a un grafo experimental."""
    upper = stage.midnight_utc(cutoff)
    seen = set()
    clean = []
    for row in rows:
        if (row.get("user_namespace") != "cinegraph-local"
                or row.get("movie_namespace") != "movielens32m"):
            raise ValueError("Identidad no namespaced: nunca fusionar userId de MovieLens")
        uid, movie = row.get("user_id"), row.get("movie_id")
        if type(uid) is not int or uid <= 0 or type(movie) is not int or movie <= 0:
            raise ValueError("Usuario o película inválidos")
        if movie not in allowed_movies:
            raise ValueError(f"Película {movie} no existe en el catálogo histórico MovieLens verificado")
        if (uid, movie) in seen:
            raise ValueError("Más de una calificación para el mismo par; resolver últimas antes de inferencia")
        seen.add((uid, movie))
        value = row.get("rating")
        if (type(value) not in (int, float) or not 0.5 <= value <= 5.0
                or float(value * 2).is_integer() is False):
            raise ValueError("Rating inválido: A9 solo consume calificaciones explícitas")
        at = datetime.fromisoformat(row["event_at"])
        if at.tzinfo is None or at.utcoffset() is None or at >= upper:
            raise ValueError("Fuga temporal: rating local no es anterior al corte UTC")
        expected_ts = int(at.timestamp())
        if type(row.get("timestamp")) is not int or row["timestamp"] != expected_ts:
            raise ValueError("Timestamp no coincide con event_at UTC")
        clean.append(row)
    return clean


def load_shadow_snapshot(s3, cutoff: str) -> tuple[dict, list[dict]]:
    manifest = stage.verify_stage(s3, expected_cutoff=cutoff)
    entries = [x for x in manifest["outputs"] if x["key"].endswith("/ratings_candidates.jsonl")]
    if len(entries) != 1:
        raise RuntimeError("Shadow carece de un único archivo de ratings explícitos")
    candidates = stage.decode_jsonl(stage.get_bytes(s3, entries[0]["key"]))
    if len(candidates) != manifest["stats"]["rating_candidate_edges"]:
        raise RuntimeError("Conteos shadow inconsistentes")
    return manifest, candidates


def score_shadow(cutoff_str: str, k: int, endpoint: str, output_root: Path = ARTIFACTS) -> Path:
    cutoff = stage.valid_cutoff(cutoff_str)
    # Nunca se toca la versión original de A9 ni el histórico en Parquet.
    if not MODEL.is_file() or hash_file(MODEL) != EXPECTED_MODEL_SHA256:
        raise RuntimeError("Checkpoint A9 de Miguel faltante o hash diferente; inferencia bloqueada")
    for name in ("ratings.parquet", "movies.parquet"):
        if not (PROCESSED / name).is_file():
            raise FileNotFoundError(f"Falta {PROCESSED / name}; corre primero la inferencia histórica A9")

    s3 = stage.client(endpoint)
    manifest, candidates = load_shadow_snapshot(s3, cutoff_str)
    if not candidates:
        raise RuntimeError("No hay calificaciones CineGraph anteriores al corte; likes/watchlist no se convierten en ratings")

    import pandas as pd
    import numpy as np
    import torch
    sys.path.insert(0, str(A9_ROOT))
    from src.grafo import GrafoTemporal
    from src.recomendar import Recomendador

    movies = pd.read_parquet(PROCESSED / "movies.parquet")
    ratings = pd.read_parquet(PROCESSED / "ratings.parquet", columns=["userId", "movieId", "rating", "timestamp"])
    if ratings.empty:
        raise RuntimeError("MovieLens histórico vacío")
    # Protección adicional si se realiza un experimento retrospectivo.
    limit = int(stage.midnight_utc(cutoff).timestamp())
    ratings = ratings.loc[ratings["timestamp"] < limit].copy()
    if ratings.empty:
        raise RuntimeError("El corte precede a todas las calificaciones históricas")
    known_movie_ids = set(map(int, movies["movieId"].to_numpy()))
    candidates = validate_candidate_rows(candidates, cutoff, known_movie_ids)
    real_max = int(ratings["userId"].max())
    mapping = assign_shadow_ids([int(x["user_id"]) for x in candidates], real_max)
    shadow = pd.DataFrame([{
        "userId": mapping[e["user_id"]], "movieId": e["movie_id"],
        "rating": e["rating"], "timestamp": e["timestamp"],
    } for e in candidates])
    for col, typ in (("userId", "int32"), ("movieId", "int32"),
                     ("rating", "float32"), ("timestamp", "int64")):
        ratings[col] = ratings[col].astype(typ)
        shadow[col] = shadow[col].astype(typ)
    combined = pd.concat([ratings, shadow], ignore_index=True)
    del ratings, shadow

    print(f"Shadow A9: {len(candidates)} ratings locales auténticos; {len(mapping)} usuarios namespaced", flush=True)
    print(f"Cutoff UTC: {cutoff_str}; solo eventos anteriores al inicio del día", flush=True)
    print("Checkpoint original sin reentrenamiento; NO se publicarán resultados de este experimento", flush=True)
    grafo = GrafoTemporal(ratings=combined, movies=movies, con_dias=True)
    del combined
    recommender = Recomendador(grafo, movies, dispositivo="cpu")
    table = recommender.recomendar(sorted(mapping.values()), cutoff_str, k=k)
    if table.empty:
        raise RuntimeError("A9 shadow no produjo candidatos; no se publica ningún ranking")

    reverse = {mapped: original for original, mapped in mapping.items()}
    rows = []
    for rec in table.to_dict("records"):
        shadow_id = int(rec["userId"])
        rows.append({
            "cutoff_utc": cutoff_str,
            "user_namespace": "cinegraph-local",
            "cinegraph_user_id": reverse[shadow_id],
            "shadow_graph_user_id": shadow_id,
            "movie_id": int(rec["movieId"]), "rank": int(rec["posicion"]),
            "raw_score_not_probability": float(rec["puntaje"]),
            "title": str(rec["titulo"]),
        })
    # Los JSON locales NO tienen forma del publicador A9 y viven fuera de Git.
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output_dir = output_root / f"{manifest['source_curated_snapshot']}-{cutoff_str}" / batch_id
    output_dir.mkdir(parents=True, exist_ok=False)
    predictions = output_dir / "shadow_topk.jsonl"
    predictions.write_bytes(stage.jsonl_bytes(rows))
    meta = {
        "pipeline": "cinegraph-a9-shadow-scoring-exploratory-v1", "status": "research_only_not_published",
        "cutoff_utc": cutoff_str, "source_shadow_snapshot": manifest["source_curated_snapshot"],
        "source_shadow_manifest": stage.stage_manifest_key(manifest),
        "original_checkpoint_sha256": EXPECTED_MODEL_SHA256,
        "historic_movielens_user_id_max": real_max,
        "shadow_ids": [{"cinegraph_user_id": old, "shadow_graph_user_id": new}
                       for old, new in sorted(mapping.items())],
        "ratings_added": len(candidates), "top_k_written": len(rows),
        "output_sha256": hash_file(predictions),
        "model": "GraphSAGE A9 (código y pesos originales); horizonte diario UTC",
        "warning": "Inferencia experimental fuera de periodo validado; sin evaluación de rendimiento ni incorporación a producción.",
    }
    (output_dir / "manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("SUCCESS: A9 shadow ejecutado; NINGÚN resultado se envió a PostgreSQL o al S3 de producción.")
    print("Salida de laboratorio:", predictions)
    print("Usuarios:", len(mapping), "Ranking rows:", len(rows))
    return output_dir


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cutoff", required=True, help="día de scoring futuro AAAA-MM-DD UTC")
    p.add_argument("--k", type=int, default=10)
    p.add_argument("--endpoint-url", default="http://127.0.0.1:4566")
    args = p.parse_args(argv)
    if not 1 <= args.k <= 50:
        p.error("k debe estar entre 1 y 50")
    stage.validate_endpoint(args.endpoint_url)
    score_shadow(args.cutoff, args.k, args.endpoint_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())