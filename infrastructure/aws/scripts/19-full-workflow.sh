#!/usr/bin/env bash
set -euo pipefail
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
account=$(aws sts get-caller-identity --query Account --output text)
[[ "$account" == 023914826547 ]]
root=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$root"
bucket=cinegraph-e4-datalake-023914826547-us-east-1
role="arn:aws:iam::$account:role/LabRole"
name=cinegraph-e4-a9-replay
arn="arn:aws:states:us-east-1:$account:stateMachine:$name"
worker=i-03306ae6540b03d3e
[[ "$(aws ec2 describe-instances --instance-ids "$worker" --query 'Reservations[0].Instances[0].State.Name' --output text)" == stopped ]]
secret=$(aws rds describe-db-instances --db-instance-identifier cinegraph-e4-postgres --query 'DBInstances[0].MasterUserSecret.SecretArn' --output text)
[[ "$secret" == arn:aws:secretsmanager:us-east-1:* ]]
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
python3 - "$secret" > "$tmp" <<'PY'
import sys,pathlib,json
p=pathlib.Path("infrastructure/aws/scripts/19-full-workflow.asl.json")
print(json.dumps(json.loads(p.read_text().replace("__SECRET_ARN__",sys.argv[1]))))
PY
validation=$(aws stepfunctions validate-state-machine-definition --definition "file://$tmp" --type STANDARD)
echo "$validation"
[[ "$(python3 -c 'import json,sys; print(json.load(sys.stdin)["result"])' <<<"$validation")" == OK ]]
aws s3 cp infrastructure/aws/scripts/19-a9-replay.py "s3://$bucket/scripts/a9/19-a9-replay.py"
if result=$(aws stepfunctions describe-state-machine --state-machine-arn "$arn" 2>&1); then
  [[ "$(aws stepfunctions list-executions --state-machine-arn "$arn" --status-filter RUNNING --query 'length(executions)' --output text)" == 0 ]]
  aws stepfunctions update-state-machine --state-machine-arn "$arn" --definition "file://$tmp" --role-arn "$role"
elif [[ "$result" == *StateMachineDoesNotExist* ]]; then
  aws stepfunctions create-state-machine --name "$name" --definition "file://$tmp" --role-arn "$role" --type STANDARD
else
  echo "$result" >&2; exit 1
fi
aws cloudwatch put-metric-alarm --alarm-name cinegraph-e4-a9-workflow-failed --namespace AWS/States --metric-name ExecutionsFailed --dimensions Name=StateMachineArn,Value="$arn" --statistic Sum --period 300 --evaluation-periods 1 --threshold 1 --comparison-operator GreaterThanOrEqualToThreshold --treat-missing-data notBreaching
execution=$(aws stepfunctions start-execution --state-machine-arn "$arn" --name "manual-$(date -u +%Y%m%d%H%M%S)" --input '{}' --query executionArn --output text)
echo "EXECUTION_ARN=$execution"
echo "WORKFLOW_LAUNCHED"
echo "Existing EventBridge behavioral schedule remains disabled; no recurrent A9 replay scheduled."
for i in $(seq 1 150); do
  state=$(aws stepfunctions describe-execution --execution-arn "$execution" --query status --output text)
  echo "WORKFLOW_STATE=$state"
  case "$state" in
    SUCCEEDED) break;;
    RUNNING) sleep 10;;
    *) aws stepfunctions describe-execution --execution-arn "$execution" --query '{status:status,error:error,cause:cause}'; echo 'Confirm worker stopped; inspect execution history'; exit 1;;
  esac
done
[[ "$state" == SUCCEEDED ]]
aws ec2 wait instance-stopped --instance-ids "$worker"
echo A9_FULL_WORKFLOW_VERIFIED
