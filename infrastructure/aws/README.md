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
| 10 | Verificar subredes, rutas, SG y oferta RDS | **Completo**: red privada validada; salida de oferta paginada | 
| 11 | Consultar ofertas PostgreSQL 16/gp3 | **Completo**: 16.9–16.15, `db.t3.micro`, gp3, cifrado |
| 12 | Crear PostgreSQL 16.15 privado | **Completo**: CloudFormation `CREATE_COMPLETE`, instancia `available` |
| 13 | Verificar preparación EC2 | **Completo**: subred pública, rutas IGW, AMI AL2023, LabInstanceProfile y SG sin ingreso; secreto RDS activo |
| 14 | Verificar AMI, IAM/SSM y plantilla de EC2 | **Completo**: AL2023 disponible, rol con AmazonSSMManagedInstanceCore, YAML válido |
| 15 | Crear EC2 `cinegraph-e4-web` | **Completo**: `CREATE_COMPLETE`; EC2 `running` y SSM `Online` |
| 16 | Verificar Docker y bootstrap en EC2 | **Siguiente**: comando remoto por SSM, sin abrir SSH |


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

## Paso 10 — Seguridad de red y opciones de RDS (validado)

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

**Resultados reales comprobados en CloudShell:**

| Control | Evidencia |
|---|---|
| Subred `subnet-0793bb5ed242a6d56` | `us-east-1a`, `172.31.96.0/24`, `MapPublicIpOnLaunch=False` |
| Subred `subnet-0b96249ebfcb8aa5b` | `us-east-1b`, `172.31.97.0/24`, `MapPublicIpOnLaunch=False` |
| Tabla `rtb-0b801c15c96837c89` | Ruta única `172.31.0.0/16 → local` |
| SG RDS `sg-0199de1701183b327` | Entrada TCP 5432 exclusivamente desde SG de aplicación `sg-0ac188ee36ce97e55`; no tiene CIDR de Internet |
| DB subnet group | `cinegraph-e4-rds-subnets`, `Complete`, ambas subredes `Active` |
| Oferta RDS `db.t3.micro` | Consulta devolvió PostgreSQL 11 con `gp2`, `gp3`, `io1`, `io2` y cifrado disponible en sus **primeras diez filas** |

`--max-items 10` truncó la oferta a los primeros diez resultados. **No deducir que solo PostgreSQL 11 está disponible.** El contenedor PostgreSQL local es versión 16, por lo cual se prefiere PostgreSQL 16 para RDS si la cuenta lo oferta.

## Paso 11 — Confirmar PostgreSQL 16 antes de crear RDS (siguiente paso)

Solo consulta AWS RDS; **no crea ninguna instancia ni genera costo de cómputo**:

```bash
cd ~/cinegraph-aws
git pull --ff-only origin main
unset AWS_PROFILE
export AWS_REGION=us-east-1

aws rds describe-orderable-db-instance-options \
  --engine postgres \
  --db-instance-class db.t3.micro \
  --query "OrderableDBInstanceOptions[?starts_with(EngineVersion, '16.') && StorageType == 'gp3'].[EngineVersion,DBInstanceClass,StorageType,SupportsStorageEncryption]" \
  --output table
```

Se omite `--max-items` para consultar toda la lista paginada. Si no devuelve versiones `16.x`, comprobar `17.x` en vez de seleccionar automáticamente PostgreSQL 11.

Solo tras verificar la versión y presupuesto se preparará la creación con nombre `cinegraph-e4-postgres`, `PubliclyAccessible=false`, Single-AZ, SG RDS restringido, almacenamiento cifrado y credenciales **fuera de Git y del historial de Shell**. AWS Academy puede no autorizar todas las opciones: cualquier error de creación debe revisarse antes de reintentar.




## Paso 11 — PostgreSQL 16 confirmado (completo)

Salida real de AWS Academy: versiones `16.9`, `16.10`, `16.11`, `16.12`, `16.13`, `16.14` y `16.15` con `db.t3.micro`, `gp3` y `SupportsStorageEncryption=True`. Se selecciona `16.15` por compatibilidad con PostgreSQL 16 del entorno local.

## Paso 12 — Instancia PostgreSQL RDS (creada y verificada)

