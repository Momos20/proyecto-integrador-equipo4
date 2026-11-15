"""Líneas base de la propuesta con el protocolo de evaluación (src/protocolo.py).

- Aleatoria: puntajes uniformes, con semilla por semana.
- Popularidad de las últimas k semanas, k ∈ {1, 2, 4, 8, 12, 26} (k = 1 es la semana
  anterior); k se elige en validación por Recall@20. También la popularidad histórica.
- ItemKNN por coseno: similitud entre películas con ≥ 10 ratings, 100 vecinos por
  película, recalculada cada 4 semanas. Puntaje de una película = suma de sus
  similitudes con todo el historial del usuario (Sarwar et al., 2001).
- Factorización matricial BPR sin grafo (Rendle et al., 2009): embeddings de dimensión
  128 y producto punto, reentrenada desde cero cada 4 semanas con las aristas de las
  últimas `ventana` semanas y negativos uniformes entre las películas conocidas. La
  ventana (8/13/26/52/104) y las épocas se eligen en validación por Recall@20.
Los modelos que se recalculan cada 4 semanas usan sólo datos anteriores a la semana
del recálculo; el historial del usuario sí se actualiza cada semana.

Uso, desde la raíz del proyecto:
    python -m src.lineas_base                      # todas, en validación
    python -m src.lineas_base --metodos itemknn mf_bpr
    python -m src.lineas_base --resumen            # elige la mejor configuración de cada familia
    python -m src.lineas_base --test               # las elegidas, una vez en test
"""

import argparse
import math
import time

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from torch import nn

from src import datos
from src.evaluacion import historial_del_lote, top
from src.grafo import CALIFICADA_POR
from src.protocolo import DISPOSITIVO, anotar_ablacion, evaluar_semanas, guardar, particion, popularidad, registrar

SEMANAS_POPULARIDAD = (1, 2, 4, 8, 12, 26)
CADA_CUANTAS_SEMANAS = 4  # recálculo de ItemKNN y reentrenamiento de la MF-BPR

ITEMKNN = {"min_ratings": 10, "vecinos": 100}
MF_BPR = {
    "dimension": 128,
    "ventanas": (8, 13, 26, 52, 104),
    "epocas": (5, 10, 20, 40),  # se evalúa al terminar cada una de estas épocas
    "lote": 65_536,
    "tasa_aprendizaje": 0.01,
    "regularizacion": 1e-5,  # L2 sobre los embeddings del lote, como en BPR original
    "semilla": 0,
}


# ---------------------------------------------------------------- aleatoria y popularidad

def aleatoria(grafo, semilla=0):
    """Puntuador con puntajes uniformes; la semilla depende de la semana (reproducible)."""
    def puntuador(semana, _):
        generador = torch.Generator(device=DISPOSITIVO).manual_seed(semilla * 100_000 + semana)
        return lambda usuarios: torch.rand(len(usuarios), grafo.n_peliculas, generator=generador, device=DISPOSITIVO)
    return puntuador


# ---------------------------------------------------------------- ItemKNN

