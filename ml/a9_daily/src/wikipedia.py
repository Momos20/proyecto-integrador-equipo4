"""Validación externa con las visitas de Wikipedia (análisis adicional, después del test).

MovieLens registra ratings, no vistas. Las visitas semanales al artículo de cada película
en Wikipedia en inglés son una medida externa de su popularidad. Aquí sólo se usan para
evaluar: no entran al modelo ni cambian nada de A9.

Dos preguntas, en las semanas de validación (2022) y test (2023):
1. ¿MovieLens refleja la popularidad real? Correlación de Spearman, semana a semana, entre
   los ratings de cada película en MovieLens y sus visitas en Wikipedia en la misma semana.
2. ¿A9 expone a los usuarios a lo que está en boga? Para la semana w, de las K películas
   candidatas con más visitas en Wikipedia, qué fracción está entre las K a las que A9 más
   expone (número de usuarios que regresan esa semana con la película en su top 20).
   Se compara con dos rankings globales: la popularidad de la semana anterior en MovieLens
   (la línea base de H1) y las visitas en Wikipedia de la semana anterior (referencia de
   qué tan predecible es la semana). Candidatas: películas con artículo y conocidas en
   MovieLens antes de w, como en el protocolo.

Películas: las que tienen al menos un rating en las semanas de validación o test. El
artículo se busca en Wikidata por el imdbId de links.csv (propiedad P345). Las visitas son
de usuarios (sin bots) al título exacto del artículo; las que llegan por redirecciones no
se cuentan. Las recomendaciones usan los pesos de resultados/graphsage/A9_sin_id/modelo.pt
(corrida de validación), igual que la página de resultados de A9.

Uso, desde la raíz del proyecto:
    python -m src.wikipedia --descargar   # artículos y visitas a data/wikipedia/ (~30 min; retoma si se corta)
    python -m src.wikipedia               # análisis a resultados/wikipedia/ (CPU, ~15 min)

Datos de visitas: Wikimedia Foundation, CC0.
"""

import argparse
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import torch
from scipy import stats

from src import datos
from src.evaluacion import historial_del_lote, top
from src.grafo import CALIFICADA_POR
from src.protocolo import fecha, particion, registrar

DIR_WIKI = datos.RAIZ / "data" / "wikipedia"
DIR_VISITAS = DIR_WIKI / "visitas"  # un JSON {día: visitas} por película (caché)
SALIDA = datos.RAIZ / "resultados" / "wikipedia"
AGENTE = "proyecto-integrador-cod/1.0 (https://github.com/pruebas-droid/proyecto-integrador-cod)"  # Wikimedia pide identificarse
URL_SPARQL = "https://query.wikidata.org/sparql"
URL_VISITAS = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{}/daily/{}/{}"
DESDE, HASTA = "2021-12-27", "2023-10-08"  # una semana antes de la validación hasta el fin del test
IMDB_POR_CONSULTA = 200
PETICIONES_POR_SEGUNDO = 25  # por debajo del límite de la API de Wikimedia
HILOS = 8
K = 100        # tamaño de los rankings que se comparan en la pregunta 2
K_USUARIO = 20  # top de cada usuario con el que se mide la exposición
N_EJEMPLOS = 5  # películas con más visitas en test, para las series de ejemplo


# ---------- descarga ----------

