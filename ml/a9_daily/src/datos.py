"""Carga de MovieLens 32M.

Convierte una sola vez los CSV del zip original a Parquet (data/processed/)
y ofrece funciones para leerlos rápido desde los notebooks.

Uso, desde la raíz del proyecto:
    python -m src.datos
"""

import zipfile
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
RUTA_ZIP = RAIZ / "ml-32m.zip"
DIR_PARQUET = RAIZ / "data" / "processed"

# Tipos compactos para que ratings (32M filas) quepa en memoria sin problema.
# userId (máx. ~200 mil) y movieId (máx. ~300 mil) caben en int32; los ratings
# van de 0.5 a 5.0 en pasos de 0.5, así que float32 los representa exactos.
# imdbId se deja como texto porque trae ceros a la izquierda; tmdbId tiene vacíos.
TIPOS = {
    "ratings": {"userId": "int32", "movieId": "int32", "rating": "float32", "timestamp": "int64"},
    "tags": {"userId": "int32", "movieId": "int32", "tag": "string", "timestamp": "int64"},
    "movies": {"movieId": "int32", "title": "string", "genres": "string"},
    "links": {"movieId": "int32", "imdbId": "string", "tmdbId": "Int64"},
}

SEGUNDOS_POR_DIA = 86_400


def convertir_a_parquet(ruta_zip=RUTA_ZIP, dir_salida=DIR_PARQUET):
    """Lee cada CSV directamente del zip (sin descomprimirlo) y lo guarda como Parquet."""
    dir_salida.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ruta_zip) as archivo_zip:
        for nombre, tipos in TIPOS.items():
            with archivo_zip.open(f"ml-32m/{nombre}.csv") as csv:
                tabla = pd.read_csv(csv, dtype=tipos)
            tabla.to_parquet(dir_salida / f"{nombre}.parquet", index=False)
            print(f"{nombre}: {len(tabla):,} filas")


def cargar(nombre, columnas=None):
    """Lee una tabla ya convertida: 'ratings', 'movies', 'tags' o 'links'."""
    ruta = DIR_PARQUET / f"{nombre}.parquet"
    if not ruta.exists():
        raise FileNotFoundError(f"No existe {ruta}. Corre primero: python -m src.datos")
    return pd.read_parquet(ruta, columns=columnas)


def semana(timestamp):
    """Índice de semana (lunes a domingo, UTC) a partir de un timestamp Unix en segundos.

    El 1 de enero de 1970 fue jueves; sumar 3 días hace que cada semana arranque en lunes.
    """
    return (timestamp // SEGUNDOS_POR_DIA + 3) // 7


def inicio_semana(indice_semana):
    """Fecha del lunes con el que empieza la semana `indice_semana`."""
    return pd.to_datetime((indice_semana * 7 - 3) * SEGUNDOS_POR_DIA, unit="s")


if __name__ == "__main__":
    convertir_a_parquet()
