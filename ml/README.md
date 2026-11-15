# Machine Learning

Aquí están **los modelos recibidos de Miguel** y los componentes de entrenamiento, evaluación, inferencia y arranque en frío que se usarán para integrarlos con la aplicación y SageMaker.

## Estructura

- `models/`: versiones de modelos y sus artefactos tal como fueron entregados.
- `training/`: código reproducible de entrenamiento, pendiente de incorporación.
- `evaluation/`: evaluación y métricas de ranking.
- `inference/`: scoring y generación de Top-K, pendiente de incorporación.
- `cold_start/`: estrategias de arranque en frío.
- `containers/`: empaquetado para SageMaker.

Consulta `models/README.md` para la descripción de `A0_base` y `A9_sin_id`. **A9 sí tiene un checkpoint `modelo.pt`**; la versión A0, por ahora, solo cuenta con su curva. No se les ha modificado el contenido ni activado ejecución automática.

El flujo actual de la web sigue consultando los rankings que haya en PostgreSQL (el seed de demostración usa `PopularityBaseline`). Tener un checkpoint guardado no equivale a haberlo registrado como campeón ni a contar con un servicio de inferencia que produzca Top-K.

El workflow de GitHub Actions se ejecuta **solo manualmente** mediante `workflow_dispatch`; no se inicia automáticamente con push o pull request.
