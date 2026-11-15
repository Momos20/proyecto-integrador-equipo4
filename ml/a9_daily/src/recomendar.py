"""Top-K de GraphSAGE A9 para cualquier día (horizonte diario): función y comando.

Para la fecha d (día UTC), A9 ve sólo los ratings anteriores a d y ordena, para cada
usuario, las películas que ya existían antes de d y que él no ha calificado. Es la regla
del protocolo, con el día en lugar de la semana (src/diario.py explica el corte diario y
cómo se validó).

Los tres pasos, cada uno con su función:
1. Reconstruir el modelo: `cargar_a9` arma el SAGEHeterogeneo con la configuración de
   resultados/graphsage/A9_sin_id/validacion.json y le carga modelo.pt. Son los pesos de
   la corrida de validación (objetivos hasta la semana del 27-dic-2021); como A9 no tiene
   embeddings de ID, sirven para cualquier fecha posterior sin reentrenar.
2. Preparar las entradas: `GrafoDiario.en_semanas(dia)` arma la instantánea del grafo y los
   atributos de usuarios y películas con los ratings anteriores al día.
3. Generar el Top-K: `Recomendador.recomendar(usuarios, fecha, k)`.

Un usuario sin ningún rating antes de la fecha no recibe recomendaciones (el protocolo
nunca evaluó a A9 con ellos); queda en `Recomendador.sin_historial`. La columna `acierto`
dice si el usuario calificó esa película ese mismo día (sólo para mostrar; no entra al modelo).

Uso como módulo, desde la raíz del proyecto:
    from src.recomendar import Recomendador
    r = Recomendador.a9()                                # datos y modelo: ~20 s y ~5 GB de RAM
    tabla = r.recomendar([123, 456], "2023-06-15", k=10)  # DataFrame, una fila por recomendación

Uso como comando (CSV o JSON según la extensión de --salida):
    python -m src.recomendar --fecha 2023-06-15 --usuarios 123 456
    python -m src.recomendar --fecha 2023-06-15 2023-06-16 --activos --salida resultados/recomendaciones/top10.json
"""

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from src import datos
from src.diario import GrafoDiario, dia_de_fecha, fecha_de_dia
from src.entrenamiento import BASE, crear_modelo, representaciones
from src.evaluacion import historial_del_lote, top
from src.protocolo import registrar

CARPETA_A9 = datos.RAIZ.parent / "models" / "A9_sin_id"
SALIDA = datos.RAIZ / "resultados" / "recomendaciones"
COLUMNAS = ["fecha", "userId", "posicion", "movieId", "titulo", "generos", "puntaje", "acierto"]


def config_a9(carpeta=CARPETA_A9):
    """Configuración de A9 guardada junto a sus pesos, completada con BASE (como entrenamiento.config_de)."""
    guardada = json.loads((carpeta / "validacion.json").read_text(encoding="utf-8"))["config"]
    return {**BASE, **{k: v for k, v in guardada.items() if k in BASE}}


def cargar_a9(grafo, diario, carpeta=CARPETA_A9):
    """(modelo, config): A9 reconstruido con sus pesos, en el dispositivo de `diario` y en modo evaluación."""
    config = config_a9(carpeta)
    modelo = crear_modelo(grafo, diario, config).to(diario.dispositivo)
    modelo.load_state_dict(torch.load(carpeta / "modelo.pt", map_location=diario.dispositivo, weights_only=True))
    return modelo.eval(), config