Plantilla `cloudformation/03-rds-postgres.yaml`: una instancia `cinegraph-e4-postgres`, PostgreSQL 16.15, `db.t3.micro`, 20 GiB gp3 cifrados, Single-AZ, `PubliclyAccessible=false`, `cinegraph-e4-rds-subnets` y Security Group de RDS. La base inicial es `cinegraph`. El usuario maestro es `cinegraphadmin`, **no es usuario de aplicación**.

Se usa `ManageMasterUserPassword: true`: RDS crea y administra la contraseña maestra con AWS Secrets Manager. **Nunca introducir una contraseña en la línea de comandos ni compartir secretos.** Secrets Manager tiene costo adicional y puede estar restringido por permisos de AWS Academy; CloudFormation `validate-template` no garantiza permisos para crear recursos. Si aparece `AccessDenied`, consultar eventos y detenerse sin sustituir el secreto por una contraseña fija.

`BackupRetentionPeriod: 0` deshabilita backups automáticos solo para esta demostración, no para producción. `DeletionPolicy: Snapshot` protege los datos al retirar la pila, pero las instantáneas retenidas pueden generar cargos. RDS y Secrets Manager empiezan a consumir presupuesto cuando se crean. Se deshabilita la inscripción automática en RDS Extended Support para evitar cargos adicionales al finalizar el soporte estándar de PostgreSQL 16.

**Comandos en CloudShell.** Solo se reemplazan región y cuenta al replicar el laboratorio. El SG se recupera de la pila, sin copiar IDs entre cuentas.

1. Actualizar y obtener SG de RDS:

```bash
cd ~/cinegraph-aws
git pull --ff-only origin main
unset AWS_PROFILE
export AWS_REGION=us-east-1
DB_SG="$(aws cloudformation describe-stacks \
  --stack-name cinegraph-e4-foundation \
  --query "Stacks[0].Outputs[?OutputKey=='DatabaseSecurityGroupId'].OutputValue | [0]" \
  --output text)"
echo "SG de RDS: $DB_SG"
```

2. Validación de YAML **sin crear recursos**:

```bash
aws cloudformation validate-template \
  --template-body file://infrastructure/aws/cloudformation/03-rds-postgres.yaml
```

3. Creación **real y cobrable** (solo después de validar el YAML y comprobar el presupuesto del Learner Lab):

```bash
aws cloudformation deploy \
  --region "$AWS_REGION" \
  --stack-name cinegraph-e4-postgres \
  --template-file infrastructure/aws/cloudformation/03-rds-postgres.yaml \
  --parameter-overrides "DatabaseSecurityGroupId=$DB_SG" \
  --tags Project=CineGraph Team=E4 Environment=lab \
  --no-fail-on-empty-changeset
```

4. Confirmar `CREATE_COMPLETE`, endpoint y ausencia de acceso público:

```bash
aws cloudformation describe-stacks \
  --stack-name cinegraph-e4-postgres \
  --query 'Stacks[0].{Estado:StackStatus,Recursos:Outputs}' \
  --output json

aws rds describe-db-instances \
  --db-instance-identifier cinegraph-e4-postgres \
  --query 'DBInstances[0].{Estado:DBInstanceStatus,Motor:Engine,Version:EngineVersion,Clase:DBInstanceClass,Publica:PubliclyAccessible,Cifrada:StorageEncrypted,Red:DBSubnetGroup.DBSubnetGroupName,Endpoint:Endpoint.Address,Secreto:MasterUserSecret.SecretStatus}' \
  --output json
```

Si falla, **no reintentar ni eliminar automáticamente**. Inspeccionar eventos:

```bash
aws cloudformation describe-stack-events \
  --stack-name cinegraph-e4-postgres \
  --query 'StackEvents[].[Timestamp,LogicalResourceId,ResourceStatus,ResourceStatusReason]' \
  --output table
```

### Resultado real de la creación RDS

La cuenta AWS Academy confirmó lo siguiente:

| Verificación | Valor |
|---|---|
| Stack | `cinegraph-e4-postgres` |
| Estado de CloudFormation | `CREATE_COMPLETE` |
| Estado RDS | `available` |
| Motor | PostgreSQL `16.15` |
| Base de datos | `cinegraph` |
| Endpoint privado | `cinegraph-e4-postgres.c3ycssa0e3xz.us-east-1.rds.amazonaws.com` |
| Puerto | `5432` |
| `PubliclyAccessible` | `false` |
| `StorageEncrypted` | `true` |

**Esto valida la instancia, no el esquema de aplicación:** aún no se han aplicado migraciones, importado el catálogo MovieLens ni publicado recomendaciones A9 en AWS. No se debe utilizar `scripts/local_setup/bootstrap.py` apuntando a RDS: está limitado deliberadamente a PostgreSQL local.

