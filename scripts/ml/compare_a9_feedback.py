#!/usr/bin/env python3
"""Compare A9 Top-K after one vs two REAL CineGraph explicit ratings.

Historical MovieLens data, original checkpoint, UTC cutoff and user identity
are identical in both scenarios. Only the second local rating changes.

This is an exploratory ranking-sensitivity experiment, NOT a precision or
clinical/product performance evaluation and NOT an AWS deployment. No publishing
or modifications to the historical training data, checkpoint or PostgreSQL.
"""
from __future__ import annotations

import argparse
import gc
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ml"))
from run_a9_shadow import (  # noqa: E402
    A9_ROOT, ARTIFACTS, EXPECTED_MODEL_SHA256, MODEL, PROCESSED,
    assign_shadow_ids, hash_file, load_shadow_snapshot, stage,
    validate_candidate_rows,
)

OUTPUT_ROOT = ROOT / "artifacts" / "a9-feedback-comparison"


def select_scenarios(candidates: list[dict], user_id: int | None = None) -> tuple[int, list[dict], list[dict]]:
    """Earliest two unique, valid ratings from ONE local user, increasing in time.

    The candidates must have already passed stage verification and temporal
    validity checks; rechecks that they cannot contain repeated movie pairs.
    """
    by_user: dict[int, list[dict]] = {}
    seen = set()
    for item in candidates:
        uid, mid = item.get("user_id"), item.get("movie_id")
        if type(uid) is not int or uid <= 0 or type(mid) is not int or mid <= 0:
            raise ValueError("User/movie identifiers must be positive integers")
        if (uid, mid) in seen:
            raise ValueError("Repeated movie rating from a single user in staging data")
        seen.add((uid, mid))
        by_user.setdefault(uid, []).append(item)
    eligible = sorted(uid for uid, ratings in by_user.items() if len(ratings) >= 2)
    if user_id is None:
        if len(eligible) != 1:
            raise ValueError("Select --user-id: expected exactly one local user with >=2 explicit ratings, found " + str(eligible))
        user_id = eligible[0]
    if user_id not in eligible:
        raise ValueError(f"User {user_id} needs >=2 explicit ratings before the cutoff; available: {eligible}")
    selected = sorted(by_user[user_id], key=lambda r: (r["event_at"], r["source_event_id"], r["movie_id"]))[:2]
    return user_id, selected[:1], selected


def rank_metrics(top_one: list[dict], top_two: list[dict], k: int) -> dict:
    """Measure ranking displacement; never calculate accuracy without labels."""
    if not 1 <= k <= 50:
        raise ValueError("k must be between 1 and 50")
    def keyed(rows):
        if not rows or len(rows) > k:
            raise ValueError("Both scenarios need nonempty rankings no longer than k")
        ids = set()
        by_movie = {}
        positions = []
        for row in rows:
            movie_id = row.get("movie_id")
            rank = row.get("rank")
            score = row.get("raw_score_not_probability")
            if type(movie_id) is not int or movie_id <= 0 or type(rank) is not int or rank <= 0:
                raise ValueError("Invalid rank or movie id")
            if movie_id in ids or not isinstance(score, (int, float)) or not math.isfinite(score):
                raise ValueError("Duplicate movie or nonfinite score")
            ids.add(movie_id)
            positions.append(rank)
            by_movie[movie_id] = row
        if sorted(positions) != list(range(1, len(rows) + 1)):
            raise ValueError("Ranking has non-contiguous positions")
        return by_movie
    a, b = keyed(top_one), keyed(top_two)
    common = sorted(set(a) & set(b))
    n_union = len(a) + len(b) - len(common)
    return {
        "top_k_requested": k,
        "n_top_one": len(a), "n_top_two": len(b),
        "intersection_count": len(common),
        "overlap_at_k": round(len(common) / k, 6),
        "jaccard": round(len(common) / n_union, 6),
        "n_added": len(set(b) - set(a)),
        "n_removed": len(set(a) - set(b)),
        "added_movie_ids": sorted(set(b) - set(a)),
        "removed_movie_ids": sorted(set(a) - set(b)),
        "mean_abs_rank_displacement_shared": (
            round(sum(abs(a[x]["rank"] - b[x]["rank"]) for x in common) / len(common), 6)
            if common else None
        ),
        "mean_abs_score_delta_shared": (
            round(sum(abs(b[x]["raw_score_not_probability"] - a[x]["raw_score_not_probability"])
                      for x in common) / len(common), 6) if common else None
        ),
        "common_movie_changes": [
            {"movie_id": movie_id,
             "rank_one": a[movie_id]["rank"], "rank_two": b[movie_id]["rank"],
             "rank_change": a[movie_id]["rank"] - b[movie_id]["rank"],
             "score_one": a[movie_id]["raw_score_not_probability"],
             "score_two": b[movie_id]["raw_score_not_probability"]}
            for movie_id in common
        ],
        "interpretation": "Sensibilidad del ranking a una segunda calificación; NO mide precisión, recall, NDCG ni mejora de recomendación.",
    }


