# CineGraph — infraestructura AWS Academy (separada del entorno local)

**Estado real:** la pila `cinegraph-lab-foundation` ya se creó correctamente en AWS Academy: bucket S3 privado y Security Groups para EC2 y RDS, con `WebIngressMode=None`. Todavía no se han desplegado EC2, RDS ni el frontend. El entorno local con Docker + Floci se conserva sin cambios. La ruta AWS usa CloudShell, CloudFormation y recursos separados bajo `infrastructure/aws/`.

## Fase 2: red privada de PostgreSQL — plantilla preparada, sin ejecutar

La pila independiente `cloudformation/02-db-network.yaml` reutiliza la VPC de `cinegraph-e4-dev-foundation` (después del cambio de nombres) y crea **dos subredes privadas en dos AZ**, una tabla de rutas que solo contiene la ruta implícita local de la VPC y un `AWS::RDS::DBSubnetGroup`. No crea una instancia de base de datos ni EC2 y no crea NAT Gateway. El Security Group privado de RDS ya existe en la pila foundation; se reutilizará cuando despleguemos PostgreSQL.

De acuerdo con el diagnóstico real de la VPC, las seis subredes actuales ocupan `172.31.0.0/20` hasta `172.31.80.0/20`. Los candidatos `172.31.96.0/24` (us-east-1a) y `172.31.97.0/24` (us-east-1b) están libres **según esa consulta**. El script comprueba nuevamente la VPC, las zonas disponibles y los solapamientos antes de permitir crear nada.

Solo validar el plan desde CloudShell:

```bash
cd ~/cinegraph-aws
git pull --ff-only origin main
unset AWS_PROFILE
export AWS_REGION=us-east-1
bash infrastructure/aws/scripts/02-db-network.sh --plan
```

El resultado esperado es `PLAN OK: 2 subredes privadas + tabla de rutas + DB Subnet Group.` **No ejecutar todavía `--apply` sin revisar la salida y aprobarla.** Si el laboratorio rechaza crear `AWS::RDS::DBSubnetGroup` por IAM, la pila puede quedar en `ROLLBACK_COMPLETE`; revisar eventos antes de reintentar.

Tras aprobar y crear la pila, antes de lanzar RDS se comprobarán sus Output IDs, que las dos subredes estén en AZ distintas, `MapPublicIpOnLaunch=false`, ausencia de rutas externas y el grupo de seguridad de RDS restringido a la aplicación.

## Nombres estandarizados y limpieza de la pila antigua

Se utiliza el prefijo `cinegraph-e4-dev` en todos los recursos nuevos. El nombre del bucket S3 es explícito y determinista: `cinegraph-e4-dev-datalake-<ACCOUNT_ID>-<REGION>`, usando los pseudoparámetros `AWS::AccountId` y `AWS::Region` de CloudFormation. Aunque es muy improbable una colisión, el nombre debe estar disponible en el namespace global de S3.

| Componente | Nuevo nombre |
|---|---|
| Foundation stack | `cinegraph-e4-dev-foundation` |
| Bucket S3 | `cinegraph-e4-dev-datalake-023914826547-us-east-1` |
| SG app | `cinegraph-e4-dev-app-sg` |
| SG RDS | `cinegraph-e4-dev-rds-sg` |
| DB network stack | `cinegraph-e4-dev-db-network` |
| Subnets RDS | `cinegraph-e4-dev-rds-private-a` y `cinegraph-e4-dev-rds-private-b` |

La **pila antigua**, `cinegraph-lab-foundation`, fue creada con un bucket autogenerado `cinegraph-lab-foundation-datalakebucket-lrnkpdjo5xiv`, SG web `sg-00d7ff2cb71f16854` y SG RDS `sg-004792f0dba4268be`. **No hemos borrado ningún recurso AWS**; su borrado debe hacerse por CloudShell después de verificar que no tiene información.

**Paso 1, inspección sin borrar:**

```bash
cd ~/cinegraph-aws
git pull --ff-only origin main
unset AWS_PROFILE
export AWS_REGION=us-east-1
export EXPECTED_ACCOUNT_ID=023914826547
bash infrastructure/aws/scripts/00-retire-legacy-foundation.sh --inspect
```

El script verifica cuenta, región, estructura exacta de la pila, ausencia de objetos actuales y versionados en S3 y SG sin interfaces asociadas. Si hay datos, **no permite eliminar**.

**Paso 2, eliminación de recursos antiguos (solo tras revisar Paso 1):**

