# CineGraph — Aplicación web

CineGraph ofrece un catálogo cinematográfico de MovieLens 32M y recomendaciones personalizadas GraphSAGE A9. El frontend utiliza una portada cinematográfica original, filas horizontales de películas, búsqueda y tarjetas con imágenes TMDB cuando están disponibles.

## Funcionalidades

- Autenticación mediante cuentas asociadas a usuarios MovieLens.
- Ranking Top-10 personalizado, leído desde PostgreSQL mediante la API autenticada.
- Interacciones: Me gusta, No me gusta, Mi lista y calificaciones.
- Catálogo de 87.585 películas verificadas.
- Identificación de la versión del modelo y fecha de corte histórica.
- Pósteres TMDB referenciados mediante HTTPS; tarjeta tipográfica para títulos sin imagen.

## Despliegue

Flask/Gunicorn se ejecuta en EC2 mediante Docker, detrás de Caddy con HTTPS. PostgreSQL se encuentra en Amazon RDS privado. Consultar la [guía de AWS](../infrastructure/aws/README.md).

## Validación

El ranking real de cine414 se verificó mediante la API autenticada y desde el navegador. Los rankings de cine123 y cine456 están publicados en RDS; sus capturas y la ejecución de la validación final de las tres cuentas están pendientes de confirmación.

Los pósteres se pueden enriquecer mediante el script `infrastructure/aws/scripts/20-final-validation.sh` con credenciales TMDB en Secrets Manager. No se modifica el ranking por enriquecer imágenes.
