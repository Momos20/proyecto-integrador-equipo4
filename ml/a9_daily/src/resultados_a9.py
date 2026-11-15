"""Resultados de GraphSAGE A9 en una página HTML autónoma (resultados/a9/resultados_a9.html).

La página muestra:
- Recomendaciones de ejemplo: el top 10 de A9 para 3 usuarios en 3 semanas de test
  (la primera, la del medio y la última de 2023), marcando las películas que el usuario
  calificó esa semana. Los usuarios son los que calificaron algo en las 3 semanas; de
  ellos se toma el de historial corto, medio y largo (percentiles 10, 50 y 90 del número
  de ratings antes de la primera semana).
- Géneros: fracción de cada género en el historial del usuario frente al top 20 de A9.
- Curva de entrenamiento de A9 (resultados/graphsage/A9_sin_id/curva.csv).
- Recall@20 y NDCG@20 por semana de A9 frente a la popularidad de la semana anterior,
  en validación (2022) y test (2023) (resultados/protocolo/).
- Comparación en test con las líneas base (resultados/h1_test_resumen.csv).
- Validación externa con las visitas de Wikipedia (resultados/wikipedia/, de src/wikipedia.py).

Las recomendaciones usan los pesos guardados en resultados/graphsage/A9_sin_id/modelo.pt,
que son los de la corrida de validación (objetivos hasta dic-2021, mejor paso de la parada
temprana). Las métricas de test vienen del reentrenamiento con objetivos hasta dic-2022,
cuyos pesos no se guardan. Igual que en el protocolo, para la semana w el modelo sólo ve
los datos anteriores a w y sólo recomienda películas conocidas que el usuario no ha calificado.

La página es src/resultados_a9.html; aquí se le agregan los datos, d3 (vendor/) y los
mismos colores del dashboard del EDA. Se abre con doble clic, sin internet.

Uso, desde la raíz del proyecto (corre en CPU, unos minutos; necesita resultados/ completo,
incluido resultados/wikipedia/ de `python -m src.wikipedia`):
    python -m src.resultados_a9
"""

import json
import time

import numpy as np
import pandas as pd
import torch

from src import datos
from src.dashboard import D3, TOKENS
from src.entrenamiento import config_de, crear_modelo, representaciones
from src.evaluacion import top
from src.hipotesis import LINEAS_BASE, MODELO
from src.protocolo import DIR_RESULTADOS, fecha, particion, registrar
from src.temporal import GrafoEnDispositivo
from src.wikipedia import SALIDA as DIR_WIKIPEDIA

NOMBRE = "A9_sin_id"
CARPETA_A9 = datos.RAIZ / "resultados" / "graphsage" / NOMBRE
PAGINA = datos.RAIZ / "src" / "resultados_a9.html"
SALIDA = datos.RAIZ / "resultados" / "a9" / "resultados_a9.html"
LINEA_BASE = ("Popularidad semana anterior", LINEAS_BASE["Popularidad semana anterior"])
GRUPOS = {"corto": 0.1, "medio": 0.5, "largo": 0.9}  # percentil del historial de cada usuario de ejemplo
N_TOP = 10      # recomendaciones que se muestran
N_GENEROS = 20  # recomendaciones con las que se calcula el perfil de géneros (el K principal)


