# Arquitectura CineGraph

## 1. Arquitectura original

[`arquitectura_aws_final.drawio`](arquitectura_aws_final.drawio): diseño objetivo con Amazon SageMaker. Se conserva sin modificaciones.

## 2. Arquitectura implementada en AWS Academy (principal)

[`arquitectura_aws_academy_ec2.drawio`](arquitectura_aws_academy_ec2.drawio): arquitectura desplegada y verificada, con EC2 como alternativa autorizada a SageMaker, Caddy HTTPS, RDS PostgreSQL, S3, Kinesis, Firehose, Glue, Step Functions y CloudWatch.

La inferencia GraphSAGE A9, la publicación de 30 recomendaciones reales en RDS y la ejecución integral de Step Functions con arranque y apagado automático del worker fueron verificadas el 24 de noviembre de 2026 UTC. EventBridge permanece configurado y deshabilitado; el reentrenamiento periódico y la incorporación del feedback actual al modelo no han sido implementados.

Esta es la arquitectura de referencia para la sustentación. Ambos diagramas son editables con [diagrams.net](https://app.diagrams.net/).
