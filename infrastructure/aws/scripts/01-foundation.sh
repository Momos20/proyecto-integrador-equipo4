#!/usr/bin/env bash
# Fase 1 AWS Academy - S3 privado y grupos de seguridad; no crea EC2/RDS.
# --plan no crea nada; --apply solo con CONFIRM_LAB_DEPLOY=YES.
set -euo pipefail
export AWS_PAGER="" AWS_EC2_METADATA_DISABLED=true AWS_MAX_ATTEMPTS=2 AWS_CLI_AUTO_PROMPT=off
PROFILE="${AWS_PROFILE:-}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
AWS=(aws)
if [[ -n "$PROFILE" ]]; then
  AWS+=(--profile "$PROFILE")
fi
if [[ -z "$REGION" ]]; then
  REGION="$("${AWS[@]}" configure get region 2>/dev/null || true)"
fi
[[ -n "$REGION" ]] || { echo "ERROR: define AWS_REGION" >&2; exit 2; }
AWS+=(--region "$REGION")
MODE="${1:---plan}"
if [[ "$MODE" != "--plan" && "$MODE" != "--apply" ]]; then
  echo "Uso: VPC_ID=vpc-... WEB_INGRESS_MODE=None|CloudFront|RestrictedIP bash infrastructure/aws/scripts/01-foundation.sh [--plan|--apply]" >&2
  exit 2
fi
: "${VPC_ID:?Se requiere el ID de VPC validado en el preflight}"
[[ "$VPC_ID" =~ ^vpc-[a-z0-9]+$ ]] || { echo "ERROR: VPC_ID invalido" >&2; exit 2; }
INGRESS="${WEB_INGRESS_MODE:-None}"
CIDR="127.0.0.1/32"
PREFIX_LIST_ID=""
case "$INGRESS" in
  None)
    echo "Sin acceso web: los SG no expondran el puerto 8000 todavia." ;;
  RestrictedIP)
    : "${ALLOWED_CIDR:?Se requiere ALLOWED_CIDR=IP/32 para diagnostico}"
    CIDR="$ALLOWED_CIDR"
    if [[ "$CIDR" == "0.0.0.0/0" || ! "$CIDR" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/32$ ]]; then
      echo "ERROR: solo se admite IP publica individual /32 para RestrictedIP" >&2; exit 2
    fi
    python3 - "$CIDR" <<'PY'
import ipaddress,sys
try:
    addr=ipaddress.ip_network(sys.argv[1], strict=True)
    assert addr.version == 4 and addr.prefixlen == 32 and addr.is_global
except (ValueError, AssertionError):
    raise SystemExit("ERROR: ALLOWED_CIDR no es IPv4 publico /32")
PY
    ;;
  CloudFront)
    PREFIX_LIST_ID="${CLOUDFRONT_PREFIX_LIST_ID:-}"
    if [[ -z "$PREFIX_LIST_ID" ]]; then
      PREFIX_LIST_ID="$("${AWS[@]}" ec2 describe-managed-prefix-lists \
        --filters "Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing" \
        --query 'PrefixLists[0].PrefixListId' --output text)"
    fi
    if [[ ! "$PREFIX_LIST_ID" =~ ^pl-[0-9a-f]+$ ]]; then
      echo "ERROR: no se pudo determinar el prefijo AWS de origen CloudFront" >&2; exit 2
    fi
    ;;
  *)
    echo "ERROR: WEB_INGRESS_MODE debe ser None, RestrictedIP o CloudFront" >&2; exit 2 ;;
esac
STACK="${STACK_NAME:-cinegraph-e4-dev-foundation}"
TEMPLATE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/cloudformation/01-foundation.yaml"
echo "AWS: region=$REGION | credenciales=${PROFILE:-CloudShell nativo} | stack=$STACK"
"${AWS[@]}" sts get-caller-identity --query Account --output text >/dev/null
"${AWS[@]}" cloudformation validate-template --template-body "file://$TEMPLATE" \
  --query Description --output text
echo "VPC=$VPC_ID | web=$INGRESS | DB=privada"
if [[ "$MODE" == "--plan" ]]; then
  echo "PLAN OK: S3 privado + 2 SG. No se crean recursos."
  echo "Acceso externo deshabilitado de momento (None)."
  exit 0
fi
if [[ "${CONFIRM_LAB_DEPLOY:-}" != "YES" ]]; then
  echo "BLOQUEADO: establece CONFIRM_LAB_DEPLOY=YES para crear recursos." >&2
  exit 2
fi
"${AWS[@]}" cloudformation deploy \
  --stack-name "$STACK" \
  --template-file "$TEMPLATE" \
  --parameter-overrides "VpcId=$VPC_ID" "WebIngressMode=$INGRESS" \
    "AllowedClientCidr=$CIDR" "CloudFrontPrefixListId=$PREFIX_LIST_ID" \
  --tags Project=CineGraph Environment=dev Team=E4 \
  --no-fail-on-empty-changeset
"${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" \
  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table
echo "BASE COMPLETADA: confirma la salida antes de EC2, RDS y distribucion HTTPS."
