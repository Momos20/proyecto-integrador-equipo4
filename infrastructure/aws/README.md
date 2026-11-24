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
| 8 | Crear `cinegraph-e4-foundation` | **Completo**: `CREATE_COMPLETE` (S3 privado + SG app/RDS) |
| 9 | Desplegar red privada `cinegraph-e4-db-network` | **Completo**: `CREATE_COMPLETE`; dos subredes privadas y DB Subnet Group |

**No quedan recursos de la primera pila**, según el resultado de CloudShell que compartió el equipo. Los scripts temporales de limpieza ya no forman parte del repositorio.

## Paso 8 — Foundation definitiva (ejecutado y confirmado)

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

**Resultado real de CloudShell:** validación de plantilla aprobada, `aws cloudformation deploy` finalizó correctamente, `StackStatus=CREATE_COMPLETE`.

| Output | Identificador creado |
|---|---|
| BucketName | `cinegraph-e4-datalake-023914826547-us-east-1` |
| AppSecurityGroupId | `sg-0ac188ee36ce97e55` |
| DatabaseSecurityGroupId | `sg-0199de1701183b327` |
| VpcId | `vpc-083d9bebc31224f94` |

La plantilla establece S3 privado y cifrado con SSE-S3 y dos SG; el acceso web no tiene reglas inbound públicas. **No hay instancia EC2 ni RDS creada todavía.** Confirmar con `get-public-access-block` si se necesitan evidencias adicionales del control S3.

## Paso 9 — Red privada de PostgreSQL (creada y verificada)

`cloudformation/02-db-network.yaml` crea dos subredes privadas en distintas AZ, tabla de rutas solo local (sin Internet) y DB Subnet Group; **todavía no crea una instancia RDS**.

Según la red observada, se proponen `172.31.96.0/24` en `us-east-1a` y `172.31.97.0/24` en `us-east-1b`. El script verifica solapamiento y AZ disponibles.

**Evidencia real de CloudShell:** el plan comprobó que ambos CIDR están libres, pertenecen a AZ distintas y no existe solapamiento con las subredes actuales. No creó recursos. Se añadió `DBSubnetGroupName: cinegraph-e4-rds-subnets` para evitar un nombre autogenerado; es necesario repetir el plan tras `git pull` y luego ejecutar la creación.

```bash
bash infrastructure/aws/scripts/02-db-network.sh --plan
```

Después de actualizar el repositorio, repetir el plan para validar la nueva propiedad con nombre explícito.

Únicamente tras revisar el plan:

```bash
CONFIRM_LAB_DEPLOY=YES bash infrastructure/aws/scripts/02-db-network.sh --apply
```

Verificar que la pila llegó a `CREATE_COMPLETE`, que el grupo RDS se llama `cinegraph-e4-rds-subnets` y que las subredes no asignan IP pública:

```bash
aws cloudformation describe-stacks \\
  --stack-name cinegraph-e4-db-network \\
  --query 'Stacks[0].{Estado:StackStatus,Recursos:Outputs}' \\
  --output json

aws rds describe-db-subnet-groups \\
  --db-subnet-group-name cinegraph-e4-rds-subnets \\
  --query 'DBSubnetGroups[0].{Nombre:DBSubnetGroupName,Estado:SubnetGroupStatus,Subredes:Subnets[].SubnetIdentifier}' \\
  --output json
```

Si CloudFormation falla o revierte el despliegue, consultar `aws cloudformation describe-stack-events --stack-name cinegraph-e4-db-network --output table` antes de cambiar recursos. Aún no existe una instancia de base de datos.

**Ejecución real confirmada en CloudShell:** el plan volvió a comprobar CIDR y AZ, `CONFIRM_LAB_DEPLOY=YES bash infrastructure/aws/scripts/02-db-network.sh --apply` creó correctamente la pila `cinegraph-e4-db-network`, y `describe-stacks` mostró `CREATE_COMPLETE`.

| Output de CloudFormation | Valor confirmado |
|---|---|
| PrivateSubnetAId | `subnet-0793bb5ed242a6d56` |
| PrivateSubnetBId | `subnet-0b96249ebfcb8aa5b` |
| PrivateRouteTableId | `rtb-0b801c15c96837c89` |
| DBSubnetGroupName | `cinegraph-e4-rds-subnets` |
| VpcId | `vpc-083d9bebc31224f94` |

## Paso 10 — Verificar seguridad de red y opciones de RDS (solo lectura)

Antes de crear `cinegraph-e4-postgres` y empezar a consumir presupuesto de RDS, confirmar que la tabla de rutas de la base contiene solamente la ruta local, que las subredes no generan IPv4 pública, que RDS admite el grupo y que el puerto 5432 solo acepta desde el SG de aplicación.

```bash
cd ~/cinegraph-aws
git pull --ff-only origin main
unset AWS_PROFILE
export AWS_REGION=us-east-1

aws ec2 describe-subnets \
  --subnet-ids subnet-0793bb5ed242a6d56 subnet-0b96249ebfcb8aa5b \
  --query 'Subnets[].[SubnetId,AvailabilityZone,CidrBlock,MapPublicIpOnLaunch]' \
  --output table

aws ec2 describe-route-tables \
  --route-table-ids rtb-0b801c15c96837c89 \
  --query 'RouteTables[0].Routes[].[DestinationCidrBlock,GatewayId,State]' \
  --output table

aws ec2 describe-security-groups \
  --group-ids sg-0199de1701183b327 \
  --query 'SecurityGroups[0].IpPermissions' \
  --output json

aws rds describe-db-subnet-groups \
  --db-subnet-group-name cinegraph-e4-rds-subnets \
  --query 'DBSubnetGroups[0].{Name:DBSubnetGroupName,Status:SubnetGroupStatus,Subnets:Subnets[].[SubnetIdentifier,SubnetAvailabilityZone.Name,SubnetStatus]}' \
  --output json

aws rds describe-orderable-db-instance-options \
  --engine postgres \
  --db-instance-class db.t3.micro \
  --max-items 10 \
  --query 'OrderableDBInstanceOptions[].[EngineVersion,DBInstanceClass,StorageType,SupportsStorageEncryption]' \
  --output table
```

**No ejecutar `rds create-db-instance` aún**. Revisar esta salida y escoger una versión de PostgreSQL realmente ofertada para `db.t3.micro`, almacenamiento y mecanismo de credenciales permitido por el Learner Lab. Plan previsto: RDS privado y Single-AZ, datos cifrados, mínimo privilegio y sin contraseñas en Git ni historial de shell. `--manage-master-user-password` utiliza AWS Secrets Manager y requiere permisos adicionales: comprobarlos antes de elegirlo.



## Próximas fases

RDS PostgreSQL privado; EC2 con Docker Compose **separado de Floci**, frontend/backend y catálogo; acceso público **HTTPS válido** para que el equipo pueda compartir el enlace e iniciar sesión con usuarios ficticios; Kinesis → Firehose → S3 Raw → Curated/Features, con orquestación según permisos de AWS Academy. Las guías SI7002 N0–N2 son referencias, no pasos de consola.

**Seguridad:** no abrir RDS a Internet, no exponer el login por HTTP, no guardar secretos en Git, no ejecutar `docker compose down -v` sobre el entorno local.
