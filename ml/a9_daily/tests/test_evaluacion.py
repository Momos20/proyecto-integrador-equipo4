"""Pruebas de las métricas, del corte temporal del grafo y de la partición.

Usa un grafo de juguete (sin cargar MovieLens), así que corre en segundos.

Uso, desde la raíz del proyecto:
    python -m tests.test_evaluacion
"""

import math

import numpy as np
import pandas as pd
import torch

from src import datos
from src.evaluacion import evaluar_semana, metricas_por_usuario, posicion_primer_acierto, top
from src.grafo import CALIFICA, CALIFICADA_POR, GrafoTemporal
from src.protocolo import semanas_del_año

S0 = 2800  # una semana cualquiera; las del juguete son S0, S0 + 1 y S0 + 2


def _timestamp(semana, segundos=3600):
    """Un instante dentro de la semana `semana` (lunes + `segundos`)."""
    return (semana * 7 - 3) * datos.SEGUNDOS_POR_DIA + segundos


def grafo_de_juguete():
    """Usuarios 10, 20, 30, 40 y películas 1..5 (índices 0..4).

    Semana S0:     10→1, 10→2 | 20→1, 20→3 | 30→1, 30→3, 30→4
    Semana S0 + 1: 10→3 | 20→4 | 20→5 (película nueva) | 40→1 (usuario nuevo)
    Semana S0 + 2: 10→4 | 30→2
    """
    aristas = [
        (10, 1, S0), (10, 2, S0), (20, 1, S0), (20, 3, S0), (30, 1, S0), (30, 3, S0), (30, 4, S0),
        (10, 3, S0 + 1), (20, 4, S0 + 1), (20, 5, S0 + 1), (40, 1, S0 + 1),
        (10, 4, S0 + 2), (30, 2, S0 + 2),
    ]
    ratings = pd.DataFrame({
        "userId": np.array([a[0] for a in aristas], dtype=np.int32),
        "movieId": np.array([a[1] for a in aristas], dtype=np.int32),
        "timestamp": np.array([_timestamp(a[2]) for a in aristas], dtype=np.int64),
    })
    movies = pd.DataFrame({"movieId": np.arange(1, 6, dtype=np.int32),
                           "title": [f"Película {i} ({2000 + i})" for i in range(1, 6)],
                           "genres": ["Drama", "Comedy", "Drama|Comedy", "Action", "Action"]})
    return GrafoTemporal(ratings, movies)


def test_metricas_calculadas_a_mano():
    # Usuario 0: 2 objetivos, aciertos en las posiciones 1 y 3. Usuario 1: 5 objetivos, ningún acierto.
    aciertos = torch.tensor([[1.0, 0.0, 1.0], [0.0, 0.0, 0.0]])
    m = metricas_por_usuario(aciertos, torch.tensor([2, 5]), ks=(2, 3))
    dcg_ideal_2 = 1 + 1 / math.log2(3)
    esperado = {
        "recall@2": [0.5, 0], "precision@2": [0.5, 0], "ndcg@2": [1 / dcg_ideal_2, 0], "hitrate@2": [1, 0],
        "recall@3": [1, 0], "precision@3": [2 / 3, 0], "ndcg@3": [(1 + 1 / math.log2(4)) / dcg_ideal_2, 0], "hitrate@3": [1, 0],
    }
    for nombre, valores in esperado.items():
        assert torch.allclose(m[nombre], torch.tensor(valores, dtype=torch.float)), nombre


def test_posicion_del_primer_acierto_con_empates():
    puntajes = torch.tensor([[5.0, 4.0, 3.0, 2.0], [5.0, 3.0, 3.0, 3.0], [3.0, 3.0, 3.0, 1.0]])
    es_objetivo = torch.tensor([[False, False, True, False], [False, False, True, False], [True, True, False, False]])
    # Sin empates: posición 3. Un objetivo empatado con otras 2 en las posiciones 2-4: en promedio 3.
    # Dos objetivos empatados con una no objetivo en las posiciones 1-3: en promedio 4/3.
    assert torch.allclose(posicion_primer_acierto(puntajes, es_objetivo), torch.tensor([3.0, 3.0, 4 / 3]))


def test_top_desempata_igual_en_cpu_y_gpu():
    puntajes = torch.tensor([[1.0, 3.0, 3.0, 2.0, 3.0, -math.inf]])
    assert top(puntajes, 4).tolist() == [[1, 2, 4, 3]]
    grandes = torch.randint(0, 5, (64, 1000)).float()  # muchos empates, como los conteos de popularidad
    assert torch.equal(top(grandes, 50)[:, :20], top(grandes, 20))
    if torch.cuda.is_available():
        assert torch.equal(top(grandes.cuda(), 50).cpu(), top(grandes, 50))


