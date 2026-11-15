"""Experimento inicial: GraphSAGE heterogéneo vs. popularidad en MovieLens 32M.

Protocolo por instantáneas: para la semana w, el modelo sólo ve las aristas anteriores
a w y debe rankear las películas que cada usuario que regresa calificará en w.
- Test: las últimas 4 semanas completas.
- Validación: las 4 semanas anteriores (eligen el mejor punto del entrenamiento).
- Entrenamiento: semanas anteriores a la validación. Por defecto cualquiera desde 1995;
  con --semanas-entrenamiento N, sólo las N semanas justo antes de la validación.
  En ambos casos el grafo de cada instantánea usa toda la historia anterior.

Uso, desde la raíz del proyecto:
    python -m src.experimento
    python -m src.experimento --semanas-entrenamiento 52
"""

import argparse
import copy
import json
import time
import warnings

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F

from src import datos
from src.evaluacion import K, evaluar_semana, puntuar_con_embeddings, puntuar_por_popularidad
from src.grafo import GrafoTemporal
from src.modelo import SAGEHeterogeneo

CONFIG = {
    "dimension": 64,
    "capas": 2,
    "tasa_aprendizaje": 0.01,
    "pasos": 400,  # cada paso = una semana de entrenamiento elegida al azar
    "evaluar_cada": 25,
    "max_positivos_por_paso": 20_000,
    "semanas_test": 4,
    "semanas_validacion": 4,
    "semanas_popularidad_reciente": 4,
    "semilla": 0,
    "semanas_entrenamiento": None,  # None = todas las semanas desde 1995
}
DIR_EXPERIMENTO = datos.RAIZ / "resultados" / "experimento_inicial"
METRICA_SELECCION = f"ndcg@{K}"

warnings.filterwarnings("ignore", message="Sparse CSR tensor support is in beta")


