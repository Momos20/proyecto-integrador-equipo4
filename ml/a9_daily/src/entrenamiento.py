"""Entrenamiento de GraphSAGE con el tiempo dentro del modelo (etapa 3), en GPU.

Protocolo (src/protocolo.py): los objetivos de entrenamiento son las `ventana` semanas
antes de la validación (2022). Cada paso toma una semana objetivo al azar, arma su
instantánea (aristas anteriores, con decaimiento opcional) y sus atributos semanales, y
aplica BPR. Para evaluar la semana w, los pesos quedan fijos y las representaciones se
recalculan con la instantánea y los atributos de w (actualización inductiva semanal).

Parada temprana por Recall@20 en 13 semanas de validación (una de cada 4); la
configuración final se reporta en las 52 semanas. Cada corrida parte de la
configuración de otra (`--desde`) y cambia una sola cosa (`--cambio clave=valor`),
y queda registrada en resultados/ablacion.csv.

Arranque en frío (H2, src/frio.py): con --frio, la parada temprana usa el Recall@20 del
estrato 0 (películas que entran esa semana) en 26 semanas de validación (una de cada 2),
y la evaluación final reporta los tres estratos. Los resultados van a resultados/h2/.

Uso, desde la raíz del proyecto:
    python -m src.entrenamiento --nombre A0_base
    python -m src.entrenamiento --nombre A1_atributos --desde A0_base --cambio atributos_semanales=true
    python -m src.entrenamiento --nombre A1_atributos --test     # una sola vez, con la configuración final
    python -m src.entrenamiento --frio --nombre F1 --desde A9_sin_id --cambio objetivos_nuevas=true
"""

import argparse
import copy
import json
import time

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F

from src import contenido, datos
from src.evaluacion import puntuar_con_embeddings
from src.frio import DIR_H2, ESTRATOS, ETAPA as ETAPA_FRIO, evaluar_semanas_frio, guardar_frio
from src.modelo import DosTorres, SAGEHeterogeneo
from src.protocolo import DISPOSITIVO, anotar_ablacion, evaluar_semanas, guardar, particion, registrar
from src.temporal import N_ATRIBUTOS_PELICULA, GrafoEnDispositivo

ETAPA = "3_graphsage"
DIR_GRAPHSAGE = datos.RAIZ / "resultados" / "graphsage"

# A0: el modelo del experimento 02 (estático) con el protocolo nuevo
BASE = {
    "modelo": "graphsage",       # graphsage | dos_torres (sólo contenido, sin grafo; H2)
    "contenido": [],             # grupos de src/contenido.py que se suman a géneros y año
    "objetivos_nuevas": False,   # entrenar también con películas que entran esa semana (H2)
    "dimension": 64,
    "capas": 2,
    "usar_id": True,
    "atributos_semanales": False,
    "vida_media": None,          # semanas; None = sin decaimiento
    "negativos": "uniforme",     # uniforme | mezcla_reciente | mezcla_historica (50 % uniformes)
    "ventana": 52,               # semanas objetivo de entrenamiento
    "optimizador": "adam",       # adam | adamw
    "tasa_aprendizaje": 0.01,
    "weight_decay": 0.0,
    "normalizar": False,         # LayerNorm entre capas
    "dropout": 0.0,
    "max_pasos": 3000,
    "evaluar_cada": 100,
    "paciencia": 5,              # evaluaciones sin mejorar antes de parar
    "max_positivos_por_paso": 20_000,
    "semilla": 0,
}
METRICA = "recall@20"


def crear_modelo(grafo, en_gpu, config):
    atributos = torch.cat([grafo.atributos_pelicula, contenido.matriz(config["contenido"], grafo.ids_pelicula)], dim=1)
    if config["modelo"] == "dos_torres":
        return DosTorres(atributos, config["dimension"], config["dropout"]).to(DISPOSITIVO)
    semanales = config["atributos_semanales"]
    return SAGEHeterogeneo(
        grafo.n_usuarios, grafo.n_peliculas, atributos, config["dimension"], config["capas"],
        n_semanales_usuario=en_gpu.n_atributos_usuario if semanales else 0,
        n_semanales_pelicula=N_ATRIBUTOS_PELICULA if semanales else 0,
        usar_id=config["usar_id"], normalizar=config["normalizar"], dropout=config["dropout"],
    ).to(DISPOSITIVO)