## Paso 13 — Preparación de EC2 (solo lectura; siguiente paso)

Meta: EC2 en **subred pública existente**, con `LabInstanceProfile`, acceso administrativo mediante AWS Systems Manager si los permisos permiten conectarlo, frontend/backend Flask en contenedor **separado** de la base RDS. La base queda en subred privada. Antes de crear EC2, verificar la subred, ruta al IGW, AMI disponible, rol y secreto administrado. **Todavía no publicar formularios de inicio de sesión hasta implementar HTTPS válido.**

```bash
cd ~/cinegraph-aws
git pull --ff-only origin main
unset AWS_PROFILE
export AWS_REGION=us-east-1
export VPC_ID=vpc-083d9bebc31224f94

# Subred PUBLICA existente en us-east-1a (no la subred nueva de RDS).
export WEB_SUBNET_ID=subnet-07413c35ec3498c14
aws ec2 describe-subnets \
  --subnet-ids "$WEB_SUBNET_ID" \
  --query 'Subnets[0].{Id:SubnetId,AZ:AvailabilityZone,CIDR:CidrBlock,PublicIpOnLaunch:MapPublicIpOnLaunch,VPC:VpcId}' \
  --output json

# Comprueba rutas/IGW. Si la subred hereda la tabla principal, puede no
# aparecer como asociacion de subred explicita; inspeccionar tabla Main.
aws ec2 describe-route-tables \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'RouteTables[].{Id:RouteTableId,Associations:Associations[].[Main,SubnetId],Routes:Routes[].[DestinationCidrBlock,GatewayId,State]}' \
  --output json

# Verificar el perfil de instancia para acceso AWS sin claves fijas.
aws iam get-instance-profile \
  --instance-profile-name LabInstanceProfile \
  --query 'InstanceProfile.{Name:InstanceProfileName,Roles:Roles[].RoleName}' \
  --output json

# AMI Amazon Linux 2023 x86_64, administrada por AWS.
aws ssm get-parameter \
  --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
  --query 'Parameter.Value' \
  --output text

# SG aplicación: sin acceso público por ahora.
aws ec2 describe-security-groups \
  --group-ids sg-0ac188ee36ce97e55 \
  --query 'SecurityGroups[0].{Id:GroupId,Ingress:IpPermissions,Egress:IpPermissionsEgress}' \
  --output json

# Estado del secreto, SIN leer ni imprimir la contraseña.
aws rds describe-db-instances \
  --db-instance-identifier cinegraph-e4-postgres \
  --query 'DBInstances[0].{MasterUser:MasterUsername,SecretStatus:MasterUserSecret.SecretStatus,Public:PubliclyAccessible,Endpoint:Endpoint.Address}' \
  --output json
```

Si `ssm get-parameter` muestra `AccessDenied`, puede consultarse la AMI mediante `ec2 describe-images` (solo lectura) antes de desplegar. El siguiente paso después de validar será diseñar/crear `cinegraph-e4-web` con EC2 y acceso seguro a RDS, y preparar un Compose **AWS** sin contenedor `db` ni Floci.

**Costos:** `cinegraph-e4-postgres` está activo y consume presupuesto de AWS Academy incluso sin tráfico. EC2 agregará costos de instancia/IPv4 pública; consultar el presupuesto disponible del Learner Lab antes del despliegue. No exponer 5432 al exterior ni registrar valores de Secrets Manager en CloudShell o Git.


## Resultado real — paso 13 (EC2 preflight completado)

La cuenta AWS Academy confirmó la subred pública `subnet-07413c35ec3498c14`, `us-east-1a`, `172.31.32.0/20`, `MapPublicIpOnLaunch=true`. La subred usa la tabla principal de la VPC, `rtb-029f59127c097ea81`, cuya ruta `0.0.0.0/0` apunta al IGW `igw-0328b4a604d6cd226`. La tabla RDS `rtb-0b801c15c96837c89` **solo** tiene `172.31.0.0/16 -> local`.

Se verificaron `LabInstanceProfile` con rol `LabRole`, AL2023 x86_64 `ami-0aacbf72109c53c0c`, SG de app `sg-0ac188ee36ce97e55` **sin reglas entrantes**, y RDS `cinegraph-e4-postgres` con `MasterUser=cinegraphadmin`, estado de secreto `active` y `PubliclyAccessible=false`.

