#!/usr/bin/env bash
set -euo pipefail
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
[[ "$(aws sts get-caller-identity --query Account --output text)" == 023914826547 ]]
root=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$root"
B=cinegraph-e4-datalake-023914826547-us-east-1
WEB=i-0e3288445cb0df13d
WORKER=i-03306ae6540b03d3e
ARN=$(aws rds describe-db-instances --db-instance-identifier cinegraph-e4-postgres --query 'DBInstances[0].MasterUserSecret.SecretArn' --output text)
[[ "$ARN" == arn:aws:secretsmanager:us-east-1:* ]]
aws s3 cp data/reference/movielens32m/links.csv "s3://$B/reference/movielens32m/links.csv"
params=$(python3 - "$ARN" <<'PY'
import json,sys,shlex
arn=shlex.quote(sys.argv[1])
print(json.dumps({"commands":["set -euo pipefail","cd /opt/cinegraph/source","git pull --ff-only origin main","docker exec -i -e RDS_SECRET_ARN="+arn+" cinegraph-e4-app python - < infrastructure/aws/scripts/20-posters.py","for user in cine123 cine414 cine456; do docker exec -i -e CINEGRAPH_SMOKE_USER=$user cinegraph-e4-app python - < infrastructure/aws/scripts/20-final-smoke.py; done","echo A9_THREE_USERS_VERIFIED"],"executionTimeout":["900"]}))
PY
)
ID=$(aws ssm send-command --instance-ids "$WEB" --document-name AWS-RunShellScript --parameters "$params" --query Command.CommandId --output text)
echo "FINAL_COMMAND_ID=$ID"
for i in $(seq 1 100); do
  status=$(aws ssm get-command-invocation --command-id "$ID" --instance-id "$WEB" --query Status --output text 2>/dev/null || echo Pending)
  case "$status" in Pending|InProgress|Delayed) sleep 10;; *) break;; esac
done
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
aws ssm get-command-invocation --command-id "$ID" --instance-id "$WEB" --query '{Status:Status,Output:StandardOutputContent,Error:StandardErrorContent}' > "$tmp/final-smoke.json"
cat "$tmp/final-smoke.json"
[[ "$status" == Success ]]
aws stepfunctions describe-execution --execution-arn "arn:aws:states:us-east-1:023914826547:execution:cinegraph-e4-a9-replay:manual-20261124031918" --query '{status:status,startDate:startDate,stopDate:stopDate,executionArn:executionArn}' > "$tmp/workflow.json"
aws ec2 describe-instances --instance-ids "$WORKER" "$WEB" --query 'Reservations[].Instances[].{ID:InstanceId,State:State.Name,Type:InstanceType}' > "$tmp/ec2.json"
aws events describe-rule --name cinegraph-e4-behavioral-daily --query '{Name:Name,State:State,Schedule:ScheduleExpression}' > "$tmp/eventbridge.json"
aws cloudwatch describe-alarms --alarm-name-prefix cinegraph-e4 --query 'MetricAlarms[].{Name:AlarmName,State:StateValue}' > "$tmp/alarms.json"
aws s3 cp "s3://$B/predictions/a9/2023-06-15/ec2-20261124031146/top10.manifest.json" "$tmp/a9-manifest.json"
prefix="evidence/final/$(date -u +%Y%m%d%H%M%S)"
aws s3 cp "$tmp/" "s3://$B/$prefix/" --recursive
echo "FINAL_EVIDENCE=s3://$B/$prefix/"
echo FINAL_VALIDATION_COMPLETE