class ItemKNN:
    """Similitud coseno entre películas con los ratings anteriores a `semana_calculo`."""

    def __init__(self, grafo, semana_calculo, min_ratings=ITEMKNN["min_ratings"], vecinos=ITEMKNN["vecinos"]):
        historial = grafo.adyacencias(semana_calculo)[CALIFICADA_POR]  # usuarios × películas
        grado = torch.bincount(historial.col_indices(), minlength=grafo.n_peliculas)
        self.elegibles = torch.nonzero(grado >= min_ratings).flatten()
        self.n_peliculas = grafo.n_peliculas
        self.columna = torch.full((grafo.n_peliculas,), -1, dtype=torch.int64)  # película → columna elegible
        self.columna[self.elegibles] = torch.arange(len(self.elegibles))

        coocurrencias = _coocurrencias(historial, self.columna, len(self.elegibles))
        norma = coocurrencias.diagonal().clone().sqrt()  # √(ratings de cada película elegible)
        vecino, similitud = [], []
        for inicio in range(0, len(norma), 2048):
            bloque = coocurrencias[inicio:inicio + 2048] / norma[inicio:inicio + 2048, None] / norma[None, :]
            diagonal = torch.arange(len(bloque), device=bloque.device)
            bloque[diagonal, diagonal + inicio] = -1  # sin la misma película
            indices = top(bloque, vecinos)
            vecino.append(indices)
            similitud.append(bloque.gather(1, indices))
        del coocurrencias
        vecino, similitud = torch.cat(vecino), torch.cat(similitud).clamp(min=0)

        # S[i, j] = similitud de j como vecina de i. Se guarda Sᵀ (fila j) para puntuar con Sᵀ · historialᵀ.
        origen = torch.arange(len(norma), device=vecino.device).repeat_interleave(vecinos)
        self.similitud_t = torch.sparse_coo_tensor(
            torch.stack([vecino.flatten(), origen]), similitud.flatten(), (len(norma), len(norma))
        ).coalesce().to_sparse_csr()

    def puntuador(self, adyacencias):
        """Puntajes de la semana: historial del usuario (instantánea de esa semana) · S."""
        historial = adyacencias[CALIFICADA_POR]
        inicio_fila, columnas = historial.crow_indices(), historial.col_indices()

        def puntuar(usuarios):
            fila, pelicula = historial_del_lote(usuarios, inicio_fila, columnas)
            columna = self.columna[pelicula]
            elegible = columna >= 0
            perfil = torch.zeros(len(self.elegibles), len(usuarios), device=DISPOSITIVO)
            perfil[columna[elegible].to(DISPOSITIVO), fila[elegible].to(DISPOSITIVO)] = 1
            puntajes = torch.zeros(len(usuarios), self.n_peliculas, device=DISPOSITIVO)
            puntajes[:, self.elegibles.to(DISPOSITIVO)] = torch.sparse.mm(self.similitud_t, perfil).T
            return puntajes
        return puntuar


def _coocurrencias(historial, columna, n_elegibles, usuarios_por_bloque=2048):
    """Matriz densa C[i, j] = usuarios que calificaron i y j (películas elegibles), en GPU.

    Se multiplica por bloques de usuarios en float16: con ≤ 2048 usuarios por bloque
    los conteos son enteros ≤ 2048, que float16 representa exactos; se acumulan en float32.
    """
    inicio_fila, columnas = historial.crow_indices(), columna[historial.col_indices()]
    coocurrencias = torch.zeros(n_elegibles, n_elegibles, device=DISPOSITIVO)
    n_usuarios = len(inicio_fila) - 1
    for inicio in range(0, n_usuarios, usuarios_por_bloque):
        fin = min(inicio + usuarios_por_bloque, n_usuarios)
        desde, hasta = int(inicio_fila[inicio]), int(inicio_fila[fin])
        fila = torch.repeat_interleave(torch.arange(fin - inicio), inicio_fila[inicio + 1:fin + 1] - inicio_fila[inicio:fin])
        col = columnas[desde:hasta]
        elegible = col >= 0
        bloque = torch.zeros(fin - inicio, n_elegibles, dtype=torch.float16, device=DISPOSITIVO)
        bloque[fila[elegible].to(DISPOSITIVO), col[elegible].to(DISPOSITIVO)] = 1
        for i in range(0, n_elegibles, 4096):
            coocurrencias[i:i + 4096] += (bloque[:, i:i + 4096].T @ bloque).float()
    return coocurrencias


def semana_de_recalculo(semana, primera_semana):
    """Última semana de recálculo ≤ `semana`: primera_semana, +4, +8, ... El modelo usa datos < esa semana."""
    return primera_semana + (semana - primera_semana) // CADA_CUANTAS_SEMANAS * CADA_CUANTAS_SEMANAS


def itemknn(grafo, semanas):
    """Puntuador de ItemKNN que recalcula la similitud cada CADA_CUANTAS_SEMANAS semanas."""
    modelo = {"semana": None, "knn": None}

    def puntuador(semana, adyacencias):
        calculo = semana_de_recalculo(semana, semanas[0])
        if modelo["semana"] != calculo:
            modelo.update(semana=calculo, knn=None)
            torch.cuda.empty_cache()
            modelo["knn"] = ItemKNN(grafo, calculo)
        return modelo["knn"].puntuador(adyacencias)
    return puntuador


