#!/usr/bin/env bash
# Fase 2: red de RDS, independiente de foundation. Por defecto, PLAN sin cambios.
set -euo pipefail
export AWS_PAGER="" AWS_EC2_METADATA_DISABLED=true AWS_MAX_ATTEMPTS=2 AWS_CLI_AUTO_PROMPT=off

MODE="${1:---plan}"
if [[ "$MODE" != "--plan" && "$MODE" != "--apply" ]]; then
  echo "Uso: bash infrastructure/aws/scripts/02-db-network.sh [--plan|--apply]" >&2
  exit 2
fi
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
[[ -n "$REGION" ]] || { echo "ERROR: configura AWS_REGION" >&2; exit 2; }
AWS=(aws)
if [[ -n "${AWS_PROFILE:-}" ]]; then AWS+=(--profile "$AWS_PROFILE"); fi
AWS+=(--region "$REGION")

FOUNDATION_STACK="${FOUNDATION_STACK_NAME:-cinegraph-lab-foundation}"
STACK="${DB_NETWORK_STACK_NAME:-cinegraph-lab-db-network}"
TEMPLATE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/cloudformation/02-db-network.yaml"
AZ_A="${PRIVATE_DB_AZ_A:-${REGION}a}"
AZ_B="${PRIVATE_DB_AZ_B:-${REGION}b}"
CIDR_A="${PRIVATE_DB_CIDR_A:-172.31.96.0/24}"
CIDR_B="${PRIVATE_DB_CIDR_B:-172.31.97.0/24}"

echo "==== CineGraph AWS Academy | Red privada para RDS ===="
echo "Region: $REGION | Stack existente: $FOUNDATION_STACK"
ACCOUNT="$("${AWS[@]}" sts get-caller-identity --query Account --output text)"
[[ "$ACCOUNT" =~ ^[0-9]{12}$ ]] || { echo "ERROR: identidad AWS invalida" >&2; exit 2; }
echo "Credenciales CloudShell correctas (cuenta termina en ${ACCOUNT: -4})."

FOUNDATION_STATUS="$("${AWS[@]}" cloudformation describe-stacks \
  --stack-name "$FOUNDATION_STACK" --query 'Stacks[0].StackStatus' --output text)"
case "$FOUNDATION_STATUS" in
  CREATE_COMPLETE|UPDATE_COMPLETE) ;;
  *)
    echo "ERROR: la pila foundation no esta estable: $FOUNDATION_STATUS" >&2
    exit 3 ;;
esac
VPC_ID="$("${AWS[@]}" cloudformation describe-stacks \
  --stack-name "$FOUNDATION_STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='VpcId'].OutputValue | [0]" --output text)"
[[ "$VPC_ID" =~ ^vpc-[0-9a-f]+$ ]] || { echo "ERROR: foundation no devolvio una VPC" >&2; exit 3; }

echo "VPC reutilizada: $VPC_ID"
"${AWS[@]}" cloudformation validate-template --template-body "file://$TEMPLATE" \
  --query Description --output text

# Si la red ya existe, mostrarla; evita que una segunda ejecucion choque
# con los CIDR que la misma pila ocupa.
if EXISTING_STATUS="$("${AWS[@]}" cloudformation describe-stacks \
  --stack-name "$STACK" --query 'Stacks[0].StackStatus' --output text 2>/dev/null)"; then
  case "$EXISTING_STATUS" in
    CREATE_COMPLETE|UPDATE_COMPLETE)
      echo "La pila de red ya existe en estado $EXISTING_STATUS; no se modificara."
      "${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" \
        --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table
      exit 0 ;;
    *)
      echo "ERROR: la pila de red ya existe pero esta en estado $EXISTING_STATUS; revisa CloudFormation." >&2
      exit 3 ;;
  esac
fi

VPC_CIDR="$("${AWS[@]}" ec2 describe-vpcs --vpc-ids "$VPC_ID" \
  --query 'Vpcs[0].CidrBlock' --output text)"
USED_CIDRS="$("${AWS[@]}" ec2 describe-subnets \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'Subnets[].CidrBlock' --output json)"
AVAILABLE_AZS="$("${AWS[@]}" ec2 describe-availability-zones \
  --filters 'Name=state,Values=available' \
  --query 'AvailabilityZones[].ZoneName' --output json)"

python3 - "$VPC_CIDR" "$CIDR_A" "$CIDR_B" "$AZ_A" "$AZ_B" "$USED_CIDRS" "$AVAILABLE_AZS" <<'PY'
import ipaddress
import json
import sys

vpc, subnet_a, subnet_b = (ipaddress.ip_network(v, strict=True) for v in sys.argv[1:4])
az_a, az_b = sys.argv[4:6]
used = [ipaddress.ip_network(value) for value in json.loads(sys.argv[6])]
available_zones = json.loads(sys.argv[7])
if (vpc.version, subnet_a.version, subnet_b.version) != (4, 4, 4):
    raise SystemExit("ERROR: solo se admite IPv4 en esta plantilla")
if subnet_a == subnet_b or subnet_a.overlaps(subnet_b):
    raise SystemExit("ERROR: las dos subredes propuestas se solapan")
if not subnet_a.subnet_of(vpc) or not subnet_b.subnet_of(vpc):
    raise SystemExit("ERROR: las subredes deben estar dentro del CIDR de la VPC")
if az_a == az_b or az_a not in available_zones or az_b not in available_zones:
    raise SystemExit("ERROR: se requieren dos zonas de disponibilidad distintas y habilitadas")
for candidate in (subnet_a, subnet_b):
    for existing in used:
        if candidate.overlaps(existing):
            raise SystemExit(f"ERROR: {candidate} se solapa con subnet existente {existing}")
print(f"CIDR verificados: {subnet_a} en {az_a}; {subnet_b} en {az_b}")
print("Sin solapamientos con las subredes existentes de la VPC.")
PY

echo "Ruta privada: solo local VPC; sin NAT Gateway ni ruta 0.0.0.0/0."
if [[ "$MODE" == "--plan" ]]; then
  echo "PLAN OK: 2 subredes privadas + tabla de rutas + DB Subnet Group."
  echo "CERO recursos creados en este paso. Esperar validacion antes de --apply."
  exit 0
fi
if [[ "${CONFIRM_LAB_DEPLOY:-}" != "YES" ]]; then
  echo "BLOQUEADO: para crear recursos establece CONFIRM_LAB_DEPLOY=YES." >&2
  exit 2
fi
echo "Creando solo subredes, tabla de rutas y DB Subnet Group; sin instancia RDS."
"${AWS[@]}" cloudformation deploy \
  --stack-name "$STACK" \
  --template-file "$TEMPLATE" \
  --parameter-overrides \
    "VpcId=$VPC_ID" \
    "AvailabilityZoneA=$AZ_A" "AvailabilityZoneB=$AZ_B" \
    "PrivateCidrA=$CIDR_A" "PrivateCidrB=$CIDR_B" \
  --tags Project=CineGraph Environment=AcademyLab \
  --no-fail-on-empty-changeset
echo "Recursos de red de BD:"
"${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" \
  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table
echo "Ahora verificar que ambas subredes no tengan IP publicas ni ruta por defecto a Internet."
