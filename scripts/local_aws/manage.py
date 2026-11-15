#!/usr/bin/env python3
"""Manual integration tools for the Floci-only local AWS sandbox.

IMPORTANT: all boto3 clients are explicitly pinned to a local HTTP endpoint.
This command is never part of GitHub Actions or an automatic application startup.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

ENDPOINT = os.environ.get("AWS_ENDPOINT_URL", "http://floci:4566")
parsed_endpoint = urlsplit(ENDPOINT)
if (
    parsed_endpoint.scheme != "http"
    or parsed_endpoint.hostname not in {"floci", "localhost", "127.0.0.1"}
    or parsed_endpoint.port != 4566
    or parsed_endpoint.username is not None
    or parsed_endpoint.password is not None
):
    raise SystemExit("SAFETY: only localhost or the Docker service 'floci' on port 4566 is allowed as AWS_ENDPOINT_URL")

REGION = os.environ.get("AWS_REGION", "us-east-1")
BUCKET = os.environ.get("S3_BUCKET", "cinegraph-local-datalake")
STREAM = os.environ.get("KINESIS_STREAM_NAME", "cinegraph-clickstream")
FIREHOSE = os.environ.get("FIREHOSE_DELIVERY_STREAM", "cinegraph-clickstream-to-s3")
PREFIX = "raw/behavioral/cinegraph/live/"
LOG = Path("/app/logs/clickstream.log")
STATE = Path("/state/clickstream-cursor.json")
ROLE = "arn:aws:iam::000000000000:role/cinegraph-local-firehose"


def client(service: str):
    import boto3

    return boto3.client(
        service, region_name=REGION, endpoint_url=ENDPOINT,
        aws_access_key_id="localtest", aws_secret_access_key="localtest",
    )


def await_floci(seconds: int = 30) -> None:
    for _ in range(seconds):
        try:
            client("sts").get_caller_identity()
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError("Floci is not responding at " + ENDPOINT)


def bootstrap() -> None:
    await_floci()
    s3 = client("s3")
    kin = client("kinesis")
    firehose = client("firehose")

    try:
        s3.head_bucket(Bucket=BUCKET)
    except Exception:
        s3.create_bucket(Bucket=BUCKET)
        print("Created local S3 bucket:", BUCKET)

    try:
        stream_info = kin.describe_stream(StreamName=STREAM)
        stream_arn = stream_info["StreamDescription"]["StreamARN"]
    except kin.exceptions.ResourceNotFoundException:
        stream_arn = kin.create_stream(StreamName=STREAM, ShardCount=1) or None
        stream_arn = kin.describe_stream(StreamName=STREAM)["StreamDescription"]["StreamARN"]
        print("Created local Kinesis stream:", STREAM)

    try:
        firehose.describe_delivery_stream(DeliveryStreamName=FIREHOSE)
    except firehose.exceptions.ResourceNotFoundException:
        firehose.create_delivery_stream(
            DeliveryStreamName=FIREHOSE,
            DeliveryStreamType="KinesisStreamAsSource",
            KinesisStreamSourceConfiguration={"KinesisStreamARN": stream_arn, "RoleARN": ROLE},
            ExtendedS3DestinationConfiguration={
                "RoleARN": ROLE,
                "BucketARN": f"arn:aws:s3:::{BUCKET}",
                "Prefix": PREFIX,
                "BufferingHints": {"SizeInMBs": 5, "IntervalInSeconds": 60},
                "CompressionFormat": "UNCOMPRESSED",
            },
        )
        print("Created local Firehose (source Kinesis):", FIREHOSE)

    print("Ready:", ENDPOINT, f"s3://{BUCKET}/{PREFIX}")
    print("Run 'ship' AFTER bootstrap and AFTER you generate interactions in CineGraph.")


def load_cursor() -> dict:
    try:
        return json.loads(STATE.read_text("utf-8"))
    except (OSError, ValueError):
        return {"offset": 0, "last_event_id": None}


def save_cursor(offset: int, last_event_id: str | None) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"offset": offset, "last_event_id": last_event_id}), "utf-8")
    tmp.replace(STATE)


def ship() -> None:
    """Send completed JSONL lines once; maintain a local cursor across invocations.

    At-least-once: a crash after PutRecord and before cursor save can replay
    an event. event_id in the payload is the required downstream dedupe key.
    """
    await_floci()
    if not LOG.exists():
        print("No clickstream yet. Generate a like or rating in CineGraph first.")
        return

    kin = client("kinesis")
    state = load_cursor()
    previous = int(state.get("offset", 0))
    if previous < 0 or previous > LOG.stat().st_size:
        previous = 0  # log rotation/truncation
    sent = 0
    last_id = state.get("last_event_id")
    with LOG.open("rb") as fh:
        fh.seek(previous)
        while True:
            start = fh.tell()
            line = fh.readline()
            if not line:
                break
            if not line.endswith(b"\n"):
                # Incomplete line: do not checkpoint until fully written.
                break
            try:
                obj = json.loads(line)
                uid = str(obj["user_id"])
                if not obj.get("event_id") or not uid.isdigit():
                    raise ValueError("missing event_id or valid user_id")
            except (json.JSONDecodeError, ValueError, KeyError, TypeError) as error:
                print(f"Skipped malformed JSONL at byte {start}: {error}")
                save_cursor(fh.tell(), last_id)
                continue
            kin.put_record(StreamName=STREAM, Data=line, PartitionKey=uid)
            last_id = str(obj["event_id"])
            save_cursor(fh.tell(), last_id)
            sent += 1

    print(f"Published {sent} new event(s) to Kinesis. Last event_id={last_id!r}")
    print("No training or scoring job has been started.")


def verify() -> None:
    """Wait for actual Floci Firehose -> S3 delivery, not just API responses."""
    await_floci()
    s3 = client("s3")
    needle = load_cursor().get("last_event_id")
    if not needle:
        raise RuntimeError("No event shipped yet. Run 'ship' after generating feedback.")
    deadline = time.monotonic() + 30
    objects = 0
    while time.monotonic() < deadline:
        response = s3.list_objects_v2(Bucket=BUCKET, Prefix=PREFIX)
        entries = response.get("Contents", [])
        objects = len(entries)
        for record in entries:
            data = s3.get_object(Bucket=BUCKET, Key=record["Key"])["Body"].read()
            if needle.encode("utf-8") in data:
                print("SUCCESS: end-to-end behavioral event found in local S3.")
                print("Object:", f"s3://{BUCKET}/{record['Key']}")
                print("Verified event_id:", needle)
                return
        time.sleep(1)
    raise RuntimeError(
        f"Firehose has not delivered the latest event to S3. "
        f"Found {objects} object(s); check docker compose logs floci."
    )


def status() -> None:
    await_floci()
    print("Floci:", client("sts").get_caller_identity()["Account"])
    print("Streams:", client("kinesis").list_streams().get("StreamNames", []))
    print("Firehose:", client("firehose").list_delivery_streams().get("DeliveryStreamNames", []))
    print("S3 buckets:", [b["Name"] for b in client("s3").list_buckets().get("Buckets", [])])
    print("Cursor:", load_cursor())


def main() -> None:
    commands = {"bootstrap": bootstrap, "ship": ship, "verify": verify, "status": status}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        raise SystemExit("Usage: manage.py bootstrap|ship|verify|status")
    commands[sys.argv[1]]()


if __name__ == "__main__":
    main()