class Recomendador:
    """Top-K diario de un modelo con la interfaz de SAGEHeterogeneo, sobre un GrafoTemporal(con_dias=True)."""

    def __init__(self, grafo, movies, modelo=None, config=None, dispositivo="cpu", carpeta=CARPETA_A9):
        """Sin `modelo`, reconstruye A9 con los pesos de `carpeta` (las pruebas pasan un modelo y su config)."""
        self.grafo = grafo
        self.diario = GrafoDiario(grafo, torch.device(dispositivo))
        if modelo is None:
            modelo, config = cargar_a9(grafo, self.diario, carpeta)
        self.modelo, self.config = modelo.to(self.diario.dispositivo).eval(), config
        fila = pd.Index(movies["movieId"]).get_indexer(grafo.ids_pelicula)
        self.titulos = movies["title"].to_numpy()[fila]
        self.generos = movies["genres"].str.replace("|", " · ", regex=False).to_numpy()[fila]
        self.sin_historial = []
        self._dia, self._z = None, None

    @classmethod
    def a9(cls, dispositivo="cpu", carpeta=CARPETA_A9):
        """Carga MovieLens 32M (data/processed/) y A9 con sus pesos guardados."""
        from src.grafo import GrafoTemporal

        return cls(GrafoTemporal(con_dias=True), datos.cargar("movies"), dispositivo=dispositivo, carpeta=carpeta)

    def representaciones(self, dia):
        """Embeddings de usuarios y películas con los ratings anteriores a `dia` (se guarda el último día)."""
        if self._dia != dia:
            with torch.no_grad():
                vista, corte = self.diario.en_semanas(dia)
                self._z = representaciones(self.modelo, vista, corte, self.config)
            self._dia = dia
        return self._z

    def indices(self, usuarios):
        """Índices internos de una lista de userId; error si alguno no está en los datos."""
        usuarios = np.asarray(usuarios, dtype=np.int64)
        indice = np.searchsorted(self.grafo.ids_usuario, usuarios).clip(max=self.grafo.n_usuarios - 1)
        faltan = usuarios[self.grafo.ids_usuario[indice] != usuarios]
        if len(faltan):
            raise ValueError(f"userId que no están en los datos: {faltan.tolist()}")
        return torch.from_numpy(indice)

    def activos(self, fecha):
        """userId de los usuarios con historia que calificaron algo ese día (los que evalúa el protocolo diario)."""
        usuarios, _, _ = self.diario.objetivos(dia_de_fecha(fecha))
        return self.grafo.ids_usuario[torch.unique(usuarios).numpy()].tolist()

    def recomendar(self, usuarios, fecha, k=10):
        """DataFrame con el Top-K de cada usuario para `fecha` (columnas de COLUMNAS, ordenado por usuario y posición)."""
        dia = dia_de_fecha(fecha)
        indices = self.indices(usuarios)
        con_historia = (self.diario.dia_alta_usuario[indices.to(self.diario.dispositivo)] < dia).cpu()
        self.sin_historial = self.grafo.ids_usuario[indices[~con_historia].numpy()].tolist()
        indices = indices[con_historia]
        if len(indices) == 0:
            return pd.DataFrame(columns=COLUMNAS)

        z_usuario, z_pelicula = self.representaciones(dia)
        puntajes = (z_usuario[indices.to(z_usuario.device)] @ z_pelicula.T).cpu()
        desconocida = torch.ones(self.grafo.n_peliculas, dtype=torch.bool)
        desconocida[self.diario.peliculas_conocidas(dia)] = False
        puntajes[:, desconocida] = -math.inf
        historial = self.diario.historial(dia)
        fila, pelicula = historial_del_lote(indices, historial.crow_indices(), historial.col_indices())
        puntajes[fila, pelicula] = -math.inf
        orden = top(puntajes, k)

        usuarios_dia, peliculas_dia = self.diario.calificadas_el_dia(dia)
        vistas = set(zip(usuarios_dia.tolist(), peliculas_dia.tolist()))
        filas = []
        for i, usuario in enumerate(indices.tolist()):
            for posicion, p in enumerate(orden[i].tolist(), start=1):
                puntaje = float(puntajes[i, p])
                if not math.isfinite(puntaje):  # menos de k candidatas
                    break
                filas.append({"fecha": fecha_de_dia(dia), "userId": int(self.grafo.ids_usuario[usuario]), "posicion": posicion,
                              "movieId": int(self.grafo.ids_pelicula[p]), "titulo": self.titulos[p], "generos": self.generos[p],
                              "puntaje": round(puntaje, 4), "acierto": (usuario, p) in vistas})
        return pd.DataFrame(filas, columns=COLUMNAS)


def escribir(tabla, ruta, k, sin_historial):
    """CSV (una fila por recomendación) o JSON (una entrada por usuario y día), según la extensión."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if ruta.suffix.lower() == ".json":
        entradas = [{"fecha": fecha, "userId": int(usuario),
                     "recomendaciones": grupo.drop(columns=["fecha", "userId"]).to_dict("records")}
                    for (fecha, usuario), grupo in tabla.groupby(["fecha", "userId"], sort=True)]
        contenido = {"modelo": "GraphSAGE A9 (sin embeddings de ID)", "pesos": (CARPETA_A9 / "modelo.pt").relative_to(datos.RAIZ.parent.parent).as_posix(),
                     "horizonte": "día siguiente: para la fecha d se usan sólo los ratings anteriores a d (UTC)",
                     "k": k, "generado": time.strftime("%Y-%m-%d"), "sin_historial": sin_historial, "recomendaciones": entradas}
        ruta.write_text(json.dumps(contenido, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        tabla.to_csv(ruta, index=False)


def main():
    argumentos = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    argumentos.add_argument("--fecha", nargs="+", required=True, help="una o más fechas AAAA-MM-DD (UTC)")
    quienes = argumentos.add_mutually_exclusive_group(required=True)
    quienes.add_argument("--usuarios", nargs="+", type=int, help="userId de MovieLens")
    quienes.add_argument("--activos", action="store_true", help="los usuarios con historia que calificaron algo ese día")
    argumentos.add_argument("--k", type=int, default=10)
    argumentos.add_argument("--salida", help="archivo .csv o .json (por defecto resultados/recomendaciones/top<k>.csv)")
    argumentos.add_argument("--gpu", action="store_true", help="usar la GPU (por defecto, CPU)")
    a = argumentos.parse_args()

    inicio = time.time()
    recomendador = Recomendador.a9("cuda" if a.gpu else "cpu")
    registrar(f"Datos y A9 cargados en {time.time() - inicio:.0f} s (último rating: {fecha_de_dia(recomendador.grafo.ultimo_dia)})")
    tablas, sin_historial = [], []
    for fecha in a.fecha:
        if dia_de_fecha(fecha) > recomendador.grafo.ultimo_dia + 1:
            registrar(f"Aviso: {fecha} es posterior al día siguiente al último rating; se usan todos los datos")
        usuarios = recomendador.activos(fecha) if a.activos else a.usuarios
        tabla = recomendador.recomendar(usuarios, fecha, a.k)
        tablas.append(tabla)
        sin_historial += [{"fecha": fecha, "userId": u} for u in recomendador.sin_historial]
        aciertos = tabla.groupby("userId")["acierto"].any().mean() if len(tabla) else float("nan")
        registrar(f"{fecha}: {tabla['userId'].nunique()} usuarios con Top-{a.k}, {len(recomendador.sin_historial)} sin historial; "
                  f"{aciertos:.0%} con al menos un acierto ese día")
    tabla = pd.concat(tablas, ignore_index=True)
    ruta = a.salida or SALIDA / f"top{a.k}.csv"
    escribir(tabla, ruta, a.k, sin_historial)
    registrar(f"{ruta}: {len(tabla)} filas. Listo en {time.time() - inicio:.0f} s")


if __name__ == "__main__":
    main()
