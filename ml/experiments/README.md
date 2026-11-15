# Experimentos del modelo compartidos por Miguel

Se reubicaron los artefactos que estaban en la raíz del repositorio. **Los cuatro archivos conservaron exactamente su contenido** (se reutilizaron los objetos originales de Git).

## Estructura

```text
ml/experiments/
├── A0_base/
│   └── curva.csv
└── A9_sin_id/
    ├── curva.csv
    ├── modelo.pt
    └── validacion.json
```

- **A0_base/curva.csv**: curva del experimento de referencia (paso, pérdida, Recall@20, NDCG@20 y segundos).
- **A9_sin_id/curva.csv**: curva de entrenamiento/validación del experimento identificado como `A9_sin_id`.
- **A9_sin_id/validacion.json**: parámetros asociados al experimento. Entre ellos: `usar_id: false`, 2 capas, dimensión 64 y `atributos_semanales: true`.
- **A9_sin_id/modelo.pt**: checkpoint de ese experimento; **no cargar automáticamente** ni interpretar como versión champion sin reproducibilidad, validación y verificación de arquitectura.

## Importante para el diseño actual

El protocolo acordado para CineGraph usa **snapshots diarios**, horizonte **7 días**, scoring **diario** y reentrenamiento periódico. La configuración que llegó en `validacion.json` declara atributos **semanales**; por tanto, este material debe considerarse un **experimento previo**, no evidencia de que ya implemente el protocolo diario.

Antes de llevarlo a SageMaker, el responsable del modelo debe proporcionar código de preprocessing, features, arquitectura, dependencias, esquema de entrada y script de scoring, y verificar el rendimiento en el protocolo temporal. El benchmark histórico y el feedback live requieren una semántica de interacción explícita.

## Pipelines

Mover archivos o actualizar documentación **no ejecuta entrenamiento ni inferencia**. El workflow de GitHub Actions del repositorio es manual (`workflow_dispatch`); se conserva la opción **Run workflow** para ejecutar pruebas a demanda.

Los checkpoints nuevos deberían almacenarse en un bucket S3/versionado para no aumentar el tamaño del repositorio; `modelo.pt` se preserva aquí por continuidad del trabajo compartido.