```bash
CONFIRM_DELETE_LEGACY_CINEGRAPH=DELETE_cinegraph-lab-foundation \
  bash infrastructure/aws/scripts/00-retire-legacy-foundation.sh --delete
```

La política `DeletionPolicy: Retain` conserva el bucket después de eliminar la pila; el script comprueba otra vez que está vacío y después elimina exclusivamente ese bucket. Si falla alguna comprobación, detiene el proceso. No usa `--force` ni elimina objetos.

**Paso 3, crear foundation nueva (solo tras comprobar eliminación):**

```bash
unset STACK_NAME
export VPC_ID=vpc-083d9bebc31224f94
export WEB_INGRESS_MODE=None
bash infrastructure/aws/scripts/01-foundation.sh --plan
CONFIRM_LAB_DEPLOY=YES bash infrastructure/aws/scripts/01-foundation.sh --apply
```

El paso 3 todavía no crea EC2, RDS ni acceso público. El resto del despliegue continúa con `02-db-network.sh`, que ahora referencia `cinegraph-e4-dev-foundation` y `cinegraph-e4-dev-db-network`.

## Ruta CLI del equipo: EC2 público, RDS privado (alternativa a CloudFront)

Esta ruta sigue **como referencia**, no como receta manual, el laboratorio N0 de SI7002: EC2 para frontend/backend, RDS PostgreSQL como OLTP y VPC/SG. Los siguientes hitos se basan en N1 (S3, streaming, Kinesis/Firehose) y N2 (Curated, Features y Step Functions). **Todos los pasos se harán desde CloudShell con AWS CLI/CloudFormation y validación de resultados**. No se requiere abrir manualmente la consola de servicios; sí iniciar la sesión del Learner Lab y CloudShell.

Situación: `cloudfront:ListDistributions` devolvió `AccessDenied`. Ese permiso de lectura denegado **no demuestra** por sí solo que la creación esté prohibida, pero no basaremos el primer entregable en ese servicio. La ruta de respaldo es una **EC2 accesible públicamente mediante una URL compartible**, con RDS no público. El acceso de usuarios debe protegerse con **HTTPS** antes de activar el inicio de sesión por Internet. Se evaluará un nombre DNS accesible y un certificado TLS válido para un proxy inverso en la EC2; sin dominio/certificado no declarar HTTPS operativo. La guía N0 usa HTTP/Elastic IP únicamente para laboratorio; no es adecuado para contraseñas reales. Usar exclusivamente usuarios ficticios.

Secuencia de implementación sin intervención manual sobre recursos:

0. **Preflight de red, tamaños y permisos de lectura**: `00-check-ec2-rds.sh`. No crea recursos.
1. **Fundación**: CloudFormation `01-foundation.yaml` con `WEB_INGRESS_MODE=None` por defecto. Crea S3 privado y SG para EC2/RDS, inicialmente sin apertura web.
2. **Red**: declarar mediante CloudFormation dos subredes privadas en distintas AZ (sin NAT Gateway) que no solapen CIDRs de la VPC actual; una subred pública existente para EC2. Verificar rutas/IGW y permisos.
3. **Compute y OLTP**: EC2 con `LabInstanceProfile` y un `compose` específico AWS; RDS PostgreSQL privada, DB subnet group, esquema y catálogo importados con herramienta separada del bootstrap local.
4. **Compartir el frontend**: publicar HTTPS en 443 con un proxy inverso y certificado validado; mantener el puerto interno 8000 inaccesible desde Internet. Compartir enlace solo después de probar salud, login, logout y recomendaciones.
5. **MLOps**: Kinesis/Firehose hacia S3 Raw, Curated/Features y posteriores servicios que el laboratorio permita.

**Siguiente comando (solo lectura):**

```bash
cd ~/cinegraph-aws
git pull --ff-only origin main
unset AWS_PROFILE
export AWS_REGION=us-east-1
export VPC_ID=vpc-083d9bebc31224f94
bash infrastructure/aws/scripts/00-check-ec2-rds.sh
```

Validar su salida antes de iniciar cualquier `--apply` o crear recursos. El entorno Docker + Floci local no se modifica.

## Objetivo: enlace compartible por todo el equipo

CineGraph NO debe quedar ligado a la IP del estudiante: tus compañeros deben entrar desde sus computadores a una URL HTTPS pública, iniciar sesión y consultar el catálogo/GraphSAGE A9.

Diseño previsto (sujeto a permisos de AWS Academy):

