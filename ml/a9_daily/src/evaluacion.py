"""Evaluación por semana: ranking de películas para los usuarios que regresan.

Para la semana w se rankean, para cada usuario con historia antes de w, todas las
películas conocidas antes de w que el usuario no ha calificado. Los aciertos son
las películas que calificó en la semana w (sin muestreo de negativos).

Métricas por usuario, para cada K de KS:
- recall@K: aciertos en el top K / películas que calificó en la semana.
- precision@K: aciertos en el top K / K.
- ndcg@K: DCG del top K / DCG ideal con min(objetivos, K) aciertos arriba.
- hitrate@K: 1 si hay al menos un acierto en el top K.
- mrr: 1 / posición del primer acierto en el ranking completo (sin cortar en K). Si
  hay empates con el mejor acierto, se usa la posición esperada al desempatar al azar.
Por semana, además, cobertura@K: fracción de las películas conocidas que aparece en
el top K de al menos un usuario.
"""

import math

import pandas as pd
import torch

from src.grafo import CALIFICADA_POR

K = 20  # K principal (criterio de H1)
KS = (10, 20, 50)


def evaluar_semana(grafo, semana_objetivo, adyacencias, puntuar, ks=KS, lote=512, candidatas=None, objetivos=None):
    """Métricas promedio de la semana y tabla con las métricas de cada usuario.

    `puntuar(usuarios)` devuelve una matriz [len(usuarios), n_peliculas] de puntajes,
    en CPU o en GPU; la evaluación ocurre en el dispositivo de esos puntajes.
    `adyacencias` es la instantánea de esa semana (aristas anteriores a ella).
    Por defecto se rankean las películas conocidas antes de la semana y los objetivos son
    los de `grafo.objetivos`. El protocolo de arranque en frío (src/frio.py) pasa sus
    propias `candidatas` (índices de películas) y `objetivos` (usuarios, películas, excluidas).
    Devuelve (resumen, por_usuario).
    """
    usuarios_objetivo, peliculas_objetivo, excluidas = objetivos if objetivos is not None else grafo.objetivos(semana_objetivo)
    usuarios = torch.unique(usuarios_objetivo)

    # Sólo se rankean las candidatas: por defecto, películas conocidas antes de la semana
    desconocida = torch.ones(grafo.n_peliculas, dtype=torch.bool)
    conocidas = grafo.peliculas_conocidas(semana_objetivo) if candidatas is None else candidatas
    desconocida[conocidas] = False

    historial = adyacencias[CALIFICADA_POR]  # filas = usuarios, columnas = películas ya calificadas
    inicio_fila, columnas = historial.crow_indices(), historial.col_indices()
    k_max = max(ks)

    tablas = []
    en_algun_top = {k: torch.zeros(grafo.n_peliculas, dtype=torch.bool) for k in ks}  # para la cobertura
    for inicio in range(0, len(usuarios), lote):
        lote_usuarios = usuarios[inicio:inicio + lote]
        posicion = torch.full((grafo.n_usuarios,), -1, dtype=torch.int64)
        posicion[lote_usuarios] = torch.arange(len(lote_usuarios))

        puntajes = puntuar(lote_usuarios).clone()
        dispositivo = puntajes.device
        puntajes[:, desconocida.to(dispositivo)] = -math.inf
        fila_hist, col_hist = historial_del_lote(lote_usuarios, inicio_fila, columnas)
        puntajes[fila_hist.to(dispositivo), col_hist.to(dispositivo)] = -math.inf

        es_objetivo = torch.zeros_like(puntajes, dtype=torch.bool)
        del_lote = posicion[usuarios_objetivo] >= 0
        es_objetivo[posicion[usuarios_objetivo[del_lote]].to(dispositivo), peliculas_objetivo[del_lote].to(dispositivo)] = True

        recomendadas = top(puntajes, k_max)
        aciertos = es_objetivo.gather(1, recomendadas).float()
        metricas = metricas_por_usuario(aciertos, es_objetivo.sum(dim=1), ks)
        metricas["mrr"] = 1 / posicion_primer_acierto(puntajes, es_objetivo)
        valida = torch.isfinite(puntajes.gather(1, recomendadas))  # con pocas candidatas, el top K incluye descartadas
        for k in ks:
            en_algun_top[k][recomendadas[:, :k][valida[:, :k]].cpu()] = True

        tabla = {"usuario": lote_usuarios.numpy(), "n_objetivos": es_objetivo.sum(dim=1).cpu().numpy(),
                 "n_historial": (inicio_fila[lote_usuarios + 1] - inicio_fila[lote_usuarios]).numpy()}
        tabla.update({nombre: valor.cpu().numpy() for nombre, valor in metricas.items()})
        tablas.append(pd.DataFrame(tabla))

    por_usuario = pd.concat(tablas, ignore_index=True)
    por_usuario.insert(0, "semana", semana_objetivo)
    resumen = {nombre: float(por_usuario[nombre].mean()) for nombre in nombres_metricas(ks)}
    for k in ks:
        resumen[f"cobertura@{k}"] = int(en_algun_top[k].sum()) / len(conocidas)
    resumen.update({"usuarios": len(usuarios), "aristas_objetivo": len(usuarios_objetivo), "aristas_excluidas": excluidas})
    return resumen, por_usuario


