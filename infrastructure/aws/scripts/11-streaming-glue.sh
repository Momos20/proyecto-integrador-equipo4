#!/usr/bin/env bash
set -euo pipefail
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
account=$(aws sts get-caller-identity --query Account --output text)
[[ "$account" == 023914826547 ]]
bucket="cinegraph-e4-datalake-${account}-us-east-1"
role="arn:aws:iam::${account}:role/LabRole"
stream=cinegraph-e4-clickstream
delivery=cinegraph-e4-firehose
db=cinegraph_e4
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
aws kinesis describe-stream-summary --stream-name "$stream" --query 'StreamDescriptionSummary.StreamStatus' --output text | grep -Fx ACTIVE
python3 - "$account" "$bucket" "$role" "$stream" "$tmp" <<'PY'
import json,sys,pathlib
a,b,r,s,d=sys.argv[1:]
p=pathlib.Path(d)
(p/'source.json').write_text(json.dumps({"KinesisStreamARN":f"arn:aws:kinesis:us-east-1:{a}:stream/{s}","RoleARN":r}))
(p/'destination.json').write_text(json.dumps({"RoleARN":r,"BucketARN":f"arn:aws:s3:::{b}","Prefix":"raw/behavioral/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/","ErrorOutputPrefix":"errors/firehose/!{firehose:error-output-type}/","BufferingHints":{"SizeInMBs":1,"IntervalInSeconds":60},"CompressionFormat":"GZIP"}))
PY
if result=$(aws firehose describe-delivery-stream --delivery-stream-name "$delivery" 2>&1); then
  echo FIREHOSE_EXISTS
  python3 - "$result" "$account" "$bucket" "$stream" <<'PY'
import json,sys
d=json.loads(sys.argv[1])["DeliveryStreamDescription"]
a,b,s=sys.argv[2:]
assert d["DeliveryStreamType"]=="KinesisStreamAsSource"
assert d["Source"]["KinesisStreamSourceDescription"]["KinesisStreamARN"]==f"arn:aws:kinesis:us-east-1:{a}:stream/{s}"
assert any(x.get("ExtendedS3DestinationDescription",{}).get("BucketARN")==f"arn:aws:s3:::{b}" and x.get("ExtendedS3DestinationDescription",{}).get("Prefix","").startswith("raw/behavioral/") for x in d["Destinations"])
PY
elif [[ "$result" == *ResourceNotFoundException* ]]; then
  aws firehose create-delivery-stream --delivery-stream-name "$delivery" --delivery-stream-type KinesisStreamAsSource --kinesis-stream-source-configuration "file://$tmp/source.json" --extended-s3-destination-configuration "file://$tmp/destination.json"
else
  echo "$result" >&2; exit 1
fi
for i in $(seq 1 30); do
  state=$(aws firehose describe-delivery-stream --delivery-stream-name "$delivery" --query 'DeliveryStreamDescription.DeliveryStreamStatus' --output text)
  echo "FIREHOSE_STATUS=$state"
  [[ "$state" == ACTIVE ]] && break
  [[ "$state" == CREATING ]] || exit 1
  sleep 10
done
[[ "$state" == ACTIVE ]]
if result=$(aws glue get-database --name "$db" 2>&1); then
  echo GLUE_DATABASE_EXISTS
elif [[ "$result" == *EntityNotFoundException* ]]; then
  aws glue create-database --database-input '{"Name":"cinegraph_e4","Description":"CineGraph behavioral lake catalog"}'
else
  echo "$result" >&2; exit 1
fi
aws glue get-database --name "$db" --query 'Database.Name'
aws firehose describe-delivery-stream --delivery-stream-name "$delivery" --query 'DeliveryStreamDescription.{Name:DeliveryStreamName,State:DeliveryStreamStatus,Destinations:Destinations[].ExtendedS3DestinationDescription.BucketARN}'
echo STREAMING_RESOURCES_READY
echo "No events or Glue transformations verified yet."
