# CineGraph — infraestructura AWS Academy (separada del entorno local)

**No hemos desplegado CineGraph todavía en AWS.** El entorno local con Docker + Floci se conserva sin cambios. La ruta AWS usa CloudShell, CloudFormation y recursos separados bajo `infrastructure/aws/`.

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

## Etapa actual: diagnósticos (sin recursos creados)

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

## Fundación con CloudFormation — solo después de validar

Archivo: `cloudformation/01-foundation.yaml`. Crea solamente S3 privado/cifrado y dos Security Groups. **Sin EC2, RDS, CloudFront ni Glue en esta fase.** Reutiliza la VPC existente.

Modos de acceso para el puerto web EC2 (se elige por `WEB_INGRESS_MODE`):

- `None` (predeterminado): sin acceso entrante desde redes externas. Seguro mientras se prepara la infraestructura.
- `CloudFront` (plan de sitio compartido): permite 8000 **solo desde el prefijo administrado `com.amazonaws.global.cloudfront.origin-facing`**. No exige IP individual de tus compañeros.
- `RestrictedIP` (diagnóstico opcional): permite 8000 desde una única IPv4 pública `/32`; no se usa para el demo del equipo.

```bash
export VPC_ID=vpc-083d9bebc31224f94
export WEB_INGRESS_MODE=CloudFront
bash infrastructure/aws/scripts/01-foundation.sh --plan
```

`--plan` no crea recursos y valida la plantilla. Si CloudFront no está disponible, no ejecutes ese plan: se decidirá un método HTTPS alternativo. **`--apply` requiere `CONFIRM_LAB_DEPLOY=YES` y solo debe ejecutarse tras comprobar permisos, costos y recursos**.

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
