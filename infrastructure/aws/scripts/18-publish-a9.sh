#!/usr/bin/env bash
set -euo pipefail
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
[[ "$(aws sts get-caller-identity --query Account --output text)" == 023914826547 ]]
B=cinegraph-e4-datalake-023914826547-us-east-1
P=predictions/a9/2023-06-15/ec2-20261124031146
W=i-03306ae6540b03d3e
WEB=i-0e3288445cb0df13d
[[ "$(aws ssm get-command-invocation --command-id 33357d81-885a-4bad-9009-a8abd24c2bc0 --instance-id "$W" --query Status --output text)" == Success ]]
aws s3api head-object --bucket "$B" --key "$P/top10.json" --query ContentLength
aws s3 cp "s3://$B/$P/top10.manifest.json" -
echo
[[ "$(aws ec2 describe-instances --instance-ids "$W" --query 'Reservations[0].Instances[0].Tags[?Key==`Name`].Value | [0]' --output text)" == cinegraph-e4-a9-worker ]]
aws ec2 stop-instances --instance-ids "$W" --query 'StoppingInstances[].CurrentState.Name'
ARN=$(aws rds describe-db-instances --db-instance-identifier cinegraph-e4-postgres --query 'DBInstances[0].MasterUserSecret.SecretArn' --output text)
[[ "$ARN" == arn:aws:secretsmanager:us-east-1:* ]]
root=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$root"
aws s3 cp infrastructure/aws/scripts/18-publish-a9.py "s3://$B/scripts/a9/18-publish-a9.py"
params=$(python3 - "$ARN" <<'PY'
import sys,json,shlex
arn=shlex.quote(sys.argv[1])
print(json.dumps({"commands":["set -euo pipefail","cd /opt/cinegraph/source","git pull --ff-only origin main","docker exec -i -e RDS_SECRET_ARN="+arn+" cinegraph-e4-app python - < infrastructure/aws/scripts/18-publish-a9.py","docker exec -i cinegraph-e4-app python - < infrastructure/aws/scripts/09-auth-smoke.py"],"executionTimeout":["300"]}))
PY
)
ID=$(aws ssm send-command --instance-ids "$WEB" --document-name AWS-RunShellScript --parameters "$params" --query Command.CommandId --output text)
echo "PUBLISH_COMMAND_ID=$ID"
aws ssm wait command-executed --command-id "$ID" --instance-id "$WEB" || true
aws ssm get-command-invocation --command-id "$ID" --instance-id "$WEB" --query '{Status:Status,Output:StandardOutputContent,Error:StandardErrorContent}'
