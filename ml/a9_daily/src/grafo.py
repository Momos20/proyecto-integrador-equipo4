"""Grafo bipartito usuario–película de MovieLens 32M, cortado por semanas.

Cada arista (usuario, película) guarda la semana de su rating. Para predecir la
semana w, el modelo sólo ve la instantánea con las aristas anteriores a w.
"""

import numpy as np
import pandas as pd
import torch

from src import datos

# Tipos de arista en el formato de PyG: (origen, relación, destino)
CALIFICA = ("usuario", "califica", "pelicula")
CALIFICADA_POR = ("pelicula", "calificada_por", "usuario")

SIN_APARICION = np.iinfo(np.int32).max  # semana de alta de las películas sin ningún rating


class GrafoTemporal:
    """Todas las aristas usuario–película con su semana, listas para cortar por fecha."""

    def __init__(self, ratings=None, movies=None, con_dias=False):
        """Sin argumentos carga MovieLens 32M; las pruebas pasan tablas pequeñas con las mismas columnas.

        Con `con_dias`, guarda también el día (UTC) de cada arista, en el mismo orden que
        `_por_usuario` y `_por_pelicula`, y el primer día de cada nodo, para el horizonte
        diario (src/diario.py). Sin él, nada cambia.
        """
        if ratings is None:
            ratings = datos.cargar("ratings", columnas=["userId", "movieId", "timestamp"])
        if movies is None:
            movies = datos.cargar("movies")

        # Índices consecutivos 0..n-1. Las películas salen de movies.csv para que
        # las que todavía no tienen ratings también existan como nodo.
        self.ids_usuario = np.sort(ratings["userId"].unique())
        self.ids_pelicula = movies["movieId"].to_numpy()
        self.n_usuarios = len(self.ids_usuario)
        self.n_peliculas = len(self.ids_pelicula)

        usuario = np.searchsorted(self.ids_usuario, ratings["userId"].to_numpy())
        pelicula = pd.Index(self.ids_pelicula).get_indexer(ratings["movieId"])
        semana = datos.semana(ratings["timestamp"].to_numpy()).astype(np.int32)
        dia = (ratings["timestamp"].to_numpy() // datos.SEGUNDOS_POR_DIA).astype(np.int32) if con_dias else None
        del ratings

        self.primera_semana, self.ultima_semana = int(semana.min()), int(semana.max())
        self.semana_alta_usuario = _primera_semana(usuario, semana, self.n_usuarios)
        self.semana_alta_pelicula = _primera_semana(pelicula, semana, self.n_peliculas)
        self.dia_por_usuario = self.dia_por_pelicula = self.dia_alta_usuario = self.dia_alta_pelicula = None
        if con_dias:
            self.ultimo_dia = int(dia.max())
            self.dia_alta_usuario = _primera_semana(usuario, dia, self.n_usuarios)  # sirve igual para días
            self.dia_alta_pelicula = _primera_semana(pelicula, dia, self.n_peliculas)

        # Dos copias ordenadas de las aristas: por usuario y por película. Así, al
        # filtrar por semana, las filas de cada matriz dispersa ya quedan en orden.
        orden = np.lexsort((pelicula, usuario))
        self._por_usuario = _a_tensores(usuario[orden], pelicula[orden], semana[orden])
        if con_dias:
            self.dia_por_usuario = torch.from_numpy(dia[orden])
        orden = np.lexsort((usuario, pelicula))
        self._por_pelicula = _a_tensores(pelicula[orden], usuario[orden], semana[orden])
        if con_dias:
            self.dia_por_pelicula = torch.from_numpy(dia[orden])

        self.atributos_pelicula = _atributos_pelicula(movies)

    def adyacencias(self, semana_corte):
        """Instantánea con las aristas anteriores a `semana_corte`, en el formato de PyG.

        Cada matriz tiene una fila por nodo destino y una columna por nodo origen
        (lo que PyG llama `adj_t`), con un 1 por arista.
        """
        return {
            CALIFICA: _matriz_csr(*self._por_pelicula, semana_corte, self.n_peliculas, self.n_usuarios),
            CALIFICADA_POR: _matriz_csr(*self._por_usuario, semana_corte, self.n_usuarios, self.n_peliculas),
        }

    def objetivos(self, semana_objetivo):
        """Aristas de la semana objetivo entre un usuario que regresa y una película ya conocida.

        Devuelve (usuarios, películas, aristas_excluidas): las excluidas son las de esa
        semana cuyo usuario o película aparece por primera vez.
        """
        usuario, pelicula, semana = self._por_usuario
        en_la_semana = semana == semana_objetivo
        usuario, pelicula = usuario[en_la_semana], pelicula[en_la_semana]
        con_historia = (
            (torch.from_numpy(self.semana_alta_usuario)[usuario] < semana_objetivo)
            & (torch.from_numpy(self.semana_alta_pelicula)[pelicula] < semana_objetivo)
        )
        return usuario[con_historia], pelicula[con_historia], int((~con_historia).sum())

    def aristas(self, desde, hasta):
        """Aristas (usuarios, películas) con semana en [desde, hasta), ordenadas por usuario."""
        usuario, pelicula, semana = self._por_usuario
        vigente = (semana >= desde) & (semana < hasta)
        return usuario[vigente], pelicula[vigente]

    def peliculas_conocidas(self, semana_corte):
        """Índices de las películas con al menos un rating antes de `semana_corte`."""
        return torch.from_numpy(np.flatnonzero(self.semana_alta_pelicula < semana_corte))

    def popularidad(self, semana_corte, semanas_atras=None):
        """Número de ratings de cada película antes de `semana_corte`.

        Con `semanas_atras`, cuenta sólo las últimas `semanas_atras` semanas.
        """
        pelicula, _, semana = self._por_pelicula
        vigente = semana < semana_corte
        if semanas_atras is not None:
            vigente &= semana >= semana_corte - semanas_atras
        return torch.bincount(pelicula[vigente], minlength=self.n_peliculas).float()


def _primera_semana(nodo, semana, n_nodos):
    primera = np.full(n_nodos, SIN_APARICION, dtype=np.int32)
    np.minimum.at(primera, nodo, semana)
    return primera


def _a_tensores(filas, columnas, semana):
    return torch.from_numpy(filas.astype(np.int64)), torch.from_numpy(columnas.astype(np.int64)), torch.from_numpy(semana)


def _matriz_csr(filas, columnas, semana, semana_corte, n_filas, n_columnas):
    vigente = semana < semana_corte
    filas, columnas = filas[vigente], columnas[vigente]
    inicio_fila = torch.zeros(n_filas + 1, dtype=torch.int64)
    inicio_fila[1:] = torch.cumsum(torch.bincount(filas, minlength=n_filas), dim=0)
    return torch.sparse_csr_tensor(
        inicio_fila, columnas, torch.ones(len(columnas)), size=(n_filas, n_columnas), check_invariants=False
    )


def _atributos_pelicula(movies):
    """Géneros (multi-hot) y año de estreno estandarizado, con una marca si falta el año."""
    generos = movies["genres"].str.get_dummies(sep="|").to_numpy(np.float32)
    año = movies["title"].str.extract(r"\((\d{4})\)\s*$", expand=False).astype("float").to_numpy()
    falta_año = np.isnan(año)
    año_estandarizado = np.where(falta_año, 0.0, (año - np.nanmean(año)) / np.nanstd(año))
    atributos = np.column_stack([generos, año_estandarizado, falta_año]).astype(np.float32)
    return torch.from_numpy(atributos)
