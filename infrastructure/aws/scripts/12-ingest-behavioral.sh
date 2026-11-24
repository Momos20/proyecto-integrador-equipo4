#!/usr/bin/env bash
set -euo pipefail
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
[[ "$(aws sts get-caller-identity --query Account --output text)" == 023914826547 ]]
instance=$(aws cloudformation describe-stacks --stack-name cinegraph-e4-web --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue | [0]" --output text)
params=$(python3 - <<'PY'
import json
print(json.dumps({"commands":[
"set -euo pipefail",
"git -C /opt/cinegraph/source pull --ff-only origin main",
"test -s /opt/cinegraph/runtime/clickstream/clickstream.log",
"docker build --tag cinegraph-e4-kinesis-agent:main --file /opt/cinegraph/source/infrastructure/docker/kinesis-agent.Dockerfile /opt/cinegraph/source",
"mkdir -p /opt/cinegraph/runtime/kinesis-agent",
"sed -e 's/__AWS_REGION__/us-east-1/g' -e 's/__KINESIS_STREAM_NAME__/cinegraph-e4-clickstream/g' -e 's/END_OF_FILE/START_OF_FILE/g' /opt/cinegraph/source/infrastructure/kinesis/agent.json.template > /opt/cinegraph/runtime/kinesis-agent/agent.json",
"if ! docker container inspect cinegraph-e4-kinesis-agent >/dev/null 2>&1; then docker run -d --name cinegraph-e4-kinesis-agent --restart unless-stopped --network host -v /opt/cinegraph/runtime/clickstream:/var/log/cinegraph:ro -v /opt/cinegraph/runtime/kinesis-agent/agent.json:/etc/aws-kinesis/agent.json:ro -v cinegraph-e4-agent-state:/var/run/aws-kinesis-agent --entrypoint start-aws-kinesis-agent cinegraph-e4-kinesis-agent:main; else docker start cinegraph-e4-kinesis-agent; fi",
"sleep 8",
"docker ps --filter name=cinegraph-e4-kinesis-agent --format '{{.Names}} {{.Status}}'",
"test \"$(docker inspect -f '{{.State.Running}}' cinegraph-e4-kinesis-agent)\" = true",
"docker logs --tail 40 cinegraph-e4-kinesis-agent 2>&1",
"echo AGENT_RUNNING"
]}))
PY
)
id=$(aws ssm send-command --instance-ids "$instance" --document-name AWS-RunShellScript --comment "CineGraph agente behavioral AWS" --timeout-seconds 900 --parameters "$params" --query Command.CommandId --output text)
echo "SSM CommandId=$id"
aws ssm wait command-executed --command-id "$id" --instance-id "$instance" || true
aws ssm get-command-invocation --command-id "$id" --instance-id "$instance" --query '{Estado:Status,Codigo:ResponseCode,Salida:StandardOutputContent,Error:StandardErrorContent}' --output json
[[ "$(aws ssm get-command-invocation --command-id "$id" --instance-id "$instance" --query Status --output text)" == Success ]]
bucket=cinegraph-e4-datalake-023914826547-us-east-1
for i in $(seq 1 12); do
  count=$(aws s3api list-objects-v2 --bucket "$bucket" --prefix raw/behavioral/ --max-keys 1 --query KeyCount --output text)
  if [[ "$count" -gt 0 ]]; then
    aws s3 ls "s3://$bucket/raw/behavioral/" --recursive
    echo RAW_OBJECT_PRESENT
    exit 0
  fi
  sleep 15
done
echo RAW_DELIVERY_NOT_YET_VERIFIED >&2
exit 2
