# Machine Learning

Esta carpeta contiene los componentes de entrenamiento, evaluación, inferencia y arranque en frío del recomendador GraphSAGE (PyTorch/PyG) que se integrará con SageMaker AI.

## Organización

- `training/`: código reproducible de entrenamiento (cuando se incorpore).
- `evaluation/`: código de evaluación y métricas de ranking.
- `inference/`: código de scoring y exportación de Top-K.
- `cold_start/`: estrategias de arranque en frío.
- `containers/`: empaquetado para SageMaker.
- `experiments/`: artefactos históricos de las ejecuciones compartidas por Miguel, separados del código productivo.

Consulta `experiments/README.md` para la procedencia y las limitaciones de los artefactos. La presencia de un `modelo.pt` en Git no significa que haya sido promovido a `champion` ni que se vaya a ejecutar automáticamente.

**Ejecución de pipelines:** los workflows de GitHub Actions están configurados solo con `workflow_dispatch`; deben iniciarse manualmente desde la pestaña Actions.
