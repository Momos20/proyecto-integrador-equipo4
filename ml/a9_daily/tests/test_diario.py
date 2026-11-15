"""Pruebas del horizonte diario (src/diario.py) y del Top-K diario (src/recomendar.py).

Grafo de juguete con ratings repartidos en días distintos. Cada atributo se compara con
un valor calculado a mano para un corte en miércoles, se verifica que el día del corte no
entra (sin fuga) y que en un lunes las entradas son exactamente las de la semana.

Uso, desde la raíz del proyecto:
    python -m tests.test_diario
"""

import math

import numpy as np
import pandas as pd
import torch

from src import datos
from src.diario import GrafoDiario, dia_de_fecha, evaluar_dias, fecha_de_dia, lunes, semana_movil
from src.evaluacion import puntuar_por_popularidad
from src.grafo import CALIFICA, CALIFICADA_POR, GrafoTemporal
from src.recomendar import Recomendador
from tests.test_evaluacion import S0

L = math.log1p
D = S0 * 7 - 3  # lunes de la semana S0
CORTE = D + 9   # miércoles de la semana S0 + 1

# (usuario, película, día). Películas: 1 Drama, 2 Comedy, 3 Drama|Comedy, 4 Action
ARISTAS = [
    (3, 1, D - 30),                 # 39 días antes del corte: ⌈39 / 7⌉ = 6 semanas
    (1, 1, D),                      # 9 días antes: 2 semanas
    (2, 3, D + 1),                  # 8 días antes: 2 semanas
    (2, 1, D + 2),                  # 7 días antes: todavía "la última semana"
    (1, 2, D + 8),                  # el día anterior al corte
    (1, 3, CORTE), (4, 2, CORTE),   # el día del corte: no entran
    (2, 2, D + 10), (3, 4, D + 12),  # después
]
MOVIES = pd.DataFrame({"movieId": np.arange(1, 5, dtype=np.int32),
                       "title": [f"Película {i} ({2000 + i})" for i in range(1, 5)],
                       "genres": ["Drama", "Comedy", "Drama|Comedy", "Action"]})


def grafo_diario():
    ratings = pd.DataFrame({"userId": np.array([a[0] for a in ARISTAS], dtype=np.int32),
                            "movieId": np.array([a[1] for a in ARISTAS], dtype=np.int32),
                            "timestamp": np.array([a[2] * datos.SEGUNDOS_POR_DIA + 3600 for a in ARISTAS], dtype=np.int64)})
    return GrafoTemporal(ratings, MOVIES, con_dias=True)


def _dispositivos():
    return [torch.device("cpu")] + ([torch.device("cuda")] if torch.cuda.is_available() else [])


def test_fechas_y_semanas_moviles():
    assert dia_de_fecha("2023-06-15") == 19523 and fecha_de_dia(19523) == "2023-06-15"
    assert dia_de_fecha(pd.Timestamp("2023-06-15 20:00", tz="America/Bogota")) == 19524  # 01:00 UTC del 16
    assert lunes(D) == D and lunes(D + 6) == D and lunes(D + 7) == D + 7
    dias = torch.arange(CORTE - 100, CORTE + 10)
    s, c = semana_movil(dias, CORTE), CORTE // 7
    antes = dias < CORTE
    assert torch.equal(c - s[antes], torch.ceil((CORTE - dias[antes]) / 7).long())  # c − s(t) = ⌈(d − t) / 7⌉
    assert (s[~antes] >= c).all()


def test_sin_fuga_adyacencias_hasta_el_dia_anterior():
    grafo = grafo_diario()
    for dispositivo in _dispositivos():
        diario = GrafoDiario(grafo, dispositivo)
        vista, corte = diario.en_semanas(CORTE)
        historial = vista.adyacencias(corte)[CALIFICADA_POR].to_dense().cpu()
        esperado = torch.tensor([[1, 1, 0, 0], [1, 0, 1, 0], [1, 0, 0, 0], [0, 0, 0, 0]], dtype=torch.float)
        assert torch.equal(historial, esperado), historial
        assert torch.equal(vista.adyacencias(corte)[CALIFICA].to_dense().cpu(), esperado.T)
        assert torch.equal(diario.historial(CORTE).to_dense(), esperado)


