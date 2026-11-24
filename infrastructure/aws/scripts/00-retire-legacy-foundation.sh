#!/usr/bin/env bash
# Retiro controlado, EXCLUSIVAMENTE de la primera pila CineGraph.
# --inspect solo lee. --delete exige confirmacion exacta y S3 vacio.
set -euo pipefail
export AWS_PAGER="" AWS_EC2_METADATA_DISABLED=true AWS_MAX_ATTEMPTS=2 AWS_CLI_AUTO_PROMPT=off
MODE="${1:---inspect}"
[[ "$MODE" == "--inspect" || "$MODE" == "--delete" ]] || { echo "Uso: --inspect|--delete" >&2; exit 2; }
: "${EXPECTED_ACCOUNT_ID:?Falta EXPECTED_ACCOUNT_ID de la cuenta validada}"
[[ "$EXPECTED_ACCOUNT_ID" =~ ^[0-9]{12}$ ]] || { echo "ERROR: cuenta esperada invalida" >&2; exit 2; }
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
[[ "$REGION" == "us-east-1" ]] || { echo "ERROR: solo us-east-1" >&2; exit 2; }
AWS=(aws)
[[ -z "${AWS_PROFILE:-}" ]] || AWS+=(--profile "$AWS_PROFILE")
AWS+=(--region "$REGION")
STACK="cinegraph-lab-foundation"
BUCKET="cinegraph-lab-foundation-datalakebucket-lrnkpdjo5xiv"
APP="sg-00d7ff2cb71f16854"
DB="sg-004792f0dba4268be"
VPC="vpc-083d9bebc31224f94"
ACCOUNT="$("${AWS[@]}" sts get-caller-identity --query Account --output text)"
[[ "$ACCOUNT" == "$EXPECTED_ACCOUNT_ID" ]] || { echo "BLOQUEADO: cuenta inesperada $ACCOUNT" >&2; exit 3; }
echo "Cuenta confirmada (ultimos cuatro: ${ACCOUNT: -4})"
STACK_JSON="$("${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" --output json)"
RESOURCES="$("${AWS[@]}" cloudformation list-stack-resources --stack-name "$STACK" --output json)"
python3 - "$STACK_JSON" "$RESOURCES" "$BUCKET" "$APP" "$DB" "$VPC" <<'PY'
import json,sys
s=json.loads(sys.argv[1])["Stacks"][0]
r=json.loads(sys.argv[2])["StackResourceSummaries"]
bucket,app,db,vpc=sys.argv[3:7]
expected={
    "DataLakeBucket": ("AWS::S3::Bucket",bucket),
    "AppSecurityGroup": ("AWS::EC2::SecurityGroup",app),
    "DatabaseSecurityGroup": ("AWS::EC2::SecurityGroup",db),
}
assert s["StackName"]=="cinegraph-lab-foundation", "Nombre de stack inesperado"
assert s["StackStatus"] in {"CREATE_COMPLETE","UPDATE_COMPLETE"}, "Estado de stack no estable"
assert len(r)==len(expected), "La pila tiene recursos adicionales; no se elimina"
for item in r:
    key=item["LogicalResourceId"]
    assert key in expected and (
        item["ResourceType"],item["PhysicalResourceId"]
    )==expected[key], f"Recurso inesperado: {key}"
assert any(o["OutputKey"]=="VpcId" and o["OutputValue"]==vpc
           for o in s.get("Outputs",[])), "VPC incorrecta"
print("OK: pila y tres recursos coinciden exactamente con los originales.")
PY

# Nunca borrar si no se pueden comprobar objetos actuales Y versiones.
verify_empty() {
  local current versions
  current="$("${AWS[@]}" s3api list-objects-v2 --bucket "$BUCKET" \
    --max-keys 1 --no-paginate --output json)"
  versions="$("${AWS[@]}" s3api list-object-versions --bucket "$BUCKET" \
    --max-keys 1 --no-paginate --output json)"
  python3 - "$current" "$versions" <<'PY'
import json,sys
a,b=map(json.loads,sys.argv[1:3])
if a.get("KeyCount",0) or a.get("Contents") or b.get("Versions") or b.get("DeleteMarkers"):
    raise SystemExit("BLOQUEADO: S3 contiene objetos o versiones; no se borraran datos.")
print("OK: S3 sin objetos actuales, versiones ni delete markers.")
PY
}
verify_empty
for group in "$APP" "$DB"; do
  count="$("${AWS[@]}" ec2 describe-network-interfaces \
    --filters "Name=group-id,Values=$group" \
    --query 'length(NetworkInterfaces)' --output text)"
  [[ "$count" == "0" ]] || { echo "BLOQUEADO: $group tiene interfaces de red" >&2; exit 4; }
done
echo "OK: SG no asociados a interfaces."
echo "Se eliminaria: stack=$STACK, SG=$APP/$DB y bucket vacio=$BUCKET"
echo "Se conserva: VPC, local Docker/Floci y cualquier recurso fuera de esta pila."
if [[ "$MODE" == "--inspect" ]]; then
  echo "INSPECCION OK: NO SE ELIMINO NINGUN RECURSO."
  exit 0
fi
[[ "${CONFIRM_DELETE_LEGACY_CINEGRAPH:-}" == "DELETE_cinegraph-lab-foundation" ]] || {
  echo "BLOQUEADO: falta CONFIRM_DELETE_LEGACY_CINEGRAPH=DELETE_cinegraph-lab-foundation" >&2; exit 2;
}
echo "Retirando pila anterior. Bucket conserva DeletionPolicy: Retain."
"${AWS[@]}" cloudformation delete-stack --stack-name "$STACK"
"${AWS[@]}" cloudformation wait stack-delete-complete --stack-name "$STACK"
echo "Pila eliminada. Verificando bucket retenido una segunda vez..."
verify_empty
"${AWS[@]}" s3api delete-bucket --bucket "$BUCKET"
echo "OK: pila anterior eliminada y bucket vacio retirado. Sin eliminar objetos."
