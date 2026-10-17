from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_WRITE_LOCK = threading.Lock()


def _log_path() -> Path:
    return Path(os.getenv("CLICKSTREAM_LOG_PATH", "/tmp/cinegraph/clickstream.log"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit_interaction_event(
    *,
    user_id: int,
    movie_id: int,
    interaction_type: str,
    rating: float | None,
    metadata: dict[str, Any] | None = None,
    request_id: str | None = None,
    event_source: str = "http",
) -> dict[str, Any]:
    """Append one behavioral event as JSONL for Kinesis Agent tailing.

    Persistence in PostgreSQL remains the operational source of truth. This log is
    the append-only behavioral stream that Kinesis Agent forwards to Kinesis Data
    Streams and, through Firehose, to the Raw zone in S3.
    """
    metadata = metadata or {}
    event = {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "event_type": interaction_type,
        "event_source": event_source,
        "event_at": _utc_now(),
        "request_id": request_id or str(uuid.uuid4()),
        "user_id": user_id,
        "movie_id": movie_id,
        "rating": rating,
        "recommendation_id": metadata.get("recommendation_id"),
        "model_version": metadata.get("model_version"),
        "position": metadata.get("position"),
        "cutoff_date": metadata.get("cutoff_date"),
        "metadata": metadata,
    }

    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))

    with _WRITE_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    return event
