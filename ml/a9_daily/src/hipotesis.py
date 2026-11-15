"""Contraste de H1 en el test (40 semanas de 2023), con el protocolo de src/estadistica.py.

H1: GraphSAGE supera en Recall@20 y NDCG@20 a la popularidad reciente, con diferencias
significativas entre semanas de prueba. Se compara el GraphSAGE elegido en validación
contra cada línea base elegida en validación: Wilcoxon bilateral por semana, IC al 95 %
con bootstrap de bloques de 4 semanas, y Holm sobre {Recall@20, NDCG@20} × líneas base.

Uso, desde la raíz del proyecto (después de correr el test del modelo y de las líneas base):
    python -m src.hipotesis
"""

import pandas as pd

from src import datos
from src.estadistica import bootstrap_media, comparar
from src.evaluacion import KS, nombres_metricas
from src.protocolo import DIR_RESULTADOS

MODELO = ("GraphSAGE (A9)", "A9_sin_id")
LINEAS_BASE = {
    "Popularidad semana anterior": "popularidad_reciente_1",
    "MF-BPR": "mf_bpr_v13_e20",
    "ItemKNN": "itemknn",
    "Popularidad histórica": "popularidad_historica",
    "Aleatoria": "aleatoria",
}
METRICAS_H1 = ["recall@20", "ndcg@20"]


def h1(particion_="test"):
    """Escribe resultados/h1_<particion>_{resumen,comparacion}.csv y los devuelve."""
    carpeta = DIR_RESULTADOS / particion_
    metodos = dict([MODELO, *LINEAS_BASE.items()])
    por_semana = {nombre: pd.read_csv(carpeta / f"{archivo}_semanas.csv") for nombre, archivo in metodos.items()}
    semanas = {nombre: tuple(t["semana"]) for nombre, t in por_semana.items()}
    if len(set(semanas.values())) != 1:
        raise ValueError("Los métodos no se evaluaron en las mismas semanas")

    filas = []
    for nombre, tabla in por_semana.items():
        fila = {"metodo": nombre, "semanas": len(tabla)}
        for metrica in nombres_metricas() + [f"cobertura@{k}" for k in KS]:
            fila[metrica] = tabla[metrica].mean()
        for metrica in METRICAS_H1:
            fila[f"ic_bajo_{metrica}"], fila[f"ic_alto_{metrica}"] = bootstrap_media(tabla[metrica])
        filas.append(fila)
    resumen = pd.DataFrame(filas)

    largo = pd.concat([t.assign(metodo=nombre) for nombre, t in por_semana.items()])
    comparacion = comparar(largo, MODELO[0], list(LINEAS_BASE), METRICAS_H1)
    salida = datos.RAIZ / "resultados"
    resumen.to_csv(salida / f"h1_{particion_}_resumen.csv", index=False)
    comparacion.to_csv(salida / f"h1_{particion_}_comparacion.csv", index=False)
    return resumen, comparacion


def main():
    resumen, comparacion = h1()
    with pd.option_context("display.width", 250, "display.max_columns", 40, "display.float_format", "{:.4f}".format):
        print(resumen[["metodo", "semanas", "recall@10", "recall@20", "recall@50", "ndcg@20", "precision@20",
                       "hitrate@20", "mrr", "cobertura@20", "ic_bajo_recall@20", "ic_alto_recall@20"]].to_string(index=False))
        print()
        print(comparacion.to_string(index=False))


if __name__ == "__main__":
    main()
