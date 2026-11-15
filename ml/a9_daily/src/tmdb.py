"""Descarga de metadatos de TMDB para las películas de MovieLens (una sola vez, con caché).

La llave se lee de la variable de entorno TMDB_API_KEY o, si no existe, del archivo
data/tmdb/llave.txt (que git ignora). Puede ser la "API Key" (v3) o el "API Read Access
Token" (v4, empieza por "eyJ"); con el token va en un encabezado y no en la URL. El
programa nunca la escribe en disco ni en los registros.

Para cada tmdbId de links.csv se pide /movie/{id} con keywords y credits, y se guarda
sólo lo que usa el modelo. Se descartan a propósito `popularity`, `vote_average` y
`vote_count`: son valores de hoy y meterían información del futuro en el pasado.

Uso, desde la raíz del proyecto (~1 hora; si se corta, retoma donde iba):
    python -m src.tmdb

This product uses the TMDB API but is not endorsed or certified by TMDB.
"""

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from src import datos

DIR_TMDB = datos.RAIZ / "data" / "tmdb"
DIR_CRUDO = DIR_TMDB / "crudo"  # un JSON reducido por película (caché)
ARCHIVO_LLAVE = DIR_TMDB / "llave.txt"
URL = "https://api.themoviedb.org/3/movie/{}?append_to_response=keywords,credits&language=en-US"
PETICIONES_POR_SEGUNDO = 30  # por debajo del límite de TMDB (~50 por segundo)
HILOS = 16
ACTORES = 5  # reparto principal que se guarda
CAMPOS_EXCLUIDOS = ("popularity", "vote_average", "vote_count")


def reducir(respuesta):
    """Sólo los campos de contenido que usa el modelo (sin popularidad ni votos)."""
    creditos = respuesta.get("credits", {})
    return {
        "tmdbId": respuesta["id"],
        "title": respuesta.get("title"),
        "release_date": respuesta.get("release_date") or None,
        "original_language": respuesta.get("original_language"),
        "runtime": respuesta.get("runtime") or None,
        "overview": respuesta.get("overview") or "",
        "genres": [g["name"] for g in respuesta.get("genres", [])],
        "keywords": [k["name"] for k in respuesta.get("keywords", {}).get("keywords", [])],
        "directors": [p["name"] for p in creditos.get("crew", []) if p.get("job") == "Director"],
        "cast": [p["name"] for p in sorted(creditos.get("cast", []), key=lambda p: p.get("order", 999))[:ACTORES]],
    }


class Cliente:
    """Peticiones a TMDB con límite de tasa y reintentos ante 429 y errores de red."""

    def __init__(self, llave):
        self.encabezados = {"accept": "application/json"}
        self.parametro = ""
        if llave.startswith("eyJ"):  # token de lectura v4
            self.encabezados["Authorization"] = f"Bearer {llave}"
        else:  # API key v3: TMDB sólo la acepta como parámetro de la URL
            self.parametro = "&" + urllib.parse.urlencode({"api_key": llave})
        self.candado, self.siguiente = threading.Lock(), time.monotonic()

    def _esperar_turno(self):
        with self.candado:
            ahora = time.monotonic()
            espera = max(0.0, self.siguiente - ahora)
            self.siguiente = max(ahora, self.siguiente) + 1 / PETICIONES_POR_SEGUNDO
        time.sleep(espera)

    def pelicula(self, tmdb_id, intentos=5):
        """El JSON reducido de la película, o None si TMDB no la tiene (404)."""
        for intento in range(intentos):
            self._esperar_turno()
            peticion = urllib.request.Request(URL.format(tmdb_id) + self.parametro, headers=self.encabezados)
            try:
                with urllib.request.urlopen(peticion, timeout=20) as respuesta:
                    return reducir(json.load(respuesta))
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return None
                if error.code == 401:
                    raise RuntimeError("TMDB rechazó la llave (401). Revisa TMDB_API_KEY.") from None
                if error.code == 429:
                    time.sleep(float(error.headers.get("Retry-After", 2)))
                    continue
                time.sleep(2 ** intento)
            except (urllib.error.URLError, TimeoutError):
                time.sleep(2 ** intento)
        raise RuntimeError(f"TMDB no respondió para tmdbId {tmdb_id} después de {intentos} intentos")


def descargar():
    llave = os.environ.get("TMDB_API_KEY", "").strip()
    if not llave and ARCHIVO_LLAVE.exists():
        llave = ARCHIVO_LLAVE.read_text(encoding="utf-8").strip()
    if not llave:
        raise SystemExit(f"Falta la llave de TMDB: variable de entorno TMDB_API_KEY o archivo {ARCHIVO_LLAVE}.")
    DIR_CRUDO.mkdir(parents=True, exist_ok=True)
    ids = datos.cargar("links")["tmdbId"].dropna().astype(int).unique()
    faltan = [i for i in ids if not (DIR_CRUDO / f"{i}.json").exists()]
    print(f"{len(ids):,} tmdbId; ya descargados {len(ids) - len(faltan):,}; faltan {len(faltan):,}", flush=True)

    cliente, hechos, inicio = Cliente(llave), [0], time.time()

    def uno(tmdb_id):
        dato = cliente.pelicula(tmdb_id)
        (DIR_CRUDO / f"{tmdb_id}.json").write_text(json.dumps(dato, ensure_ascii=False), encoding="utf-8")
        hechos[0] += 1
        if hechos[0] % 2000 == 0:
            print(f"  {hechos[0]:,} de {len(faltan):,} ({time.time() - inicio:.0f} s)", flush=True)

    with ThreadPoolExecutor(HILOS) as hilos:
        list(hilos.map(uno, faltan))
    consolidar()


def consolidar():
    """Une la caché en data/tmdb/peliculas.parquet (una fila por película de MovieLens)."""
    links = datos.cargar("links")[["movieId", "tmdbId"]].dropna()
    filas = []
    for movie_id, tmdb_id in links.itertuples(index=False):
        ruta = DIR_CRUDO / f"{int(tmdb_id)}.json"
        dato = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None
        if dato is not None:
            filas.append({"movieId": int(movie_id), **dato})
    tabla = pd.DataFrame(filas)
    assert not set(CAMPOS_EXCLUIDOS) & set(tabla.columns)
    tabla.to_parquet(DIR_TMDB / "peliculas.parquet", index=False)
    print(f"{len(tabla):,} películas con metadatos de TMDB de {datos.cargar('links').shape[0]:,} en links.csv")


if __name__ == "__main__":
    descargar()
