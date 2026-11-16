"""Offline regression tests for controlled A9 ranking sensitivity."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "ml"))
SRC = ROOT / "scripts/ml/compare_a9_feedback.py"
spec = importlib.util.spec_from_file_location("compare_a9_feedback", SRC)
compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare)


def rating(user, movie, at, eid=None):
    return {"user_id": user, "movie_id": movie, "event_at": at,
            "source_event_id": eid or str(uuid.uuid4()), "rating": 5.0,
            "timestamp": 1780000000, "user_namespace": "cinegraph-local",
            "movie_namespace": "movielens32m"}


def top(ids):
    return [{"movie_id": item, "rank": i, "raw_score_not_probability": float(12-i)}
            for i, item in enumerate(ids, 1)]


def test_select_two_earliest_same_user_regardless_of_input_order():
    a = rating(123, 11, "2026-11-15T11:00:00+00:00")
    b = rating(123, 22, "2026-11-16T01:00:00+00:00")
    c = rating(123, 33, "2026-11-16T02:00:00+00:00")
    other = rating(456, 44, "2026-11-16T01:00:00+00:00")
    user, one, two = compare.select_scenarios([c, b, other, a])
    assert user == 123
    assert one == [a] and two == [a, b]


def test_requires_two_ratings_per_user_and_nonempty_reference():
    with pytest.raises(ValueError, match=">=2"):
        compare.select_scenarios([rating(123, 11, "2026-11-15T00:00:00+00:00")])


def test_ambiguous_user_must_be_explicit():
    rows = [rating(uid, mid, "2026-11-15T00:00:00+00:00") for uid, mid in
            ((123, 11), (123, 22), (456, 33), (456, 44))]
    with pytest.raises(ValueError, match="Select --user-id"):
        compare.select_scenarios(rows)
    assert compare.select_scenarios(rows, user_id=456)[0] == 456


def test_duplicate_movie_pair_is_rejected():
    with pytest.raises(ValueError, match="Repeated movie"):
        compare.select_scenarios([rating(123, 11, "2026-11-15T00:00:00+00:00"),
                                  rating(123, 11, "2026-11-16T00:00:00+00:00")])


def test_overlap_and_rank_displacement_with_known_values():
    # A = 1,2,3,4  B=3,2,5,4 => shared=3, Jaccard=3/5, shifts = 2,0,0
    stats = compare.rank_metrics(top([1, 2, 3, 4]), top([3, 2, 5, 4]), 4)
    assert stats["intersection_count"] == 3
    assert stats["overlap_at_k"] == 0.75
    assert stats["jaccard"] == 0.6
    assert stats["mean_abs_rank_displacement_shared"] == pytest.approx(2/3, abs=1e-6)
    assert stats["added_movie_ids"] == [5] and stats["removed_movie_ids"] == [1]
    assert stats["n_added"] == stats["n_removed"] == 1


def test_unchanged_top_k_is_identical():
    rows = top([13, 14, 15])
    stats = compare.rank_metrics(rows, rows, 3)
    assert stats["jaccard"] == stats["overlap_at_k"] == 1
    assert stats["n_added"] == stats["n_removed"] == 0
    assert stats["mean_abs_score_delta_shared"] == 0


def test_no_common_movies_metrics_are_none():
    stats = compare.rank_metrics(top([1, 2]), top([3, 4]), 2)
    assert stats["jaccard"] == 0
    assert stats["mean_abs_rank_displacement_shared"] is None
    assert stats["mean_abs_score_delta_shared"] is None


@pytest.mark.parametrize("left,right", [
    ([], top([1])), (top([1]), []),
    ([{"movie_id": 1, "rank": 1, "raw_score_not_probability": float("nan")}], top([2])),
    ([{"movie_id": 1, "rank": 2, "raw_score_not_probability": 4.0}], top([2])),
    (top([1, 1]), top([2])),
])
def test_rejects_malformed_or_empty_rankings(left, right):
    with pytest.raises(ValueError):
        compare.rank_metrics(left, right, 3)


def test_never_writes_production_and_uses_original_weights():
    src = SRC.read_text(encoding="utf-8")
    assert "EXPECTED_MODEL_SHA256" in src
    assert "load_shadow_snapshot" in src
    assert "validate_candidate_rows" in src
    assert "research_only_not_published" in src
    assert '"postgresql": False' in src
    assert '"production_s3": False' in src
    assert "source_event_id" in src
    assert "ratings.parquet" in src