def main():
    argumentos = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    argumentos.add_argument("--semanas-entrenamiento", type=int, default=None,
                            help="usar como objetivos de entrenamiento sólo las N semanas antes de la validación")
    CONFIG["semanas_entrenamiento"] = argumentos.parse_args().semanas_entrenamiento
    n = CONFIG["semanas_entrenamiento"]
    dir_resultados = DIR_EXPERIMENTO / ("todas_las_semanas" if n is None else f"ultimas_{n}_semanas")

    torch.manual_seed(CONFIG["semilla"])
    azar = np.random.default_rng(CONFIG["semilla"])
    inicio = time.time()

    grafo = GrafoTemporal()
    ultima_completa = grafo.ultima_semana - 1  # la última semana de los datos está incompleta
    semanas_test = list(range(ultima_completa - CONFIG["semanas_test"] + 1, ultima_completa + 1))
    semanas_validacion = list(range(semanas_test[0] - CONFIG["semanas_validacion"], semanas_test[0]))
    desde = grafo.primera_semana + 1 if n is None else semanas_validacion[0] - n
    _registrar(f"Grafo cargado en {time.time() - inicio:.0f} s. Entrenamiento desde {_fecha(desde)}, "
               f"validación desde {_fecha(semanas_validacion[0])}, test desde {_fecha(semanas_test[0])}")

    resultados = {"config": CONFIG, "semanas_validacion": _fechas(semanas_validacion), "semanas_test": _fechas(semanas_test)}
    baselines = {
        "Popularidad histórica": None,
        f"Popularidad reciente ({CONFIG['semanas_popularidad_reciente']} semanas)": CONFIG["semanas_popularidad_reciente"],
    }
    for nombre, semanas_atras in baselines.items():
        resultados[nombre] = {
            "validacion": evaluar_popularidad(grafo, semanas_validacion, semanas_atras),
            "test": evaluar_popularidad(grafo, semanas_test, semanas_atras),
        }
        _registrar(f"{nombre}: validación {_resumen(resultados[nombre]['validacion'])}")

    modelo = SAGEHeterogeneo(grafo.n_usuarios, grafo.n_peliculas, grafo.atributos_pelicula, CONFIG["dimension"], CONFIG["capas"])
    optimizador = torch.optim.Adam(modelo.parameters(), lr=CONFIG["tasa_aprendizaje"])

    curva, perdidas = [], []
    mejor = {"valor": -1.0, "paso": 0, "estado": None}
    paso = 0
    while paso < CONFIG["pasos"]:
        semana = int(azar.integers(desde, semanas_validacion[0]))
        perdida = paso_de_entrenamiento(modelo, optimizador, grafo, semana)
        if perdida is None:  # semana sin usuarios que regresan
            continue
        perdidas.append(perdida)
        paso += 1

        if paso % CONFIG["evaluar_cada"] == 0:
            validacion = promedio(evaluar_modelo(modelo, grafo, semanas_validacion))
            curva.append({"paso": paso, "perdida": float(np.mean(perdidas)), **validacion, "segundos": round(time.time() - inicio)})
            perdidas = []
            if validacion[METRICA_SELECCION] > mejor["valor"]:
                mejor = {"valor": validacion[METRICA_SELECCION], "paso": paso, "estado": copy.deepcopy(modelo.state_dict())}
            _registrar(f"paso {paso}: pérdida {curva[-1]['perdida']:.4f} | validación {_resumen_metricas(validacion)}")

    modelo.load_state_dict(mejor["estado"])
    resultados["GraphSAGE heterogéneo"] = {
        "mejor_paso": mejor["paso"],
        "validacion": evaluar_modelo(modelo, grafo, semanas_validacion),
        "test": evaluar_modelo(modelo, grafo, semanas_test),
    }
    resultados["minutos_totales"] = round((time.time() - inicio) / 60, 1)

    dir_resultados.mkdir(parents=True, exist_ok=True)
    (dir_resultados / "metricas.json").write_text(json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8")
    pd.DataFrame(curva).to_csv(dir_resultados / "curva_entrenamiento.csv", index=False)

    _registrar(f"Mejor paso: {mejor['paso']}. Test (promedio de {len(semanas_test)} semanas):")
    for nombre in [*baselines, "GraphSAGE heterogéneo"]:
        _registrar(f"  {nombre}: {_resumen(resultados[nombre]['test'])}")
    _registrar(f"Resultados guardados en {dir_resultados}")


def paso_de_entrenamiento(modelo, optimizador, grafo, semana):
    """Un paso de BPR: cada película calificada en `semana` debe puntuar más que una al azar."""
    usuarios, peliculas, _ = grafo.objetivos(semana)
    if len(usuarios) == 0:
        return None
    if len(usuarios) > CONFIG["max_positivos_por_paso"]:
        muestra = torch.randperm(len(usuarios))[:CONFIG["max_positivos_por_paso"]]
        usuarios, peliculas = usuarios[muestra], peliculas[muestra]
    conocidas = grafo.peliculas_conocidas(semana)
    negativas = conocidas[torch.randint(len(conocidas), (len(usuarios),))]

    z_usuario, z_pelicula = modelo(grafo.adyacencias(semana))
    z = z_usuario[usuarios]
    positivo = (z * z_pelicula[peliculas]).sum(dim=1)
    negativo = (z * z_pelicula[negativas]).sum(dim=1)
    perdida = -F.logsigmoid(positivo - negativo).mean()

    optimizador.zero_grad()
    perdida.backward()
    optimizador.step()
    return perdida.item()


@torch.no_grad()
def evaluar_modelo(modelo, grafo, semanas):
    modelo.eval()
    resultados = []
    for semana in semanas:
        adyacencias = grafo.adyacencias(semana)
        z_usuario, z_pelicula = modelo(adyacencias)
        resultados.append({"semana": _fecha(semana), **evaluar_semana(grafo, semana, adyacencias, puntuar_con_embeddings(z_usuario, z_pelicula))[0]})
    modelo.train()
    return resultados


def evaluar_popularidad(grafo, semanas, semanas_atras):
    resultados = []
    for semana in semanas:
        puntuar = puntuar_por_popularidad(grafo.popularidad(semana, semanas_atras))
        resultados.append({"semana": _fecha(semana), **evaluar_semana(grafo, semana, grafo.adyacencias(semana), puntuar)[0]})
    return resultados


def promedio(por_semana):
    """Promedio simple entre semanas (cada semana pesa igual)."""
    return {metrica: float(np.mean([r[metrica] for r in por_semana])) for metrica in (f"recall@{K}", f"ndcg@{K}")}


def _resumen(por_semana):
    return _resumen_metricas(promedio(por_semana))


def _resumen_metricas(metricas):
    return " ".join(f"{nombre} {valor:.4f}" for nombre, valor in metricas.items())


def _fecha(semana):
    return str(datos.inicio_semana(semana).date())


def _fechas(semanas):
    return [_fecha(s) for s in semanas]


def _registrar(mensaje):
    print(f"[{time.strftime('%H:%M:%S')}] {mensaje}", flush=True)


if __name__ == "__main__":
    main()