# ---------------------------------------------------------------- MF-BPR

class FactorizacionBPR(nn.Module):
    def __init__(self, n_usuarios, n_peliculas, dimension):
        super().__init__()
        self.usuario = nn.Embedding(n_usuarios, dimension)
        self.pelicula = nn.Embedding(n_peliculas, dimension)
        nn.init.normal_(self.usuario.weight, std=0.01)
        nn.init.normal_(self.pelicula.weight, std=0.01)


def entrenar_mf(grafo, semana_corte, ventana, epocas_a_guardar, config=MF_BPR):
    """Entrena una MF-BPR con las aristas de [semana_corte - ventana, semana_corte).

    Devuelve {épocas: (embeddings de usuario, embeddings de película)} para cada valor
    de `epocas_a_guardar`, y la pérdida promedio de la última época.
    """
    torch.manual_seed(config["semilla"])
    usuarios, peliculas = (t.to(DISPOSITIVO) for t in grafo.aristas(semana_corte - ventana, semana_corte))
    conocidas = grafo.peliculas_conocidas(semana_corte).to(DISPOSITIVO)
    modelo = FactorizacionBPR(grafo.n_usuarios, grafo.n_peliculas, config["dimension"]).to(DISPOSITIVO)
    optimizador = torch.optim.Adam(modelo.parameters(), lr=config["tasa_aprendizaje"])

    guardados, perdida_epoca = {}, math.nan
    for epoca in range(1, max(epocas_a_guardar) + 1):
        orden = torch.randperm(len(usuarios), device=DISPOSITIVO)
        perdidas = []
        for inicio in range(0, len(orden), config["lote"]):
            lote = orden[inicio:inicio + config["lote"]]
            u = modelo.usuario(usuarios[lote])
            p = modelo.pelicula(peliculas[lote])
            n = modelo.pelicula(conocidas[torch.randint(len(conocidas), (len(lote),), device=DISPOSITIVO)])
            perdida = -F.logsigmoid((u * p).sum(1) - (u * n).sum(1)).mean()
            perdida = perdida + config["regularizacion"] * (u.square().sum(1) + p.square().sum(1) + n.square().sum(1)).mean()
            optimizador.zero_grad()
            perdida.backward()
            optimizador.step()
            perdidas.append(perdida.item())
        perdida_epoca = float(np.mean(perdidas))
        if epoca in epocas_a_guardar:
            guardados[epoca] = (modelo.usuario.weight.detach().clone(), modelo.pelicula.weight.detach().clone())
    return guardados, perdida_epoca, len(usuarios)


def evaluar_mf(grafo, semanas, ventana, config=MF_BPR):
    """Evalúa la MF-BPR reentrenada cada 4 semanas, para cada número de épocas de la rejilla.

    Devuelve {épocas: (por_semana, por_usuario)}.
    """
    resultados = {epocas: ([], []) for epocas in config["epocas"]}
    for inicio in range(0, len(semanas), CADA_CUANTAS_SEMANAS):
        bloque = semanas[inicio:inicio + CADA_CUANTAS_SEMANAS]
        t = time.time()
        guardados, perdida, n_aristas = entrenar_mf(grafo, bloque[0], ventana, config["epocas"], config)
        for epocas, (z_usuario, z_pelicula) in guardados.items():
            puntuador = lambda semana, _, zu=z_usuario, zp=z_pelicula: (lambda usuarios: zu[usuarios.to(DISPOSITIVO)] @ zp.T)
            por_semana, por_usuario = evaluar_semanas(grafo, bloque, puntuador, f"mf_bpr_v{ventana}_e{epocas}")
            resultados[epocas][0].append(por_semana)
            resultados[epocas][1].append(por_usuario)
        registrar(f"  MF-BPR ventana {ventana}, reentrenamiento en {bloque[0]}: {n_aristas:,} aristas, "
                  f"pérdida final {perdida:.4f}, {time.time() - t:.0f} s")
    return {epocas: (pd.concat(s, ignore_index=True), pd.concat(u, ignore_index=True)) for epocas, (s, u) in resultados.items()}


# ---------------------------------------------------------------- corridas

