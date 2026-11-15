"""H3: la ventaja de GraphSAGE sobre la popularidad según la longitud del historial del usuario.

H3 (propuesta): la ventaja de la personalización frente a la popularidad crece con la
longitud del historial del usuario; existe un umbral por debajo del cual recomendar lo
popular es preferible.

Unidad: el par (usuario, semana) de los usuarios que regresan. Historial = ratings del
usuario antes de esa semana. Se compara GraphSAGE (A9) con la popularidad de la semana
anterior, la línea base más fuerte, con la diferencia por usuario de Recall@20 y NDCG@20.
- Deciles de historial: los cortes se fijan con los pares de validación (2022) y se
  aplican tal cual al test (2023).
- IC al 95 %: bootstrap por conglomerados de usuarios (cada réplica remuestrea usuarios
  con todas sus semanas), 10 000 réplicas.
- Tendencia ("crece"): pendiente de la diferencia sobre log(1 + historial), con IC y p
  del mismo bootstrap y Holm sobre las dos métricas.
- Umbral, regla fijada antes de mirar los datos y aplicada en validación: el borde
  superior del decil más alto en el que la popularidad es significativamente mejor
  (IC de la diferencia por debajo de 0). Si no hay ninguno, no hay umbral. En el test se
  verifica que la regla dé el mismo resultado con los mismos cortes.

Uso, desde la raíz del proyecto:
    python -m src.h3
"""

import numpy as np
import pandas as pd

from src import datos
from src.estadistica import bootstrap_por_conglomerados, holm
from src.protocolo import DIR_RESULTADOS

MODELO, REFERENCIA = "A9_sin_id", "popularidad_reciente_1"
METRICAS = ["recall@20", "ndcg@20"]
N_GRUPOS = 10
SALIDA = datos.RAIZ / "resultados" / "h3"


def pares(particion_):
    """Una fila por (semana, usuario) con el historial y la métrica de los dos métodos."""
    carpeta = DIR_RESULTADOS / particion_
    columnas = ["semana", "usuario", "n_historial", *METRICAS]
    modelo = pd.read_parquet(carpeta / f"{MODELO}_usuarios.parquet", columns=columnas)
    referencia = pd.read_parquet(carpeta / f"{REFERENCIA}_usuarios.parquet", columns=columnas)
    tabla = modelo.merge(referencia, on=["semana", "usuario", "n_historial"], suffixes=("_modelo", "_referencia"), validate="one_to_one")
    if len(tabla) != len(modelo) or len(tabla) != len(referencia):
        raise ValueError(f"{particion_}: los dos métodos no tienen los mismos pares usuario–semana")
    for metrica in METRICAS:
        tabla[f"dif_{metrica}"] = tabla[f"{metrica}_modelo"] - tabla[f"{metrica}_referencia"]
    return tabla


def cortes_de_deciles(historial):
    """Bordes de los grupos (cuantiles 10 %, …, 90 % del historial), sin repetir."""
    return np.unique(np.quantile(historial, np.linspace(0, 1, N_GRUPOS + 1)[1:-1]))


def por_grupo(tabla, cortes):
    """Diferencia media por grupo de historial, con IC por usuario, para cada métrica."""
    tabla = tabla.assign(grupo=np.searchsorted(cortes, tabla["n_historial"], side="right"))
    bordes = np.concatenate([[0], cortes, [np.inf]])
    filas = []
    for grupo, sub in tabla.groupby("grupo"):
        fila = {"grupo": grupo + 1, "historial_desde": bordes[grupo], "historial_hasta": bordes[grupo + 1],
                "historial_mediana": sub["n_historial"].median(), "pares": len(sub), "usuarios": sub["usuario"].nunique()}
        for metrica in METRICAS:
            estimado, bajo, alto, p = bootstrap_por_conglomerados(sub[f"dif_{metrica}"], sub["usuario"])
            fila.update({f"{metrica}_modelo": sub[f"{metrica}_modelo"].mean(), f"{metrica}_referencia": sub[f"{metrica}_referencia"].mean(),
                         f"dif_{metrica}": estimado, f"ic_bajo_{metrica}": bajo, f"ic_alto_{metrica}": alto, f"p_{metrica}": p})
        filas.append(fila)
    return pd.DataFrame(filas)


def tendencia(tabla):
    """Pendiente de la diferencia sobre log(1 + historial), con IC por usuario y Holm."""
    filas = []
    for metrica in METRICAS:
        estimado, bajo, alto, p = bootstrap_por_conglomerados(tabla[f"dif_{metrica}"], tabla["usuario"], x=np.log1p(tabla["n_historial"]))
        filas.append({"metrica": metrica, "pendiente": estimado, "ic_bajo": bajo, "ic_alto": alto, "p": p})
    resultado = pd.DataFrame(filas)
    resultado["p_holm"] = holm(resultado["p"])
    return resultado


def umbral(grupos, metrica):
    """Borde superior del decil más alto donde la popularidad es significativamente mejor (o None)."""
    peores = grupos[grupos[f"ic_alto_{metrica}"] < 0]
    return None if peores.empty else float(peores["historial_hasta"].max())


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    validacion = pares("validacion")
    cortes = cortes_de_deciles(validacion["n_historial"])
    (SALIDA / "cortes_deciles.txt").write_text(" ".join(str(int(c)) for c in cortes), encoding="utf-8")

    resumen = []
    for particion_, tabla in (("validacion", validacion), ("test", pares("test"))):
        grupos = por_grupo(tabla, cortes)
        pendiente = tendencia(tabla)
        grupos.to_csv(SALIDA / f"deciles_{particion_}.csv", index=False)
        pendiente.to_csv(SALIDA / f"tendencia_{particion_}.csv", index=False)
        for metrica in METRICAS:
            fila = pendiente[pendiente["metrica"] == metrica].iloc[0]
            resumen.append({"particion": particion_, "metrica": metrica, "pares": len(tabla), "usuarios": tabla["usuario"].nunique(),
                            "pendiente": fila["pendiente"], "ic_bajo": fila["ic_bajo"], "ic_alto": fila["ic_alto"], "p_holm": fila["p_holm"],
                            "umbral": umbral(grupos, metrica),
                            "deciles_modelo_mejor": int((grupos[f"ic_bajo_{metrica}"] > 0).sum()),
                            "deciles_sin_diferencia": int(((grupos[f"ic_bajo_{metrica}"] <= 0) & (grupos[f"ic_alto_{metrica}"] >= 0)).sum()),
                            "deciles_popularidad_mejor": int((grupos[f"ic_alto_{metrica}"] < 0).sum())})
        with pd.option_context("display.width", 250, "display.max_columns", 30, "display.float_format", "{:.4f}".format):
            print(f"\n== {particion_}: {len(tabla):,} pares, {tabla['usuario'].nunique():,} usuarios")
            print(grupos[["grupo", "historial_desde", "historial_hasta", "pares", "usuarios",
                          "recall@20_modelo", "recall@20_referencia", "dif_recall@20", "ic_bajo_recall@20", "ic_alto_recall@20",
                          "dif_ndcg@20", "ic_bajo_ndcg@20", "ic_alto_ndcg@20"]].to_string(index=False))
            print(pendiente.to_string(index=False))
    resumen = pd.DataFrame(resumen)
    resumen.to_csv(SALIDA / "resumen.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 30, "display.float_format", "{:.4f}".format):
        print("\n" + resumen.to_string(index=False))


if __name__ == "__main__":
    main()