def nombres_metricas(ks=KS):
    """Nombres de las métricas por usuario, en el orden en que se reportan."""
    return [f"{m}@{k}" for m in ("recall", "precision", "ndcg", "hitrate") for k in ks] + ["mrr"]


def metricas_por_usuario(aciertos, n_objetivos, ks=KS):
    """Recall, Precision, NDCG y HitRate para cada K a partir de la matriz de aciertos del top.

    `aciertos[u, i]` = 1 si la película en la posición i+1 del usuario u es un objetivo.
    `n_objetivos[u]` = películas que el usuario calificó en la semana (≥ 1).
    """
    descuento = 1 / torch.log2(torch.arange(2, aciertos.shape[1] + 2, dtype=torch.float, device=aciertos.device))
    dcg_ideal_acumulado = torch.cumsum(descuento, dim=0)
    metricas = {}
    for k in ks:
        en_top = aciertos[:, :k].sum(dim=1)
        metricas[f"recall@{k}"] = en_top / n_objetivos
        metricas[f"precision@{k}"] = en_top / k
        dcg = (aciertos[:, :k] * descuento[:k]).sum(dim=1)
        metricas[f"ndcg@{k}"] = dcg / dcg_ideal_acumulado[n_objetivos.clamp(max=k) - 1]
        metricas[f"hitrate@{k}"] = (en_top > 0).float()
    return metricas


def top(puntajes, k):
    """Índices de las k películas con mayor puntaje; los empates van al índice menor.

    `torch.topk` desempata distinto en CPU y en GPU (y según k), lo que cambia el
    top 20 de la popularidad, cuyos puntajes son conteos enteros con empates.
    """
    return torch.sort(puntajes, dim=1, descending=True, stable=True).indices[:, :k].clone()  # copia: no retener el orden completo


def posicion_primer_acierto(puntajes, es_objetivo):
    """Posición (desde 1) del primer objetivo en el ranking completo de cada usuario.

    Con empates en el puntaje del mejor objetivo se toma la posición esperada al
    desempatar al azar: si e películas empatan y t de ellas son objetivos, el primer
    objetivo cae en promedio en la posición (e + 1) / (t + 1) dentro del empate.
    """
    mejor = puntajes.masked_fill(~es_objetivo, -math.inf).max(dim=1, keepdim=True).values
    por_encima = (puntajes > mejor).sum(dim=1)
    empatadas = (puntajes == mejor).sum(dim=1)
    objetivos_empatados = (es_objetivo & (puntajes == mejor)).sum(dim=1)
    return por_encima + (empatadas + 1) / (objetivos_empatados + 1)


def historial_del_lote(lote_usuarios, inicio_fila, columnas):
    """Pares (fila del lote, película) de todo lo que cada usuario del lote ya calificó."""
    desde, hasta = inicio_fila[lote_usuarios], inicio_fila[lote_usuarios + 1]
    cuantas = hasta - desde
    fila = torch.repeat_interleave(torch.arange(len(lote_usuarios)), cuantas)
    desplazamiento = torch.arange(int(cuantas.sum())) - torch.repeat_interleave(torch.cumsum(cuantas, 0) - cuantas, cuantas)
    return fila, columnas[torch.repeat_interleave(desde, cuantas) + desplazamiento]


def puntuar_por_popularidad(popularidad):
    """Mismo ranking para todos los usuarios: las películas con más ratings primero."""
    return lambda usuarios: popularidad.expand(len(usuarios), -1)


def puntuar_con_embeddings(z_usuario, z_pelicula):
    return lambda usuarios: z_usuario[usuarios.to(z_usuario.device)] @ z_pelicula.T
