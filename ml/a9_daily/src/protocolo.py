"""Protocolo de evaluación: partición temporal y evaluación semana a semana.

Partición (propuesta, fase de preparación de datos; acordada en la etapa 1):
- Entrenamiento: semanas objetivo hasta la del 27-dic-2021.
- Validación: las 52 semanas de 2022 (03-ene a 26-dic). Eligen hiperparámetros.
- Test: las 40 semanas completas de 2023 (02-ene a 02-oct). Se miran una vez por
  configuración final. La semana del 09-oct-2023 está incompleta y no se usa.
Una semana pertenece al año de su lunes. Para predecir la semana w, cualquier
método sólo ve los datos anteriores a w; los atributos se recalculan cada semana.

Uso, desde la raíz del proyecto (verifica el protocolo con las popularidades):
    python -m src.protocolo
"""

import json
import time
import warnings

import pandas as pd
import torch

from src import datos
from src.evaluacion import KS, evaluar_semana, nombres_metricas, puntuar_por_popularidad

AÑO_VALIDACION = 2022
AÑO_TEST = 2023
DIR_RESULTADOS = datos.RAIZ / "resultados" / "protocolo"
DISPOSITIVO = torch.device("cuda" if torch.cuda.is_available() else "cpu")

warnings.filterwarnings("ignore", message="Sparse CSR tensor support is in beta")


def semanas_del_año(año, ultima_semana):
    """Semanas cuyo lunes cae en `año`, sin la última semana de los datos (incompleta)."""
    desde = datos.semana(int(pd.Timestamp(f"{año}-01-01").timestamp()))
    hasta = datos.semana(int(pd.Timestamp(f"{año}-12-31").timestamp()))
    return [s for s in range(desde, hasta + 1) if datos.inicio_semana(s).year == año and s < ultima_semana]


def particion(grafo):
    """Semanas de validación y test. Los objetivos de entrenamiento son las semanas anteriores a la validación."""
    validacion = semanas_del_año(AÑO_VALIDACION, grafo.ultima_semana)
    test = semanas_del_año(AÑO_TEST, grafo.ultima_semana)
    return {"validacion": validacion, "test": test}


def evaluar_semanas(grafo, semanas, puntuador_de_semana, metodo):
    """Evalúa un método en varias semanas.

    `puntuador_de_semana(semana, adyacencias)` devuelve la función `puntuar(usuarios)`
    de esa semana; debe usar sólo datos anteriores a `semana`.
    Devuelve (por_semana, por_usuario) como DataFrames con una columna `metodo`.
    """
    resumenes, tablas = [], []
    for semana in semanas:
        adyacencias = grafo.adyacencias(semana)
        resumen, por_usuario = evaluar_semana(grafo, semana, adyacencias, puntuador_de_semana(semana, adyacencias))
        resumenes.append({"semana": semana, "fecha": fecha(semana), **resumen})
        tablas.append(por_usuario)
    por_semana = pd.DataFrame(resumenes)
    por_usuario = pd.concat(tablas, ignore_index=True)
    por_semana.insert(0, "metodo", metodo)
    por_usuario.insert(0, "metodo", metodo)
    return por_semana, por_usuario


def popularidad(grafo, semanas_atras=None):
    """Puntuador de popularidad (histórica si `semanas_atras` es None), en DISPOSITIVO."""
    return lambda semana, _: puntuar_por_popularidad(grafo.popularidad(semana, semanas_atras).to(DISPOSITIVO))


def guardar(por_semana, por_usuario, nombre, particion_):
    """Escribe resultados/protocolo/<particion>/<nombre>_{semanas.csv,usuarios.parquet}."""
    carpeta = DIR_RESULTADOS / particion_
    carpeta.mkdir(parents=True, exist_ok=True)
    por_semana.to_csv(carpeta / f"{nombre}_semanas.csv", index=False)
    por_usuario.to_parquet(carpeta / f"{nombre}_usuarios.parquet", index=False)