def correr(nombre, config, puntuador, grafo, semanas, etapa="2_lineas_base", particion_="validacion"):
    inicio = time.time()
    por_semana, por_usuario = evaluar_semanas(grafo, semanas, puntuador, nombre)
    guardar(por_semana, por_usuario, nombre, particion_)
    anotar_ablacion(etapa, nombre, config, por_semana, particion_, time.time() - inicio)
    registrar(f"{nombre}: recall@20 {por_semana['recall@20'].mean():.4f} ndcg@20 {por_semana['ndcg@20'].mean():.4f} ({time.time() - inicio:.0f} s)")


def resumen_validacion(metrica_seleccion="recall@20"):
    """Elige la mejor configuración de cada familia en validación y compara contra la más fuerte.

    Escribe resultados/lineas_base/{resumen_validacion,comparacion_validacion}.csv.
    """
    from src.estadistica import bootstrap_media, comparar
    from src.protocolo import DIR_RESULTADOS

    carpeta = DIR_RESULTADOS / "validacion"
    familias = {
        "Aleatoria": ["aleatoria"],
        "Popularidad histórica": ["popularidad_historica"],
        "Popularidad semana anterior": ["popularidad_reciente_1"],
        "Popularidad últimas k semanas": [f"popularidad_reciente_{k}" for k in SEMANAS_POPULARIDAD],
        "ItemKNN": ["itemknn"],
        "MF-BPR": [f"mf_bpr_v{v}_e{e}" for v in MF_BPR["ventanas"] for e in MF_BPR["epocas"]],
    }
    por_semana = {m: pd.read_csv(carpeta / f"{m}_semanas.csv") for ms in familias.values() for m in ms}
    filas, elegidos = [], {}
    for familia, metodos in familias.items():
        elegido = max(metodos, key=lambda m: por_semana[m][metrica_seleccion].mean())
        elegidos[familia] = elegido
        tabla = por_semana[elegido]
        fila = {"familia": familia, "configuracion": elegido}
        for metrica in ("recall@10", "recall@20", "recall@50", "ndcg@20", "precision@20", "hitrate@20", "mrr", "cobertura@20"):
            fila[metrica] = tabla[metrica].mean()
        for metrica in ("recall@20", "ndcg@20"):
            fila[f"ic_{metrica}"] = "[{:.4f}, {:.4f}]".format(*bootstrap_media(tabla[metrica]))
        filas.append(fila)
    resumen = pd.DataFrame(filas)

    # Comparación pareada por semana: la línea base más fuerte contra las demás (una familia de Holm)
    distintas = {}  # familia → configuración, sin repetir configuraciones (k = 1 es la semana anterior)
    for familia, elegido in elegidos.items():
        if elegido not in distintas.values():
            distintas[familia] = elegido
    largo = pd.concat([por_semana[m].assign(metodo=familia) for familia, m in distintas.items()])
    mejor = max(distintas, key=lambda f: por_semana[distintas[f]][metrica_seleccion].mean())
    otras = [f for f in distintas if f != mejor]
    comparacion = comparar(largo, mejor, otras, ["recall@20", "ndcg@20"])

    salida = datos.RAIZ / "resultados" / "lineas_base"
    salida.mkdir(parents=True, exist_ok=True)
    resumen.to_csv(salida / "resumen_validacion.csv", index=False)
    comparacion.to_csv(salida / "comparacion_validacion.csv", index=False)
    return resumen, comparacion


