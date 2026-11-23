#!/usr/bin/env bash
# Solo lectura: comprueba credenciales efimeras, region, red y servicios AWS Academy.
# NO CREA NI BORRA recursos. No imprime access keys ni tokens.
set -euo pipefail
export AWS_PAGER="" AWS_EC2_METADATA_DISABLED=true AWS_MAX_ATTEMPTS=2 AWS_CLI_AUTO_PROMPT=off

PROFILE="${AWS_PROFILE:-}"
# En CloudShell las credenciales son nativas de la sesion, sin perfil de Mac.
# Si AWS_PROFILE se define explicitamente, se respeta.
AWS=(aws)
if [[ -n "$PROFILE" ]]; then
  AWS+=(--profile "$PROFILE")
fi
if ! command -v aws >/dev/null 2>&1; then
  echo 'ERROR: no esta instalada AWS CLI. En Mac con Homebrew: brew install awscli' >&2
  exit 2
fi
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
if [[ -z "$REGION" ]]; then
  REGION="$("${AWS[@]}" configure get region 2>/dev/null || true)"
fi
if [[ -z "$REGION" ]]; then
  echo "ERROR: establece AWS_REGION con la region indicada por el laboratorio; ejemplo: export AWS_REGION=us-east-1" >&2
  exit 2
fi
if [[ ! "$REGION" =~ ^[a-z]{2}-[a-z-]+-[0-9]+$ ]]; then
  echo 'ERROR: codigo de region invalido' >&2
  exit 2
fi
awsc() { "${AWS[@]}" --region "$REGION" "$@"; }

echo '==== CINEGRAPH | AWS ACADEMY - PRECHECK SIN COSTO ===='
echo "AWS CLI: $(aws --version 2>&1)"
echo "Credenciales: ${PROFILE:-sesion nativa de CloudShell (sin --profile)}"
echo "Region seleccionada: $REGION"
echo '[1/6] Validando sesion temporal del Learner Lab...'
if ! ACCOUNT="$(awsc sts get-caller-identity --query Account --output text 2>/dev/null)"; then
  echo 'ERROR: sesion de AWS sin credenciales validas. Verifica que CloudShell corresponda al Learner Lab activo.' >&2
  exit 3
fi
if [[ ! "$ACCOUNT" =~ ^[0-9]{12}$ ]]; then
  echo 'ERROR: la identidad devuelta por STS no es una cuenta AWS valida.' >&2
  exit 3
fi
echo "OK: credenciales temporales activas (cuenta final ${ACCOUNT: -4})."
echo '[2/6] Buscando VPC predeterminada...'
if ! VPC="$(awsc ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text 2>/dev/null)"; then
  echo 'AVISO: no pudimos consultar EC2/VPC; se requiere confirmar permisos y region.'
  VPC=''
fi
if [[ "$VPC" =~ ^vpc- ]]; then
  echo "VPC predeterminada: $VPC"
  echo '[3/6] Subredes y zonas de disponibilidad: '
  if ! awsc ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC" --query 'Subnets[].[SubnetId,AvailabilityZone,MapPublicIpOnLaunch]' --output table; then
    echo 'AVISO: no pudimos listar subredes; validar red manualmente.'
  fi
else
  echo 'AVISO: no aparece VPC predeterminada. No intentaremos crear una automaticamente.'
fi
echo '[4/6] Perfil de instancia que suelen incluir los Learner Labs...'
if role="$(awsc iam get-instance-profile --instance-profile-name LabInstanceProfile --query 'InstanceProfile.Roles[0].RoleName' --output text 2>/dev/null)"; then
  echo "OK: LabInstanceProfile disponible (rol: $role)."
else
  echo 'AVISO: LabInstanceProfile no se pudo consultar; podria existir, pero IAM:GetInstanceProfile puede estar restringido.'
fi
echo '[5/6] Acceso de consulta a RDS...'
if awsc rds describe-db-instances --max-records 20 --query 'length(DBInstances)' --output text >/dev/null 2>&1; then
  echo 'OK: RDS DescribeDBInstances autorizado (no garantiza permiso de creacion).'
else
  echo 'AVISO: RDS no permite consulta o el servicio no esta habilitado en esta region.'
fi
echo '[6/6] CloudFormation y validacion del YAML de infraestructura...'
TEMPLATE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/cloudformation/01-foundation.yaml"
if awsc cloudformation validate-template --template-body "file://$TEMPLATE" --query 'Description' --output text; then
  echo 'OK: CloudFormation reconoce la plantilla (no se ha creado ningun recurso).'
else
  echo 'AVISO: no se pudo validar la plantilla mediante CloudFormation (posibles restricciones del Learner Lab).'
fi
echo '==== FIN DEL DIAGNOSTICO: CERO RECURSOS CREADOS ===='
echo 'No compartas credenciales ni tokens; para continuar, comparte solamente esta salida del diagnostico.'