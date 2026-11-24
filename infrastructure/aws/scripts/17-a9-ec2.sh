#!/usr/bin/env bash
set -euo pipefail
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
[[ "$(aws sts get-caller-identity --query Account --output text)" == 023914826547 ]]
bucket=cinegraph-e4-datalake-023914826547-us-east-1
root=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$root"
# Independent worker; no inbound access, managed through SSM.
vpc=vpc-083d9bebc31224f94
subnet=subnet-07413c35ec3498c14
ami=ami-0aacbf72109c53c0c
sg=$(aws ec2 describe-security-groups --filters Name=vpc-id,Values="$vpc" Name=group-name,Values=cinegraph-e4-a9-worker --query 'SecurityGroups[0].GroupId' --output text)
if [[ "$sg" == None ]]; then
  sg=$(aws ec2 create-security-group --group-name cinegraph-e4-a9-worker --description 'A9 batch worker; no inbound access' --vpc-id "$vpc" --query GroupId --output text)
fi
instance=$(aws ec2 describe-instances --filters Name=tag:Name,Values=cinegraph-e4-a9-worker Name=instance-state-name,Values=pending,running,stopping,stopped --query 'Reservations[0].Instances[0].InstanceId' --output text)
if [[ "$instance" == None ]]; then
  rootdev=$(aws ec2 describe-images --image-ids "$ami" --query 'Images[0].RootDeviceName' --output text)
  instance=$(aws ec2 run-instances --image-id "$ami" --instance-type t3.large --count 1 --iam-instance-profile Name=LabInstanceProfile --network-interfaces "DeviceIndex=0,SubnetId=$subnet,Groups=$sg,AssociatePublicIpAddress=true" --metadata-options HttpTokens=required --block-device-mappings "DeviceName=$rootdev,Ebs={VolumeSize=30,VolumeType=gp3,DeleteOnTermination=true}" --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=cinegraph-e4-a9-worker}]' --credit-specification CpuCredits=standard --query 'Instances[0].InstanceId' --output text)
else
  state=$(aws ec2 describe-instances --instance-ids "$instance" --query 'Reservations[0].Instances[0].State.Name' --output text)
  [[ "$state" != stopping ]] || { echo 'Worker stopping; retry after stopped'; exit 1; }
  if [[ "$state" == stopped ]]; then aws ec2 start-instances --instance-ids "$instance" >/dev/null; fi
fi
echo "A9_WORKER=$instance"
aws ec2 wait instance-running --instance-ids "$instance"
for i in $(seq 1 60); do
  online=$(aws ssm describe-instance-information --filters Key=InstanceIds,Values="$instance" --query 'InstanceInformationList[0].PingStatus' --output text)
  [[ "$online" == Online ]] && break
  sleep 5
done
[[ "$online" == Online ]]
# Keep one job per worker. A repeat deployment does not start another if locked.
aws s3 cp infrastructure/aws/scripts/17-a9-worker.py "s3://$bucket/scripts/a9/17-a9-worker.py"
prefix="predictions/a9/2023-06-15/ec2-$(date -u +%Y%m%d%H%M%S)"
params=$(python3 - "$prefix" <<'PY'
import json,sys
p=sys.argv[1]
print(json.dumps({"commands":[
"set -euo pipefail",
"exec 9>/var/lock/cinegraph-a9.lock",
"flock -n 9",
"mkdir -p /opt/cinegraph-a9",
"cd /opt/cinegraph-a9",
"if ! swapon --show=NAME --noheadings | grep -Fxq /swap-a9; then if [ ! -f /swap-a9 ]; then fallocate -l 12G /swap-a9; chmod 600 /swap-a9; mkswap /swap-a9; fi; swapon /swap-a9; fi",
"free -h",
"df -h /",
"command -v python3.11 || dnf install -y python3.11 python3.11-pip",
"python3.11 -m venv /opt/cinegraph-a9/venv",
"venv/bin/python -m pip install --no-cache-dir boto3",
"aws s3 cp s3://cinegraph-e4-datalake-023914826547-us-east-1/scripts/a9/17-a9-worker.py worker.py",
"OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 PREDICTION_PREFIX="+p+" venv/bin/python -u worker.py"
],"executionTimeout":["7200"]}))
PY
)
id=$(aws ssm send-command --instance-ids "$instance" --document-name AWS-RunShellScript --comment "CineGraph A9 historical CPU batch" --timeout-seconds 600 --parameters "$params" --query Command.CommandId --output text)
echo "A9_COMMAND_ID=$id"
echo "A9_OUTPUT=s3://$bucket/$prefix/"
echo "A9_WORKER=$instance"
echo "Use aws ssm get-command-invocation --command-id $id --instance-id $instance --query '{Status:Status,Output:StandardOutputContent,Error:StandardErrorContent}'"
echo "Stop worker after verified output or failure to avoid ongoing compute costs."
