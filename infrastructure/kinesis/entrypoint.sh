#!/usr/bin/env bash
set -euo pipefail

: "${AWS_REGION:=us-east-1}"
: "${KINESIS_STREAM_NAME:=cinegraph-clickstream}"

sed \
  -e "s/__AWS_REGION__/${AWS_REGION}/g" \
  -e "s/__KINESIS_STREAM_NAME__/${KINESIS_STREAM_NAME}/g" \
  /opt/cinegraph/agent.json.template \
  > /etc/aws-kinesis/agent.json

mkdir -p /var/log/cinegraph

echo "Starting Kinesis Agent -> stream=${KINESIS_STREAM_NAME}, region=${AWS_REGION}"
exec start-aws-kinesis-agent
