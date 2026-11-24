# CineGraph — AWS Academy | Equipo 4

Despliegue **100 % por comandos AWS CLI/CloudFormation en CloudShell**. Esta carpeta conserva solo plantillas operativas y el registro de pasos. La infraestructura AWS permanece **separada de Docker + Floci local**.

## Convención de recursos y valores a reemplazar

Se utilizan nombres `cinegraph-e4-<componente>`, sin `dev` ni sufijos aleatorios elegidos por CloudFormation.

| Variable | Valor confirmado en la cuenta del equipo | Para otra cuenta, reemplazar por |
|---|---|---|
| `AWS_REGION` | `us-east-1` | Región autorizada de Learner Lab |
| `ACCOUNT_ID` | `023914826547` | `aws sts get-caller-identity --query Account --output text` |
| `VPC_ID` | `vpc-083d9bebc31224f94` | VPC existente en esa cuenta |
| Stack base | `cinegraph-e4-foundation` | Mantener convención salvo necesidad específica |
| Bucket | `cinegraph-e4-datalake-023914826547-us-east-1` | Generado en el YAML con cuenta y región |
| SG app y DB | `cinegraph-e4-app-sg` / `cinegraph-e4-rds-sg` | Se generan dentro de la VPC |
| Stack red RDS | `cinegraph-e4-db-network` | Mantener convención |

Los nombres S3 deben ser globalmente únicos. Si hay colisión, el despliegue fallará sin intentar borrar datos ajenos.

## Bitácora de pasos completados

| Paso | Acción y comandos | Resultado |
|---|---|---|
| 1 | `aws sts get-caller-identity` | CloudShell autenticado mediante rol `voclabs` en la cuenta indicada |
| 2 | `aws ec2 describe-vpcs`, `describe-subnets`, `describe-route-tables`, `describe-internet-gateways` | VPC predeterminada, 6 subredes y salida a Internet confirmadas |
| 3 | `aws iam get-instance-profile --instance-profile-name LabInstanceProfile` | `LabRole` disponible |
| 4 | `aws ec2 describe-instance-type-offerings` y `aws rds describe-orderable-db-instance-options` | Oferta regional t3.micro/t3.small y db.t3.micro; aún no se crearon |
| 5 | `aws cloudfront list-distributions` | `AccessDenied`. No depender de CloudFront |
| 6 | Primera pila `cinegraph-lab-foundation` | Creada, verificada, luego eliminada por cambio de nombres |
| 7 | Inspección de S3 vacío y SG libres; script temporal de eliminación | **Completado**: pila antigua y bucket vacío eliminados; consulta de stacks activos sin CineGraph |
| 8 | Crear `cinegraph-e4-foundation` | **SIGUIENTE PASO** |
| 9 | Crear red privada `cinegraph-e4-db-network` | Pendiente, ya existe plantilla y script |

**No quedan recursos de la primera pila**, según el resultado de CloudShell que compartió el equipo. Los scripts temporales de limpieza ya no forman parte del repositorio.

## Paso 8 — Foundation definitiva (comandos listos)

**1. Actualizar y comprobar identidad.** Cambiar `AWS_REGION` y `VPC_ID` solo si se replica en otra cuenta.

```bash
cd ~/cinegraph-aws
git pull --ff-only origin main
unset AWS_PROFILE
export AWS_REGION=us-east-1
export VPC_ID=vpc-083d9bebc31224f94
aws sts get-caller-identity --query '[Account,Arn]' --output table
```

**2. Validar el YAML (no crea recursos):**

```bash
aws cloudformation validate-template \
  --template-body file://infrastructure/aws/cloudformation/01-foundation.yaml
```

**3. Crear recursos AWS reales (S3 privado y 2 Security Groups sin web público):**

```bash
aws cloudformation deploy \
  --region "$AWS_REGION" \
  --stack-name cinegraph-e4-foundation \
  --template-file infrastructure/aws/cloudformation/01-foundation.yaml \
  --parameter-overrides "VpcId=$VPC_ID" \
  --tags Project=CineGraph Team=E4 Environment=lab \
  --no-fail-on-empty-changeset
```

**4. Confirmar `CREATE_COMPLETE` y salidas del stack:**

```bash
aws cloudformation describe-stacks \
  --stack-name cinegraph-e4-foundation \
  --query 'Stacks[0].{Estado:StackStatus,Recursos:Outputs}' \
  --output json
```

**5. Confirmar bloqueo de acceso público S3:**

```bash
aws s3api get-public-access-block \
  --bucket cinegraph-e4-datalake-023914826547-us-east-1
```

Si falla el despliegue, consultar eventos en lugar de borrar por fuerza:

```bash
aws cloudformation describe-stack-events \
  --stack-name cinegraph-e4-foundation \
  --query 'StackEvents[].[Timestamp,LogicalResourceId,ResourceStatus,ResourceStatusReason]' \
  --output table
```

Tras verificar en CloudShell, actualizar esta bitácora con el estado real y los IDs que devuelva CloudFormation.

## Paso 9 — Red privada de PostgreSQL (solo después del Paso 8)

`cloudformation/02-db-network.yaml` crea dos subredes privadas en distintas AZ, tabla de rutas solo local (sin Internet) y DB Subnet Group; **todavía no crea una instancia RDS**.

Según la red observada, se proponen `172.31.96.0/24` en `us-east-1a` y `172.31.97.0/24` en `us-east-1b`. El script verifica solapamiento y AZ disponibles.

```bash
bash infrastructure/aws/scripts/02-db-network.sh --plan
```

Únicamente tras revisar el plan:

```bash
CONFIRM_LAB_DEPLOY=YES bash infrastructure/aws/scripts/02-db-network.sh --apply
```

## Próximas fases

RDS PostgreSQL privado; EC2 con Docker Compose **separado de Floci**, frontend/backend y catálogo; acceso público **HTTPS válido** para que el equipo pueda compartir el enlace e iniciar sesión con usuarios ficticios; Kinesis → Firehose → S3 Raw → Curated/Features, con orquestación según permisos de AWS Academy. Las guías SI7002 N0–N2 son referencias, no pasos de consola.

**Seguridad:** no abrir RDS a Internet, no exponer el login por HTTP, no guardar secretos en Git, no ejecutar `docker compose down -v` sobre el entorno local.