Este preflight **no confirma** permisos de `ssm:StartSession` para el usuario de CloudShell ni los permisos de `AmazonSSMManagedInstanceCore` para el rol EC2; es imprescindible comprobarlo antes de depender de Session Manager.

## Paso 14 — Preparar EC2 CineGraph sin abrir el sitio

Plantilla nueva: `cloudformation/04-web-ec2.yaml`. Crea solo `cinegraph-e4-web` con AMI Amazon Linux 2023, `t3.small` (2 GiB), 24 GiB gp3 cifrado, `LabInstanceProfile`, IP pública para el tráfico saliente y **SG de app sin ninguna entrada pública**. El `UserData` instala Docker; no contiene contraseñas, no descarga el código ni inicia el frontend.

Una IP pública no equivale a un sitio compartible: antes de publicar el login necesitamos un proxy HTTPS válido. Como no hay SSH abierto ni par de claves SSH, la administración prevista es AWS Systems Manager Session Manager; **se debe comprobar primero que esté disponible y tenga permisos**. SSM necesita permiso en la instancia para conectarse a servicios SSM por HTTPS y permisos del operador para iniciar la sesión.

**1. Consultas antes del despliegue (solo lectura):**

```bash
cd ~/cinegraph-aws
git pull --ff-only origin main
unset AWS_PROFILE
export AWS_REGION=us-east-1

# Confirmar AMI de AL2023 y nombre del dispositivo EBS raiz.
aws ec2 describe-images \
  --image-ids ami-0aacbf72109c53c0c \
  --query 'Images[0].{Id:ImageId,State:State,Architecture:Architecture,RootDeviceName:RootDeviceName,VirtualizationType:VirtualizationType}' \
  --output json

# Comprobar politicas administradas del rol LabRole.
aws iam list-attached-role-policies \
  --role-name LabRole \
  --query 'AttachedPolicies[].[PolicyName,PolicyArn]' \
  --output table

# Verificar si CloudShell puede consultar la flota de Systems Manager.
aws ssm describe-instance-information \
  --max-results 5 \
  --query 'InstanceInformationList[].[InstanceId,PingStatus,PlatformName]' \
  --output table

# Comprobar que aun no existe ninguna EC2 de CineGraph.
aws ec2 describe-instances \
  --filters 'Name=tag:Name,Values=cinegraph-e4-web' \
  --query 'Reservations[].Instances[].[InstanceId,State.Name,InstanceType]' \
  --output table

# Validar plantilla sin crear recursos.
aws cloudformation validate-template \
  --template-body file://infrastructure/aws/cloudformation/04-web-ec2.yaml
```

Si `list-attached-role-policies` no muestra `AmazonSSMManagedInstanceCore`, también puede haber políticas inline que otorguen permisos equivalentes. Se inspeccionarán antes de lanzar EC2. Un permiso de lectura de flota no prueba que el operador pueda iniciar sesiones; esto se valida posteriormente con la instancia, sin abrir SSH.

**2. Despliegue (AÚN NO EJECUTADO, incurre costos EC2/EBS/IPv4):**

```bash
export WEB_SUBNET_ID=subnet-07413c35ec3498c14
APP_SG="$(aws cloudformation describe-stacks \
  --stack-name cinegraph-e4-foundation \
  --query "Stacks[0].Outputs[?OutputKey=='AppSecurityGroupId'].OutputValue | [0]" \
  --output text)"

aws cloudformation deploy \
  --region "$AWS_REGION" \
  --stack-name cinegraph-e4-web \
  --template-file infrastructure/aws/cloudformation/04-web-ec2.yaml \
  --parameter-overrides "WebSubnetId=$WEB_SUBNET_ID" "AppSecurityGroupId=$APP_SG" \
  --tags Project=CineGraph Team=E4 Environment=lab
```

**3. Verificación tras crearla (AÚN NO EJECUTADA):**

```bash
aws cloudformation describe-stacks \
  --stack-name cinegraph-e4-web \
  --query 'Stacks[0].{Estado:StackStatus,Recursos:Outputs}' \
  --output json
```

```bash
aws ec2 describe-instances \
  --filters 'Name=tag:Name,Values=cinegraph-e4-web' \
  --query 'Reservations[].Instances[].[InstanceId,State.Name,PrivateIpAddress,PublicIpAddress,IamInstanceProfile.Arn]' \
  --output table
```