def representaciones(modelo, en_gpu, semana, config):
    """Embeddings de usuarios y películas para la semana, sólo con datos anteriores a ella."""
    adyacencias = en_gpu.adyacencias(semana, config["vida_media"])
    semanales = en_gpu.atributos(semana) if config["atributos_semanales"] else None
    return modelo(adyacencias, semanales)


def muestrear_negativos(en_gpu, semana, n, tipo):
    """Negativos uniformes entre las películas conocidas; las mezclas reemplazan la mitad
    por películas muestreadas en proporción a su popularidad (última semana o histórica)."""
    conocidas = en_gpu.peliculas_conocidas(semana)
    uniformes = conocidas[torch.randint(len(conocidas), (n,), device=DISPOSITIVO)]
    if tipo == "uniforme":
        return uniformes
    popularidad = en_gpu.popularidad(semana, 1 if tipo == "mezcla_reciente" else None)
    if popularidad.sum() == 0:
        return uniformes
    n_dificiles = n // 2
    dificiles = torch.multinomial(popularidad, n_dificiles, replacement=True)
    return torch.cat([uniformes[:n - n_dificiles], dificiles])


def paso_de_entrenamiento(modelo, optimizador, en_gpu, semana, config):
    usuarios, peliculas = en_gpu.objetivos(semana, incluir_nuevas=config["objetivos_nuevas"])
    if len(usuarios) == 0:
        return None
    if len(usuarios) > config["max_positivos_por_paso"]:
        muestra = torch.randperm(len(usuarios), device=DISPOSITIVO)[:config["max_positivos_por_paso"]]
        usuarios, peliculas = usuarios[muestra], peliculas[muestra]
    negativas = muestrear_negativos(en_gpu, semana, len(usuarios), config["negativos"])
    if config["objetivos_nuevas"]:
        # Un positivo en una película nueva compite contra otra película nueva de la misma
        # semana, como en la evaluación del estrato 0 (si no, "ser nueva" bastaría para ganar)
        nuevas = en_gpu.peliculas_nuevas(semana)
        es_nueva = en_gpu.semana_alta_pelicula[peliculas] == semana
        if es_nueva.any():
            negativas[es_nueva] = nuevas[torch.randint(len(nuevas), (int(es_nueva.sum()),), device=DISPOSITIVO)]

    z_usuario, z_pelicula = representaciones(modelo, en_gpu, semana, config)
    z = z_usuario[usuarios]
    perdida = -F.logsigmoid((z * z_pelicula[peliculas]).sum(1) - (z * z_pelicula[negativas]).sum(1)).mean()
    optimizador.zero_grad()
    perdida.backward()
    optimizador.step()
    return perdida.item()


def evaluar(modelo, grafo, en_gpu, semanas, config, nombre):
    """Evalúa con el protocolo: para cada semana, representaciones con su instantánea."""
    modelo.eval()

    @torch.no_grad()
    def puntuador(semana, _):
        z_usuario, z_pelicula = representaciones(modelo, en_gpu, semana, config)
        return puntuar_con_embeddings(z_usuario, z_pelicula)

    por_semana, por_usuario = evaluar_semanas(grafo, semanas, puntuador, nombre)
    modelo.train()
    return por_semana, por_usuario


def evaluar_frio(modelo, grafo, en_gpu, semanas, config, nombre, estratos=tuple(ESTRATOS)):
    """Como `evaluar`, con el protocolo de arranque en frío (src/frio.py)."""
    modelo.eval()

    @torch.no_grad()
    def puntuador(semana, _):
        z_usuario, z_pelicula = representaciones(modelo, en_gpu, semana, config)
        return puntuar_con_embeddings(z_usuario, z_pelicula)

    resultado = evaluar_semanas_frio(grafo, semanas, puntuador, nombre, estratos)
    modelo.train()
    return resultado


