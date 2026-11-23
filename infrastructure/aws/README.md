# CineGraph | despliegue por etapas en AWS Academy Learner Lab

**Estado:** archivos preparados, sin despliegue real confirmado. Lo validado hasta ahora funciona en **Docker + Floci local**. Este directorio contiene la ruta real por AWS CLI. No usar credenciales ni datos de Floci en AWS.

## Fase 0 — Solo diagnóstico (empezar aquí)

1. Inicia la sesión del Learner Lab (**Start Lab**). En **AWS Details > AWS CLI > Show**, copia las credenciales temporales en un **perfil dedicado** `cinegraph-lab` de `~/.aws/credentials` (crea el directorio con `mkdir -p ~/.aws` y protege el archivo con `chmod 600 ~/.aws/credentials`). No pegues las claves en ChatGPT, Git, capturas ni terminal compartida. Si el bloque aparece con `[default]`, renombra **solo el encabezado** del nuevo bloque a `[cinegraph-lab]` sin alterar sus tres campos. Si ya usas `[default]`, ejecuta con `AWS_PROFILE=default`.
2. Configura la **región habilitada en tu laboratorio**, sin asumir que us-east-1 está disponible:

```bash
export AWS_PROFILE=cinegraph-lab
export AWS_REGION=us-east-1  # EJEMPLO: sustituye por la región permitida por tu Learner Lab
bash infrastructure/aws/scripts/00-preflight.sh
```

No crea recursos, ni EC2, RDS, S3, IAM o roles. Comprueba STS, VPC, subredes, `LabInstanceProfile`, lectura de RDS y validación CloudFormation. **Una lectura autorizada NO garantiza permisos de creación**. Si hay `ExpiredToken` o `InvalidClientTokenId`, renueva las credenciales del laboratorio. Evita ejecutar `aws configure` sobre tu cuenta personal.

**Antes de continuar:** compartir solo el resultado del preflight, nunca claves, tokens ni contraseñas.

## Fase 1 — Infraestructura mínima (archivos listos, NO ejecutarla todavía)

`cloudformation/01-foundation.yaml` crea únicamente:

- Un **bucket S3 privado**, cifrado con SSE-S3 y con acceso público bloqueado; la eliminación de la pila **retiene** el bucket y sus datos.
- Security Group de la **aplicación** que permite TCP/8000 **solo desde la IP pública del estudiante (/32)**. Sin SSH abierto; el acceso administrativo se diseñará con `LabInstanceProfile`/SSM si está disponible.
- Security Group de **PostgreSQL** que acepta TCP/5432 solamente desde el grupo de la aplicación. La futura RDS será **no pública**.

Se reutiliza la VPC existente y no se crean NAT Gateways ni balanceadores. **En esta fase aún NO se crean instancias EC2/RDS**. Las pilas/roles/recursos exactos pueden variar por las restricciones del Learner Lab.

Tras aprobar Fase 0, necesitarás `VPC_ID` y `ALLOWED_CIDR` (IP pública actual del Mac, terminada en `/32`). Para obtener tu IP en un canal de confianza: `curl -4 https://checkip.amazonaws.com` (muestra solo la IP pública; no implica autorización para abrir un puerto a toda Internet). En una red corporativa o VPN podría requerirse actualizarla.

**Plan sin crear nada:**

```bash
export VPC_ID=vpc-REEMPLAZAR
export ALLOWED_CIDR=203.0.113.10/32  # EJEMPLO, NO usar esta IP ilustrativa
bash infrastructure/aws/scripts/01-foundation.sh --plan
```

**Creación explícita, solamente cuando validemos el plan y los permisos:**

```bash
CONFIRM_LAB_DEPLOY=YES bash infrastructure/aws/scripts/01-foundation.sh --apply
```

Revisaremos Outputs del stack antes de diseñar/desplegar la siguiente fase.

## Fases siguientes (se implementarán tras validar cada paso)

| Paso | Qué se migrará | Requisito de seguridad y control |
|---|---|---|
| 2 | EC2 con CineGraph y RDS PostgreSQL | Nuevo Compose para AWS **sin `db` local**, secretos protegidos, RDS sin IP pública, esquema y MovieLens 87 585; no ejecutar bootstrap `local_setup` contra RDS sin adaptar su bloqueo local |
| 3 | Recomendaciones históricas A9 | Publicar solo los 30 resultados verificables del corte 2023-06-15 con manifiesto y hash; **no fingir inferencia sobre AWS** |
| 4 | Kinesis Data Streams → Firehose → S3 Raw | IAM/roles ya disponibles en Learner Lab, sin abrir el Data Lake; validar con eventos reales desde la aplicación |
| 5 | Curated/Features y orquestación | Adaptar scripts locales a AWS y evaluar permisos/costos de Glue, Step Functions y SageMaker; no asumir disponibilidad |

### Reglas innegociables

- **No usar `docker-compose.floci.yml` contra AWS**: sus scripts bloquean endpoints no locales por diseño.
- **No ejecutar `docker compose down -v`**, borrar buckets/RDS o migraciones destructivas.
- **No usar `--profile default` por accidente** si hay más de una cuenta AWS.
- No registrar credenciales/contraseñas en Git, logs, pantallas o archivos de la app. Learner Lab usa credenciales temporales y puede restringir servicios, presupuesto, cuotas y regiones.
- El primer despliegue de la app sería **HTTP en puerto 8000 restringido por IP**, solo para demostración de laboratorio; Internet público requiere HTTPS, control de acceso y una arquitectura adicional.
- La app actual usa `DATABASE_URL` con hostname `db` de Docker; **no servirá para RDS hasta configurar un Compose separado** en una fase posterior.

### Comprobación de integridad de plantillas

```bash
python3 -m unittest tests/test_aws_academy_scaffold.py -v
```

Las pruebas son offline: comprueban que los scripts tengan bloqueo de creación y que la infraestructura no permita DB pública ni tráfico abierto por defecto. **No sustituyen CloudFormation validate-template real.**