"""H2: arranque en frío de películas, con el protocolo de src/frio.py.

Métodos (todos rankean las mismas candidatas de cada estrato):
- Aleatoria.
- Popularidad reciente por género (respaldo de la propuesta): el puntaje de una película
  es el promedio, sobre sus géneros, de los ratings de la semana anterior a películas de
  ese género (cada rating reparte su peso entre los géneros de la película).
- GraphSAGE A9 tal como salió de la etapa 3 (géneros y año como único contenido).
- Coseno de contenido (sin entrenamiento): perfil del usuario = promedio del contenido
  (normalizado) de lo que ya calificó; puntaje = coseno con el contenido de la película.
- Ablación (`--ablacion`), con `python -m src.entrenamiento --frio`, una cosa a la vez y
  eligiendo por el Recall@20 del estrato 0 en validación:
    grafo + contenido: desde A9, + objetivos en películas nuevas, + sinopsis,
    + palabras clave, + ficha (personas, idioma, duración);
    sólo contenido: la mejor configuración anterior con modelo = dos_torres (todo igual
    salvo el grafo), con su mismo contenido y con todos los grupos.

Uso, desde la raíz del proyecto (sólo validación):
    python -m src.h2 --metodos aleatoria popularidad_genero A9_sin_id coseno
    python -m src.h2 --ablacion
    python -m src.h2 --semillas        # estabilidad de F4 vs T1 con 3 semillas (0, 1, 2)

Test (una sola vez; F4 y T1 con `python -m src.entrenamiento --frio --test` por semilla):
    python -m src.h2 --test --metodos aleatoria popularidad_genero coseno
    python -m src.h2 --comparar test
"""

import argparse
import subprocess
import sys
import time

import pandas as pd
import torch
import torch.nn.functional as F

from src import contenido, datos
from src.entrenamiento import config_de, crear_modelo, representaciones
from src.evaluacion import puntuar_con_embeddings
from src.frio import DIR_H2, ETAPA, evaluar_semanas_frio, guardar_frio
from src.grafo import CALIFICADA_POR
from src.lineas_base import aleatoria
from src.protocolo import DISPOSITIVO, particion, registrar
from src.temporal import GrafoEnDispositivo

GRUPOS_COSENO = ["sinopsis", "palabras_clave"]
TODO_EL_CONTENIDO = ["sinopsis", "palabras_clave", "ficha"]
GRAFO_CONTENIDO = [
    ("F1_objetivos_nuevas", ["objetivos_nuevas=true"]),
    ("F2_sinopsis", ['contenido=["sinopsis"]']),
    ("F3_palabras_clave", ['contenido=["sinopsis", "palabras_clave"]']),
    ("F4_ficha", [f"contenido={TODO_EL_CONTENIDO}".replace("'", '"')]),
]



def popularidad_por_genero(grafo):
    """Puntuador: popularidad de la semana anterior de los géneros de cada película."""
    generos = grafo.atributos_pelicula[:, :-2]  # multi-hot de movies.csv (sin año ni marca de año)
    por_genero_de_pelicula = generos / generos.sum(dim=1, keepdim=True).clamp(min=1)

    def puntuador(semana, _):
        ratings = grafo.popularidad(semana, semanas_atras=1)  # ratings de cada película en la semana anterior
        popularidad_genero = ratings @ por_genero_de_pelicula  # ratings repartidos por género
        puntajes = (por_genero_de_pelicula @ popularidad_genero).to(DISPOSITIVO)
        return lambda usuarios: puntajes.expand(len(usuarios), -1)
    return puntuador


def coseno(grafo, grupos=GRUPOS_COSENO):
    """Puntuador de contenido sin entrenamiento: coseno entre el perfil del usuario y la película."""
    vectores = F.normalize(contenido.matriz(list(grupos), grafo.ids_pelicula), dim=1).to(DISPOSITIVO)

    def puntuador(semana, adyacencias):
        historial = adyacencias[CALIFICADA_POR].to(DISPOSITIVO)  # aristas anteriores a la semana
        perfil = F.normalize(torch.sparse.mm(historial, vectores), dim=1)
        return lambda usuarios: perfil[usuarios.to(DISPOSITIVO)] @ vectores.T
    return puntuador


def graphsage_guardado(grafo, nombre):
    """Puntuador del GraphSAGE de la etapa 3 con sus pesos guardados (actualización inductiva semanal)."""
    config = config_de(nombre)
    en_gpu = GrafoEnDispositivo(grafo, DISPOSITIVO)
    modelo = crear_modelo(grafo, en_gpu, config)
    modelo.load_state_dict(torch.load(datos.RAIZ / "resultados" / "graphsage" / nombre / "modelo.pt", map_location=DISPOSITIVO))
    modelo.eval()

    @torch.no_grad()
    def puntuador(semana, _):
        return puntuar_con_embeddings(*representaciones(modelo, en_gpu, semana, config))
    return puntuador, config