def test_atributos_de_pelicula_en_un_miercoles_a_mano():
    grafo = grafo_diario()
    for dispositivo in _dispositivos():
        vista, corte = GrafoDiario(grafo, dispositivo).en_semanas(CORTE)
        a = vista.atributos(corte)["pelicula"].cpu()
        esperado = torch.tensor([
            # últimos 7 días, 28, 84, ⌈semanas desde el primer rating⌉, conocida
            [L(1), L(2), L(3), L(6), 1],  # película 1: D + 2 | D, D + 2 | D − 30, D, D + 2
            [L(1), L(1), L(1), L(1), 1],  # película 2: sólo D + 8 (CORTE y D + 10 no cuentan)
            [L(0), L(1), L(1), L(2), 1],  # película 3: D + 1, 8 días antes
            [0, 0, 0, 0, 0],              # película 4: su primer rating es posterior
        ])
        assert torch.allclose(a, esperado, atol=1e-6), a


def test_atributos_de_usuario_en_un_miercoles_a_mano():
    grafo = grafo_diario()
    for dispositivo in _dispositivos():
        vista, corte = GrafoDiario(grafo, dispositivo).en_semanas(CORTE)
        a = vista.atributos(corte)["usuario"].cpu()
        esperado = torch.tensor([
            # total, últimos 28 días, ⌈semanas desde el último⌉, ⌈semanas desde el primero⌉, Action, Comedy, Drama
            [L(2), L(2), L(1), L(2), 0, 0.5, 0.5],  # usuario 1: D (película 1), D + 8 (película 2)
            [L(2), L(2), L(1), L(2), 0, 0.5, 1.0],  # usuario 2: D + 1 (película 3), D + 2 (película 1)
            [L(1), L(0), L(6), L(6), 0, 0.0, 1.0],  # usuario 3: D − 30, fuera de los 28 días
            [0, 0, 0, 0, 0, 0, 0],                  # usuario 4: su primer rating es el día del corte
        ])
        assert torch.allclose(a, esperado, atol=1e-6), a


def test_en_un_lunes_las_entradas_son_las_de_la_semana():
    grafo = grafo_diario()
    for dispositivo in _dispositivos():
        diario = GrafoDiario(grafo, dispositivo)
        for semana in (S0, S0 + 1, S0 + 2):
            vista, corte = diario.en_semanas(semana * 7 - 3)
            for relacion in (CALIFICA, CALIFICADA_POR):
                assert torch.equal(vista.adyacencias(corte)[relacion].to_dense(), diario.semanal.adyacencias(semana)[relacion].to_dense())
            for tipo in ("usuario", "pelicula"):
                assert torch.equal(vista.atributos(corte)[tipo], diario.semanal.atributos(semana)[tipo]), (semana, tipo)


def test_objetivos_candidatas_y_popularidad_del_dia():
    grafo = grafo_diario()
    for dispositivo in _dispositivos():
        diario = GrafoDiario(grafo, dispositivo)
        usuarios, peliculas, excluidas = diario.objetivos(CORTE)
        # Ese día: 1→3 (cuenta) y 4→2 (usuario sin historia: se excluye)
        assert usuarios.tolist() == [0] and peliculas.tolist() == [2] and excluidas == 1
        assert diario.peliculas_conocidas(CORTE).tolist() == [0, 1, 2]
        assert diario.popularidad(CORTE).cpu().tolist() == [3, 1, 1, 0]
        assert diario.popularidad(CORTE, 7).cpu().tolist() == [1, 1, 0, 0]  # D + 2 y D + 8
        assert diario.popularidad(CORTE, 1).cpu().tolist() == [0, 1, 0, 0]


