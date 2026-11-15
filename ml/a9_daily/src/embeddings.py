"""UMAP de las representaciones de películas de GraphSAGE A9 (interpretabilidad básica).

Las representaciones se calculan con los pesos de A9 (resultados/graphsage/A9_sin_id/modelo.pt)
y la instantánea y los atributos de la primera semana de validación. Se proyectan a 2D
con UMAP (distancia coseno) las películas con al menos MIN_RATINGS ratings antes de esa
semana. Cada una se etiqueta con su género principal: el primero en movies.csv entre los
más frecuentes, para que los colores sean legibles.

Uso, desde la raíz del proyecto (~2 minutos; corre en CPU para no competir por la GPU):
    python -m src.embeddings
"""

import numpy as np
import pandas as pd
import torch

from src import datos
from src.entrenamiento import config_de, crear_modelo, representaciones
from src.protocolo import particion, registrar
from src.temporal import GrafoEnDispositivo

MIN_RATINGS = 200
GENEROS_PRINCIPALES = ["Drama", "Comedy", "Action", "Horror", "Documentary", "Animation", "Romance", "Thriller"]
SALIDA = datos.RAIZ / "resultados" / "comparadores" / "umap_a9.csv"


def genero_principal(generos):
    """El primer género de la lista que esté entre los principales; si no, "Otro"."""
    for genero in generos.split("|"):
        if genero in GENEROS_PRINCIPALES:
            return genero
    return "Otro"


def main():
    import umap
    from src.grafo import GrafoTemporal

    cpu = torch.device("cpu")
    grafo = GrafoTemporal()
    semana = particion(grafo)["validacion"][0]
    en_cpu = GrafoEnDispositivo(grafo, cpu)
    config = config_de("A9_sin_id")
    modelo = crear_modelo(grafo, en_cpu, config).to(cpu)
    modelo.load_state_dict(torch.load(datos.RAIZ / "resultados" / "graphsage" / "A9_sin_id" / "modelo.pt", map_location=cpu))
    modelo.eval()
    with torch.no_grad():
        _, z_pelicula = representaciones(modelo, en_cpu, semana, config)

    ratings = grafo.popularidad(semana).numpy()
    elegidas = np.flatnonzero(ratings >= MIN_RATINGS)
    registrar(f"{len(elegidas):,} películas con ≥ {MIN_RATINGS} ratings antes de {datos.inicio_semana(semana).date()}")
    proyeccion = umap.UMAP(n_neighbors=30, min_dist=0.1, metric="cosine", random_state=0).fit_transform(z_pelicula[elegidas].numpy())

    movies = datos.cargar("movies").set_index("movieId")
    ids = grafo.ids_pelicula[elegidas]
    tabla = pd.DataFrame({"movieId": ids, "titulo": movies.loc[ids, "title"].to_numpy(),
                          "genero_principal": [genero_principal(g) for g in movies.loc[ids, "genres"]],
                          "ratings_previos": ratings[elegidas].astype(int), "x": proyeccion[:, 0], "y": proyeccion[:, 1]})
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    tabla.to_csv(SALIDA, index=False)
    registrar(f"UMAP guardado en {SALIDA}")


if __name__ == "__main__":
    main()
