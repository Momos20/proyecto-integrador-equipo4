#!/usr/bin/env bash
set -euo pipefail
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
account=$(aws sts get-caller-identity --query Account --output text)
[[ "$account" == 023914826547 ]]
role="arn:aws:iam::$account:role/LabRole"
name=cinegraph-e4-behavioral
arn="arn:aws:states:us-east-1:$account:stateMachine:$name"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/definition.json" <<'JSON'
{"Comment":"CineGraph behavioral ETL only; A9 scoring not included","StartAt":"TransformBehavioral","States":{"TransformBehavioral":{"Type":"Task","Resource":"arn:aws:states:::glue:startJobRun.sync","Parameters":{"JobName":"cinegraph-e4-behavioral-etl"},"TimeoutSeconds":900,"End":true}}}
JSON
if result=$(aws stepfunctions describe-state-machine --state-machine-arn "$arn" 2>&1); then
  aws stepfunctions update-state-machine --state-machine-arn "$arn" --definition "file://$tmp/definition.json" --role-arn "$role"
elif [[ "$result" == *StateMachineDoesNotExist* ]]; then
  aws stepfunctions create-state-machine --name "$name" --definition "file://$tmp/definition.json" --role-arn "$role" --type STANDARD
else
  echo "$result" >&2; exit 1
fi
aws events put-rule --name cinegraph-e4-behavioral-daily --schedule-expression 'cron(0 7 * * ? *)' --state DISABLED --description 'Daily behavioral ETL at 07:00 UTC; disabled until validated'
python3 - "$arn" "$role" > "$tmp/targets.json" <<'PY'
import json,sys
print(json.dumps([{"Id":"BehavioralETL","Arn":sys.argv[1],"RoleArn":sys.argv[2],"Input":"{}"}]))
PY
aws events put-targets --rule cinegraph-e4-behavioral-daily --targets "file://$tmp/targets.json" > "$tmp/result.json"
python3 - "$tmp/result.json" <<'PY'
import json,sys
assert json.load(open(sys.argv[1]))["FailedEntryCount"]==0
PY
aws cloudwatch put-metric-alarm --alarm-name cinegraph-e4-etl-execution-failed --namespace AWS/States --metric-name ExecutionsFailed --dimensions Name=StateMachineArn,Value="$arn" --statistic Sum --period 300 --evaluation-periods 1 --threshold 1 --comparison-operator GreaterThanOrEqualToThreshold --treat-missing-data notBreaching
aws cloudwatch put-metric-alarm --alarm-name cinegraph-e4-firehose-delivery-failure --namespace AWS/Firehose --metric-name DeliveryToS3.Success --dimensions Name=DeliveryStreamName,Value=cinegraph-e4-firehose --statistic Average --period 300 --evaluation-periods 2 --threshold 1 --comparison-operator LessThanThreshold --treat-missing-data notBreaching
execution=$(aws stepfunctions start-execution --state-machine-arn "$arn" --name "manual-$(date -u +%Y%m%d%H%M%S)" --input '{}' --query executionArn --output text)
echo "EXECUTION_ARN=$execution"
for i in $(seq 1 100); do
 state=$(aws stepfunctions describe-execution --execution-arn "$execution" --query status --output text)
 echo "WORKFLOW_STATE=$state"
 case "$state" in
 SUCCEEDED) break;;
 RUNNING) sleep 10;;
 *) aws stepfunctions describe-execution --execution-arn "$execution" --query '{status:status,error:error,cause:cause}'; exit 1;;
 esac
done
[[ "$state" == SUCCEEDED ]]
aws events list-targets-by-rule --rule cinegraph-e4-behavioral-daily
aws cloudwatch describe-alarms --alarm-name-prefix cinegraph-e4 --query 'MetricAlarms[].{Name:AlarmName,State:StateValue}'
echo BEHAVIORAL_ORCHESTRATION_VERIFIED
echo 'Schedule remains DISABLED to conserve lab budget. GraphSAGE is not part of this workflow.'