def entrenar(grafo, en_gpu, config, semana_fin, semanas_parada=None, pasos_fijos=None, nombre="", frio=False):
    """Entrena con objetivos en [semana_fin - ventana, semana_fin).

    Con `semanas_parada`, evalúa cada `evaluar_cada` pasos y se queda con el mejor estado
    (parada temprana; con `frio`, por el estrato 0). Con `pasos_fijos`, entrena exactamente
    esos pasos (para el test).
    Devuelve (modelo, curva, mejor_paso).
    """
    torch.manual_seed(config["semilla"])
    azar = np.random.default_rng(config["semilla"])
    modelo = crear_modelo(grafo, en_gpu, config)
    clase = torch.optim.AdamW if config["optimizador"] == "adamw" else torch.optim.Adam
    optimizador = clase(modelo.parameters(), lr=config["tasa_aprendizaje"], weight_decay=config["weight_decay"])

    inicio, curva, perdidas = time.time(), [], []
    mejor = {"valor": -1.0, "paso": 0, "estado": None}
    sin_mejorar, paso = 0, 0
    total = pasos_fijos or config["max_pasos"]
    while paso < total:
        semana = int(azar.integers(semana_fin - config["ventana"], semana_fin))
        perdida = paso_de_entrenamiento(modelo, optimizador, en_gpu, semana, config)
        if perdida is None:
            continue
        if not np.isfinite(perdida):
            raise RuntimeError(f"Pérdida no finita en el paso {paso + 1} (semana {semana})")
        perdidas.append(perdida)
        paso += 1
        if semanas_parada is None or paso % config["evaluar_cada"] != 0:
            continue

        if frio:
            por_semana, _ = evaluar_frio(modelo, grafo, en_gpu, semanas_parada, config, nombre, estratos=("0",))
        else:
            por_semana, _ = evaluar(modelo, grafo, en_gpu, semanas_parada, config, nombre)
        valor = por_semana[METRICA].mean()
        curva.append({"paso": paso, "perdida": float(np.mean(perdidas)), METRICA: valor,
                      "ndcg@20": por_semana["ndcg@20"].mean(), "segundos": round(time.time() - inicio)})
        perdidas = []
        registrar(f"  {nombre} paso {paso}: pérdida {curva[-1]['perdida']:.4f} | {METRICA} {valor:.4f} ndcg@20 {curva[-1]['ndcg@20']:.4f}")
        if valor > mejor["valor"]:
            mejor = {"valor": valor, "paso": paso, "estado": copy.deepcopy(modelo.state_dict())}
            sin_mejorar = 0
        else:
            sin_mejorar += 1
            if sin_mejorar >= config["paciencia"]:
                break
    if mejor["estado"] is not None:
        modelo.load_state_dict(mejor["estado"])
    return modelo, curva, mejor["paso"] or paso


def config_de(nombre):
    """Configuración registrada de una corrida anterior (etapa 3 o H2), completada con BASE.

    Las opciones que no existían cuando se hizo la corrida toman su valor de BASE, que es
    el que tenían de hecho (p. ej. A9 no usa contenido ni objetivos en películas nuevas).
    """
    tabla = pd.read_csv(datos.RAIZ / "resultados" / "ablacion.csv")
    tabla = tabla[tabla["particion"] == "validacion"]
    fila = tabla[((tabla["etapa"] == ETAPA) & (tabla["metodo"] == nombre))
                 | ((tabla["etapa"] == ETAPA_FRIO) & (tabla["metodo"] == f"{nombre}__0"))]
    if fila.empty:
        raise ValueError(f"No hay una corrida '{nombre}' en resultados/ablacion.csv")
    guardada = json.loads(fila.iloc[-1]["configuracion"])
    return {**BASE, **{k: v for k, v in guardada.items() if k in BASE}}


def aplicar_cambio(config, cambio):
    """`clave=valor`, con el valor en JSON (números, true/false, null) o como texto."""
    clave, valor = cambio.split("=", 1)
    if clave not in BASE:
        raise ValueError(f"'{clave}' no es un hiperparámetro. Opciones: {', '.join(BASE)}")
    try:
        config[clave] = json.loads(valor)
    except json.JSONDecodeError:
        config[clave] = valor
    return config


