"""Protocolo de arranque en frío de películas (H2 y curva por estratos de historial).

H2 (propuesta): para películas sin historial, el modelo que combina el grafo con
metadatos de contenido supera a un recomendador basado sólo en contenido. La curva por
estratos responde a la pregunta del README: ¿cuántas interacciones necesita una película
nueva para que el grafo supere al contenido?

Para la semana w y un estrato de historial (ratings de la película antes de w):
- Candidatas: películas del estrato que reciben algún rating en w. Con el estrato 0 son
  "las películas que entran esa semana" (protocolo estándar de arranque en frío de
  ítems). Saber que una película recibe ratings en w es información de la semana w;
  todos los métodos rankean las mismas candidatas, así que la comparación es justa, pero
  los valores absolutos no son los de un sistema en producción (limitación declarada).
- Objetivos: aristas de w entre un usuario que regresa (con historia antes de w) y una
  candidata. Se evalúa a esos usuarios rankeando todas las candidatas que no han calificado.
Todo lo demás (grafo, atributos, contenido) usa sólo datos anteriores a w.
"""

import pandas as pd
import torch

from src import datos
from src.evaluacion import evaluar_semana
from src.protocolo import anotar_ablacion, fecha

ESTRATOS = {"0": (0, 0), "1-4": (1, 4), "5-19": (5, 19)}
KS_FRIO = (10, 20, 50)
ETAPA = "h2_frio"
DIR_H2 = datos.RAIZ / "resultados" / "h2"


def candidatas(grafo, semana, estrato):
    """Índices de las películas del estrato (ratings previos) que reciben algún rating en `semana`."""
    minimo, maximo = ESTRATOS[estrato]
    previos = grafo.popularidad(semana)  # ratings antes de la semana
    pelicula, _, semana_arista = grafo._por_pelicula
    en_la_semana = torch.zeros(grafo.n_peliculas, dtype=torch.bool)
    en_la_semana[pelicula[semana_arista == semana]] = True
    return torch.nonzero(en_la_semana & (previos >= minimo) & (previos <= maximo)).flatten()


def objetivos(grafo, semana, indices_candidatas):
    """(usuarios, películas, excluidas): aristas de la semana de usuarios que regresan hacia candidatas.

    `excluidas` cuenta las aristas hacia candidatas de usuarios que llegan esa semana.
    """
    usuario, pelicula, semana_arista = grafo._por_usuario
    es_candidata = torch.zeros(grafo.n_peliculas, dtype=torch.bool)
    es_candidata[indices_candidatas] = True
    en_la_semana = (semana_arista == semana) & es_candidata[pelicula]
    usuario, pelicula = usuario[en_la_semana], pelicula[en_la_semana]
    regresa = torch.from_numpy(grafo.semana_alta_usuario)[usuario] < semana
    return usuario[regresa], pelicula[regresa], int((~regresa).sum())


def evaluar_semanas_frio(grafo, semanas, puntuador_de_semana, metodo, estratos=tuple(ESTRATOS)):
    """Como protocolo.evaluar_semanas, por estrato. Devuelve (por_semana, por_usuario) con columna `estrato`."""
    resumenes, tablas = [], []
    for semana in semanas:
        adyacencias = grafo.adyacencias(semana)
        puntuar = puntuador_de_semana(semana, adyacencias)
        for estrato in estratos:
            indices = candidatas(grafo, semana, estrato)
            usuarios, peliculas, excluidas = objetivos(grafo, semana, indices)
            if len(usuarios) == 0:
                continue
            resumen, por_usuario = evaluar_semana(grafo, semana, adyacencias, puntuar, ks=KS_FRIO,
                                                  candidatas=indices, objetivos=(usuarios, peliculas, excluidas))
            resumenes.append({"semana": semana, "fecha": fecha(semana), "estrato": estrato, "candidatas": len(indices), **resumen})
            tablas.append(por_usuario.assign(estrato=estrato))
    por_semana, por_usuario = pd.DataFrame(resumenes), pd.concat(tablas, ignore_index=True)
    por_semana.insert(0, "metodo", metodo)
    por_usuario.insert(0, "metodo", metodo)
    return por_semana, por_usuario


def guardar_frio(por_semana, por_usuario, nombre, particion_, config, segundos):
    """Escribe resultados/h2/<partición>/<nombre>_{semanas.csv,usuarios.parquet} y una fila
    de la tabla de ablación por estrato (método "<nombre>__<estrato>")."""
    carpeta = DIR_H2 / particion_
    carpeta.mkdir(parents=True, exist_ok=True)
    por_semana.to_csv(carpeta / f"{nombre}_semanas.csv", index=False)
    por_usuario.to_parquet(carpeta / f"{nombre}_usuarios.parquet", index=False)
    for estrato, tabla in por_semana.groupby("estrato"):
        anotar_ablacion(ETAPA, f"{nombre}__{estrato}", config, tabla, particion_, segundos)
    return por_semana.groupby("estrato")[["recall@20", "ndcg@20"]].mean()
