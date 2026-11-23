#!/usr/bin/env bash
# Fase 1 - S3 privado + SG EC2/RDS. Solo crea con --apply y confirmacion explicita.
set -euo pipefail
export AWS_PAGER="" AWS_EC2_METADATA_DISABLED=true AWS_MAX_ATTEMPTS=2 AWS_CLI_AUTO_PROMPT=off
PROFILE="${AWS_PROFILE:-}"
AWS=(aws)
if [[ -n "$PROFILE" ]]; then
  AWS+=(--profile "$PROFILE")
fi
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
if [[ -z "$REGION" ]]; then
  REGION="$("${AWS[@]}" configure get region 2>/dev/null || true)"
fi
[[ -n "$REGION" ]] || { echo 'ERROR: falta AWS_REGION' >&2; exit 2; }
MODE="${1:---plan}"
if [[ "$MODE" != '--plan' && "$MODE" != '--apply' ]]; then
  echo 'Uso: AWS_REGION=<region> VPC_ID=vpc-... ALLOWED_CIDR=a.b.c.d/32 bash infrastructure/aws/scripts/01-foundation.sh [--plan|--apply] (AWS_PROFILE opcional)' >&2
  exit 2
fi
: "${VPC_ID:?Falta VPC_ID; usa el ID verificado en el preflight.}"
: "${ALLOWED_CIDR:?Falta ALLOWED_CIDR; usa la IP publica de tu Mac con /32.}"
if [[ ! "$VPC_ID" =~ ^vpc-[a-z0-9]+$ ]]; then
  echo 'ERROR: formato VPC_ID invalido' >&2; exit 2
fi
if [[ "$ALLOWED_CIDR" == '0.0.0.0/0' || ! "$ALLOWED_CIDR" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/32$ ]]; then
  echo 'ERROR: ALLOWED_CIDR debe ser una IP individual a.b.c.d/32 (no abierto a Internet).' >&2; exit 2
fi
if ! python3 - "$ALLOWED_CIDR" <<'PY_IP'
import ipaddress,sys
try:
    network = ipaddress.ip_network(sys.argv[1],strict=True)
    assert network.prefixlen == 32 and network.is_global
except (ValueError,AssertionError):
    raise SystemExit(1)
PY_IP
then
  echo 'ERROR: ALLOWED_CIDR no es una direccion IPv4 publica valida /32.' >&2; exit 2
fi
AWS+=(--region "$REGION")
TEMPLATE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/cloudformation/01-foundation.yaml"
STACK="${STACK_NAME:-cinegraph-lab-foundation}"
echo "Credenciales: ${PROFILE:-CloudShell nativo} | Region: $REGION | Stack: $STACK"
"${AWS[@]}" sts get-caller-identity --query Account --output text >/dev/null
"${AWS[@]}" cloudformation validate-template --template-body "file://$TEMPLATE" --query Description --output text
echo "VPC: $VPC_ID | Acceso web: $ALLOWED_CIDR (solo puerto 8000)"
if [[ "$MODE" == '--plan' ]]; then
  echo 'PLAN OK: S3 privado + 2 Security Groups. NO se crearon recursos.'
  echo 'Con autorizacion de tu laboratorio, ejecuta el mismo comando con --apply tras validar permisos.'
  exit 0
fi
if [[ "${CONFIRM_LAB_DEPLOY:-}" != 'YES' ]]; then
  echo 'BLOQUEADO: para crear recursos establece CONFIRM_LAB_DEPLOY=YES; valida primero el preflight.' >&2
  exit 2
fi
echo 'Creando recursos CloudFormation SOLO para fase 1 (S3 y Security Groups)...'
"${AWS[@]}" cloudformation deploy \
  --stack-name "$STACK" \
  --template-file "$TEMPLATE" \
  --parameter-overrides "VpcId=$VPC_ID" "AllowedClientCidr=$ALLOWED_CIDR" \
  --tags Project=CineGraph Environment=AcademyLab \
  --no-fail-on-empty-changeset
"${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" \
  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table
echo 'FASE 1 COMPLETA: verifica los Outputs antes de continuar con EC2/RDS.'