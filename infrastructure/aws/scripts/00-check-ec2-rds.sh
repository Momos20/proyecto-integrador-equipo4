#!/usr/bin/env bash
# CineGraph AWS Academy: comprobación EC2 / RDS / VPC para despliegue público.
# SOLO LECTURA; no crea ni modifica recursos AWS.
set -euo pipefail
export AWS_PAGER="" AWS_CLI_AUTO_PROMPT=off AWS_EC2_METADATA_DISABLED=true AWS_MAX_ATTEMPTS=2
AWS=(aws)
if [[ -n "${AWS_PROFILE:-}" ]]; then AWS+=(--profile "$AWS_PROFILE"); fi
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
[[ -n "$REGION" ]] || { echo "ERROR: define AWS_REGION" >&2; exit 2; }
AWS+=(--region "$REGION")
: "${VPC_ID:?Define VPC_ID con la VPC comprobada en el laboratorio}"
[[ "$VPC_ID" =~ ^vpc-[a-z0-9]+$ ]] || { echo "ERROR: identificador VPC invalido" >&2; exit 2; }
run() {
  local label="$1"; shift
  printf '\n%s\n' "$label"
  if ! "${AWS[@]}" "$@"; then
    echo "AVISO: consulta no autorizada, recurso no disponible o filtro vacio."
  fi
}
echo "==== CineGraph | Preflight operacional para EC2 + RDS (solo lectura) ===="
echo "Region=$REGION | VPC=$VPC_ID | no se requieren credenciales copiadas desde Mac"
run "[1/8] Cuenta AWS (identificador, sin claves)" sts get-caller-identity --query 'Account' --output text
run "[2/8] VPC y DNS publico para nombre de EC2" ec2 describe-vpc-attribute --vpc-id "$VPC_ID" --attribute enableDnsHostnames --query '[EnableDnsHostnames.Value]' --output table
run "[3/8] Subredes y CIDR ocupados (para no solapar nuevas subredes privadas)" ec2 describe-subnets \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'Subnets[].[SubnetId,AvailabilityZone,CidrBlock,MapPublicIpOnLaunch]' --output table
run "[4/8] Internet Gateway adjunto (para acceso publico al frontend)" ec2 describe-internet-gateways \
  --filters "Name=attachment.vpc-id,Values=$VPC_ID" \
  --query 'InternetGateways[].[InternetGatewayId,Attachments[0].State]' --output table
run "[5/8] Tablas de rutas; revisar ruta 0.0.0.0/0 hacia igw" ec2 describe-route-tables \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'RouteTables[].[RouteTableId,Associations[].SubnetId,Routes[?DestinationCidrBlock==`0.0.0.0/0`].GatewayId]' --output json
run "[6/8] Oferta regional de instancias EC2 t3.micro y t3.small" ec2 describe-instance-type-offerings \
  --location-type region --filters "Name=instance-type,Values=t3.micro,t3.small" \
  --query 'InstanceTypeOfferings[].[InstanceType,Location]' --output table
run "[7/8] Tipo db.t3.micro disponible para PostgreSQL en RDS" rds describe-orderable-db-instance-options \
  --engine postgres --db-instance-class db.t3.micro --max-items 1 \
  --query 'OrderableDBInstanceOptions[].[EngineVersion,DBInstanceClass,StorageType]' --output table
run "[8/8] Instancias EC2 existentes para evitar duplicados" ec2 describe-instances \
  --filters "Name=instance-state-name,Values=pending,running,stopped" \
  --query 'Reservations[].Instances[].[InstanceId,InstanceType,State.Name,PublicIpAddress]' --output table
echo
echo "FIN: no se creó ninguna VPC, subred, EC2, RDS, SG ni otro recurso."
echo "Comparte solo esta salida sin tokens ni contraseñas."
