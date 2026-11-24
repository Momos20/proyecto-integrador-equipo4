#!/usr/bin/env bash
set -euo pipefail
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
[[ "$(aws sts get-caller-identity --query Account --output text)" == 023914826547 ]]
bucket=cinegraph-e4-datalake-023914826547-us-east-1
root=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$root"
python3 -m py_compile infrastructure/aws/scripts/15-a9-processing.py
aws s3 cp infrastructure/aws/scripts/15-a9-processing.py "s3://$bucket/scripts/a9/15-a9-processing.py"
job="cinegraph-e4-a9-$(date -u +%Y%m%d%H%M%S)"
prefix="predictions/a9/2023-06-15/$job"
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
python3 - "$job" "$bucket" "$prefix" > "$tmp" <<'PY'
import json,sys
j,b,p=sys.argv[1:]
def inp(name,key,path):
    return {"InputName":name,"S3Input":{"S3Uri":"s3://"+b+"/"+key,"LocalPath":path,"S3DataType":"S3Prefix","S3InputMode":"File"}}
print(json.dumps({
"ProcessingJobName":j,
"RoleArn":"arn:aws:iam::023914826547:role/LabRole",
"AppSpecification":{"ImageUri":"683313688378.dkr.ecr.us-east-1.amazonaws.com/sagemaker-scikit-learn:1.2-1-cpu-py3","ContainerEntrypoint":["python3","-u","/opt/ml/processing/input/code/15-a9-processing.py"]},
"ProcessingResources":{"ClusterConfig":{"InstanceCount":1,"InstanceType":"ml.m5.2xlarge","VolumeSizeInGB":30}},
"StoppingCondition":{"MaxRuntimeInSeconds":3600},
"ProcessingInputs":[inp("code","scripts/a9/15-a9-processing.py","/opt/ml/processing/input/code"),inp("assets","models/a9/a9-source.tar.gz","/opt/ml/processing/input/assets")],
"ProcessingOutputConfig":{"Outputs":[{"OutputName":"predictions","S3Output":{"S3Uri":"s3://"+b+"/"+p,"LocalPath":"/opt/ml/processing/output","S3UploadMode":"EndOfJob"}}]},
"Environment":{"PREDICTION_PREFIX":p,"OMP_NUM_THREADS":"4","MKL_NUM_THREADS":"4"},
"NetworkConfig":{"EnableNetworkIsolation":False}
}))
PY
aws sagemaker create-processing-job --cli-input-json "file://$tmp"
echo "A9_JOB=$job"
echo "A9_OUTPUT=s3://$bucket/$prefix/"
for i in $(seq 1 120); do
 state=$(aws sagemaker describe-processing-job --processing-job-name "$job" --query ProcessingJobStatus --output text)
 echo "A9_STATE=$state"
 case "$state" in
 Completed) aws s3 cp "s3://$bucket/$prefix/top10.manifest.json" -; echo; echo A9_PROCESSING_VERIFIED; exit 0;;
 Failed|Stopped) aws sagemaker describe-processing-job --processing-job-name "$job" --query '{Status:ProcessingJobStatus,Reason:FailureReason}'; exit 1;;
 *) sleep 30;;
 esac
done
echo "Polling limit reached; inspect $job before retrying." >&2
exit 2
