# CineGraph — Identidad y recomendaciones personalizadas

## Modelo de acceso

Las cuentas cine123, cine414 y cine456 están vinculadas a sus respectivos identificadores MovieLens. Flask mantiene sesiones firmadas con cookies Secure y HttpOnly, y protege las operaciones mediante CSRF. El backend determina la identidad a partir de la sesión autenticada.

Amazon Secrets Manager custodia las credenciales; el rol SQL de aplicación dispone de permisos limitados. La conexión a RDS utiliza TLS verify-full. No se incluyen contraseñas en la documentación.

## Recomendaciones

GraphSAGE A9 genera rankings Top-10 con el checkpoint original y el protocolo temporal de MovieLens 32M. La inferencia verificada corresponde al 15 de junio de 2023, con 30 recomendaciones reales publicadas en RDS para tres usuarios, ejecución run_id=1. La API sirve los resultados persistidos del modelo champion.

## Evidencia

- 16 pruebas originales del modelo superadas.
- Integridad SHA-256 del checkpoint y de las predicciones validada.
- Autenticación, catálogo, rutas privadas, recomendaciones y cierre de sesión verificados con cine414.
- Reproducción histórica mediante Step Functions completada sin duplicar el ranking.
- Validación final automatizada de las tres cuentas preparada, pendiente de confirmación.

Consultar la [documentación de despliegue AWS](../infrastructure/aws/README.md).
