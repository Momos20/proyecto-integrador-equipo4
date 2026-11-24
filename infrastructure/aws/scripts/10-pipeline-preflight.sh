#!/usr/bin/env bash
# Paso 36: preflight AWS Academy; único recurso que puede crear: Kinesis.
set -uo pipefail
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
account=$(aws sts get-caller-identity --query Account --output text) || exit 1
if [[ "$account" != "023914826547" ]]; then echo "Cuenta inesperada: $account" >&2; exit 1; fi
bucket="cinegraph-e4-datalake-${account}-us-east-1"
stream="cinegraph-e4-clickstream"
failed=0
check() {
  local label="$1"; shift
  printf '\n===== %s =====\n' "$label"
  if "$@"; then echo "OK: $label"; else echo "FAILED: $label" >&2; failed=1; fi
}
check IAM aws iam get-role --role-name LabRole --query 'Role.{Arn:Arn,Trust:AssumeRolePolicyDocument}' --output json
check S3 aws s3api head-bucket --bucket "$bucket"
check S3_OBJECTS aws s3api list-objects-v2 --bucket "$bucket" --max-items 10 --query 'Contents[].Key'
echo "===== KINESIS ====="
if result=$(aws kinesis describe-stream-summary --stream-name "$stream" 2>&1); then
  echo "KINESIS_ALREADY_EXISTS"
elif [[ "$result" == *ResourceNotFoundException* ]]; then
  check KINESIS_CREATE aws kinesis create-stream --stream-name "$stream" --shard-count 1
else
  printf '%s\n' "$result" >&2
  failed=1
fi
check KINESIS_WAIT aws kinesis wait stream-exists --stream-name "$stream"
check KINESIS_STATUS aws kinesis describe-stream-summary --stream-name "$stream" --query 'StreamDescriptionSummary.{ARN:StreamARN,Status:StreamStatus}' --output json
check FIREHOSE aws firehose list-delivery-streams
check GLUE aws glue get-databases --query 'DatabaseList[].Name'
check SAGEMAKER aws sagemaker list-processing-jobs --max-results 10 --query 'ProcessingJobSummaries[].{Name:ProcessingJobName,Status:ProcessingJobStatus}'
check STEP_FUNCTIONS aws stepfunctions list-state-machines
check EVENTBRIDGE aws events list-rules --name-prefix cinegraph
check CLOUDWATCH aws cloudwatch describe-alarms --alarm-name-prefix cinegraph
echo "PREFLIGHT_EXIT_CODE=$failed"
exit "$failed"
