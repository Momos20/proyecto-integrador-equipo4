#!/usr/bin/env bash
# Valida viabilidad de compartir CineGraph por CloudFront HTTPS.
# Solo APIs de lectura, sin creacion de recursos ni credenciales.
set -euo pipefail
export AWS_PAGER="" AWS_CLI_AUTO_PROMPT=off AWS_MAX_ATTEMPTS=2 AWS_EC2_METADATA_DISABLED=true
AWS=(aws)
if [[ -n "${AWS_PROFILE:-}" ]]; then AWS+=(--profile "$AWS_PROFILE"); fi
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
AWS+=(--region "$REGION")
echo "==== CineGraph | prueba de acceso HTTPS para compañeros (solo lectura) ===="
echo "Region: $REGION"
echo "[1/3] Consultando distribuciones CloudFront (acceso de lectura)..."
if "${AWS[@]}" cloudfront list-distributions --max-items 1 --query 'DistributionList.Quantity' --output text; then
  echo "OK: CloudFront permite consulta; aun NO sabemos si permite crear distribuciones."
else
  echo "AVISO: CloudFront no permite consultar distribuciones. Se evaluara otra opcion HTTPS."
fi
echo "[2/3] Consultando lista de IPs de origen CloudFront para EC2..."
if "${AWS[@]}" ec2 describe-managed-prefix-lists \
  --filters "Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing" \
  --query 'PrefixLists[].[PrefixListId,PrefixListName,State]' --output table; then
  echo "OK: consulta del prefijo completada; verifica que haya un ID pl-... en la tabla."
else
  echo "AVISO: no se pudo consultar el prefijo; no abrir 8000 a toda Internet como alternativa."
fi
echo "[3/3] Validando plantilla sin crear recursos..."
TEMPLATE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/cloudformation/01-foundation.yaml"
if "${AWS[@]}" cloudformation validate-template --template-body "file://$TEMPLATE" \
  --query Description --output text; then
  echo "OK: YAML valido para CloudFormation."
else
  echo "AVISO: CloudFormation rechazo el YAML o la accion de lectura."
fi
echo "FIN: cero recursos creados. Comparte la salida sin credenciales."