def anotar_ablacion(etapa, metodo, config, por_semana, particion_, segundos):
    """Agrega (o reemplaza, si ya existe) la fila de una corrida en resultados/ablacion.csv.

    Una fila por (etapa, método, partición): configuración completa en JSON y el
    promedio entre semanas de cada métrica.
    """
    ruta = datos.RAIZ / "resultados" / "ablacion.csv"
    metricas = nombres_metricas() + [f"cobertura@{k}" for k in KS]
    fila = {"registrado": time.strftime("%Y-%m-%d %H:%M"), "etapa": etapa, "metodo": metodo, "particion": particion_,
            "semanas": len(por_semana), **{m: round(float(por_semana[m].mean()), 6) for m in metricas},
            "segundos": round(segundos), "configuracion": json.dumps(config, ensure_ascii=False, sort_keys=True)}
    tabla = pd.read_csv(ruta) if ruta.exists() else pd.DataFrame(columns=list(fila))
    misma = (tabla["etapa"] == etapa) & (tabla["metodo"] == metodo) & (tabla["particion"] == particion_)
    tabla = pd.concat([tabla[~misma], pd.DataFrame([fila])], ignore_index=True)
    tabla.to_csv(ruta, index=False)


def fecha(semana):
    return str(datos.inicio_semana(semana).date())


def registrar(mensaje):
    print(f"[{time.strftime('%H:%M:%S')}] {mensaje}", flush=True)


def main():
    from src.estadistica import comparar
    from src.grafo import GrafoTemporal

    inicio = time.time()
    grafo = GrafoTemporal()
    semanas = particion(grafo)
    registrar(f"Grafo cargado en {time.time() - inicio:.0f} s. Dispositivo: {DISPOSITIVO}. "
              f"Validación: {len(semanas['validacion'])} semanas ({fecha(semanas['validacion'][0])} a {fecha(semanas['validacion'][-1])}); "
              f"test: {len(semanas['test'])} semanas ({fecha(semanas['test'][0])} a {fecha(semanas['test'][-1])})")

    # 1. El código nuevo debe reproducir las métricas del experimento 02 (mismas 8 semanas,
    #    números ya publicados; no se usa para elegir nada). Sólo pueden cambiar por empates
    #    en el borde del top 20, que antes desempataba torch.topk y ahora `evaluacion.top`.
    anterior = json.loads((datos.RAIZ / "resultados" / "experimento_inicial" / "ultimas_52_semanas" / "metricas.json").read_text(encoding="utf-8"))
    for nombre, semanas_atras in (("Popularidad histórica", None), ("Popularidad reciente (4 semanas)", 4)):
        esperado = pd.DataFrame(anterior[nombre]["validacion"] + anterior[nombre]["test"])
        semanas_02 = [datos.semana(int(pd.Timestamp(f).timestamp())) for f in esperado["semana"]]
        nuevo, _ = evaluar_semanas(grafo, semanas_02, popularidad(grafo, semanas_atras), nombre)
        for metrica in ("recall@20", "ndcg@20"):
            maximo = (nuevo[metrica] - esperado[metrica]).abs().max()
            registrar(f"Reproducción exp. 02, {nombre}, {metrica}: diferencia máxima por semana {maximo:.2e}")
        if DISPOSITIVO.type == "cuda":  # en CPU debe salir lo mismo, salvo redondeo de float32
            en_cpu, _ = evaluar_semanas(grafo, semanas_02, lambda semana, _: puntuar_por_popularidad(grafo.popularidad(semana, semanas_atras)), nombre)
            maximo = (nuevo[nombres_metricas()] - en_cpu[nombres_metricas()]).abs().to_numpy().max()
            registrar(f"{nombre}: diferencia máxima entre CPU y GPU, todas las métricas: {maximo:.1e}")

    # 2. Las dos popularidades del experimento 02 con el protocolo nuevo, en validación (2022)
    metodos = {"popularidad_historica": None, "popularidad_reciente_4": 4}
    tablas = []
    for nombre, semanas_atras in metodos.items():
        por_semana, por_usuario = evaluar_semanas(grafo, semanas["validacion"], popularidad(grafo, semanas_atras), nombre)
        guardar(por_semana, por_usuario, nombre, "validacion")
        tablas.append(por_semana)
        registrar(f"{nombre}: " + " ".join(f"{m} {por_semana[m].mean():.4f}" for m in ("recall@20", "ndcg@20", "mrr", "cobertura@20")))

    # 3. Ejemplo del protocolo estadístico (validación): reciente vs. histórica
    comparacion = comparar(pd.concat(tablas), "popularidad_reciente_4", ["popularidad_historica"], ["recall@20", "ndcg@20"])
    comparacion.to_csv(DIR_RESULTADOS / "validacion" / "comparacion_popularidades.csv", index=False)
    registrar("Comparación en validación:\n" + comparacion.to_string(index=False))
    registrar(f"Listo en {(time.time() - inicio) / 60:.1f} minutos")


if __name__ == "__main__":
    main()
