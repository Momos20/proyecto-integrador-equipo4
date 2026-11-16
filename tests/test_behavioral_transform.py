"""Pruebas offline: transformación fiel a eventos CineGraph, sin Docker ni AWS."""
import importlib.util
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "scripts/data/transform_behavioral_floci.py"
spec = importlib.util.spec_from_file_location("transform_behavioral_floci", SRC)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def event(kind="like", *, event_id=None, rating=None, user_id=123, movie_id=109487, at="2026-11-16T01:58:54+00:00"):
    return {"schema_version": 1, "event_id": event_id or str(uuid.uuid4()),
            "event_type": kind, "event_at": at, "event_source": "http",
            "user_id": user_id, "movie_id": movie_id, "rating": rating,
            "model_version": "a9-miguel-diario", "position": 1,
            "cutoff_date": "2023-06-15", "recommendation_id": "123:2023-06-15:1",
            "metadata": {"surface": "top10_a9"}}


class Body:
    def __init__(self, data): self.data = data
    def read(self, size=None): return self.data[:size] if size is not None else self.data


class FakeS3:
    def __init__(self, raw=None): self.objects = dict(raw or {})
    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        index = int(ContinuationToken or 0)
        page = keys[index:index + 2]
        return {"Contents": [{"Key": k} for k in page], "IsTruncated": index + 2 < len(keys),
                **({"NextContinuationToken": str(index + 2)} if index + 2 < len(keys) else {})}
    def get_object(self, Bucket, Key): return {"Body": Body(self.objects[Key])}
    def put_object(self, Bucket, Key, Body, ContentType): self.objects[Key] = Body


def rows(blob): return [json.loads(line) for line in blob.splitlines()]


def test_event_normalization_utc_and_traceability():
    item = pipeline.normalize_event(event(at="2026-11-15T20:58:54-05:00"))
    assert item["event_date"] == "2026-11-16"
    assert item["event_at"] == "2026-11-16T01:58:54+00:00"
    assert item["model_version"] == "a9-miguel-diario"
    assert item["cutoff_date"] == "2023-06-15"


@pytest.mark.parametrize("bad", [
    {"schema_version": 2},
    {"event_id": "not-uuid"},
    {"user_id": True},
    {"movie_id": 0},
    {"event_type": "hack"},
    {"event_at": "2026-11-15T21:00:00"},
    {"rating": 4.0},
])
def test_invalid_events_rejected(bad):
    item = event()
    item.update(bad)
    with pytest.raises(ValueError): pipeline.normalize_event(item)


def test_rating_allowed_half_star_only():
    item = pipeline.normalize_event(event("rating", rating=4.5))
    assert item["rating"] == 4.5
    for invalid in (0, 5.5, 3.3, None, float("nan")):
        with pytest.raises(ValueError): pipeline.normalize_event(event("rating", rating=invalid))


def test_pipeline_dedupe_quarantine_partition_and_features():
    e1 = event("like", at="2026-11-15T20:30:00-05:00")
    e2 = event("rating", rating=5, user_id=123, movie_id=109487)
    e3 = event("watchlist", user_id=123, movie_id=50872)
    invalid = event("rating", rating=20)
    conflicting = dict(e1, movie_id=999999)
    prefix = pipeline.RAW_PREFIX
    raw = {
        prefix + "b.jsonl": pipeline.jsonl_bytes([e1, e2]),
        prefix + "a.jsonl": pipeline.jsonl_bytes([e1, e3, invalid]),
        prefix + "c.jsonl": pipeline.jsonl_bytes([conflicting]),
    }
    s3 = FakeS3(raw)
    manifest, outputs = pipeline.build_snapshot(s3)
    assert manifest["stats"]["valid_events"] == 3
    assert manifest["stats"]["raw_lines"] == 6
    assert manifest["stats"]["duplicates"] == 2
    assert manifest["stats"]["conflicting_duplicates"] == 1
    assert manifest["stats"]["invalid_rows"] == 1
    curated_key = next(k for k in outputs if "event_date=2026-11-16/" in k)
    curated = rows(outputs[curated_key])
    assert len(curated) == 3
    assert set(x["event_id"] for x in curated) == {e1["event_id"], e2["event_id"], e3["event_id"]}
    um = rows(next(v for k, v in outputs.items() if k.endswith("user_movie_daily.jsonl")))
    one = next(x for x in um if x["movie_id"] == 109487)
    assert (one["n_events"], one["n_like"], one["n_rating"], one["avg_rating"]) == (2, 1, 1, 5.0)
    ud = rows(next(v for k, v in outputs.items() if k.endswith("user_daily.jsonl")))
    assert len(ud) == 1 and ud[0]["n_movies"] == 2 and ud[0]["n_events"] == 3
    q = rows(next(v for k, v in outputs.items() if k.endswith("quarantine.jsonl")))
    assert len(q) == 2 and {x["reason"] for x in q} >= {"conflicting_event_id"}
    assert pipeline.build_snapshot(s3) == (manifest, outputs)  # reproducción determinista
    pipeline.put_outputs(s3, manifest, outputs)
    assert pipeline.verify_outputs(s3)["snapshot"] == manifest["snapshot"]
    # Repetir sobre mismo Raw no duplica eventos ni cambia claves/manifest.
    m2, output2 = pipeline.build_snapshot(s3)
    assert m2 == manifest and output2 == outputs


def test_verify_detects_modified_outputs():
    e = event()
    s3 = FakeS3({pipeline.RAW_PREFIX + "event.jsonl": pipeline.jsonl_bytes([e])})
    manifest, outputs = pipeline.build_snapshot(s3)
    pipeline.put_outputs(s3, manifest, outputs)
    first = manifest["outputs"][0]["key"]
    s3.objects[first] = b"tampered"
    with pytest.raises(RuntimeError, match="checksum"): pipeline.verify_outputs(s3)


def test_no_raw_events_does_not_publish():
    with pytest.raises(RuntimeError, match="No hay eventos"):
        pipeline.build_snapshot(FakeS3())


def test_local_endpoint_never_allows_real_aws():
    for url in ["https://s3.amazonaws.com", "http://example.com:4566", "http://floci:4567",
                "http://floci:4566/path", "http://floci:4566?redirect=x", "http://user:pass@floci:4566"]:
        with pytest.raises(ValueError): pipeline.validate_local_endpoint(url)
    assert pipeline.validate_local_endpoint("http://floci:4566") == "http://floci:4566"


def test_snapshot_fingerprint_changes_with_new_raw():
    e = event()
    s3 = FakeS3({pipeline.RAW_PREFIX + "a": pipeline.jsonl_bytes([e])})
    one, _ = pipeline.build_snapshot(s3)
    s3.objects[pipeline.RAW_PREFIX + "b"] = pipeline.jsonl_bytes([event()])
    two, _ = pipeline.build_snapshot(s3)
    assert two["snapshot"] != one["snapshot"]
    assert two["stats"]["valid_events"] == 2


def test_compose_has_manual_local_job():
    compose = (ROOT / "docker-compose.floci.yml").read_text("utf-8")
    job = compose.split("  behavioral-transform:", 1)[1].split("\n  a9-publish:", 1)[0]
    assert 'profiles: ["floci"]' in job
    assert 'dockerfile: infrastructure/docker/behavioral-transform.Dockerfile' in job
    assert "http://floci:4566" in job
    assert 'run --rm behavioral-transform' not in compose  # no automatic invocation