No confundir `CREATE_COMPLETE` con Docker configurado: el `UserData` se ejecuta durante el arranque; se verificará con SSM o consola de EC2 según permisos. El archivo `docker-compose.yml` local contiene PostgreSQL dentro de Docker y contraseñas de ejemplo: **no se ejecutará en AWS**. Crearemos un Compose AWS exclusivo para Flask con RDS y credenciales obtenidas de forma segura, sin modificar Docker + Floci local.

**Costos:** EC2 `t3.small`, EBS gp3 e IPv4 pública son cobrables. RDS está `available` y ya consume presupuesto. Detener recursos cuando no se utilicen y cerrar el laboratorio cuando termine la demostración.


## Paso 14 — Validaciones EC2 completadas (resultado real)

El laboratorio devolvió la AMI `ami-0aacbf72109c53c0c` en estado `available`, arquitectura `x86_64`, dispositivo raíz `/dev/xvda`. El rol `LabRole`, asociado a `LabInstanceProfile`, tiene adjunta la política administrada `AmazonSSMManagedInstanceCore` junto con otras políticas del laboratorio. `aws ssm describe-instance-information` funcionó, pero devolvió una lista vacía porque aún no había instancias gestionadas. `cloudformation validate-template` aprobó `04-web-ec2.yaml`. Estas comprobaciones **no demuestran todavía que el operador tenga `ssm:StartSession`**.

## Paso 15 — Creación de EC2 con Docker (siguiente)

Esta fase **sí genera costos de EC2, EBS e IPv4 pública**. Usa la subred web **pública** confirmada anteriormente; la tabla de rutas DB continúa siendo privada. No se abre ni SSH ni el puerto de Flask. El despliegue instalará Docker mediante UserData, pero **no instalará aún CineGraph ni conectará RDS**.

```bash
cd ~/cinegraph-aws
git pull --ff-only origin main
unset AWS_PROFILE
export AWS_REGION=us-east-1
export WEB_SUBNET_ID=subnet-07413c35ec3498c14

APP_SG="$(aws cloudformation describe-stacks \
  --stack-name cinegraph-e4-foundation \
  --query "Stacks[0].Outputs[?OutputKey=='AppSecurityGroupId'].OutputValue | [0]" \
  --output text)"

echo "Subnet: $WEB_SUBNET_ID | SG: $APP_SG"
aws cloudformation validate-template \
  --template-body file://infrastructure/aws/cloudformation/04-web-ec2.yaml

# Crea recursos reales: no ejecutar sin presupuesto disponible.
aws cloudformation deploy \
  --region "$AWS_REGION" \
  --stack-name cinegraph-e4-web \
  --template-file infrastructure/aws/cloudformation/04-web-ec2.yaml \
  --parameter-overrides "WebSubnetId=$WEB_SUBNET_ID" "AppSecurityGroupId=$APP_SG" \
  --tags Project=CineGraph Team=E4 Environment=lab \
  --no-fail-on-empty-changeset
```

**Confirmar Outputs y estado real, sin imprimir secretos:**

```bash
aws cloudformation describe-stacks \
  --stack-name cinegraph-e4-web \
  --query 'Stacks[0].{Estado:StackStatus,Recursos:Outputs}' \
  --output json

WEB_INSTANCE_ID="$(aws cloudformation describe-stacks \
  --stack-name cinegraph-e4-web \
  --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue | [0]" \
  --output text)"

aws ec2 describe-instances \
  --instance-ids "$WEB_INSTANCE_ID" \
  --query 'Reservations[].Instances[].[InstanceId,State.Name,PrivateIpAddress,PublicIpAddress]' \
  --output table

aws ssm describe-instance-information \
  --filters "Key=InstanceIds,Values=$WEB_INSTANCE_ID" \
  --query 'InstanceInformationList[].[InstanceId,PingStatus,PlatformName]' \
  --output table
```

`CREATE_COMPLETE` no garantiza que UserData haya terminado ni que SSM esté en línea. El estado deseado es `running` en EC2, después `Online` en SSM. Si no aparece en SSM, comprobar registro del agente, rutas salientes, permisos de sesión y estado del arranque antes de modificar SG o abrir SSH.

**No usar el Compose local:** contiene PostgreSQL dentro de Docker y contraseñas ficticias. El siguiente paso será implantar la aplicación con un Compose exclusivo para AWS y autenticación segura hacia RDS. La URL pública no tendrá login hasta contar con un certificado HTTPS válido.

