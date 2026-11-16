#!/usr/bin/env python3
"""Floci local: prepara feedback REAL como entrada aislada de futuras inferencias.

Curated/Features verificadas -> snapshot shadow-only. No mezcla identidades
MovieLens con cuentas CineGraph, no convierte likes en ratings ni entrena A9.
Un evento del propio día del corte nunca se usa como entrada (sin fuga).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

from transform_behavioral_floci import (
    BUCKET, FEATURES_PREFIX, LATEST_KEY as CURATED_LATEST_KEY, CURATED_PREFIX,
    normalize_event, to_json_bytes, jsonl_bytes,
)

STAGE_PREFIX = FEATURES_PREFIX + "a9-shadow/"
STAGE_LATEST_KEY = STAGE_PREFIX + "latest.json"
EXPECTED_SOURCE_PIPELINE = "cinegraph-local-raw-curated-features-v1"
STAGE_PIPELINE = "cinegraph-a9-feedback-shadow-v1"
MAX_INPUT_BYTES = 64 * 1024 * 1024


def validate_endpoint(url: str) -> str:
    p = urlsplit(url)
    if (p.scheme != "http" or p.hostname not in ("localhost", "127.0.0.1", "floci")
            or p.port != 4566 or p.path not in ("", "/") or p.query or p.fragment
            or p.username or p.password):
        raise ValueError("Solo se permite el S3 emulado por Floci local, puerto 4566")
    return url.rstrip("/")


def valid_cutoff(value: str) -> date:
    try:
        day = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("Corte UTC inválido: utilice AAAA-MM-DD") from None
    if day.isoformat() != value:
        raise ValueError("Corte UTC no canónico")
    return day


def midnight_utc(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get_bytes(s3, key: str) -> bytes:
    body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read(MAX_INPUT_BYTES + 1)
    if len(body) > MAX_INPUT_BYTES:
        raise RuntimeError("Objeto S3 demasiado grande: " + key)
    return body


def verified_source(s3) -> tuple[dict, dict[str, bytes]]:
    """Revalida todas las salidas Curated/Features antes de usarlas como datos ML."""
    source = json.loads(get_bytes(s3, CURATED_LATEST_KEY))
    if (source.get("pipeline") != EXPECTED_SOURCE_PIPELINE
            or not re.fullmatch(r"[0-9a-f]{24}", str(source.get("snapshot", "")))):
        raise ValueError("Manifiesto Curated no reconocido")
    entries = source.get("outputs")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Curated carece de salidas verificables")
    blobs = {}
    for entry in entries:
        key = entry.get("key")
        if not isinstance(key, str) or not key.startswith((CURATED_PREFIX + "snapshots/", FEATURES_PREFIX + "snapshots/")):
            raise ValueError("Ruta de salida Curated/Features incorrecta")
        if source["snapshot"] not in key:
            raise ValueError("Salida no pertenece al snapshot Curated anunciado")
        if key in blobs:
            raise ValueError("Salida duplicada en el manifiesto Curated")
        data = get_bytes(s3, key)
        if len(data) != entry.get("bytes") or hash_bytes(data) != entry.get("sha256"):
            raise ValueError("Integridad Curated/Features fallida: " + key)
        blobs[key] = data
    return source, blobs


def decode_jsonl(blob: bytes) -> list[dict]:
    result = []
    for line in blob.splitlines():
        if line.strip():
            result.append(json.loads(line))
    return result


def build_stage(source: dict, verified_blobs: dict[str, bytes], cutoff: date) -> tuple[dict, dict[str, bytes]]:
    snapshot = source["snapshot"]
    base = f"{STAGE_PREFIX}snapshots/{snapshot}/cutoff_date={cutoff.isoformat()}/"
    limit = midnight_utc(cutoff)
    curated_files = sorted((k, v) for k, v in verified_blobs.items()
                           if k.startswith(f"{CURATED_PREFIX}snapshots/{snapshot}/")
                           and k.endswith("/events.jsonl"))
    if not curated_files:
        raise ValueError("Curated no contiene eventos válidos")

    # Los eventos Curated son únicos por event_id; volver a validarlos contra el schema v1.
    eligible = []
    event_ids = set()
    future = 0
    for _, blob in curated_files:
        for row in decode_jsonl(blob):
            e = normalize_event(row)
            if e != row:
                raise ValueError("El evento Curated no está normalizado al schema v1")
            if e["event_id"] in event_ids:
                raise ValueError("Duplicado event_id inesperado en Curated")
            event_ids.add(e["event_id"])
            occurred = datetime.fromisoformat(e["event_at"])
            if occurred >= limit:
                future += 1
                continue
            eligible.append(e)
    eligible.sort(key=lambda e: (e["event_at"], e["event_id"]))
    # Solo una calificación explícita puede generar una arista de MovieLens. La más
    # reciente de un par usuario-película domina, con desempate determinista por UUID.
    ratings_latest: dict[tuple[int, int], dict] = {}
    for e in eligible:
        if e["event_type"] == "rating":
            ratings_latest[(e["user_id"], e["movie_id"])] = e
    rating_rows = []
    for (user, movie), e in sorted(ratings_latest.items()):
        rating_rows.append({
            "user_namespace": "cinegraph-local", "user_id": user,
            "movie_namespace": "movielens32m", "movie_id": movie,
            "rating": e["rating"], "timestamp": int(datetime.fromisoformat(e["event_at"]).timestamp()),
            "event_at": e["event_at"], "source_event_id": e["event_id"],
        })

    # Preparar features contextuales reales sin colar datos del día a predecir.
    contexts = {}
    for kind in ("user_daily", "user_movie_daily"):
        key = f"{FEATURES_PREFIX}snapshots/{snapshot}/{kind}.jsonl"
        if key not in verified_blobs:
            raise ValueError("Falta Feature verificada: " + kind)
        rows = []
        for e in decode_jsonl(verified_blobs[key]):
            dt = e.get("event_date")
            if not isinstance(dt, str) or valid_cutoff(dt) < date(1970, 1, 1):
                raise ValueError("Feature con fecha inválida")
            if dt < cutoff.isoformat():
                if not isinstance(e.get("user_id"), int) or e["user_id"] <= 0:
                    raise ValueError("Feature de usuario inválido")
                rows.append({"user_namespace": "cinegraph-local", **e})
        contexts[kind] = rows

    outputs = {
        base + "ratings_candidates.jsonl": jsonl_bytes(rating_rows),
        base + "user_daily_context.jsonl": jsonl_bytes(contexts["user_daily"]),
        base + "user_movie_daily_context.jsonl": jsonl_bytes(contexts["user_movie_daily"]),
    }
    manifest = {
        "pipeline": STAGE_PIPELINE,
        "status": "shadow_only_not_published",
        "environment": "Floci local; NO AWS real",
        "cutoff_utc": cutoff.isoformat(),
        "temporal_rule": "input.event_at < cutoff 00:00:00 UTC (strict)",
        "user_namespace": "cinegraph-local",
        "movie_namespace": "movielens32m",
        "merge_into_movielens_original_ids_allowed": False,
        "converted_like_to_rating": False,
        "checkpoint_modified": False,
        "source_curated_latest": f"s3://{BUCKET}/{CURATED_LATEST_KEY}",
        "source_curated_snapshot": snapshot,
        "source_curated_sha256": hash_bytes(to_json_bytes(source)),
        "stats": {"source_curated_events": len(event_ids), "eligible_pre_cutoff_events": len(eligible),
                  "excluded_on_or_after_cutoff": future, "eligible_explicit_rating_events": sum(x["event_type"] == "rating" for x in eligible),
                  "rating_candidate_edges": len(rating_rows),
                  "eligible_shadow_users": len({e["user_id"] for e in rating_rows}),
                  "user_daily_context_rows": len(contexts["user_daily"]),
                  "user_movie_daily_context_rows": len(contexts["user_movie_daily"])},
        "outputs": [{"key": key, "sha256": hash_bytes(blob), "bytes": len(blob)}
                    for key, blob in sorted(outputs.items())],
        "note": "Los IDs de cuenta CineGraph NO son las identidades MovieLens. No se publica scoring; shadow exploratorio solamente.",
    }
    return manifest, outputs


def stage_manifest_key(manifest: dict) -> str:
    snap = manifest["source_curated_snapshot"]
    day = manifest["cutoff_utc"]
    if not re.fullmatch(r"[0-9a-f]{24}", str(snap)):
        raise ValueError("Snapshot inválido")
    valid_cutoff(day)
    return f"{STAGE_PREFIX}snapshots/{snap}/cutoff_date={day}/manifest.json"


def put_unmodified(s3, key: str, blob: bytes) -> None:
    """Un snapshot versionado publicado no puede mutar por una segunda ejecución."""
    try:
        original = get_bytes(s3, key)
    except s3.exceptions.NoSuchKey:
        original = None
    except Exception as exc:
        # Algunos emuladores devuelven ClientError (404) en lugar de NoSuchKey.
        if getattr(exc, "response", {}).get("Error", {}).get("Code") not in ("NoSuchKey", "404", "NotFound"):
            raise
        original = None
    if original is not None:
        if original != blob:
            raise RuntimeError("Intento de sobrescribir un snapshot de auditoría existente: " + key)
        return
    s3.put_object(Bucket=BUCKET, Key=key, Body=blob,
                  ContentType="application/json" if key.endswith(".json") else "application/x-ndjson")


def publish(s3, manifest: dict, outputs: dict[str, bytes]) -> None:
    for entry in manifest["outputs"]:
        put_unmodified(s3, entry["key"], outputs[entry["key"]])
    manifest_key = stage_manifest_key(manifest)
    manifest_bytes = to_json_bytes(manifest)
    put_unmodified(s3, manifest_key, manifest_bytes)
    pointer = {"pipeline": STAGE_PIPELINE, "cutoff_utc": manifest["cutoff_utc"],
               "manifest_key": manifest_key, "manifest_sha256": hash_bytes(manifest_bytes)}
    # Solo el puntero latest es mutable: el dataset y su manifiesto son inmutables.
    s3.put_object(Bucket=BUCKET, Key=STAGE_LATEST_KEY, Body=to_json_bytes(pointer),
                  ContentType="application/json")


def verify_stage(s3, *, expected_cutoff: str | None = None) -> dict:
    pointer = json.loads(get_bytes(s3, STAGE_LATEST_KEY))
    if pointer.get("pipeline") != STAGE_PIPELINE:
        raise ValueError("Puntero shadow desconocido")
    if expected_cutoff is not None and pointer.get("cutoff_utc") != expected_cutoff:
        raise ValueError("El último shadow corresponde a otro cutoff UTC")
    manifest_key = pointer.get("manifest_key", "")
    if not isinstance(manifest_key, str) or not manifest_key.startswith(STAGE_PREFIX + "snapshots/"):
        raise ValueError("El puntero shadow apunta fuera de snapshots")
    raw = get_bytes(s3, manifest_key)
    if hash_bytes(raw) != pointer.get("manifest_sha256"):
        raise RuntimeError("SHA-256 del manifiesto shadow incompatible")
    manifest = json.loads(raw)
    if manifest.get("pipeline") != STAGE_PIPELINE or manifest.get("status") != "shadow_only_not_published":
        raise ValueError("Manifiesto de ML shadow inesperado")
    if stage_manifest_key(manifest) != manifest_key or manifest["cutoff_utc"] != pointer["cutoff_utc"]:
        raise ValueError("Snapshot o fecha del shadow no coincide con puntero")
    if manifest.get("merge_into_movielens_original_ids_allowed") is not False:
        raise ValueError("Riesgo de colisión: se requiere separación explícita de identidades")
    for entry in manifest["outputs"]:
        key = entry["key"]
        if not key.startswith(manifest_key[:-len("manifest.json")]):
            raise ValueError("Salida shadow fuera de su snapshot")
        data = get_bytes(s3, key)
        if len(data) != entry["bytes"] or hash_bytes(data) != entry["sha256"]:
            raise RuntimeError("Integridad shadow fallida: " + key)
        if key.endswith("ratings_candidates.jsonl"):
            limit = midnight_utc(valid_cutoff(manifest["cutoff_utc"]))
            for row in decode_jsonl(data):
                if row.get("user_namespace") != "cinegraph-local" or datetime.fromisoformat(row["event_at"]) >= limit:
                    raise ValueError("Arista shadow fuera de espacio de identidad o posterior al corte")
    return manifest


def client(endpoint: str):
    import boto3
    from botocore.config import Config
    return boto3.client("s3", region_name="us-east-1", endpoint_url=validate_endpoint(endpoint),
                        aws_access_key_id="localtest", aws_secret_access_key="localtest",
                        config=Config(s3={"addressing_style": "path"}))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", nargs="?", default="run", choices=("run", "verify"))
    parser.add_argument("--cutoff", default=(datetime.now(timezone.utc).date()+timedelta(days=1)).isoformat())
    parser.add_argument("--endpoint-url", default=os.environ.get("AWS_ENDPOINT_URL", "http://floci:4566"))
    args = parser.parse_args(argv)
    cutoff = valid_cutoff(args.cutoff)
    s3 = client(args.endpoint_url)
    s3.head_bucket(Bucket=BUCKET)
    if args.operation == "run":
        source, blobs = verified_source(s3)
        manifest, outputs = build_stage(source, blobs, cutoff)
        publish(s3, manifest, outputs)
        print("SUCCESS: feedback Curated/Features preparado para inferencia shadow futura, SIN fusionar usuarios MovieLens.")
    else:
        print("Verificando snapshot shadow contra S3 Floci...")
    result = verify_stage(s3, expected_cutoff=cutoff.isoformat())
    print("SUCCESS: snapshot shadow SHA-256 verificado.")
    print("Cutoff UTC:", result["cutoff_utc"])
    print("Snapshot Curated:", result["source_curated_snapshot"])
    print("Stats:", json.dumps(result["stats"], sort_keys=True))
    print("A9 NO se ha ejecutado ni publicado. Las cuentas locales están aisladas de MovieLens.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())