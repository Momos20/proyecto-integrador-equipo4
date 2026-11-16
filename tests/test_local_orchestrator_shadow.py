"""No requiere Docker, MovieLens, AWS ni descarga de datos durante pruebas."""
from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))


def load(name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel_path)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[name] = obj
    spec.loader.exec_module(obj)
    return obj


t = load("transform_behavioral_floci", "scripts/data/transform_behavioral_floci.py")
s = load("stage_a9_feedback_floci", "scripts/ml/stage_a9_feedback_floci.py")
o = load("orchestrate_local", "scripts/local_aws/orchestrate_local.py")
r = load("run_a9_shadow", "scripts/ml/run_a9_shadow.py")


def event(kind, at, *, eid=None, user=123, movie=109487, rating=None):
    return t.normalize_event({
        "schema_version": 1,
        "event_id": eid or str(uuid.uuid4()),
        "event_type": kind,
        "event_at": at,
        "event_source": "http",
        "user_id": user,
        "movie_id": movie,
        "rating": rating,
        "model_version": "a9-miguel-diario",
        "cutoff_date": "2023-06-15",
        "metadata": {"surface": "top10_a9"},
    })


class S3NoSuchKey(Exception): pass


class FakeS3:
    exceptions = SimpleNamespace(NoSuchKey=S3NoSuchKey)

    def __init__(self, objects):
        self.objects = dict(objects)

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise S3NoSuchKey(Key)
        return {"Body": SimpleNamespace(read=lambda n=None: self.objects[Key][:n])}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[Key] = Body


@pytest.fixture
def curated():
    snapshot = "a" * 24
    cutoff = "2026-11-17"
    items = [
        event("like", "2026-11-15T20:30:00-05:00"),
        event("rating", "2026-11-16T01:00:00+00:00", rating=3.5),
        event("rating", "2026-11-16T02:00:00+00:00", rating=4.5),
        event("watchlist", "2026-11-16T03:00:00+00:00", movie=50872),
        event("rating", "2026-11-17T00:00:00+00:00", movie=50872, rating=5.0),
    ]
    key = f"{t.CURATED_PREFIX}snapshots/{snapshot}/event_date=2026-11-16/events.jsonl"
    key_future = f"{t.CURATED_PREFIX}snapshots/{snapshot}/event_date=2026-11-17/events.jsonl"
    daily = f"{t.FEATURES_PREFIX}snapshots/{snapshot}/user_daily.jsonl"
    movie = f"{t.FEATURES_PREFIX}snapshots/{snapshot}/user_movie_daily.jsonl"
    blobs = {
        key: t.jsonl_bytes(items[:-1]),
        key_future: t.jsonl_bytes([items[-1]]),
        daily: t.jsonl_bytes([{"event_date": "2026-11-16", "user_id": 123, "n_events": 4},
                              {"event_date": "2026-11-17", "user_id": 123, "n_events": 1}]),
        movie: t.jsonl_bytes([{"event_date": "2026-11-16", "user_id": 123, "movie_id": 109487, "n_events": 3},
                              {"event_date": "2026-11-17", "user_id": 123, "movie_id": 50872, "n_events": 1}]),
    }
    manifest = {"pipeline": s.EXPECTED_SOURCE_PIPELINE, "snapshot": snapshot,
                "outputs": [{"key": key, "bytes": len(data), "sha256": s.hash_bytes(data)} for key, data in blobs.items()]}
    return cutoff, manifest, blobs


def test_snapshot_filters_cutoff_and_uses_explicit_last_rating_only(curated):
    cutoff, source, blobs = curated
    m, outputs = s.build_stage(source, blobs, s.valid_cutoff(cutoff))
    assert m["stats"]["source_curated_events"] == 5
    assert m["stats"]["excluded_on_or_after_cutoff"] == 1
    assert m["stats"]["rating_candidate_edges"] == 1
    assert m["stats"]["eligible_explicit_rating_events"] == 2
    assert m["merge_into_movielens_original_ids_allowed"] is False
    assert m["converted_like_to_rating"] is False
    ratings = next(s.decode_jsonl(v) for k, v in outputs.items() if k.endswith("ratings_candidates.jsonl"))
    assert len(ratings) == 1
    assert ratings[0]["rating"] == 4.5
    assert ratings[0]["user_id"] == 123
    assert ratings[0]["user_namespace"] == "cinegraph-local"
    assert ratings[0]["movie_namespace"] == "movielens32m"
    daily = next(s.decode_jsonl(v) for k, v in outputs.items() if k.endswith("user_daily_context.jsonl"))
    assert len(daily) == 1 and daily[0]["event_date"] == "2026-11-16"


