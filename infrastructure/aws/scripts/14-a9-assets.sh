#!/usr/bin/env bash
set -euo pipefail
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
[[ "$(aws sts get-caller-identity --query Account --output text)" == 023914826547 ]]
bucket=cinegraph-e4-datalake-023914826547-us-east-1
root=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$root"
git sparse-checkout disable
git pull --ff-only origin main
model=ml/models/A9_sin_id/modelo.pt
git restore --source=HEAD --worktree -- "$model"
echo "8c9aa61fb7e8d3ed3a6476fe759f9861283387bc6561ea5aa03595ab516a2358  $model" | sha256sum -c -
test -s ml/models/A9_sin_id/validacion.json
test -s ml/a9_daily/src/recomendar.py
aws s3 cp "$model" "s3://$bucket/models/a9/modelo.pt"
aws s3 cp ml/models/A9_sin_id/validacion.json "s3://$bucket/models/a9/validacion.json"
# Avoid downloading 32M ratings to CloudShell's small persistent home.
# Stage a bootstrap bundle for the independent compute job.
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git archive --format=tar.gz --output="$tmp/a9-source.tar.gz" HEAD ml/a9_daily ml/models/A9_sin_id scripts/data/prepare_miguel_a9.py data/reference/movielens32m
aws s3 cp "$tmp/a9-source.tar.gz" "s3://$bucket/models/a9/a9-source.tar.gz"
aws s3 ls "s3://$bucket/models/a9/"
echo A9_ASSETS_STAGED
echo "MovieLens 32M must be downloaded and verified in independent AWS compute; no inference has run."