def standardized_rows(table, local_user_id: int, cutoff_str: str) -> list[dict]:
    rows = []
    for rec in table.to_dict("records"):
        rows.append({
            "cutoff_utc": cutoff_str,
            "user_namespace": "cinegraph-local",
            "cinegraph_user_id": local_user_id,
            "movie_id": int(rec["movieId"]),
            "rank": int(rec["posicion"]),
            "raw_score_not_probability": float(rec["puntaje"]),
            "title": str(rec["titulo"]),
        })
    return rows


def score_one_scenario(historical, movie_catalogue, added, shadow_user_id, cutoff_str, k):
    """Build a fresh graph and A9 model to avoid state contamination."""
    import pandas as pd
    from src.grafo import GrafoTemporal
    from src.recomendar import Recomendador

    newer = pd.DataFrame([{
        "userId": shadow_user_id, "movieId": r["movie_id"],
        "rating": r["rating"], "timestamp": r["timestamp"],
    } for r in added])
    for col, ty in (("userId", "int32"), ("movieId", "int32"),
                    ("rating", "float32"), ("timestamp", "int64")):
        newer[col] = newer[col].astype(ty)
    joined = pd.concat([historical, newer], ignore_index=True)
    del newer
    graph = GrafoTemporal(ratings=joined, movies=movie_catalogue, con_dias=True)
    del joined
    recommender = Recomendador(graph, movie_catalogue, dispositivo="cpu")
    table = recommender.recomendar([shadow_user_id], cutoff_str, k=k)
    del graph, recommender
    gc.collect()
    if table.empty:
        raise RuntimeError("Scenario produced no recommendations: do not fabricate a Top-K")
    return table