def _pedir(url, datos_post=None, intentos=5, espera=None):
    """GET (o POST con `datos_post`) con reintentos ante 429 y errores de red. None si es 404."""
    for intento in range(intentos):
        if espera is not None:
            espera()
        peticion = urllib.request.Request(url, data=datos_post, headers={"User-Agent": AGENTE, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(peticion, timeout=60) as respuesta:
                return json.load(respuesta)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if error.code == 429:
                time.sleep(float(error.headers.get("Retry-After", 5)))
                continue
            time.sleep(2 ** intento)
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2 ** intento)
    raise RuntimeError(f"Sin respuesta después de {intentos} intentos: {url[:120]}")


def consulta_sparql(imdb_ids):
    """Consulta de Wikidata: artículo de Wikipedia en inglés de cada imdbId (tt...)."""
    valores = " ".join(f'"{i}"' for i in imdb_ids)
    return ("SELECT ?imdb ?articulo WHERE { VALUES ?imdb { " + valores + " } "
            "?item wdt:P345 ?imdb . ?articulo schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . }")


def leer_sparql(respuesta):
    """{imdbId: título del artículo}. Si un imdbId tiene varios, se queda el primero en orden alfabético."""
    articulos = {}
    for fila in respuesta["results"]["bindings"]:
        titulo = urllib.parse.unquote(fila["articulo"]["value"].split("/wiki/", 1)[1])
        imdb = fila["imdb"]["value"]
        articulos[imdb] = min(articulos.get(imdb, titulo), titulo)
    return articulos


def peliculas_evaluadas():
    """movieId e imdbId (tt...) de las películas con algún rating en validación o test."""
    ratings = datos.cargar("ratings", columnas=["movieId", "timestamp"])
    semana = datos.semana(ratings["timestamp"].to_numpy())
    desde = datos.semana(int(pd.Timestamp("2022-01-03").timestamp()))
    hasta = datos.semana(int(pd.Timestamp(HASTA).timestamp()))
    ids = np.unique(ratings["movieId"].to_numpy()[(semana >= desde) & (semana <= hasta)])
    links = datos.cargar("links")[["movieId", "imdbId"]]
    links = links[links["movieId"].isin(ids) & links["imdbId"].notna()]
    return links.assign(imdbId="tt" + links["imdbId"].astype(str))


def buscar_articulos():
    """data/wikipedia/articulos.csv: movieId, imdbId y título del artículo (sólo las que tienen)."""
    peliculas = peliculas_evaluadas()
    imdb = peliculas["imdbId"].tolist()
    articulos = {}
    for inicio in range(0, len(imdb), IMDB_POR_CONSULTA):
        consulta = consulta_sparql(imdb[inicio:inicio + IMDB_POR_CONSULTA])
        cuerpo = urllib.parse.urlencode({"query": consulta, "format": "json"}).encode()
        articulos.update(leer_sparql(_pedir(URL_SPARQL, datos_post=cuerpo)))
        time.sleep(1)  # Wikidata limita el tiempo de consulta por minuto
    tabla = peliculas.assign(articulo=peliculas["imdbId"].map(articulos)).dropna(subset=["articulo"])
    DIR_WIKI.mkdir(parents=True, exist_ok=True)
    tabla.to_csv(DIR_WIKI / "articulos.csv", index=False)
    registrar(f"{len(tabla):,} de {len(peliculas):,} películas tienen artículo en Wikipedia en inglés")


def url_visitas(articulo):
    titulo = urllib.parse.quote(articulo.replace(" ", "_"), safe="")  # también codifica "/" del título
    return URL_VISITAS.format(titulo, DESDE.replace("-", ""), HASTA.replace("-", ""))


def leer_visitas(respuesta):
    """{AAAA-MM-DD: visitas} de la respuesta de la API (vacío si no hay datos)."""
    if respuesta is None:
        return {}
    return {f"{i['timestamp'][:4]}-{i['timestamp'][4:6]}-{i['timestamp'][6:8]}": int(i["views"]) for i in respuesta["items"]}


def descargar_visitas():
    articulos = pd.read_csv(DIR_WIKI / "articulos.csv")
    DIR_VISITAS.mkdir(parents=True, exist_ok=True)
    faltan = [(m, a) for m, a in zip(articulos["movieId"], articulos["articulo"]) if not (DIR_VISITAS / f"{m}.json").exists()]
    registrar(f"{len(articulos):,} artículos; faltan {len(faltan):,}")
    candado, siguiente, hechos, inicio = threading.Lock(), [time.monotonic()], [0], time.time()

    def esperar_turno():
        with candado:
            ahora = time.monotonic()
            espera = max(0.0, siguiente[0] - ahora)
            siguiente[0] = max(ahora, siguiente[0]) + 1 / PETICIONES_POR_SEGUNDO
        time.sleep(espera)

    def uno(par):
        movie_id, articulo = par
        visitas = leer_visitas(_pedir(url_visitas(articulo), espera=esperar_turno))
        (DIR_VISITAS / f"{movie_id}.json").write_text(json.dumps(visitas), encoding="utf-8")
        hechos[0] += 1
        if hechos[0] % 2000 == 0:
            registrar(f"  {hechos[0]:,} de {len(faltan):,} ({time.time() - inicio:.0f} s)")

    with ThreadPoolExecutor(HILOS) as hilos:
        list(hilos.map(uno, faltan))
    consolidar()


def visitas_por_semana(visitas_diarias):
    """{semana: visitas} sumando los días de cada semana (lunes a domingo, como datos.semana)."""
    semanales = {}
    for dia, visitas in visitas_diarias.items():
        semana = int(datos.semana(int(pd.Timestamp(dia).timestamp())))
        semanales[semana] = semanales.get(semana, 0) + visitas
    return semanales


def consolidar():
    """data/wikipedia/visitas_semanales.parquet: movieId, semana, visitas (sólo semanas completas del periodo)."""
    articulos = pd.read_csv(DIR_WIKI / "articulos.csv")
    filas = []
    for movie_id in articulos["movieId"]:
        diarias = json.loads((DIR_VISITAS / f"{movie_id}.json").read_text(encoding="utf-8"))
        filas += [(movie_id, s, v) for s, v in visitas_por_semana(diarias).items()]
    tabla = pd.DataFrame(filas, columns=["movieId", "semana", "visitas"])
    tabla.to_parquet(DIR_WIKI / "visitas_semanales.parquet", index=False)
    registrar(f"{tabla['movieId'].nunique():,} películas con visitas; {len(tabla):,} filas película-semana")


# ---------- análisis ----------

def exposicion(grafo, semana, adyacencias, puntuar, k=K_USUARIO, lote=512):
    """Cuántos usuarios que regresan en `semana` tienen cada película en su top k.

    Igual que en la evaluación: sólo películas conocidas antes de la semana y que el
    usuario no ha calificado. Devuelve un tensor [n_peliculas].
    """
    usuarios = torch.unique(grafo.objetivos(semana)[0])
    desconocida = torch.ones(grafo.n_peliculas, dtype=torch.bool)
    desconocida[grafo.peliculas_conocidas(semana)] = False
    historial = adyacencias[CALIFICADA_POR]
    inicio_fila, columnas = historial.crow_indices(), historial.col_indices()
    conteo = torch.zeros(grafo.n_peliculas, dtype=torch.int64)
    for inicio in range(0, len(usuarios), lote):
        lote_usuarios = usuarios[inicio:inicio + lote]
        puntajes = puntuar(lote_usuarios).clone()
        puntajes[:, desconocida] = -torch.inf
        fila, columna = historial_del_lote(lote_usuarios, inicio_fila, columnas)
        puntajes[fila, columna] = -torch.inf
        recomendadas = top(puntajes, k)
        validas = torch.isfinite(puntajes.gather(1, recomendadas))
        conteo += torch.bincount(recomendadas[validas], minlength=grafo.n_peliculas)
    return conteo


def coincidencia(puntaje, referencia, k=K):
    """Fracción de las k películas con más `referencia` que también están entre las k con más `puntaje`.

    Ambos son arreglos sobre las mismas películas candidatas. Los empates se rompen por
    índice (el menor primero), como en `evaluacion.top`.
    """
    k = min(k, len(referencia))
    arriba = lambda x: set(np.argsort(-np.asarray(x, dtype=float), kind="stable")[:k])
    return len(arriba(puntaje) & arriba(referencia)) / k


def analizar():
    from src.entrenamiento import config_de, crear_modelo, representaciones
    from src.evaluacion import puntuar_con_embeddings
    from src.grafo import GrafoTemporal
    from src.resultados_a9 import CARPETA_A9, NOMBRE
    from src.temporal import GrafoEnDispositivo

    inicio = time.time()
    cpu = torch.device("cpu")
    grafo = GrafoTemporal()
    en_cpu = GrafoEnDispositivo(grafo, cpu)
    config = config_de(NOMBRE)
    modelo = crear_modelo(grafo, en_cpu, config).to(cpu)
    modelo.load_state_dict(torch.load(CARPETA_A9 / "modelo.pt", map_location=cpu))
    modelo.eval()

    semanas = particion(grafo)
    primera = semanas["validacion"][0] - 1  # la semana anterior a la validación también se usa
    indice = pd.Index(grafo.ids_pelicula)
    con_articulo = np.unique(indice.get_indexer(pd.read_csv(DIR_WIKI / "articulos.csv")["movieId"]))
    visitas = pd.read_parquet(DIR_WIKI / "visitas_semanales.parquet")
    visitas = visitas[visitas["semana"].between(primera, semanas["test"][-1])]
    # visitas_de[:, s - primera] = visitas de cada película en la semana s
    visitas_de = np.zeros((grafo.n_peliculas, semanas["test"][-1] - primera + 1), dtype=np.int64)
    visitas_de[indice.get_indexer(visitas["movieId"]), visitas["semana"].to_numpy() - primera] = visitas["visitas"].to_numpy()
    filas, total_ratings = [], {}
    for particion_ in ("validacion", "test"):
        for semana in semanas[particion_]:
            ratings = grafo.popularidad(semana + 1, 1).numpy()  # ratings de la semana `semana`
            total_ratings[semana] = ratings
            wiki, wiki_anterior = visitas_de[:, semana - primera], visitas_de[:, semana - 1 - primera]
            rho = stats.spearmanr(ratings[con_articulo], wiki[con_articulo]).statistic

            candidatas = np.intersect1d(con_articulo, grafo.peliculas_conocidas(semana).numpy())
            adyacencias = grafo.adyacencias(semana)
            with torch.no_grad():
                z_usuario, z_pelicula = representaciones(modelo, en_cpu, semana, config)
            expuestas = exposicion(grafo, semana, adyacencias, puntuar_con_embeddings(z_usuario, z_pelicula)).numpy()
            popularidad_anterior = grafo.popularidad(semana, 1).numpy()
            filas.append({
                "semana": semana, "fecha": fecha(semana), "particion": particion_,
                "peliculas": len(con_articulo), "candidatas": len(candidatas), "spearman_ratings_visitas": rho,
                "coincidencia_a9": coincidencia(expuestas[candidatas], wiki[candidatas]),
                "coincidencia_popularidad_anterior": coincidencia(popularidad_anterior[candidatas], wiki[candidatas]),
                "coincidencia_wikipedia_anterior": coincidencia(wiki_anterior[candidatas], wiki[candidatas]),
            })
            registrar(f"{fecha(semana)}: Spearman {rho:.3f} | coincidencia@{K} A9 {filas[-1]['coincidencia_a9']:.2f}, "
                      f"popularidad {filas[-1]['coincidencia_popularidad_anterior']:.2f}, "
                      f"Wikipedia anterior {filas[-1]['coincidencia_wikipedia_anterior']:.2f}")
    semanal = pd.DataFrame(filas)

    # Series de ejemplo: las películas con más visitas en las semanas de test
    test = semanas["test"]
    elegidas = con_articulo[np.argsort(-visitas_de[con_articulo][:, np.array(test) - primera].sum(1), kind="stable")[:N_EJEMPLOS]]
    titulos = datos.cargar("movies")["title"].to_numpy()
    ejemplos = pd.DataFrame([
        {"movieId": int(grafo.ids_pelicula[p]), "titulo": titulos[p], "semana": s, "fecha": fecha(s),
         "ratings": int(total_ratings[s][p]), "visitas": int(visitas_de[p, s - primera])}
        for p in elegidas for s in semanas["validacion"] + test
    ])
    cobertura = {"peliculas_evaluadas": len(peliculas_evaluadas()), "con_articulo": int(len(con_articulo)),
                 "con_visitas": int(visitas["movieId"].nunique()), "k": K, "k_usuario": K_USUARIO}

    SALIDA.mkdir(parents=True, exist_ok=True)
    semanal.to_csv(SALIDA / "semanal.csv", index=False)
    ejemplos.to_csv(SALIDA / "ejemplos.csv", index=False)
    (SALIDA / "cobertura.json").write_text(json.dumps(cobertura, indent=2), encoding="utf-8")
    resumen = semanal.groupby("particion")[[c for c in semanal.columns if c.startswith(("spearman", "coincidencia"))]].mean()
    registrar(f"Promedios por partición:\n{resumen.round(3).to_string()}\nListo en {(time.time() - inicio) / 60:.1f} min")


def main():
    argumentos = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    argumentos.add_argument("--descargar", action="store_true", help="buscar artículos y descargar visitas (con caché)")
    if argumentos.parse_args().descargar:
        if not (DIR_WIKI / "articulos.csv").exists():
            buscar_articulos()
        descargar_visitas()
        return
    analizar()


if __name__ == "__main__":
    main()