def test_evaluar_semana_en_grafo_de_juguete():
    grafo = grafo_de_juguete()
    semana = S0 + 1
    puntajes_fijos = torch.tensor([10.0, 9.0, 8.0, 7.0, 6.0])  # películas 1..5
    resumen, por_usuario = evaluar_semana(grafo, semana, grafo.adyacencias(semana),
                                          lambda usuarios: puntajes_fijos.expand(len(usuarios), -1), ks=(1, 2))

    # 20→5 (película nueva) y 40→1 (usuario nuevo) no se evalúan
    assert (resumen["usuarios"], resumen["aristas_objetivo"], resumen["aristas_excluidas"]) == (2, 2, 2)
    # Usuario 10: vio 1 y 2, candidatas 3 (8) y 4 (7); el objetivo 3 queda primero.
    # Usuario 20: vio 1 y 3, candidatas 2 (9) y 4 (7); el objetivo 4 queda segundo.
    # La película 5 no es candidata porque nadie la había calificado antes de la semana.
    fila = por_usuario.set_index(pd.Index(grafo.ids_usuario[por_usuario["usuario"]]))
    assert fila.loc[10, "recall@1"] == 1 and fila.loc[20, "recall@1"] == 0 and fila.loc[20, "recall@2"] == 1
    assert fila.loc[10, "mrr"] == 1 and fila.loc[20, "mrr"] == 0.5
    assert fila.loc[10, "n_historial"] == 2 and fila.loc[20, "n_historial"] == 2
    assert (fila["n_objetivos"] == 1).all() and (fila["semana"] == semana).all()
    # Top 1: {3, 2}; top 2: {3, 4, 2}; de 4 películas conocidas
    assert resumen["cobertura@1"] == 2 / 4 and resumen["cobertura@2"] == 3 / 4


def test_sin_fuga_temporal_en_el_grafo():
    grafo = grafo_de_juguete()
    semana_de = {(u, p): s for u, p, s in zip(grafo._por_usuario[0].tolist(), grafo._por_usuario[1].tolist(),
                                              grafo._por_usuario[2].tolist())}
    for semana in (S0, S0 + 1, S0 + 2, S0 + 3):
        # La instantánea de la semana tiene exactamente las aristas anteriores a ella
        anteriores = {par for par, s in semana_de.items() if s < semana}
        adyacencias = grafo.adyacencias(semana)
        usuario_pelicula = adyacencias[CALIFICADA_POR].to_sparse_coo().indices().T.tolist()
        pelicula_usuario = adyacencias[CALIFICA].to_sparse_coo().indices().T.tolist()
        assert {tuple(par) for par in usuario_pelicula} == anteriores
        assert {(u, p) for p, u in pelicula_usuario} == anteriores

        # Los objetivos son de la semana, con usuario y película vistos antes
        usuarios, peliculas, _ = grafo.objetivos(semana)
        vistos_u = {u for u, _ in anteriores}
        vistos_p = {p for _, p in anteriores}
        for u, p in zip(usuarios.tolist(), peliculas.tolist()):
            assert semana_de[(u, p)] == semana and u in vistos_u and p in vistos_p

        # Las películas conocidas son las calificadas antes de la semana
        assert set(grafo.peliculas_conocidas(semana).tolist()) == vistos_p

        # Aristas de una ventana (positivos de la MF-BPR): sólo las semanas [semana - 2, semana)
        usuarios, peliculas = grafo.aristas(semana - 2, semana)
        assert set(zip(usuarios.tolist(), peliculas.tolist())) == {par for par, s in semana_de.items() if semana - 2 <= s < semana}

        # Popularidad: histórica y de la última semana
        historica = grafo.popularidad(semana)
        ultima = grafo.popularidad(semana, semanas_atras=1)
        for p in range(grafo.n_peliculas):
            assert historica[p] == sum(1 for (_, q), s in semana_de.items() if q == p and s < semana)
            assert ultima[p] == sum(1 for (_, q), s in semana_de.items() if q == p and s == semana - 1)


def test_particion_acordada():
    ultima_semana = datos.semana(int(pd.Timestamp("2023-10-09").timestamp()))  # la incompleta de los datos
    validacion = semanas_del_año(2022, ultima_semana)
    test = semanas_del_año(2023, ultima_semana)
    assert len(validacion) == 52 and len(test) == 40
    assert str(datos.inicio_semana(validacion[0]).date()) == "2022-01-03"
    assert str(datos.inicio_semana(validacion[-1]).date()) == "2022-12-26"
    assert str(datos.inicio_semana(test[0]).date()) == "2023-01-02"
    assert str(datos.inicio_semana(test[-1]).date()) == "2023-10-02"
    assert validacion[-1] + 1 == test[0]  # consecutivas, sin traslape ni huecos
    assert validacion == list(range(validacion[0], validacion[-1] + 1))


if __name__ == "__main__":
    for nombre, prueba in list(globals().items()):
        if nombre.startswith("test_"):
            prueba()
            print(f"OK: {nombre}")