def run_comparison(cutoff_str: str, k: int = 10, user_id: int | None = None,
                   endpoint: str = "http://127.0.0.1:4566", output_root: Path = OUTPUT_ROOT) -> Path:
    cutoff = stage.valid_cutoff(cutoff_str)
    stage.validate_endpoint(endpoint)
    if hash_file(MODEL) != EXPECTED_MODEL_SHA256:
        raise RuntimeError("Original A9 checkpoint changed or missing: comparison blocked")
    for filename in ("ratings.parquet", "movies.parquet"):
        if not (PROCESSED / filename).is_file():
            raise FileNotFoundError("Run historical A9 preparation first: " + filename)

    manifest, candidate_rows = load_shadow_snapshot(stage.client(endpoint), cutoff_str)
    if manifest["status"] != "shadow_only_not_published":
        raise RuntimeError("Staging manifest must prohibit production publication")
    import pandas as pd
    sys.path.insert(0, str(A9_ROOT))
    catalogue = pd.read_parquet(PROCESSED / "movies.parquet")
    allowed_movies = set(map(int, catalogue["movieId"].to_numpy()))
    candidate_rows = validate_candidate_rows(candidate_rows, cutoff, allowed_movies)
    user_id, first, both = select_scenarios(candidate_rows, user_id)
    historical = pd.read_parquet(PROCESSED / "ratings.parquet", columns=["userId", "movieId", "rating", "timestamp"])
    limit = int(stage.midnight_utc(cutoff).timestamp())
    historical = historical.loc[historical["timestamp"] < limit].copy()
    if historical.empty:
        raise RuntimeError("Cutoff is before MovieLens history")
    for field, typ in (("userId", "int32"), ("movieId", "int32"),
                       ("rating", "float32"), ("timestamp", "int64")):
        historical[field] = historical[field].astype(typ)
    # Map all users in the verified staging dataset, not only the chosen user.
    # This keeps the user's shadow-graph ID stable across runs and scenarios.
    historical_max_id = int(historical["userId"].max())
    mapping = assign_shadow_ids([r["user_id"] for r in candidate_rows], historical_max_id)
    internal_id = mapping[user_id]
    print(f"Control A9: user namespace=cinegraph-local, user_id={user_id}, shadow_id={internal_id}", flush=True)
    print(f"Fixed cutoff={cutoff_str} 00:00 UTC, k={k}, MovieLens={len(historical):,} ratings", flush=True)
    print("Scenario 1: earliest one real rating", flush=True)
    a = standardized_rows(score_one_scenario(historical, catalogue, first, internal_id, cutoff_str, k), user_id, cutoff_str)
    print("Scenario 2: earliest two real ratings", flush=True)
    b = standardized_rows(score_one_scenario(historical, catalogue, both, internal_id, cutoff_str, k), user_id, cutoff_str)
    metrics = rank_metrics(a, b, k)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_path = output_root / f"{manifest['source_curated_snapshot']}-{cutoff_str}" / stamp
    run_path.mkdir(parents=True, exist_ok=False)
    outputs = {
        "one_rating_topk.jsonl": stage.jsonl_bytes(a),
        "two_ratings_topk.jsonl": stage.jsonl_bytes(b),
        "comparison.json": (json.dumps(metrics, ensure_ascii=False, indent=2) + "\n").encode(),
    }
    for name, value in outputs.items():
        (run_path / name).write_bytes(value)
    report = {
        "pipeline": "cinegraph-feedback-controlled-a9-v1",
        "environment": "Floci local with macOS CPU, NO AWS deployment",
        "status": "research_only_not_published",
        "cutoff_utc": cutoff_str,
        "tested_user_namespace": "cinegraph-local",
        "tested_user_id": user_id,
        "shadow_graph_user_id": internal_id,
        "rating_event_ids_first": [r["source_event_id"] for r in first],
        "rating_event_ids_both": [r["source_event_id"] for r in both],
        "historical_movielens_ratings_before_cutoff": len(historical),
        "historical_movie_count": len(catalogue),
        "source_shadow_manifest": stage.stage_manifest_key(manifest),
        "source_curated_snapshot": manifest["source_curated_snapshot"],
        "checkpoint_sha256": EXPECTED_MODEL_SHA256,
        "scenarios": {"one_rating": 1, "two_ratings": 2},
        "top_k": k,
        "files": [{"name": name, "sha256": stage.hash_bytes(content), "bytes": len(content)} for name, content in outputs.items()],
        "publication": {"postgresql": False, "production_s3": False, "retrained": False},
        "limitations": [
            "User had no pre-existing local MovieLens identity: a zero-feedback scenario is cold start and invalid as an A9 baseline.",
            "The experiment measures rank/score sensitivity to one additional authentic rating, not relevance or predictive performance.",
            "New interaction dates (2026) are outside the original historical validation; 7-day objective has not been evaluated.",
        ],
    }
    (run_path / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("SUCCESS: two A9 scenarios compared with checkpoint unchanged. NO production publication.")
    print("Shared Top-K:", metrics["intersection_count"], "/", k, "Jaccard:", metrics["jaccard"])
    print("New movies:", metrics["n_added"], "Removed:", metrics["n_removed"])
    print("Output:", run_path)
    return run_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutoff", required=True, help="YYYY-MM-DD day start at 00:00 UTC")
    parser.add_argument("--user-id", type=int, help="CineGraph-local user id; if omitted requires one eligible user")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--endpoint-url", default="http://127.0.0.1:4566")
    args = parser.parse_args(argv)
    if not 1 <= args.k <= 50:
        parser.error("k must be between 1 and 50")
    run_comparison(args.cutoff, k=args.k, user_id=args.user_id, endpoint=args.endpoint_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())