def correr_test(grafo):
    """Las líneas base elegidas en validación (resumen_validacion), una vez sobre las 40 semanas de test."""
    semanas = particion(grafo)["test"]
    elegidas = list(dict.fromkeys(resumen_validacion()[0]["configuracion"]))  # sin repetir (k = 1)
    registrar(f"Test: {len(semanas)} semanas. Configuraciones elegidas en validación: {', '.join(elegidas)}")
    for nombre in elegidas:
        if nombre == "aleatoria":
            correr(nombre, {"semilla": 0}, aleatoria(grafo), grafo, semanas, particion_="test")
        elif nombre == "popularidad_historica":
            correr(nombre, {"semanas": "todas"}, popularidad(grafo), grafo, semanas, particion_="test")
        elif nombre.startswith("popularidad_reciente_"):
            k = int(nombre.rsplit("_", 1)[1])
            correr(nombre, {"semanas": k}, popularidad(grafo, k), grafo, semanas, particion_="test")
        elif nombre == "itemknn":
            correr(nombre, {**ITEMKNN, "recalculo_cada": CADA_CUANTAS_SEMANAS}, itemknn(grafo, semanas), grafo, semanas, particion_="test")
        elif nombre.startswith("mf_bpr_v"):
            ventana, epocas = (int(x) for x in nombre[len("mf_bpr_v"):].split("_e"))
            inicio = time.time()
            config = {**MF_BPR, "epocas": (epocas,)}
            por_semana, por_usuario = evaluar_mf(grafo, semanas, ventana, config)[epocas]
            guardar(por_semana, por_usuario, nombre, "test")
            config_registro = {**{k: v for k, v in MF_BPR.items() if k not in ("ventanas", "epocas")},
                               "ventana": ventana, "epocas": epocas, "reentrenamiento_cada": CADA_CUANTAS_SEMANAS}
            anotar_ablacion("2_lineas_base", nombre, config_registro, por_semana, "test", time.time() - inicio)
            registrar(f"{nombre}: recall@20 {por_semana['recall@20'].mean():.4f} ndcg@20 {por_semana['ndcg@20'].mean():.4f}")
        else:
            raise ValueError(f"Configuración desconocida: {nombre}")


def main():
    from src.grafo import GrafoTemporal

    argumentos = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    argumentos.add_argument("--metodos", nargs="+", default=["aleatoria", "popularidad", "itemknn", "mf_bpr"])
    argumentos.add_argument("--resumen", action="store_true", help="sólo resumir las corridas ya guardadas")
    argumentos.add_argument("--ventanas", nargs="+", type=int, default=None, help="ventanas de la MF-BPR (por defecto, todas)")
    argumentos.add_argument("--test", action="store_true", help="correr en test (una vez) las configuraciones elegidas en validación")
    argumentos_leidos = argumentos.parse_args()
    if argumentos_leidos.resumen:
        resumen, comparacion = resumen_validacion()
        with pd.option_context("display.width", 250, "display.max_columns", 30, "display.float_format", "{:.4f}".format):
            print(resumen.to_string(index=False), "\n")
            print(comparacion.to_string(index=False))
        return
    metodos = argumentos_leidos.metodos

    grafo = GrafoTemporal()
    if argumentos_leidos.test:
        correr_test(grafo)
        return
    semanas = particion(grafo)["validacion"]
    registrar(f"Validación: {len(semanas)} semanas. Dispositivo: {DISPOSITIVO}")

    if "aleatoria" in metodos:
        correr("aleatoria", {"semilla": 0}, aleatoria(grafo), grafo, semanas)
    if "popularidad" in metodos:
        correr("popularidad_historica", {"semanas": "todas"}, popularidad(grafo), grafo, semanas)
        for k in SEMANAS_POPULARIDAD:
            correr(f"popularidad_reciente_{k}", {"semanas": k}, popularidad(grafo, k), grafo, semanas)
    if "itemknn" in metodos:
        correr("itemknn", {**ITEMKNN, "recalculo_cada": CADA_CUANTAS_SEMANAS}, itemknn(grafo, semanas), grafo, semanas)
    if "mf_bpr" in metodos:
        for ventana in argumentos_leidos.ventanas or MF_BPR["ventanas"]:
            inicio = time.time()
            for epocas, (por_semana, por_usuario) in evaluar_mf(grafo, semanas, ventana).items():
                nombre = f"mf_bpr_v{ventana}_e{epocas}"
                config = {**{k: v for k, v in MF_BPR.items() if k not in ("ventanas", "epocas")},
                          "ventana": ventana, "epocas": epocas, "reentrenamiento_cada": CADA_CUANTAS_SEMANAS}
                guardar(por_semana, por_usuario, nombre, "validacion")
                anotar_ablacion("2_lineas_base", nombre, config, por_semana, "validacion", time.time() - inicio)
                registrar(f"{nombre}: recall@20 {por_semana['recall@20'].mean():.4f} ndcg@20 {por_semana['ndcg@20'].mean():.4f}")


if __name__ == "__main__":
    main()