def correr(nombre, config, puntuador, grafo, semanas, particion_="validacion"):
    inicio = time.time()
    por_semana, por_usuario = evaluar_semanas_frio(grafo, semanas, puntuador, nombre)
    resumen = guardar_frio(por_semana, por_usuario, nombre, particion_, config, time.time() - inicio)
    registrar(f"{nombre}: " + " | ".join(f"estrato {e}: recall@20 {f['recall@20']:.4f} ndcg@20 {f['ndcg@20']:.4f}"
                                         for e, f in resumen.iterrows()) + f" ({time.time() - inicio:.0f} s)")


def recall_frio(nombre):
    """Recall@20 del estrato 0 en validación de una corrida ya registrada (o None)."""
    tabla = pd.read_csv(datos.RAIZ / "resultados" / "ablacion.csv")
    fila = tabla[(tabla["etapa"] == ETAPA) & (tabla["metodo"] == f"{nombre}__0") & (tabla["particion"] == "validacion")]
    return None if fila.empty else float(fila.iloc[-1]["recall@20"])


def entrenar_frio(nombre, desde, cambios):
    """Corre (o reutiliza, si ya está en la tabla) `python -m src.entrenamiento --frio`."""
    if recall_frio(nombre) is None:
        comando = [sys.executable, "-W", "ignore", "-m", "src.entrenamiento", "--frio", "--nombre", nombre,
                   "--desde", desde, "--cambio", *cambios]
        DIR_H2.mkdir(parents=True, exist_ok=True)
        with open(DIR_H2 / f"registro_{nombre}.txt", "w", encoding="utf-8") as registro:
            subprocess.run(comando, check=True, stdout=registro, stderr=subprocess.STDOUT, cwd=datos.RAIZ)
    registrar(f"{nombre}: recall@20 estrato 0 = {recall_frio(nombre):.4f}")
    return recall_frio(nombre)


def ablacion():
    """Grafo + contenido (una cosa a la vez) y después sólo contenido con la misma configuración."""
    actual, mejor = "A9_sin_id", recall_frio("A9_sin_id")
    if mejor is None:
        raise SystemExit("Primero: python -m src.h2 --metodos A9_sin_id")
    for nombre, cambios in GRAFO_CONTENIDO:
        valor = entrenar_frio(nombre, actual, cambios)
        if valor > mejor:
            registrar(f"  se queda {nombre}: {mejor:.4f} -> {valor:.4f}")
            actual, mejor = nombre, valor
        else:
            registrar(f"  no mejora; sigue {actual} ({mejor:.4f})")
    registrar(f"Mejor grafo + contenido: {actual} ({mejor:.4f})")

    # Sólo contenido: idéntico a la mejor configuración salvo el grafo
    entrenar_frio("T1_dos_torres", actual, ["modelo=dos_torres"])
    if config_de(actual)["contenido"] != TODO_EL_CONTENIDO:
        entrenar_frio("T2_dos_torres_todo", "T1_dos_torres", [f"contenido={TODO_EL_CONTENIDO}".replace("'", '"')])


def estabilidad(modelo="F4_ficha", referencia="T1_dos_torres", semillas=(0, 1, 2)):
    """F4 vs T1 en validación, por semilla y con la métrica semanal promediada entre semillas.

    La semilla 0 es la corrida original; las demás se llaman <nombre>_s<semilla>.
    Escribe resultados/h2/estabilidad_{por_semilla,promedio}.csv.
    """
    from src.estadistica import comparar

    carpeta = DIR_H2 / "validacion"
    nombre = lambda base, semilla: base if semilla == 0 else f"{base}_s{semilla}"
    largo = pd.concat([pd.read_csv(carpeta / f"{nombre(base, semilla)}_semanas.csv").assign(metodo=etiqueta, semilla=semilla)
                       for base, etiqueta in ((modelo, "grafo"), (referencia, "contenido")) for semilla in semillas])
    filas = []
    for estrato, sub in largo.groupby("estrato"):
        for semilla in semillas:
            tabla = comparar(sub[sub["semilla"] == semilla], "grafo", ["contenido"], ["recall@20", "ndcg@20"])
            filas.append(tabla.assign(estrato=estrato, semilla=semilla))
    por_semilla = pd.concat(filas)
    promedio = largo.groupby(["estrato", "metodo", "semana"], as_index=False)[["recall@20", "ndcg@20"]].mean()
    promedio = pd.concat([comparar(sub, "grafo", ["contenido"], ["recall@20", "ndcg@20"]).assign(estrato=estrato)
                          for estrato, sub in promedio.groupby("estrato")])
    por_semilla.to_csv(DIR_H2 / "estabilidad_por_semilla.csv", index=False)
    promedio.to_csv(DIR_H2 / "estabilidad_promedio.csv", index=False)
    return por_semilla, promedio


SEMILLAS = (0, 1, 2)
MODELO_H2, REFERENCIA_H2 = "F4_ficha", "T1_dos_torres"
OTRAS_REFERENCIAS = {"coseno": "Sólo contenido: coseno", "popularidad_genero": "Popularidad por género", "aleatoria": "Aleatoria"}