def main():
    from src.grafo import GrafoTemporal

    argumentos = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    argumentos.add_argument("--nombre", required=True)
    argumentos.add_argument("--desde", help="corrida de la que se copia la configuración")
    argumentos.add_argument("--cambio", nargs="+", default=[],
                            help="el único cambio respecto a --desde, como clave=valor (varias claves sólo si son un mismo cambio, p. ej. AdamW con weight decay)")
    argumentos.add_argument("--test", action="store_true", help="reentrenar con 2022 y evaluar en test (una vez)")
    argumentos.add_argument("--frio", action="store_true", help="protocolo de arranque en frío (H2): parada y evaluación por estratos")
    a = argumentos.parse_args()

    inicio = time.time()
    grafo = GrafoTemporal()
    en_gpu = GrafoEnDispositivo(grafo, DISPOSITIVO)
    semanas = particion(grafo)
    carpeta = (DIR_H2 if a.frio else DIR_GRAPHSAGE) / a.nombre
    carpeta.mkdir(parents=True, exist_ok=True)

    if a.test:
        config = config_de(a.nombre)
        mejor_paso = json.loads((carpeta / "validacion.json").read_text(encoding="utf-8"))["mejor_paso"]
        registrar(f"{a.nombre}: test. Reentrenamiento con objetivos hasta {semanas['test'][0]} durante {mejor_paso} pasos")
        modelo, _, _ = entrenar(grafo, en_gpu, config, semanas["test"][0], pasos_fijos=mejor_paso, nombre=a.nombre)
        if a.frio:
            por_semana, por_usuario = evaluar_frio(modelo, grafo, en_gpu, semanas["test"], config, a.nombre)
            resumen = guardar_frio(por_semana, por_usuario, a.nombre, "test", config, time.time() - inicio)
            registrar(f"{a.nombre} test:\n{resumen.to_string()}")
            return
        por_semana, por_usuario = evaluar(modelo, grafo, en_gpu, semanas["test"], config, a.nombre)
        guardar(por_semana, por_usuario, a.nombre, "test")
        anotar_ablacion(ETAPA, a.nombre, config, por_semana, "test", time.time() - inicio)
        registrar(f"{a.nombre} test: {METRICA} {por_semana[METRICA].mean():.4f} ndcg@20 {por_semana['ndcg@20'].mean():.4f}")
        return

    config = dict(BASE) if a.desde is None else config_de(a.desde)
    for cambio in a.cambio:
        config = aplicar_cambio(config, cambio)
    registro = {**config, "desde": a.desde, "cambio": " ".join(a.cambio) or None}
    registrar(f"{a.nombre}: desde {a.desde}, cambio {registro['cambio']}. Dispositivo {DISPOSITIVO}")

    modelo, curva, mejor_paso = entrenar(grafo, en_gpu, config, semanas["validacion"][0], nombre=a.nombre, frio=a.frio,
                                         semanas_parada=semanas["validacion"][::2 if a.frio else 4])
    pd.DataFrame(curva).to_csv(carpeta / "curva.csv", index=False)
    (carpeta / "validacion.json").write_text(json.dumps({"mejor_paso": mejor_paso, "config": registro}, indent=2, ensure_ascii=False), encoding="utf-8")
    torch.save(modelo.state_dict(), carpeta / "modelo.pt")
    if a.frio:
        por_semana, por_usuario = evaluar_frio(modelo, grafo, en_gpu, semanas["validacion"], config, a.nombre)
        resumen = guardar_frio(por_semana, por_usuario, a.nombre, "validacion", registro, time.time() - inicio)
        registrar(f"{a.nombre}: mejor paso {mejor_paso}. Validación (52 semanas) por estrato:\n{resumen.to_string()}\n"
                  f"{(time.time() - inicio) / 60:.1f} min")
        return
    por_semana, por_usuario = evaluar(modelo, grafo, en_gpu, semanas["validacion"], config, a.nombre)
    guardar(por_semana, por_usuario, a.nombre, "validacion")
    anotar_ablacion(ETAPA, a.nombre, registro, por_semana, "validacion", time.time() - inicio)
    registrar(f"{a.nombre}: mejor paso {mejor_paso}. Validación (52 semanas): {METRICA} {por_semana[METRICA].mean():.4f} "
              f"ndcg@20 {por_semana['ndcg@20'].mean():.4f} | {(time.time() - inicio) / 60:.1f} min")


if __name__ == "__main__":
    main()
