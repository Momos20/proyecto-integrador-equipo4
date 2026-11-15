# Interfaz CineGraph — diseño cinematográfico

Rediseño visual original, inspirado en patrones generales de plataformas de streaming (portada destacada, carrusel visual y tarjetas con póster), **sin incorporar código, componentes ni activos del repositorio Netflix-Clone** de terceros. Las tarjetas del catálogo son ilustrativas, no predicciones. Los pósteres remotos se solicitan al CDN de TMDB y tienen fallback visual si no están disponibles; el proyecto no redistribuye esas imágenes.

## Puntos que se mantuvieron funcionales

- `GET /api/recommendations/<user_id>?limit=10`: el Top 10 sigue saliendo de PostgreSQL.
- `POST /api/interactions`: Me gusta, No me gusta, Mi lista y calificaciones entre 0,5 y 5 estrellas.
- Metadatos `model_version`, `position`, `cutoff_date` por cada acción.
- Usuario demo `414`, loading, no-results y manejo de errores.
- Filtro de texto **local** dentro del Top 10 devuelto, sin modificar resultados persistidos.
- A9_sin_id como **único modelo seleccionado mostrado**; no se afirma que esté sirviendo todavía.

## Cómo verla

```bash
git switch main
git pull origin main
docker compose up -d --build
```

Abrir http://localhost:8000. Desplazarse a «Mi selección», probar el usuario 414 y marcar una interacción para verificar feedback. Los datos de demostración identificados como `baseline-v0` siguen siendo los disponibles hasta que se integre la inferencia real.

## Notas

La galería de la portada contiene títulos del catálogo de demostración, no una lista ordenada por GraphSAGE. Los pósteres son imágenes promocionales de TMDB referenciadas por HTTPS. Las imágenes se pueden mejorar cuando el pipeline TMDB construya `poster_url` para el catálogo completo. Este rediseño **no habilita ningún pipeline automático**.