def test_evaluar_dias_salta_los_dias_sin_objetivos():
    grafo = grafo_diario()
    diario = GrafoDiario(grafo, torch.device("cpu"))
    # Objetivos: CORTE (1→3) y D + 10 (2→2); D + 11 no tiene ninguno
    por_dia, por_usuario = evaluar_dias(grafo, diario, [CORTE, D + 10, D + 11],
                                        lambda d: puntuar_por_popularidad(diario.popularidad(d, 7)), "prueba")
    assert por_dia["dia"].tolist() == [CORTE, D + 10] and por_usuario["dia"].tolist() == [CORTE, D + 10]
    # CORTE: al usuario 1 sólo le queda la 3 (ya calificó 1 y 2; la 4 no existe), así que acierta en la posición 1
    assert por_dia.loc[0, "recall@10"] == 1 and por_dia.loc[0, "mrr"] == 1
    # D + 10: el usuario 2 (ya calificó 1 y 3) sólo puede recibir la 2, que es su objetivo
    assert por_dia.loc[1, "recall@10"] == 1
    # Con el corte del lunes (D + 7), el día D + 10 la película 2 (primer rating en D + 8) no es candidata:
    # las conocidas son sólo 1 y 3, y al usuario 2 (que ya las calificó) no le queda ninguna en su top.
    # (No se mira el recall: con menos candidatas que K el top se rellena con descartadas en −inf,
    # algo que con las ~80 mil candidatas reales y K ≤ 50 no ocurre.)
    semanal, _ = evaluar_dias(grafo, diario, [D + 10], lambda d: puntuar_por_popularidad(diario.popularidad(d, 7)), "prueba",
                              corte_semanal=True)
    assert semanal.loc[0, "cobertura@10"] == 0 and math.isclose(por_dia.loc[1, "cobertura@10"], 1 / 3)


class _PuntajesFijos(torch.nn.Module):
    """Mismo puntaje para todos los usuarios: películas 1 > 2 > 3 > 4."""

    def __init__(self, n_usuarios):
        super().__init__()
        self.n_usuarios = n_usuarios
        self.register_buffer("z_pelicula", torch.tensor([[5.0], [4.0], [3.0], [2.0]]))

    def forward(self, adyacencias, semanales=None):
        return torch.ones(self.n_usuarios, 1), self.z_pelicula


def _recomendador():
    grafo = grafo_diario()
    return Recomendador(grafo, MOVIES, _PuntajesFijos(grafo.n_usuarios), {"vida_media": None, "atributos_semanales": False})


def test_top_k_sin_historial_ni_peliculas_desconocidas():
    r = _recomendador()
    tabla = r.recomendar([1, 2, 3, 4], fecha_de_dia(CORTE), k=10)
    # 1 ya calificó 1 y 2; 2 ya calificó 1 y 3; 3 sólo 1. La película 4 todavía no existe.
    assert tabla.groupby("userId")["movieId"].apply(list).to_dict() == {1: [3], 2: [2], 3: [2, 3]}
    assert tabla.loc[tabla["userId"] == 3, "posicion"].tolist() == [1, 2]
    assert tabla.loc[tabla["userId"] == 1, "acierto"].tolist() == [True]  # 1 calificó la 3 ese día
    assert not tabla.loc[tabla["userId"] != 1, "acierto"].any()          # 2 calificó la 2 al día siguiente
    assert r.sin_historial == [4]
    assert tabla.loc[0, "generos"] == "Drama · Comedy" and tabla.loc[0, "titulo"] == "Película 3 (2003)"


def test_top_k_al_dia_siguiente_ya_cuenta_lo_del_dia():
    # Con corte semanal (lunes D + 7), al usuario 1 se le seguiría recomendando la película 3
    r = _recomendador()
    tabla = r.recomendar([1, 4], fecha_de_dia(CORTE + 1), k=10)
    assert 1 not in set(tabla["userId"])                                  # ya calificó 1, 2 y 3
    assert tabla.loc[tabla["userId"] == 4, "movieId"].tolist() == [1, 3]  # 4 ya tiene historia (la 2)
    assert r.sin_historial == []


def test_usuario_desconocido():
    try:
        _recomendador().recomendar([1, 99], fecha_de_dia(CORTE))
        raise AssertionError("debió fallar con un userId que no está en los datos")
    except ValueError as error:
        assert "99" in str(error)


if __name__ == "__main__":
    for nombre, prueba in list(globals().items()):
        if nombre.startswith("test_"):
            prueba()
            print(f"OK: {nombre}")
