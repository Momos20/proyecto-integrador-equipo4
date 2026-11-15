# Modelos entregados por Miguel

Carpeta para las **versiones de modelo del equipo**, no para descartarlas como simples experimentos. Los archivos se trasladaron conservando exactamente los objetos Git originales.

```text
ml/models/
├── A0_base/
│   └── curva.csv
└── A9_sin_id/
    ├── curva.csv
    ├── modelo.pt
    └── validacion.json
```

## A0_base — versión base

- `curva.csv` contiene 15 registros de entrenamiento/validación de los pasos 100 a 1500.
- Máximo Recall@20 observado en la curva: **0.029167** (paso 1000).
- Máximo NDCG@20 observado en la curva: **0.014515** (paso 900).
- **No se ha entregado checkpoint de esta versión**. No podemos ejecutar scoring con solo la curva.

## A9_sin_id — modelo GraphSAGE disponible

- `modelo.pt`: checkpoint binario (7,860,057 bytes) aportado por Miguel.
- `curva.csv`: registros de los pasos 100 a 2100.
- `validacion.json`: informa `mejor_paso: 1600`. En ese paso, la curva registra **Recall@20 = 0.138956** y **NDCG@20 = 0.091508**.
- Configuración informada: **2 capas, dimensión 64, dropout 0.1, Adam, LR 0.01, negativos uniformes, usar_id=false, atributos_semanales=true, ventana=13, semilla=0**.

Las métricas son **las que vienen en los archivos**, no una evaluación independiente del checkpoint. No se puede garantizar equivalencia entre protocolos de A0 y A9, ni extrapolar las curvas al test de 2023.

## Estado de integración

**Disponibilidad del modelo:** sí, A9 tiene checkpoint. **Serving en CineGraph:** todavía no. Actualmente `GET /api/recommendations/<user_id>` solo lee el Top-K ya persistido en PostgreSQL. En el seed local los registros pertenecen al modelo `PopularityBaseline` (`baseline-v0`), distinto de los modelos anteriores.

El protocolo objetivo de CineGraph usa **snapshot diario, horizonte de 7 días y scoring diario**. El archivo de A9 declara `atributos_semanales=true` y `ventana=13`; Miguel debe verificar si la entrada actual y el target corresponden a ese protocolo o si se requiere adaptar el procesamiento/modelo. Esto **no invalida el checkpoint como versión de modelo**.

Miguel entregó el ZIP **A9_topk_diario.zip** con la implementación de `src.recomendar`, `src.diario`, utilidades, pruebas y resultados. Véase [la revisión de la entrega](../../docs/revision-a9-miguel.md). El checkpoint, configuración y curva del ZIP son idénticos a estos archivos (SHA Git sin cambios).

**La integración con CineGraph está preparada, pero todavía no conectada al endpoint:** el paquete implementa cortes diarios con objetivo **del mismo día**, mientras el protocolo vigente exige un corte diario con predicción para los **siguientes 7 días**. Se deben generar y validar etiquetas del horizonte de 7 días sin fuga temporal. Las métricas informadas son de evaluación retrospectiva y no validación independiente.

Para integrar A9 sin inventar resultados hacen falta al menos:

1. La clase/arquitectura y el código para cargar `modelo.pt` de forma segura y reconstruir el modelo.
2. La definición exacta de features, normalización, orden/dimensión de entrada, índices de usuario/película y grafos.
3. El código reproducible de generación de candidatos y scoring Top-K.
4. Identificación del split/protocolo usado para calcular Recall@20 y NDCG@20.
5. Validación del objetivo temporal `(d,d+7]` y del manejo de usuarios/películas nuevos antes del despliegue.

No se habilita inferencia ni reentrenamiento automáticamente por agregar estos archivos. Los workflows de Actions siguen siendo **manuales** (`workflow_dispatch`).