def test_snapshot_publishes_immutable_outputs_and_verifies_hashes(curated):
    cutoff, source, blobs = curated
    manifest, outputs = s.build_stage(source, blobs, s.valid_cutoff(cutoff))
    store = FakeS3({s.CURATED_LATEST_KEY: t.to_json_bytes(source), **blobs})
    verified_source, verified_blobs = s.verified_source(store)
    assert verified_source["snapshot"] == source["snapshot"]
    assert len(verified_blobs) == 4
    s.publish(store, manifest, outputs)
    assert s.verify_stage(store, expected_cutoff=cutoff)["stats"]["rating_candidate_edges"] == 1
    # Ejecución idempotente para el mismo snapshot y mismo corte.
    s.publish(store, manifest, outputs)
    candidate_key = next(k for k in outputs if k.endswith("ratings_candidates.jsonl"))
    store.objects[candidate_key] = b"tampered"
    with pytest.raises(RuntimeError, match="Integridad"):
        s.verify_stage(store, expected_cutoff=cutoff)
    with pytest.raises(RuntimeError, match="sobrescribir"):
        s.publish(store, manifest, outputs)


def test_shadow_rejects_corrupt_curated_source(curated):
    cutoff, source, blobs = curated
    key = next(iter(blobs))
    bad = FakeS3({s.CURATED_LATEST_KEY: t.to_json_bytes(source), **blobs})
    bad.objects[key] = b"tampered"
    with pytest.raises(ValueError, match="Integridad"):
        s.verified_source(bad)


def test_shadow_source_is_local_only():
    for value in ("https://s3.amazonaws.com", "http://amazonaws.com:4566", "http://floci:80",
                  "http://other:4566", "http://floci:4566/path", "http://user:pw@floci:4566"):
        with pytest.raises(ValueError):
            s.validate_endpoint(value)
    assert s.validate_endpoint("http://127.0.0.1:4566") == "http://127.0.0.1:4566"


def test_shadow_strictly_separates_cinegraph_and_movielens_identity():
    mapping = r.assign_shadow_ids([456, 123, 123, 414], largest_movielens_user=200948)
    assert mapping == {123: 200949, 414: 200950, 456: 200951}
    assert set(mapping.values()).isdisjoint({123, 414, 456})
    with pytest.raises(OverflowError):
        r.assign_shadow_ids([1], largest_movielens_user=2**31-1)
    with pytest.raises(ValueError):
        r.assign_shadow_ids([0], largest_movielens_user=200948)


def test_shadow_candidate_gate_blocks_future_invalid_and_wrong_namespace(curated):
    cutoff, manifest, blobs = curated
    staged, outputs = s.build_stage(manifest, blobs, s.valid_cutoff(cutoff))
    row = next(s.decode_jsonl(v)[0] for k, v in outputs.items() if k.endswith("ratings_candidates.jsonl"))
    assert r.validate_candidate_rows([row], s.valid_cutoff(cutoff), {109487}) == [row]
    with pytest.raises(ValueError, match="Identidad"):
        r.validate_candidate_rows([{**row, "user_namespace": "movielens32m"}], s.valid_cutoff(cutoff), {109487})
    with pytest.raises(ValueError, match="Fuga temporal"):
        r.validate_candidate_rows([{**row, "event_at": "2026-11-17T00:00:00+00:00", "timestamp": 1794873600}],
                                  s.valid_cutoff(cutoff), {109487})
    with pytest.raises(ValueError, match="no existe"):
        r.validate_candidate_rows([row], s.valid_cutoff(cutoff), {318})
    with pytest.raises(ValueError, match="Más de una"):
        r.validate_candidate_rows([row, row], s.valid_cutoff(cutoff), {109487})
    with pytest.raises(ValueError, match="Rating"):
        r.validate_candidate_rows([{**row, "rating": 4.3}], s.valid_cutoff(cutoff), {109487})