def semanas_de_ejemplo(semanas_test):
    """La primera, la del medio y la última semana de test."""
    return [semanas_test[0], semanas_test[len(semanas_test) // 2], semanas_test[-1]]


def elegir_usuarios(grafo, semanas):
    """{grupo: índice de usuario}: entre los que calificaron algo en todas las `semanas`,
    el más cercano a cada percentil de GRUPOS en ratings antes de la primera semana
    (los empates van al índice menor)."""
    activos = None
    for semana in semanas:
        usuarios = set(torch.unique(grafo.objetivos(semana)[0]).tolist())
        activos = usuarios if activos is None else activos & usuarios
    if len(activos) < len(GRUPOS):
        raise ValueError(f"Sólo {len(activos)} usuarios calificaron algo en las {len(semanas)} semanas")
    activos = np.array(sorted(activos))
    usuarios_previos, _ = grafo.aristas(grafo.primera_semana, semanas[0])
    historial = torch.bincount(usuarios_previos, minlength=grafo.n_usuarios).numpy()[activos]
    elegidos = {}
    for grupo, percentil in GRUPOS.items():
        distancia = np.abs(historial - np.quantile(historial, percentil))
        distancia[np.isin(activos, list(elegidos.values()))] = np.inf  # un usuario por grupo
        elegidos[grupo] = int(activos[np.argmin(distancia)])
    return elegidos


def ranking(grafo, semana, usuarios, puntajes):
    """Para cada usuario: su historial antes de `semana`, su ranking de películas candidatas
    (conocidas antes de la semana y no calificadas por él; las demás quedan en -inf) y las
    películas que calificó en la semana (objetivos del protocolo).

    `puntajes` es una matriz [len(usuarios), n_peliculas]. Devuelve una lista de
    {"historial", "orden", "puntajes", "objetivos"} (índices de película), uno por usuario.
    """
    puntajes = puntajes.clone()
    puntajes[:, grafo.semana_alta_pelicula >= semana] = -torch.inf
    usuarios_previos, peliculas_previas = grafo.aristas(grafo.primera_semana, semana)
    usuarios_objetivo, peliculas_objetivo, _ = grafo.objetivos(semana)
    resultado = []
    for fila, usuario in enumerate(usuarios):
        historial = peliculas_previas[usuarios_previos == usuario]
        puntajes[fila, historial] = -torch.inf
        resultado.append({
            "historial": historial,
            "orden": top(puntajes[fila:fila + 1], grafo.n_peliculas)[0],
            "puntajes": puntajes[fila],
            "objetivos": peliculas_objetivo[usuarios_objetivo == usuario],
        })
    return resultado


def perfil_de_generos(peliculas, generos_por_pelicula):
    """Fracción de las películas en cada género (una película cuenta en todos los suyos)."""
    conteo = pd.Series([g for p in peliculas for g in generos_por_pelicula[p]]).value_counts()
    return (conteo / max(len(peliculas), 1)).to_dict()


def recomendaciones(grafo, en_dispositivo, modelo, config, semanas, elegidos):
    """Filas de recomendaciones (top N_TOP con aciertos y lo que el usuario vio) y de géneros."""
    movies = datos.cargar("movies")
    titulos = movies["title"].tolist()
    generos_por_pelicula = [g.split("|") for g in movies["genres"]]
    filas, filas_generos = [], []
    for semana in semanas:
        with torch.no_grad():
            z_usuario, z_pelicula = representaciones(modelo, en_dispositivo, semana, config)
        usuarios = torch.tensor(list(elegidos.values()))
        for (grupo, usuario), r in zip(elegidos.items(), ranking(grafo, semana, usuarios, z_usuario[usuarios] @ z_pelicula.T)):
            objetivos = set(r["objetivos"].tolist())
            superan = lambda p: int((r["puntajes"] > r["puntajes"][p]).sum()) + 1  # posición en el ranking
            filas.append({
                "grupo": grupo, "usuario": int(grafo.ids_usuario[usuario]), "semana": fecha(semana),
                "n_historial": len(r["historial"]),
                "recomendadas": [{"posicion": i + 1, "titulo": titulos[p], "generos": " · ".join(generos_por_pelicula[p]),
                                  "acierto": p in objetivos} for i, p in enumerate(r["orden"][:N_TOP].tolist())],
                "vistas": sorted(({"titulo": titulos[p], "generos": " · ".join(generos_por_pelicula[p]), "posicion": superan(p)}
                                  for p in objetivos), key=lambda v: v["posicion"]),
            })
            historial = perfil_de_generos(r["historial"].tolist(), generos_por_pelicula)
            recomendado = perfil_de_generos(r["orden"][:N_GENEROS].tolist(), generos_por_pelicula)
            for genero in sorted(set(historial) | set(recomendado)):
                filas_generos.append({"usuario": filas[-1]["usuario"], "semana": fecha(semana), "genero": genero,
                                      "historial": round(historial.get(genero, 0.0), 4),
                                      "recomendado": round(recomendado.get(genero, 0.0), 4)})
    return filas, filas_generos


def metricas_por_semana():
    """Recall@20 y NDCG@20 por semana de A9 y de la línea base, en validación y test."""
    tablas = []
    for particion_ in ("validacion", "test"):
        for metodo, archivo in (MODELO, LINEA_BASE):
            tabla = pd.read_csv(DIR_RESULTADOS / particion_ / f"{archivo}_semanas.csv")
            tablas.append(tabla[["fecha", "recall@20", "ndcg@20"]].assign(metodo=metodo, particion=particion_))
    return pd.concat(tablas).round(5).to_dict("records")


def comparacion_test():
    """Promedio en las semanas de test de A9 y de cada línea base (el resumen de H1)."""
    resumen = pd.read_csv(datos.RAIZ / "resultados" / "h1_test_resumen.csv")
    return resumen[["metodo", "recall@20", "ndcg@20", "hitrate@20", "mrr"]].round(4).to_dict("records")


def curva():
    """Curva de la corrida de validación de A9 y su mejor paso."""
    validacion = json.loads((CARPETA_A9 / "validacion.json").read_text(encoding="utf-8"))
    return {"mejor_paso": validacion["mejor_paso"], "puntos": pd.read_csv(CARPETA_A9 / "curva.csv").round(5).to_dict("records")}


def wikipedia():
    """Resultados de src/wikipedia.py: métricas por semana, series de ejemplo y cobertura."""
    return {
        "semanal": pd.read_csv(DIR_WIKIPEDIA / "semanal.csv").round(4).to_dict("records"),
        "ejemplos": pd.read_csv(DIR_WIKIPEDIA / "ejemplos.csv").to_dict("records"),
        "cobertura": json.loads((DIR_WIKIPEDIA / "cobertura.json").read_text(encoding="utf-8")),
    }


def escribir_html(datos_pagina):
    en_script = lambda texto: texto.replace("</", "<\\/")  # que ningún texto cierre el <script> antes de tiempo
    html = "\n".join([
        "<!doctype html>",
        '<html lang="es">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Resultados GraphSAGE A9</title>",
        f"<style>{TOKENS}</style>",
        f"<script>{D3.read_text(encoding='utf-8')}</script>",
        f"<script>window.DATOS_A9 = {en_script(json.dumps(datos_pagina, ensure_ascii=False, separators=(',', ':')))};</script>",
        "</head>",
        "<body>",
        PAGINA.read_text(encoding="utf-8"),
        "</body>",
        "</html>",
    ])
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(html, encoding="utf-8")
    registrar(f"{SALIDA} ({SALIDA.stat().st_size / 1e6:.1f} MB)")


def main():
    from src.grafo import GrafoTemporal

    inicio = time.time()
    cpu = torch.device("cpu")
    grafo = GrafoTemporal()
    en_dispositivo = GrafoEnDispositivo(grafo, cpu)
    config = config_de(NOMBRE)
    modelo = crear_modelo(grafo, en_dispositivo, config).to(cpu)
    modelo.load_state_dict(torch.load(CARPETA_A9 / "modelo.pt", map_location=cpu))
    modelo.eval()
    registrar(f"Grafo y modelo cargados en {time.time() - inicio:.0f} s")

    semanas = semanas_de_ejemplo(particion(grafo)["test"])
    elegidos = elegir_usuarios(grafo, semanas)
    registrar("Usuarios de ejemplo: " + ", ".join(f"{g} = {grafo.ids_usuario[u]}" for g, u in elegidos.items()))
    filas, filas_generos = recomendaciones(grafo, en_dispositivo, modelo, config, semanas, elegidos)
    escribir_html({
        "generado": time.strftime("%Y-%m-%d"),
        "recomendaciones": filas, "generos": filas_generos,
        "curva": curva(), "semanal": metricas_por_semana(), "comparacion": comparacion_test(), "wikipedia": wikipedia(),
        "linea_base": LINEA_BASE[0], "modelo": MODELO[0],
    })
    registrar(f"Listo en {(time.time() - inicio) / 60:.1f} min")


if __name__ == "__main__":
    main()