## Paso 15 — EC2 creada y registrada en Systems Manager (confirmado)

El despliegue `aws cloudformation deploy --stack-name cinegraph-e4-web` finalizó correctamente, y se verificó la instancia en ejecución. Evidencias reales de CloudShell:

| Componente | Valor |
|---|---|
| Estado CloudFormation | `CREATE_COMPLETE` |
| Stack | `cinegraph-e4-web` |
| InstanceId | `i-0e3288445cb0df13d` |
| Estado EC2 | `running` |
| PrivateIp | `172.31.44.20` |
| PublicIp | `3.84.177.220` (efímera; puede cambiar al detener/iniciar) |
| PublicDnsName | `ec2-3-84-177-220.compute-1.amazonaws.com` |
| AppSecurityGroupId | `sg-0ac188ee36ce97e55` |
| Systems Manager PingStatus | `Online` |
| Plataforma SSM | `Amazon Linux` |

**Alcance:** se confirmó la ejecución de la instancia y la conectividad con el agente SSM. Aún no se verificó que el `UserData` haya instalado Docker. Aunque la instancia tiene IP pública, **el SG no permite ningún ingreso HTTP/HTTPS/SSH**. RDS sigue sin acceso público.

## Paso 16 — Verificar Docker de forma remota por Systems Manager

Todos los comandos se envían desde AWS CloudShell a EC2; no necesitan una dirección SSH, clave privada ni acceso público a puertos de administración. Este paso **no modifica el software ni crea nuevos servicios**, solo consulta el resultado del bootstrap remoto. El usuario de CloudShell debe tener `ssm:SendCommand` y `ssm:GetCommandInvocation`; que el agente muestre `Online` no demuestra esos permisos.

```bash
cd ~/cinegraph-aws
git pull --ff-only origin main
unset AWS_PROFILE
export AWS_REGION=us-east-1

WEB_INSTANCE_ID="$(aws cloudformation describe-stacks \
  --stack-name cinegraph-e4-web \
  --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue | [0]" \
  --output text)"
echo "Instancia CineGraph: $WEB_INSTANCE_ID"

COMMAND_ID="$(aws ssm send-command \
  --instance-ids "$WEB_INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --comment "CineGraph: verificar Docker y estado cloud-init" \
  --parameters '{"commands":["systemctl is-active docker","docker --version","cloud-init status","test -d /opt/cinegraph && echo cinegraph_directory_ok"]}' \
  --query 'Command.CommandId' \
  --output text)"

echo "SSM CommandId: $COMMAND_ID"
aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$WEB_INSTANCE_ID" \
  --query '{Estado:Status,Detalle:StatusDetails,Codigo:ResponseCode,Salida:StandardOutputContent,Error:StandardErrorContent}' \
  --output json
```

Si el comando todavía muestra `Pending` o `InProgress`, volver a ejecutar **solo** `get-command-invocation` usando el mismo `COMMAND_ID`. No reenviar comandos en un bucle. Resultado satisfactorio: `Status=Success`, `ResponseCode=0`, Docker activo, versión Docker visible, directorio `/opt/cinegraph` creado y `cloud-init` terminado.

Si aparece `AccessDeniedException` en `ssm send-command`, no abrir SSH como alternativa inmediata: primero revisar los permisos del rol CloudShell/Learner Lab. Si Docker no está activo, inspeccionar `/var/log/cinegraph-bootstrap.log` por SSM y corregir solo después de localizar el error.

**Próxima fase:** aplicación Flask y esquemas de MovieLens en RDS; usar un Compose exclusivo para AWS **sin PostgreSQL local ni Floci**. Ninguna contraseña puede incorporarse al YAML/Compose ni registrarse en Github. Antes de habilitar el inicio de sesión del equipo por Internet, disponer de una URL HTTPS válida.

## Próximas fases

RDS PostgreSQL privado; EC2 con Docker Compose **separado de Floci**, frontend/backend y catálogo; acceso público **HTTPS válido** para que el equipo pueda compartir el enlace e iniciar sesión con usuarios ficticios; Kinesis → Firehose → S3 Raw → Curated/Features, con orquestación según permisos de AWS Academy. Las guías SI7002 N0–N2 son referencias, no pasos de consola.

**Seguridad:** no abrir RDS a Internet, no exponer el login por HTTP, no guardar secretos en Git, no ejecutar `docker compose down -v` sobre el entorno local.