def test_orchestrator_step_order_and_fail_fast(tmp_path, monkeypatch):
    names = [name for name, _ in o.steps("2026-11-17")]
    assert names == ["01-ship", "02-verify-raw", "03-transform", "04-verify-curated-features",
                     "05-stage-a9-shadow", "06-verify-a9-shadow"]
    root = tmp_path / "repo"
    root.mkdir()
    (root / "docker-compose.floci.yml").write_text("services: {}")
    monkeypatch.setattr(o, "ROOT", root)
    called = []
    def fake_run(name, cmd, directory):
        called.append(name)
        return {"step": name, "exit_code": 1 if name == "03-transform" else 0,
                "status": "failed" if name == "03-transform" else "ok", "log": name + ".log"}
    monkeypatch.setattr(o, "run_step", fake_run)
    assert o.execute("2026-11-17", run_dir=tmp_path / "runs") == 1
    assert called == names[:3]
    summary = json.loads(next((tmp_path / "runs").glob("*/summary.json")).read_text())
    assert summary["status"] == "failed" and summary["failed_at"] == "03-transform"


def test_orchestrator_success_and_dry_run_is_side_effect_free(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "docker-compose.floci.yml").write_text("services: {}")
    monkeypatch.setattr(o, "ROOT", root)
    invoked = []
    def fake_run(name, cmd, directory):
        invoked.append(name)
        return {"step": name, "exit_code": 0, "status": "ok", "log": name + ".log"}
    monkeypatch.setattr(o, "run_step", fake_run)
    out = tmp_path / "runs"
    assert o.execute("2026-11-17", dry_run=True, run_dir=out) == 0
    assert not out.exists() and not invoked
    assert o.execute("2026-11-17", run_dir=out) == 0
    summary = json.loads(next(out.glob("*/summary.json")).read_text())
    assert summary["status"] == "succeeded" and len(invoked) == 6


def test_cutoff_date_is_strict():
    assert s.valid_cutoff("2026-11-17") == date(2026, 11, 17)
    assert o.validate_cutoff("2026-11-17") == "2026-11-17"
    with pytest.raises(ValueError): s.valid_cutoff("2026-11-17T00:00:00")


def test_nonrating_feedback_keeps_context_without_faking_ratings(curated):
    cutoff, source, blobs = curated
    # Una ejecución puede contener únicamente likes o watchlist: no sintetizar ratings.
    item = event("watchlist", "2026-11-16T03:00:00+00:00", movie=50872)
    for key in list(blobs):
        if key.endswith("/events.jsonl"):
            blobs[key] = t.jsonl_bytes([item]) if item["event_date"] in key else b""
    m, outputs = s.build_stage(source, blobs, s.valid_cutoff(cutoff))
    assert m["stats"]["rating_candidate_edges"] == 0
    assert m["stats"]["eligible_pre_cutoff_events"] == 1
    ratings = next(s.decode_jsonl(v) for k, v in outputs.items() if k.endswith("ratings_candidates.jsonl"))
    assert ratings == []
    # Los aggregates del pasado siguen disponibles para análisis observacional.
    context = next(s.decode_jsonl(v) for k, v in outputs.items() if k.endswith("user_daily_context.jsonl"))
    assert context and context[0]["user_namespace"] == "cinegraph-local"


def test_orchestrator_does_not_start_shadow_scoring():
    all_commands = [" ".join(cmd) for _, cmd in o.steps("2026-11-17")]
    assert "run_a9_shadow.py" not in " ".join(all_commands)
    assert "a9-publish" not in " ".join(all_commands)
    assert "scripts/ml/run_a9_floci.py" not in " ".join(all_commands)