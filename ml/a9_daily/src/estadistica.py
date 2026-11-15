"""Comparaciones pareadas entre métodos, semana a semana (protocolo de la propuesta).

La unidad de análisis es la semana: la métrica de un método en una semana es el
promedio sobre los usuarios evaluados en ella, y dos métodos se comparan con la
diferencia de esas métricas en las mismas semanas.
- Prueba de rangos con signo de Wilcoxon, bilateral, sobre las diferencias semanales.
- IC al 95 % de la diferencia media con bootstrap de bloques móviles: se remuestrean
  bloques de semanas consecutivas, porque las semanas vecinas comparten usuarios y
  películas de moda y sus diferencias no son independientes. Con bloque = 1 es el
  bootstrap i.i.d. de siempre (sirve también para remuestrear usuarios en H3).
- Corrección de Holm sobre la familia de comparaciones.

Para el EDA, dos herramientas descriptivas: el ajuste de una ley de potencia a los
grados del grafo y el PSI, que mide cuánto cambia una distribución entre dos periodos.
"""

import numpy as np
import pandas as pd
from scipy import optimize, special, stats

NIVEL = 0.95
REPLICAS = 10_000
BLOQUE = 4  # semanas


def wilcoxon(diferencias):
    """Valor p bilateral de Wilcoxon para la mediana de las diferencias = 0."""
    return float(stats.wilcoxon(diferencias, alternative="two-sided").pvalue)


