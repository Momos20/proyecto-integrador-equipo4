#!/usr/bin/env bash
set -euo pipefail
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
[[ "$(aws sts get-caller-identity --query Account --output text)" == 023914826547 ]]
bucket=cinegraph-e4-datalake-023914826547-us-east-1
role=arn:aws:iam::023914826547:role/LabRole
job=cinegraph-e4-behavioral-etl
root=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$root"
python3 -m py_compile infrastructure/aws/scripts/13-glue-behavioral.py
aws s3 cp infrastructure/aws/scripts/13-glue-behavioral.py "s3://$bucket/scripts/glue/13-glue-behavioral.py"
command='{"Name":"pythonshell","ScriptLocation":"s3://'"$bucket"'/scripts/glue/13-glue-behavioral.py","PythonVersion":"3.9"}'
if result=$(aws glue get-job --job-name "$job" 2>&1); then
  echo GLUE_JOB_EXISTS
  python3 - "$result" "$bucket" "$role" <<'PY'
import json,sys
j=json.loads(sys.argv[1])["Job"]
assert j["Role"]==sys.argv[3]
assert j["Command"]["ScriptLocation"]=="s3://"+sys.argv[2]+"/scripts/glue/13-glue-behavioral.py"
assert j["Command"]["Name"]=="pythonshell"
PY
elif [[ "$result" == *EntityNotFoundException* ]]; then
  aws glue create-job --name "$job" --role "$role" --command "$command" --max-capacity 0.0625 --timeout 10 --max-retries 0 --execution-property MaxConcurrentRuns=1
else
  echo "$result" >&2; exit 1
fi
run=$(aws glue start-job-run --job-name "$job" --query JobRunId --output text)
echo "GLUE_RUN=$run"
for i in $(seq 1 90); do
 state=$(aws glue get-job-run --job-name "$job" --run-id "$run" --query JobRun.JobRunState --output text)
 echo "GLUE_STATE=$state"
 case "$state" in
 SUCCEEDED) break;;
 STARTING|RUNNING|WAITING|STOPPING) sleep 10;;
 *) aws glue get-job-run --job-name "$job" --run-id "$run" --query 'JobRun.{State:JobRunState,Error:ErrorMessage}'; exit 1;;
 esac
done
[[ "$state" == SUCCEEDED ]]
aws s3 cp "s3://$bucket/curated/behavioral/cinegraph/latest.json" -
echo
echo GLUE_ETL_VERIFIED
