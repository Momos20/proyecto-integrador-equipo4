"""Atributos de contenido de cada película (fijos en el tiempo), para H2.

Grupos (se eligen por nombre en la configuración del modelo):
- "sinopsis":       embedding Sentence-BERT (all-MiniLM-L6-v2, 384) de la sinopsis de TMDB.
- "palabras_clave": embedding Sentence-BERT de sus palabras clave unidas por comas, y una
                    marca de "no tiene".
- "ficha":          director y reparto principal (multi-hot de las PERSONAS más frecuentes),
                    idioma original (los IDIOMAS más frecuentes + "otro") y log(duración)
                    estandarizada, con marcas de dato faltante.
Una película sin datos de TMDB queda en 0 en todos los grupos, con su marca de faltante.

Sin fuga temporal: el contenido no depende de ratings. Los vocabularios (personas e
idiomas) y la estandarización de la duración se calculan sólo con las películas cuyo
primer rating es anterior a la validación (2022), y TMDB se descargó sin popularidad ni
votos (src/tmdb.py).

Uso, desde la raíz del proyecto (una vez, ~3 min en GPU; guarda data/tmdb/contenido.pt):
    python -m src.contenido
"""

import numpy as np
import pandas as pd
import torch

from src import datos
from src.protocolo import AÑO_VALIDACION, semanas_del_año
from src.tmdb import DIR_TMDB

MODELO_TEXTO = "sentence-transformers/all-MiniLM-L6-v2"
PERSONAS = 500
IDIOMAS = 10
GRUPOS = ("sinopsis", "palabras_clave", "ficha")
RUTA = DIR_TMDB / "contenido.pt"


def vocabulario(listas, tamaño):
    """Los `tamaño` valores más frecuentes de una serie de listas (empates por orden alfabético)."""
    conteo = pd.Series([v for lista in listas for v in lista]).value_counts()
    conteo = conteo.sort_index().sort_values(ascending=False, kind="stable")
    return list(conteo.index[:tamaño])


def ficha(tmdb, permitidas):
    """Multi-hot de personas, one-hot de idioma y duración, con vocabularios de `permitidas`.

    `tmdb`: una fila por película (movieId, directors, cast, original_language, runtime).
    `permitidas`: movieIds cuyo primer rating es anterior a la validación.
    """
    base = tmdb[tmdb["movieId"].isin(permitidas)]
    personas = vocabulario((list(d) + list(c) for d, c in zip(base["directors"], base["cast"])), PERSONAS)
    idiomas = vocabulario(([l] for l in base["original_language"].dropna()), IDIOMAS)
    duracion_log = np.log1p(base["runtime"].dropna().astype(float))
    media, desviacion = duracion_log.mean(), duracion_log.std()

    columna_persona = {p: i for i, p in enumerate(personas)}
    matriz = np.zeros((len(tmdb), PERSONAS + IDIOMAS + 1 + 2), dtype=np.float32)
    for fila, (directores, reparto, idioma, duracion) in enumerate(zip(tmdb["directors"], tmdb["cast"], tmdb["original_language"], tmdb["runtime"])):
        for persona in list(directores) + list(reparto):
            if persona in columna_persona:
                matriz[fila, columna_persona[persona]] = 1
        matriz[fila, PERSONAS + (idiomas.index(idioma) if idioma in idiomas else IDIOMAS)] = 1
        if pd.notna(duracion) and duracion > 0:
            matriz[fila, -2] = (np.log1p(duracion) - media) / desviacion
        else:
            matriz[fila, -1] = 1
    return matriz, {"personas": personas, "idiomas": idiomas, "duracion_log_media": float(media), "duracion_log_desviacion": float(desviacion)}


def construir():
    """Calcula los grupos para todas las películas de movies.csv y los guarda en RUTA."""
    from sentence_transformers import SentenceTransformer

    movies = datos.cargar("movies")[["movieId"]]
    tmdb = movies.merge(pd.read_parquet(DIR_TMDB / "peliculas.parquet"), on="movieId", how="left")
    for columna in ("directors", "cast", "keywords"):
        tmdb[columna] = tmdb[columna].map(lambda x: list(x) if isinstance(x, (list, np.ndarray)) else [])
    tmdb["overview"] = tmdb["overview"].fillna("")

    ratings = datos.cargar("ratings", ["movieId", "timestamp"])
    primera = datos.semana(ratings.groupby("movieId")["timestamp"].min())
    inicio_validacion = semanas_del_año(AÑO_VALIDACION, ultima_semana=10**9)[0]
    permitidas = set(primera.index[primera.to_numpy() < inicio_validacion])

    texto = SentenceTransformer(MODELO_TEXTO, device="cuda" if torch.cuda.is_available() else "cpu")
    codificar = lambda frases: texto.encode(frases, batch_size=256, convert_to_tensor=True, normalize_embeddings=True,
                                            show_progress_bar=True).float().cpu()
    tiene_sinopsis = torch.tensor((tmdb["overview"].str.len() > 0).to_numpy())
    sinopsis = codificar(tmdb["overview"].tolist()) * tiene_sinopsis[:, None]
    tiene_claves = torch.tensor(tmdb["keywords"].map(len).gt(0).to_numpy())
    claves = codificar([", ".join(k) for k in tmdb["keywords"]]) * tiene_claves[:, None]
    matriz_ficha, vocabularios = ficha(tmdb, permitidas)

    grupos = {
        "sinopsis": sinopsis,
        "palabras_clave": torch.cat([claves, (~tiene_claves).float()[:, None]], dim=1),
        "ficha": torch.from_numpy(matriz_ficha),
    }
    torch.save({"movieId": torch.tensor(tmdb["movieId"].to_numpy()), "grupos": grupos, "vocabularios": vocabularios,
                "modelo_texto": MODELO_TEXTO, "peliculas_permitidas_vocabulario": len(permitidas)}, RUTA)
    for nombre, matriz in grupos.items():
        print(f"{nombre}: {tuple(matriz.shape)}, filas no nulas {(matriz.abs().sum(1) > 0).float().mean():.1%}")


def matriz(grupos, ids_pelicula):
    """Concatena los grupos pedidos, en el orden de `ids_pelicula` (el de GrafoTemporal)."""
    if not grupos:
        return torch.zeros(len(ids_pelicula), 0)
    guardado = torch.load(RUTA)
    fila = pd.Index(guardado["movieId"].numpy()).get_indexer(ids_pelicula)
    if (fila < 0).any():
        raise ValueError("Hay películas sin fila de contenido; vuelve a correr python -m src.contenido")
    return torch.cat([guardado["grupos"][g][fila] for g in grupos], dim=1)


if __name__ == "__main__":
    construir()