def bootstrap_media(valores, bloque=BLOQUE, replicas=REPLICAS, nivel=NIVEL, semilla=0):
    """IC percentil de la media con bootstrap de bloques móviles (Künsch, 1989).

    Cada réplica concatena bloques de `bloque` valores consecutivos, con inicio al azar,
    hasta completar len(valores), y calcula su media.
    """
    valores = np.asarray(valores, dtype=float)
    n = len(valores)
    azar = np.random.default_rng(semilla)
    n_bloques = -(-n // bloque)  # techo de n / bloque
    inicios = azar.integers(0, n - bloque + 1, size=(replicas, n_bloques))
    indices = (inicios[:, :, None] + np.arange(bloque)).reshape(replicas, -1)[:, :n]
    medias = valores[indices].mean(axis=1)
    alfa = (1 - nivel) / 2
    return float(np.quantile(medias, alfa)), float(np.quantile(medias, 1 - alfa))


def holm(valores_p):
    """Valores p ajustados por Holm (1979), en el mismo orden de entrada."""
    valores_p = np.asarray(valores_p, dtype=float)
    m = len(valores_p)
    orden = np.argsort(valores_p)
    ajustados = np.minimum(1, np.maximum.accumulate((m - np.arange(m)) * valores_p[orden]))
    resultado = np.empty(m)
    resultado[orden] = ajustados
    return resultado


def comparar(por_semana, modelo, referencias, metricas, bloque=BLOQUE, semilla=0):
    """Tabla de comparaciones de `modelo` contra cada método de `referencias`.

    `por_semana` es un DataFrame con columnas semana, metodo y una por métrica (una fila
    por método y semana). Todas las filas de la tabla forman una sola familia de Holm.
    """
    ancho = por_semana.pivot(index="semana", columns="metodo")
    filas = []
    for referencia in referencias:
        for metrica in metricas:
            diferencia = (ancho[(metrica, modelo)] - ancho[(metrica, referencia)]).to_numpy()
            bajo, alto = bootstrap_media(diferencia, bloque=bloque, semilla=semilla)
            filas.append({
                "modelo": modelo, "referencia": referencia, "metrica": metrica, "semanas": len(diferencia),
                "media_modelo": ancho[(metrica, modelo)].mean(), "media_referencia": ancho[(metrica, referencia)].mean(),
                "diferencia": diferencia.mean(), "ic_bajo": bajo, "ic_alto": alto,
                "semanas_gana": int((diferencia > 0).sum()), "p": wilcoxon(diferencia),
            })
    tabla = pd.DataFrame(filas)
    tabla["p_holm"] = holm(tabla["p"])
    tabla["significativa"] = tabla["p_holm"] < 1 - NIVEL
    return tabla


def bootstrap_por_conglomerados(valores, grupos, x=None, replicas=REPLICAS, nivel=NIVEL, semilla=0, lote=500):
    """IC percentil remuestreando conglomerados completos (p. ej. usuarios con todas sus semanas).

    Sin `x`, el estadístico es la media de `valores`. Con `x`, es la pendiente de la
    regresión lineal de `valores` sobre `x` (mínimos cuadrados). Devuelve
    (estimado, ic_bajo, ic_alto, p), con p bilateral de que el estadístico sea 0
    (proporción de réplicas al otro lado del 0, por dos).
    """
    tabla = pd.DataFrame({"g": grupos, "y": np.asarray(valores, float)})
    if x is not None:
        tabla["x"] = np.asarray(x, float)
        tabla["xy"], tabla["xx"] = tabla["x"] * tabla["y"], tabla["x"] ** 2
    por_grupo = tabla.groupby("g")
    sumas, n = por_grupo.sum(), por_grupo.size().to_numpy(float)

    def estadistico(pesos):  # pesos: [réplicas, conglomerados]
        if x is None:
            return (pesos @ sumas["y"].to_numpy()) / (pesos @ n)
        total = pesos @ n
        sx, sy = pesos @ sumas["x"].to_numpy(), pesos @ sumas["y"].to_numpy()
        sxy, sxx = pesos @ sumas["xy"].to_numpy(), pesos @ sumas["xx"].to_numpy()
        return (sxy - sx * sy / total) / (sxx - sx ** 2 / total)

    estimado = float(estadistico(np.ones((1, len(n))))[0])
    azar = np.random.default_rng(semilla)
    replicas_valores = []
    for inicio in range(0, replicas, lote):
        pesos = azar.multinomial(len(n), np.full(len(n), 1 / len(n)), size=min(lote, replicas - inicio)).astype(float)
        replicas_valores.append(estadistico(pesos))
    replicas_valores = np.concatenate(replicas_valores)
    alfa = (1 - nivel) / 2
    p = min(1.0, 2 * min((replicas_valores <= 0).mean(), (replicas_valores >= 0).mean()))
    return estimado, float(np.quantile(replicas_valores, alfa)), float(np.quantile(replicas_valores, 1 - alfa)), p


def ajustar_ley_potencia(valores, x_min=None, cola_minima=50):
    """Ley de potencia discreta P(k) ∝ k^-α para k ≥ x_min (Clauset, Shalizi y Newman, 2009).

    α es el estimador de máxima verosimilitud exacto, con la zeta de Hurwitz como
    constante de normalización. Sin `x_min`, se prueba cada valor observado que deja al
    menos `cola_minima` observaciones en la cola y se elige el que minimiza la distancia
    KS entre la CCDF empírica y la ajustada. Devuelve un dict con alfa, x_min,
    error_estandar ((α − 1) / √n), ks y n_cola.
    """
    k, conteo = np.unique(np.asarray(valores, dtype=np.int64), return_counts=True)
    # Tamaño y suma de logaritmos de la cola que empieza en cada valor observado
    n_desde = np.cumsum(conteo[::-1])[::-1]
    log_desde = np.cumsum((conteo * np.log(k))[::-1])[::-1]
    inicios = np.flatnonzero(n_desde >= cola_minima) if x_min is None else [np.searchsorted(k, x_min)]

    mejor = None
    for i in inicios:
        x0 = k[i] if x_min is None else x_min
        n, suma_log = n_desde[i], log_desde[i]
        alfa = optimize.minimize_scalar(lambda a: n * np.log(special.zeta(a, x0)) + a * suma_log,
                                        bounds=(1.001, 10), method="bounded").x
        # La CCDF empírica es escalonada y la ajustada decrece: la mayor distancia está
        # en un valor observado o justo después de él
        en_k = n_desde[i:] / n
        despues = en_k - conteo[i:] / n
        normalizacion = special.zeta(alfa, x0)
        ks = max(np.abs(en_k - special.zeta(alfa, k[i:]) / normalizacion).max(),
                 np.abs(despues - special.zeta(alfa, k[i:] + 1) / normalizacion).max())
        if mejor is None or ks < mejor["ks"]:
            mejor = {"alfa": float(alfa), "x_min": int(x0), "error_estandar": float((alfa - 1) / np.sqrt(n)),
                     "ks": float(ks), "n_cola": int(n)}
    return mejor


def psi(referencia, actual, cuantiles=10, piso=1e-4):
    """Índice de estabilidad poblacional: Σ (a − r) · ln(a / r) sobre intervalos de la referencia.

    Los cortes son los cuantiles únicos de `referencia`; con valores enteros hay empates
    y puede haber menos de `cuantiles` intervalos. Las proporciones se acotan por abajo
    con `piso` para que un intervalo vacío no dé log(0). Umbrales usuales: < 0.1 estable,
    0.1–0.25 cambio moderado, > 0.25 cambio grande.
    """
    referencia, actual = np.asarray(referencia, dtype=float), np.asarray(actual, dtype=float)
    cortes = np.unique(np.quantile(referencia, np.linspace(0, 1, cuantiles + 1)[1:-1]))
    r = np.bincount(np.searchsorted(cortes, referencia, side="right"), minlength=len(cortes) + 1) / len(referencia)
    a = np.bincount(np.searchsorted(cortes, actual, side="right"), minlength=len(cortes) + 1) / len(actual)
    r, a = np.maximum(r, piso), np.maximum(a, piso)
    return float(np.sum((a - r) * np.log(a / r)))
