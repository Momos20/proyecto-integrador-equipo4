# Arquitectura

La arquitectura objetivo integra S3, Glue, EventBridge, Step Functions, SageMaker AI, ECR, RDS PostgreSQL, EC2/Flask y CloudWatch.

El archivo `arquitectura_aws_final.drawio` es la fuente editable oficial del diagrama.

## Versiones del diagrama

- `arquitectura_aws_final.drawio`: arquitectura objetivo original con SageMaker, sin cambios.
- `arquitectura_aws_cinegraph_kinesis.drawio`: arquitectura objetivo detallada de streaming, sin cambios.
- `arquitectura_aws_academy_ec2.drawio`: copia adaptada al laboratorio AWS Academy; Caddy HTTPS, EC2 t3.large independiente para A9, Glue behavioral verificado, EventBridge deshabilitado y publicación pendiente. Flechas discontinuas indican flujos pendientes, propuestos o de monitorización. El entrenamiento periódico continúa como propuesta, no como ejecución real.

SageMaker Processing rechazado por política Pvoclabs2. La instancia EC2 alternativa i-03306ae6540b03d3e fue creada y recibió el comando SSM 4e75f83c-4be5-4768-bc61-44881691065d. Inferencia lanzada, resultado aún no confirmado. No se ha publicado Top-K en RDS.
