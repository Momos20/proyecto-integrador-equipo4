#!/usr/bin/env python3
"""CineGraph | S3 Raw -> Curated -> Features (Floci SOLO LOCAL).

Job manual, reproducible, sin datos sintéticos, Glue, SageMaker ni retraining.
Reconstruye un snapshot completo desde todos los objetos Raw y deduplica por
`event_id` en todo el histórico, no solo dentro de una ejecución. Publica
los datos y sus hashes antes de reemplazar el puntero `latest.json`.

Dependencias: boto3 (la imagen Docker incluye boto3); resto biblioteca estándar.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

BUCKET = "cinegraph-local-datalake"
RAW_PREFIX = "raw/behavioral/cinegraph/live/"
CURATED_PREFIX = "curated/behavioral/cinegraph/"
FEATURES_PREFIX = "features/behavioral/cinegraph/"
LATEST_KEY = CURATED_PREFIX + "latest.json"
LOCAL_ENDPOINT = "http://floci:4566"
ALLOWED_EVENTS = {"like", "dislike", "rating", "watchlist", "watchlist_remove", "view_details"}
MAX_RAW_OBJECT_BYTES = 64 * 1024 * 1024
COLUMNS = ("event_id", "schema_version", "event_at", "event_date", "user_id", "movie_id",
           "event_type", "event_source", "rating", "request_id", "recommendation_id",
           "model_version", "position", "cutoff_date", "metadata")


def validate_local_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "http" or parsed.hostname not in {"floci", "localhost", "127.0.0.1"}
            or parsed.port != 4566 or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or parsed.username or parsed.password):
        raise ValueError("SEGURIDAD: este transformador SOLO admite Floci local (HTTP, puerto 4566).")
    return endpoint.rstrip("/")


def positive_int(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} debe ser un entero positivo")
    return value


def optional_str(value, field: str, max_length=250) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > max_length:
        raise ValueError(f"{field} no tiene un formato válido")
    return value


def normalize_event(raw: object) -> dict:
    """Valida eventos v1 de Flask, conserva fecha UTC y procedencia A9."""
    if not isinstance(raw, dict) or type(raw.get("schema_version")) is not int or raw["schema_version"] != 1:
        raise ValueError("schema_version desconocido (se requiere v1)")
    raw_id = raw.get("event_id")
    try:
        event_id = str(uuid.UUID(raw_id))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("event_id debe ser UUID válido") from None
    if not isinstance(raw.get("event_type"), str) or raw["event_type"] not in ALLOWED_EVENTS:
        raise ValueError("event_type no permitido")
    user_id = positive_int(raw.get("user_id"), "user_id")
    movie_id = positive_int(raw.get("movie_id"), "movie_id")
    event_at = raw.get("event_at")
    if not isinstance(event_at, str):
        raise ValueError("event_at debe ser ISO 8601 con zona horaria")
    try:
        timestamp = datetime.fromisoformat(event_at.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("event_at no tiene fecha válida") from None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("event_at no contiene zona horaria")
    timestamp = timestamp.astimezone(timezone.utc)
    rating = raw.get("rating")
    if raw["event_type"] == "rating":
        if isinstance(rating, bool) or not isinstance(rating, (float, int)):
            raise ValueError("rating requiere número entre 0.5 y 5 en pasos de 0.5")
        rating = float(rating)
        if not math.isfinite(rating) or not (0.5 <= rating <= 5.0) or (rating * 2) % 1:
            raise ValueError("rating fuera de rango o paso inválido")
    elif rating is not None:
        raise ValueError("rating solo aplica a event_type=rating")
    position = raw.get("position")
    if position is not None:
        position = positive_int(position, "position")
    cutoff = raw.get("cutoff_date")
    if cutoff is not None:
        if not isinstance(cutoff, str):
            raise ValueError("cutoff_date debe ser AAAA-MM-DD")
        try:
            if date.fromisoformat(cutoff).isoformat() != cutoff:
                raise ValueError()
        except ValueError:
            raise ValueError("cutoff_date inválido") from None
    metadata = raw.get("metadata")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict) or len(json.dumps(metadata)) > 3000:
        raise ValueError("metadata debe ser un objeto JSON pequeño")
    return {
        "event_id": event_id, "schema_version": 1,
        "event_at": timestamp.isoformat(), "event_date": timestamp.date().isoformat(),
        "user_id": user_id, "movie_id": movie_id, "event_type": raw["event_type"],
        "event_source": optional_str(raw.get("event_source"), "event_source", 50),
        "rating": rating, "request_id": optional_str(raw.get("request_id"), "request_id"),
        "recommendation_id": optional_str(raw.get("recommendation_id"), "recommendation_id"),
        "model_version": optional_str(raw.get("model_version"), "model_version", 100),
        "position": position, "cutoff_date": cutoff, "metadata": metadata,
    }


def to_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def jsonl_bytes(rows: list[dict]) -> bytes:
    return b"".join(to_json_bytes(row) for row in rows)


def iter_raw_objects(s3):
    """Recorre todas las páginas, no únicamente los primeros 1.000 objetos."""
    token = None
    while True:
        args = {"Bucket": BUCKET, "Prefix": RAW_PREFIX}
        if token:
            args["ContinuationToken"] = token
        response = s3.list_objects_v2(**args)
        for obj in response.get("Contents", []):
            if not obj["Key"].endswith("/"):
                yield obj["Key"]
        if not response.get("IsTruncated"):
            return
        token = response.get("NextContinuationToken")
        if not token:
            raise RuntimeError("S3 devolvió paginación incompleta")


def build_snapshot(s3) -> tuple[dict, dict[str, bytes]]:
    """El resultado depende del contenido Raw y es idempotente entre ejecuciones."""
    keys = sorted(iter_raw_objects(s3))
    if not keys:
        raise RuntimeError("No hay eventos S3 Raw. Registra interacciones y ejecuta floci-tools ship + verify.")
    source_hash = hashlib.sha256()
    valid: dict[str, dict] = {}
    quarantine = []
    stats = {"source_objects": len(keys), "raw_lines": 0, "valid_events": 0,
             "duplicates": 0, "conflicting_duplicates": 0, "invalid_rows": 0}
    for key in keys:
        response = s3.get_object(Bucket=BUCKET, Key=key)
        raw_bytes = response["Body"].read(MAX_RAW_OBJECT_BYTES + 1)
        if len(raw_bytes) > MAX_RAW_OBJECT_BYTES:
            raise ValueError(f"Objeto Raw demasiado grande (>64 MiB): {key}")
        source_hash.update(to_json_bytes({"key": key, "sha256": hashlib.sha256(raw_bytes).hexdigest()}))
        # Firehose en este laboratorio envía JSONL sin comprimir; cada PutRecord ya lleva \n.
        for line_number, line in enumerate(raw_bytes.splitlines(), start=1):
            if not line.strip():
                continue
            stats["raw_lines"] += 1
            try:
                parsed = json.loads(line)
                event = normalize_event(parsed)
            except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                stats["invalid_rows"] += 1
                quarantine.append({"source_key": key, "line": line_number,
                                   "reason": str(exc), "raw_sha256": hashlib.sha256(line).hexdigest()})
                continue
            previous = valid.get(event["event_id"])
            if previous is not None:
                stats["duplicates"] += 1
                if previous != event:
                    stats["conflicting_duplicates"] += 1
                    quarantine.append({"source_key": key, "line": line_number,
                                       "reason": "conflicting_event_id", "event_id": event["event_id"],
                                       "raw_sha256": hashlib.sha256(line).hexdigest()})
                continue
            valid[event["event_id"]] = event
    if not valid:
        raise RuntimeError("No se encontraron eventos válidos. Se evita publicar un snapshot vacío.")
    events = sorted(valid.values(), key=lambda e: (e["event_at"], e["event_id"]))
    stats["valid_events"] = len(events)
    fingerprint = source_hash.hexdigest()[:24]
    curated_base = f"{CURATED_PREFIX}snapshots/{fingerprint}/"
    features_base = f"{FEATURES_PREFIX}snapshots/{fingerprint}/"
    groups: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        groups[event["event_date"]].append(event)
    outputs = {}
    for day, rows in sorted(groups.items()):
        outputs[f"{curated_base}event_date={day}/events.jsonl"] = jsonl_bytes(rows)

    # Features descriptivas para analítica; no forman automáticamente el grafo A9.
    user_movie: dict[tuple, dict] = {}
    for e in events:
        key = (e["event_date"], e["user_id"], e["movie_id"])
        if key not in user_movie:
            row = {"event_date": key[0], "user_id": key[1], "movie_id": key[2],
                   "n_events": 0, "n_like": 0, "n_dislike": 0, "n_watchlist": 0, "n_watchlist_remove": 0,
                   "n_view_details": 0, "n_rating": 0, "rating_sum": 0.0,
                   "last_event_at": e["event_at"], "a9_feedback_events": 0}
            user_movie[key] = row
        row = user_movie[key]
        row["n_events"] += 1
        row["n_" + e["event_type"]] += 1
        if e["event_type"] == "rating":
            row["rating_sum"] += e["rating"]
        if e["model_version"] == "a9-miguel-diario":
            row["a9_feedback_events"] += 1
        row["last_event_at"] = max(row["last_event_at"], e["event_at"])
    movie_rows = []
    for key in sorted(user_movie):
        row = user_movie[key]
        movie_rows.append({k: v for k, v in row.items() if k != "rating_sum"} | {
            "avg_rating": round(row["rating_sum"] / row["n_rating"], 4) if row["n_rating"] else None,
        })
    outputs[f"{features_base}user_movie_daily.jsonl"] = jsonl_bytes(movie_rows)

    user_daily: dict[tuple, dict] = {}
    for row in movie_rows:
        key = (row["event_date"], row["user_id"])
        if key not in user_daily:
            user_daily[key] = {"event_date": key[0], "user_id": key[1],
                               "n_events": 0, "n_movies": 0,
                               "n_like": 0, "n_dislike": 0, "n_watchlist": 0, "n_watchlist_remove": 0,
                               "n_view_details": 0, "n_rating": 0,
                               "a9_feedback_events": 0, "rating_sum": 0.0}
        day = user_daily[key]
        day["n_movies"] += 1
        for col in ("n_events", "n_like", "n_dislike", "n_watchlist", "n_watchlist_remove",
                    "n_view_details", "n_rating", "a9_feedback_events"):
            day[col] += row[col]
        if row["n_rating"]:
            day["rating_sum"] += user_movie[(row["event_date"], row["user_id"], row["movie_id"])]["rating_sum"]
    daily_rows = []
    for key in sorted(user_daily):
        row = user_daily[key]
        daily_rows.append({k: v for k, v in row.items() if k != "rating_sum"} | {
            "avg_rating": round(row["rating_sum"] / row["n_rating"], 4) if row["n_rating"] else None,
        })
    outputs[f"{features_base}user_daily.jsonl"] = jsonl_bytes(daily_rows)
    stats["user_movie_daily_rows"] = len(movie_rows)
    stats["user_daily_rows"] = len(daily_rows)
    stats["curated_dates"] = sorted(groups)
    outputs[f"{curated_base}quality.json"] = to_json_bytes({"schema_version": 1, "source": "Floci local Raw",
                                                            "stats": stats})
    outputs[f"{curated_base}quarantine.jsonl"] = jsonl_bytes(quarantine)
    manifest = {
        "pipeline": "cinegraph-local-raw-curated-features-v1",
        "environment": "Floci local; NO AWS real",
        "input_prefix": f"s3://{BUCKET}/{RAW_PREFIX}",
        "snapshot": fingerprint,
        "source_sha256": source_hash.hexdigest(),
        "stats": stats,
        "outputs": [{"key": key, "sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}
                    for key, value in sorted(outputs.items())],
        "note": "Features observacionales; A9 original no consume estos eventos automáticamente.",
    }
    return manifest, outputs


def client(endpoint: str):
    import boto3
    from botocore.config import Config
    return boto3.client("s3", endpoint_url=validate_local_endpoint(endpoint), region_name="us-east-1",
                        aws_access_key_id="localtest", aws_secret_access_key="localtest",
                        config=Config(s3={"addressing_style": "path"}))


def put_outputs(s3, manifest: dict, outputs: dict[str, bytes]) -> None:
    for entry in manifest["outputs"]:
        key = entry["key"]
        blob = outputs[key]
        s3.put_object(Bucket=BUCKET, Key=key, Body=blob,
                      ContentType="application/json" if key.endswith(".json") else "application/x-ndjson")
    # Manifest latest se publica al final, únicamente con todas las salidas escritas.
    s3.put_object(Bucket=BUCKET, Key=LATEST_KEY, Body=to_json_bytes(manifest),
                  ContentType="application/json")


def verify_outputs(s3) -> dict:
    try:
        manifest = json.loads(s3.get_object(Bucket=BUCKET, Key=LATEST_KEY)["Body"].read())
    except Exception as exc:
        raise RuntimeError("No existe un manifiesto Curated publicado; ejecuta 'run'.") from exc
    if manifest.get("pipeline") != "cinegraph-local-raw-curated-features-v1":
        raise RuntimeError("Manifiesto Curated inesperado")
    for entry in manifest["outputs"]:
        data = s3.get_object(Bucket=BUCKET, Key=entry["key"])["Body"].read()
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise RuntimeError("S3 alteró la salida o su checksum: " + entry["key"])
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", nargs="?", choices=("run", "verify"), default="run")
    parser.add_argument("--endpoint-url", default=os.environ.get("AWS_ENDPOINT_URL", LOCAL_ENDPOINT))
    args = parser.parse_args(argv)
    s3 = client(args.endpoint_url)  # bloquea endpoints AWS antes de contactar al servidor
    s3.head_bucket(Bucket=BUCKET)
    if args.operation == "verify":
        manifest = verify_outputs(s3)
        print("SUCCESS: Curated y Features existen en S3 local y sus SHA-256 coinciden.")
    else:
        manifest, outputs = build_snapshot(s3)
        put_outputs(s3, manifest, outputs)
        verified = verify_outputs(s3)
        if verified["snapshot"] != manifest["snapshot"]:
            raise RuntimeError("La verificación final no corresponde al último snapshot")
        print("SUCCESS: Raw -> Curated -> Features publicado y verificado en S3 local.")
    print("Snapshot:", manifest["snapshot"])
    print("Manifest:", f"s3://{BUCKET}/{LATEST_KEY}")
    for entry in manifest["outputs"]:
        if entry["key"].endswith("user_movie_daily.jsonl") or entry["key"].endswith("user_daily.jsonl"):
            print("Features:", f"s3://{BUCKET}/{entry['key']}")
    print("Calidad:", json.dumps(manifest["stats"], ensure_ascii=False, sort_keys=True))
    print("No se ha iniciado un entrenamiento ni scoring de GraphSAGE.")


if __name__ == "__main__":
    main()