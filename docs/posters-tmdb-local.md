# CineGraph | Portada cinematográfica y pósteres originales (local)

## Qué aparece inmediatamente

- El inicio usa `app/static/img/hero-cinegraph.webp`: una imagen panorámica **original** almacenada en GitHub, sin vínculos externos ni derechos de fotogramas de películas.
- Las primeras tarjetas priorizan los títulos auténticos de MovieLens 32M que ya tienen `poster_url` guardado en PostgreSQL y diez títulos populares cuyos **pósteres TMDB fueron identificados previamente por sus `movieId`**, no recomendaciones de GraphSAGE. Esos pósteres se enlazan al CDN de TMDB.
- Las películas sin póster conocido conservan un diseño tipográfico con el título auténtico, sin inventar una portada. MovieLens por sí solo no contiene `poster_path`.

## Cómo obtener más imágenes de TMDB para el catálogo

Para la cobertura del resto del catálogo hace falta autorización de TMDB. No es necesaria una cuenta AWS ni cambiar GraphSAGE. El flujo usa `links.csv` **original de MovieLens**, verificado por MD5 antes de consultar datos, para obtener `tmdbId` correspondiente a cada `movieId`; utiliza `/3/movie/{tmdbId}` para leer `poster_path` y escribe solamente `movies.poster_url` en PostgreSQL local.

1. Obtén un API Read Access Token de [TMDB](https://www.themoviedb.org/settings/api). No lo incluyas en GitHub, mensajes de chat, capturas ni commits.
2. Abre la Terminal desde la carpeta raíz del proyecto. Define el token **solo en tu entorno de Terminal**:

   ```bash
   export TMDB_READ_TOKEN='TU_TOKEN_PRIVADO_DE_TMDB'
   ```

3. Ejecuta el importador manual:

   ```bash
   docker compose --profile setup run --rm poster-enrich --limit 120
   ```

4. Recarga `http://localhost:8000` con Cmd+Shift+R. No hace falta reiniciar la aplicación Flask: los pósteres se consultan desde PostgreSQL.

El importador utiliza una pausa entre peticiones, comprueba el catálogo local, procesa primero géneros que se muestran en la portada y omite pósteres no disponibles. Puede repetirse para ampliar la cobertura; no descarga los archivos de imagen, **guarda sus URL oficiales**. No modifica ratings, entrenamientos, predicciones, interacciones ni las cuentas existentes.

**Sin token:** la portada y los primeros pósteres siguen funcionando con las rutas públicas conocidas; el resto seguirá con tarjeta tipográfica. No es correcto prometer que todas las 87.585 películas tendrán fotografía.

## Atribuciones

- El catálogo, títulos y asociación `movieId`–`tmdbId` proceden de MovieLens 32M (GroupLens).
- Los pósteres se muestran desde TMDB, sujeto a su disponibilidad, reglas de uso y atribución. Esta aplicación académica incluye la atribución obligatoria en su pie de página. Este producto utiliza la API de TMDB, pero TMDB no lo respalda ni certifica.
- La imagen del hero fue creada originalmente para CineGraph, no es un póster ni material de una película.

Documentación oficial: [autenticación TMDB](https://developer.themoviedb.org/docs/authentication-application), [construcción de URL de imágenes](https://developer.themoviedb.org/docs/image-basics) y [atribución](https://developer.themoviedb.org/docs/faq).