def comparar_h2(particion_):
    """Contraste de H2 fijado antes de mirar el test.

    Grafo + contenido (F4) contra sólo contenido (T1), cada uno con la métrica semanal
    promediada entre las 3 semillas, y contra coseno, popularidad por género y aleatoria.
    Por estrato: Wilcoxon por semana, IC por bloques y Holm sobre {Recall@20, NDCG@20} × 4
    referencias. H2 es la comparación F4 vs T1 en el estrato 0.
    Escribe resultados/h2/{resumen,comparacion}_<partición>.csv.
    """
    from src.estadistica import comparar

    carpeta = DIR_H2 / particion_
    nombre = lambda base, semilla: base if semilla == 0 else f"{base}_s{semilla}"
    metricas = ["recall@10", "recall@20", "recall@50", "ndcg@20", "hitrate@20", "mrr"]
    tablas = []
    for base, etiqueta in ((MODELO_H2, "Grafo + contenido (F4)"), (REFERENCIA_H2, "Sólo contenido: dos torres (T1)")):
        semillas = pd.concat([pd.read_csv(carpeta / f"{nombre(base, s)}_semanas.csv") for s in SEMILLAS])
        tablas.append(semillas.groupby(["estrato", "semana"], as_index=False)[metricas].mean().assign(metodo=etiqueta))
    for archivo, etiqueta in OTRAS_REFERENCIAS.items():
        tablas.append(pd.read_csv(carpeta / f"{archivo}_semanas.csv")[["estrato", "semana", *metricas]].assign(metodo=etiqueta))
    largo = pd.concat(tablas)
    largo["estrato"] = largo["estrato"].astype(str)
    resumen = largo.groupby(["estrato", "metodo"])[metricas].mean().reset_index()
    referencias = ["Sólo contenido: dos torres (T1)", *OTRAS_REFERENCIAS.values()]
    comparacion = pd.concat([comparar(sub, "Grafo + contenido (F4)", referencias, ["recall@20", "ndcg@20"]).assign(estrato=estrato)
                             for estrato, sub in largo.groupby("estrato")])
    resumen.to_csv(DIR_H2 / f"resumen_{particion_}.csv", index=False)
    comparacion.to_csv(DIR_H2 / f"comparacion_{particion_}.csv", index=False)
    return resumen, comparacion


def main():
    from src.grafo import GrafoTemporal

    argumentos = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    argumentos.add_argument("--metodos", nargs="+", default=["aleatoria", "popularidad_genero", "A9_sin_id", "coseno"])
    argumentos.add_argument("--ablacion", action="store_true")
    argumentos.add_argument("--semillas", action="store_true")
    argumentos.add_argument("--test", action="store_true", help="correr --metodos en test (una vez)")
    argumentos.add_argument("--comparar", choices=["validacion", "test"], help="contraste de H2 en esa partición")
    leidos = argumentos.parse_args()
    if leidos.comparar:
        resumen, comparacion = comparar_h2(leidos.comparar)
        with pd.option_context("display.width", 250, "display.max_columns", 30, "display.float_format", "{:.4f}".format):
            print(resumen.to_string(index=False), "\n")
            print(comparacion[["estrato", "referencia", "metrica", "media_modelo", "media_referencia", "diferencia",
                               "ic_bajo", "ic_alto", "semanas_gana", "p", "p_holm", "significativa"]].to_string(index=False))
        return
    if leidos.ablacion:
        ablacion()
        return
    if leidos.semillas:
        columnas = ["estrato", "metrica", "media_modelo", "media_referencia", "diferencia", "ic_bajo", "ic_alto", "semanas_gana", "p", "p_holm"]
        por_semilla, promedio = estabilidad()
        with pd.option_context("display.width", 250, "display.float_format", "{:.4f}".format):
            print(por_semilla[["semilla"] + columnas].to_string(index=False), "\n")
            print(promedio[columnas].to_string(index=False))
        return
    metodos = leidos.metodos

    grafo = GrafoTemporal()
    particion_ = "test" if leidos.test else "validacion"
    semanas = particion(grafo)[particion_]
    registrar(f"H2, {particion_}: {len(semanas)} semanas. Dispositivo: {DISPOSITIVO}")
    for metodo in metodos:
        if metodo == "aleatoria":
            correr(metodo, {"semilla": 0}, aleatoria(grafo), grafo, semanas, particion_)
        elif metodo == "popularidad_genero":
            correr(metodo, {"semanas": 1}, popularidad_por_genero(grafo), grafo, semanas, particion_)
        elif metodo == "coseno":
            correr(metodo, {"contenido": GRUPOS_COSENO}, coseno(grafo), grafo, semanas, particion_)
        elif leidos.test:
            raise SystemExit("En test, los modelos entrenados se corren con: python -m src.entrenamiento --frio --test --nombre ...")
        else:
            puntuador, config = graphsage_guardado(grafo, metodo)
            correr(metodo, {"pesos_de": metodo, **config}, puntuador, grafo, semanas)


if __name__ == "__main__":
    main()