```text
Navegadores del equipo
       | HTTPS (dominio *.cloudfront.net)
       v
  Amazon CloudFront  (sin cache de sesiones/API)
       | HTTP 8000 solo hasta origen EC2 (*)
       v
EC2 publica + CineGraph Flask/Gunicorn  --- RDS PostgreSQL privada
       |                                        ^
       | clickstream                            |
       v                                        |
Kinesis -> Firehose -> S3 privado           Top-K A9
```

(*) La sesión del navegador viaja cifrada hasta CloudFront, pero la conexión CloudFront→EC2 sería HTTP en este primer laboratorio. **No es seguridad de producción ni HTTPS extremo a extremo**; utilizaremos solo cuentas ficticias de demostración, nada personal/sensible. Una arquitectura final deberá cifrar también el tramo de origen o usar ALB/ACM y HTTPS hacia EC2.

CloudFront proporciona un dominio `https://d....cloudfront.net`, sin necesidad de registrar dominio propio, si la cuenta permite crear distribuciones. En EC2, el puerto 8000 estará abierto **solo al prefijo AWS administrado de IP de origen CloudFront**, no a todo Internet. RDS no recibe conexiones públicas. Si la cuenta no permite CloudFront, diseñaremos otro acceso HTTPS antes de abrir credenciales en la red.

## Diagnósticos ejecutados antes de crear la pila inicial

Ya se comprobó que las credenciales de CloudShell funcionan, `us-east-1` es la región, existe la VPC `vpc-083d9bebc31224f94` y tiene seis subredes, está disponible `LabInstanceProfile / LabRole`, RDS permite consulta y CloudFormation valida la plantilla.

En CloudShell:

```bash
cd ~/cinegraph-aws
git pull --ff-only origin main
unset AWS_PROFILE
export AWS_REGION=us-east-1
bash infrastructure/aws/scripts/00-check-sharing.sh
```

Este script comprueba, **sin crear recursos**, si la cuenta permite leer CloudFront y el prefijo de red necesario. No prueba todavía permisos de creación. **Esperar validación antes de continuar.**

## Fundación CloudFormation — usar la nueva nomenclatura

Archivo: `cloudformation/01-foundation.yaml`. Crea solamente S3 privado/cifrado y dos Security Groups. **Sin EC2, RDS, CloudFront ni Glue en esta fase.** Reutiliza la VPC existente.

Modos de acceso para el puerto web EC2 (se elige por `WEB_INGRESS_MODE`):

- `None` (predeterminado): sin acceso entrante desde redes externas. Seguro mientras se prepara la infraestructura.
- `CloudFront` (plan de sitio compartido): permite 8000 **solo desde el prefijo administrado `com.amazonaws.global.cloudfront.origin-facing`**. No exige IP individual de tus compañeros.
- `RestrictedIP` (diagnóstico opcional): permite 8000 desde una única IPv4 pública `/32`; no se usa para el demo del equipo.

```bash
export VPC_ID=vpc-083d9bebc31224f94
export WEB_INGRESS_MODE=None
bash infrastructure/aws/scripts/01-foundation.sh --plan
```

`--plan` no crea recursos y valida la plantilla. CloudFront devolvió AccessDenied al consultar distribuciones; la estrategia principal ahora es EC2 con una URL compartible y un HTTPS válido para el inicio de sesión. La apertura de red permanece cerrada hasta esa fase. **`--apply` requiere `CONFIRM_LAB_DEPLOY=YES` y solo debe ejecutarse tras comprobar permisos, costos y recursos**.

## Secuencia posterior

1. Fundación de S3 y SG en CloudFormation.
2. EC2 con Docker Compose **específico para AWS**, sin `db` local ni Floci.
3. RDS PostgreSQL no pública, esquema y importación de MovieLens y Top-K históricos verificados; no utilizar sin cambios `local_setup`, que bloquea destinos no locales.
4. Distribución CloudFront HTTPS configurada **sin cachear sesiones, cookies ni APIs**, con métodos POST para login/interacciones y dominio público para compartir al equipo.
5. Kinesis Streams → Firehose → S3 Raw, transformación, observabilidad y MLOps según permisos de laboratorio.

**Seguridad y limpieza:** nunca guardar access keys, contraseñas o cookies en GitHub; no eliminar volúmenes locales; no crear NAT Gateway ni abrir PostgreSQL a Internet; no abrir HTTP 8000 a `0.0.0.0/0` para transportar credenciales; controlar presupuesto y borrar recursos de lab cuando termine la demostración.

Comprobación offline de las plantillas:

```bash
python3 -m unittest tests/test_aws_academy_scaffold.py -v
```
