"""Datos del dashboard del EDA: agregados del notebook 01 exportados a JSON.

Cada archivo de resultados/dashboard/ es una fuente del dashboard "EDA MovieLens 32M"
(artifact en claude.ai): una lista de filas con los números que el notebook 01 muestra
en tablas y figuras. El cálculo es el mismo del notebook; si cambia uno, hay que cambiar
el otro. El dashboard guarda una copia fija de estos archivos: para actualizarlo, se
vuelven a generar y se reemplazan en el dashboard.

Con --html, en vez de recalcular, arma una versión autónoma del dashboard en un solo
archivo (resultados/dashboard/eda_movielens_32m.html) para compartir sin cuenta de
claude.ai: la página publicada (src/dashboard.html), los JSON ya generados, d3 7.9.0
(vendor/) y una imitación mínima de la API `dash` del dashboard. Funciona sin internet.

Uso, desde la raíz del proyecto:
    python -m src.dashboard           # recalcula los JSON (~2 minutos, ~5 GB de RAM)
    python -m src.dashboard --html    # arma el HTML autónomo con los JSON (segundos)
"""

import argparse
import json
import time
from functools import lru_cache

import numpy as np
import pandas as pd
from scipy import special, stats

from src import datos
from src.estadistica import ajustar_ley_potencia, psi
from src.protocolo import AÑO_TEST, AÑO_VALIDACION, registrar, semanas_del_año

SALIDA = datos.RAIZ / "resultados" / "dashboard"
PAGINA = datos.RAIZ / "src" / "dashboard.html"
D3 = datos.RAIZ / "vendor" / "d3-7.9.0" / "d3.min.js"
HTML_AUTONOMO = SALIDA / "eda_movielens_32m.html"
K = 20            # top de popularidad en la persistencia (E3)
HORIZONTE = 52     # semanas desde la primera aparición de una película (E4)
PUNTOS_CCDF = 220  # valores de k por tipo de nodo en la CCDF (M1)
AÑOS_DERIVA = (2021, 2022, 2023)

r4 = lambda x: round(float(x), 4)


def fecha(semana):
    return f"{datos.inicio_semana(semana):%Y-%m-%d}"


def gini(valores):
    x = np.sort(np.asarray(valores, dtype=float))
    return 2 * np.sum(np.arange(1, len(x) + 1) * x) / (len(x) * x.sum()) - (len(x) + 1) / len(x)


@lru_cache
def semanas_de_evaluacion(ultima_semana):
    return set(semanas_del_año(AÑO_VALIDACION, ultima_semana)), set(semanas_del_año(AÑO_TEST, ultima_semana))


def particion_de(semana, ultima_semana):
    """Nombre de la partición del protocolo a la que pertenece una semana."""
    validacion, test = semanas_de_evaluacion(ultima_semana)
    return "validación" if semana in validacion else "test" if semana in test else "entrenamiento"


def escribir(nombre, filas):
    ruta = SALIDA / f"{nombre}.json"
    ruta.write_text(json.dumps(filas, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    registrar(f"{nombre}: {len(filas)} filas, {ruta.stat().st_size / 1024:.0f} KB")


def cargar():
    """Las cuatro tablas, con la semana y su año (el del lunes, como en el protocolo) y las marcas de alta."""
    ratings, movies, tags, links = (datos.cargar(n) for n in ("ratings", "movies", "tags", "links"))
    ratings["semana"] = datos.semana(ratings["timestamp"]).astype("int32")
    primera = int(ratings["semana"].min())
    fechas = datos.inicio_semana(np.arange(primera, int(ratings["semana"].max()) + 1))
    ratings["año"] = fechas.year.to_numpy(np.int16)[ratings["semana"] - primera]
    ratings["usuario_nuevo"] = ratings["semana"] == ratings.groupby("userId")["semana"].transform("min")
    ratings["pelicula_nueva"] = ratings["semana"] == ratings.groupby("movieId")["semana"].transform("min")
    return ratings, movies, tags, links, fechas


def obtener_y_depurar(ratings, movies, tags, links, fechas):
    """O y S: tablas de origen, contrato de datos y la escala del rating antes y después de las medias estrellas."""
    ultima_semana = int(ratings["semana"].max())
    grado_usuario = ratings.groupby("userId").size()
    grado_pelicula = ratings.groupby("movieId").size()
    media_estrella = (ratings["rating"] * 2) % 2 == 1
    año_titulo = movies.set_index("movieId")["title"].str.extract(r"\((\d{4})\)\s*$", expand=False).astype("float")
    año_primer_rating = pd.to_datetime(ratings.groupby("movieId")["timestamp"].min(), unit="s").dt.year
    años_hasta_primer_rating = (año_primer_rating - año_titulo).dropna()
    tag_limpio = tags["tag"].str.strip()
    assert not ratings.duplicated(["userId", "movieId"]).any()

    periodo = lambda ts: f"{pd.to_datetime(ts.min(), unit='s'):%Y-%m-%d} a {pd.to_datetime(ts.max(), unit='s'):%Y-%m-%d}"
    fuentes = [
        {"tabla": nombre, "filas": len(tabla), "columnas": ", ".join(datos.TIPOS[nombre]), "llave": llave,  # columnas originales, sin las que agrega cargar()
         "periodo": periodo(tabla["timestamp"]) if "timestamp" in tabla else "—",
         "mb": round((datos.DIR_PARQUET / f"{nombre}.parquet").stat().st_size / 1e6)}
        for nombre, tabla, llave in (("ratings", ratings, "userId, movieId"), ("tags", tags, "—"),
                                     ("movies", movies, "movieId"), ("links", links, "movieId"))
    ]
    contrato = [
        {"chequeo": c, "resultado": r, "accion": a, "tipo": t} for c, r, a, t in [
            ("Nulos en ratings", "0", "—", "invariante"),
            ("Pares (usuario, película) repetidos", "0", "Se predicen enlaces nuevos; lo ya calificado sale de las candidatas", "invariante"),
            ("movieId de ratings y tags fuera de movies", "0", "—", "invariante"),
            ("links frente a movies", f"1 a 1 ({len(links):,})", "—", "invariante"),
            ("tmdbId nulos / repetidos en links", f"{links['tmdbId'].isna().sum()} / {links['tmdbId'].dropna().duplicated().sum()}",
             "Esas películas no tienen contenido de TMDB (H2)", "anomalía"),
            ("Valores de rating", "0.5 a 5.0, en pasos de 0.5", "—", "invariante"),
            ("Primera media estrella", f"{pd.to_datetime(ratings.loc[media_estrella, 'timestamp'].min(), unit='s'):%Y-%m-%d}",
             "La escala cambió: el valor del rating no es comparable en el tiempo", "decisión"),
            ("Medias estrellas desde 2016", f"{media_estrella[ratings['año'] >= 2016].mean():.0%}", "—", "decisión"),
            ("Ratings ≥ 3 / ≥ 4", f"{(ratings['rating'] >= 3).mean():.0%} / {(ratings['rating'] >= 4).mean():.0%}",
             "Interacción = cualquier rating (grafo binario)", "decisión"),
            ("Ratings por usuario, mínimo", f"{grado_usuario.min()}", "Filtro de GroupLens: no hay usuarios ocasionales (sesgo de selección)", "invariante"),
            ("Películas sin ningún rating", f"{len(movies) - len(grado_pelicula):,}", "Nodos sin aristas", "anomalía"),
            ("Títulos repetidos", f"{movies['title'].duplicated().sum()}", "La llave es movieId, nunca el título", "anomalía"),
            ("Películas sin año en el título", f"{año_titulo.isna().sum()}", "Atributo de año con marca falta_año", "anomalía"),
            ("Primer rating antes del año del título", f"{(años_hasta_primer_rating < 0).sum()}", "Se dejan: no afectan al grafo", "anomalía"),
            ("Películas con (no genres listed)", f"{(movies['genres'] == '(no genres listed)').sum():,}", "Una categoría más", "anomalía"),
            ("Tags nulos / vacíos / con espacios en los bordes",
             f"{tags['tag'].isna().sum()} / {(tag_limpio == '').sum()} / {(tags['tag'] != tag_limpio).sum():,}", "Tags fuera del modelo; no se limpian", "anomalía"),
            ("Última semana", f"{fechas[-1]:%Y-%m-%d}, {(ratings['semana'] == ultima_semana).sum():,} ratings", "Incompleta: fuera de la evaluación", "decisión"),
        ]
    ]
    era = np.where(ratings["año"] <= 2002, "hasta_2002", np.where(ratings["año"] >= 2016, "desde_2016", "otro"))
    reparto = pd.crosstab(ratings["rating"], era, normalize="columns")
    escala = [{"rating": float(v), "hasta_2002": r4(reparto.loc[v, "hasta_2002"]), "desde_2016": r4(reparto.loc[v, "desde_2016"])}
              for v in reparto.index]
    resumen = {
        "ratings": len(ratings), "usuarios": len(grado_usuario), "peliculas_catalogo": len(movies),
        "peliculas_con_rating": len(grado_pelicula), "tags": len(tags),
        "densidad": float(f"{len(ratings) / (len(grado_usuario) * len(grado_pelicula)):.4g}"),
        "primer_rating": f"{pd.to_datetime(ratings['timestamp'].min(), unit='s'):%Y-%m-%d}",
        "ultimo_rating": f"{pd.to_datetime(ratings['timestamp'].max(), unit='s'):%Y-%m-%d}",
        "estreno_mismo_año_o_siguiente": r4((años_hasta_primer_rating <= 1).mean()),
        "años_mediana_estreno_a_primer_rating": float(años_hasta_primer_rating.median()),
    }
    return {"fuentes": fuentes, "contrato": contrato, "ratings_valor": escala}, resumen, grado_usuario, grado_pelicula


def actividad(ratings, fechas):
    """E1 y E2: actividad semanal con su partición, medianas por periodo y composición anual de las aristas."""
    ultima_semana = int(ratings["semana"].max())
    todas = np.arange(int(ratings["semana"].min()), ultima_semana + 1)
    por_semana = pd.DataFrame({
        "ratings": ratings.groupby("semana").size(),
        "usuarios_activos": ratings.groupby("semana")["userId"].nunique(),
        "usuarios_nuevos": ratings[ratings["usuario_nuevo"]].groupby("semana")["userId"].nunique(),
    }).reindex(todas, fill_value=0)
    por_semana["usuarios_que_regresan"] = por_semana["usuarios_activos"] - por_semana["usuarios_nuevos"]
    completas = por_semana.iloc[:-1]  # sin la última semana, incompleta
    periodos = pd.cut(fechas.year, [1994, 1999, 2014, 2021, 2022, 2023],
                      labels=["1995–1999", "2000–2014", "2015–2021", "2022 (validación)", "2023 (test)"])[:-1]
    semanal = [
        {"semana": fecha(s), "ratings": int(f["ratings"]), "usuarios_nuevos": int(f["usuarios_nuevos"]),
         "usuarios_que_regresan": int(f["usuarios_que_regresan"]), "particion": particion_de(s, ultima_semana), "periodo": str(p)}
        for (s, f), p in zip(completas.iterrows(), periodos)
    ]
    mediana = completas.groupby(periodos, observed=True)[["ratings", "usuarios_activos", "usuarios_que_regresan"]].median().astype(int)

    por_usuario = ratings.groupby("userId").agg(semanas_activas=("semana", "nunique"), primera=("semana", "min"), ultima=("semana", "max"))
    con_historia = ~(ratings["usuario_nuevo"] | ratings["pelicula_nueva"])
    anual = pd.DataFrame({
        "ratings": ratings.groupby("año").size(),
        "pct_usuario_nuevo": ratings.groupby("año")["usuario_nuevo"].mean(),
        "pct_pelicula_nueva": ratings.groupby("año")["pelicula_nueva"].mean(),
        "pct_ambos_conocidos": con_historia.groupby(ratings["año"]).mean(),
    })
    resumen = {
        "semanas_completas": len(completas),
        "usuarios_una_semana": r4((por_usuario["semanas_activas"] == 1).mean()),
        "ratings_en_alta": r4(ratings["usuario_nuevo"].mean()),
        "vuelven_8_semanas": r4((por_usuario["ultima"] - por_usuario["primera"] >= 8).mean()),
    }
    return {
        "semanal": semanal,
        "periodos": [{"periodo": str(p), **{c: int(v) for c, v in f.items()}} for p, f in mediana.iterrows()],
        "anual": [{"año": int(a), "ratings": int(f["ratings"]), **{c: r4(f[c]) for c in anual.columns[1:]}} for a, f in anual.iterrows()],
    }, resumen, con_historia


def popularidad(ratings, con_historia, grado_pelicula):
    """E3: concentración y persistencia del top K semanal frente al histórico, desde 2016.

    Para cada semana w, fracción de las películas que cada usuario califica en w (sólo
    usuarios que regresan y películas conocidas) que estaba en el top K de la semana w-1
    y en el top K de todo lo anterior a w; promedio por usuario.
    """
    ultima_semana = int(ratings["semana"].max())
    desde = semanas_del_año(2016, ultima_semana)[0]
    codigo, _ = pd.factorize(ratings["movieId"])
    n_peliculas = codigo.max() + 1
    en_ventana = (ratings["semana"] >= desde - 1).to_numpy()
    fila = ratings["semana"].to_numpy()[en_ventana] - (desde - 1)
    conteo = np.bincount(fila * n_peliculas + codigo[en_ventana], minlength=(ultima_semana - desde + 2) * n_peliculas).reshape(-1, n_peliculas)
    historico = np.bincount(codigo[~en_ventana], minlength=n_peliculas) + np.cumsum(conteo, axis=0)  # fila j: todo hasta la semana desde-1+j

    objetivo = (con_historia & (ratings["semana"] >= desde) & (ratings["semana"] < ultima_semana)).to_numpy()
    orden = np.argsort(ratings["semana"].to_numpy()[objetivo], kind="stable")
    semana_objetivo = ratings["semana"].to_numpy()[objetivo][orden]
    usuario_objetivo = ratings["userId"].to_numpy()[objetivo][orden]
    pelicula_objetivo = codigo[objetivo][orden]
    cortes = np.searchsorted(semana_objetivo, np.arange(desde, ultima_semana + 1))
    top = lambda puntaje: np.argsort(-puntaje, kind="stable")[:K]
    reciente, de_siempre = np.zeros(len(pelicula_objetivo), bool), np.zeros(len(pelicula_objetivo), bool)
    for w, a, b in zip(range(desde, ultima_semana), cortes[:-1], cortes[1:]):
        reciente[a:b] = np.isin(pelicula_objetivo[a:b], top(conteo[w - desde]))
        de_siempre[a:b] = np.isin(pelicula_objetivo[a:b], top(historico[w - desde]))
    persistencia = (pd.DataFrame({"semana": semana_objetivo, "usuario": usuario_objetivo, "reciente": reciente, "historico": de_siempre})
                    .groupby(["semana", "usuario"]).mean().groupby("semana").mean())
    años = datos.inicio_semana(persistencia.index).year
    por_periodo = persistencia.groupby(pd.cut(años, [2015, 2021, 2022, 2023], labels=["2016–2021", "2022", "2023"]), observed=True).mean()

    mas_calificadas = grado_pelicula.sort_values(ascending=False)
    uno_por_ciento = len(mas_calificadas) // 100
    resumen = {"top1_peliculas": int(uno_por_ciento), "top1_cuota": r4(mas_calificadas.iloc[:uno_por_ciento].sum() / len(ratings))}
    return {
        "persistencia": [{"semana": fecha(s), "reciente": r4(f["reciente"]), "historico": r4(f["historico"]),
                          "particion": particion_de(s, ultima_semana)} for s, f in persistencia.iterrows()],
        "persistencia_periodos": [{"periodo": str(p), "reciente": r4(f["reciente"]), "historico": r4(f["historico"]),
                                   "veces": round(float(f["reciente"] / f["historico"]), 1)} for p, f in por_periodo.iterrows()],
    }, resumen


def peliculas_y_contenido(ratings, movies, tags, grado_usuario):
    """E4 y E5: ratings acumulados de las películas nuevas, géneros y tags."""
    ultima_semana = int(ratings["semana"].max())
    semana_alta = ratings.groupby("movieId")["semana"].transform("min")
    desde_alta = ratings["semana"] - semana_alta
    acumulado = (
        ratings.loc[(semana_alta <= ultima_semana - HORIZONTE) & (desde_alta < HORIZONTE)]
        .groupby([ratings["movieId"], desde_alta]).size()
        .unstack(fill_value=0).reindex(columns=range(HORIZONTE), fill_value=0).cumsum(axis=1)
    )
    cuantiles = acumulado.quantile([0.25, 0.5, 0.75, 0.9, 0.99])

    generos = movies["genres"].str.split("|")
    tags_por_usuario = tags["userId"].value_counts()
    llave = lambda tabla: tabla["userId"].to_numpy(np.int64) * 1_000_000 + tabla["movieId"].to_numpy(np.int64)
    resumen = {
        "peliculas_observadas_un_año": len(acumulado),
        "generos_distintos": int(generos.explode().nunique() - 1), "generos_por_pelicula": round(float(generos.str.len().mean()), 2),
        "usuarios_con_tags": int(len(tags_por_usuario)), "pct_usuarios_con_tags": r4(len(tags_por_usuario) / len(grado_usuario)),
        "tags_top1": r4(tags_por_usuario.head(len(tags_por_usuario) // 100).sum() / len(tags)),
        "tags_sin_rating": r4(1 - np.isin(llave(tags), llave(ratings)).mean()),
    }
    return {
        "acumulado": [{"semana": int(s) + 1, **{f"p{int(q * 100)}": round(float(cuantiles.loc[q, s]), 2) for q in cuantiles.index}}
                      for s in acumulado.columns],
        "generos": [{"genero": "Sin género" if g == "(no genres listed)" else g, "peliculas": int(n)}
                    for g, n in generos.explode().value_counts().items()],
    }, resumen


def ley_de_potencia(grado_usuario, grado_pelicula):
    """M1: ajuste de la ley de potencia y la CCDF de los grados, con la curva ajustada desde x_min."""
    grados = {"usuarios": grado_usuario, "películas": grado_pelicula}
    ajustes = {nombre: ajustar_ley_potencia(grado) for nombre, grado in grados.items()}
    filas_ccdf = []
    for nombre, grado in grados.items():
        valores = np.sort(grado.to_numpy())
        k, primeros = np.unique(valores, return_index=True)
        ccdf = 1 - primeros / len(valores)  # P(X ≥ k)
        elegidos = np.unique(np.searchsorted(k, np.geomspace(k[0], k[-1], PUNTOS_CCDF)).clip(0, len(k) - 1))
        a = ajustes[nombre]
        for i in elegidos:
            ajustada = None
            if k[i] >= a["x_min"]:
                ajustada = float(f"{a['n_cola'] / len(valores) * special.zeta(a['alfa'], k[i]) / special.zeta(a['alfa'], a['x_min']):.6g}")
            filas_ccdf.append({"nodo": nombre, "k": int(k[i]), "ccdf": float(f"{ccdf[i]:.6g}"), "ajuste": ajustada})
    return {
        "ley_potencia": [{"nodo": n, "alfa": round(a["alfa"], 3), "error_estandar": round(a["error_estandar"], 4), "x_min": a["x_min"],
                          "nodos_cola": a["n_cola"], "pct_cola": r4(a["n_cola"] / len(grados[n])), "ks": round(a["ks"], 4)}
                         for n, a in ajustes.items()],
        "ccdf": filas_ccdf,
    }, {"gini_peliculas": round(gini(grado_pelicula), 2), "gini_usuarios": round(gini(grado_usuario), 2)}


def deriva(ratings, con_historia):
    """M2: KS y PSI entre años, y percentiles de cada variable por año, al nivel en que se evalúa."""
    ultima_semana = int(ratings["semana"].max())

    def previos(columna):  # ratings del usuario (o de la película) en semanas anteriores
        por_semana = ratings.groupby([columna, "semana"]).size()
        return por_semana.groupby(level=0).cumsum() - por_semana

    historial_usuario, popularidad_pelicula = previos("userId"), previos("movieId")
    semanas = sum((semanas_del_año(año, ultima_semana) for año in AÑOS_DERIVA), [])
    objetivos = ratings.loc[con_historia & ratings["semana"].isin(semanas), ["userId", "movieId", "semana", "año"]]
    usuario_semana = objetivos.groupby(["userId", "semana"]).agg(aristas=("movieId", "size"), año=("año", "first"))
    usuario_semana["historial"] = historial_usuario.loc[usuario_semana.index].to_numpy()
    objetivos["popularidad"] = popularidad_pelicula.loc[pd.MultiIndex.from_frame(objetivos[["movieId", "semana"]])].to_numpy()
    variables = {
        "Historial previo del usuario evaluado": (usuario_semana, "historial", "usuario-semana"),
        "Popularidad previa de la película objetivo": (objetivos, "popularidad", "arista"),
        "Aristas objetivo por usuario-semana": (usuario_semana, "aristas", "usuario-semana"),
    }
    filas, cuantiles = [], []
    for nombre, (tabla, columna, unidad) in variables.items():
        por_año = {año: tabla.loc[tabla["año"] == año, columna].to_numpy() for año in AÑOS_DERIVA}
        fila = {"variable": nombre, "unidad": unidad, **{f"mediana_{año}": float(np.median(v)) for año, v in por_año.items()}}
        for antes, despues in zip(AÑOS_DERIVA, AÑOS_DERIVA[1:]):
            fila[f"ks_{antes}_{despues}"] = round(float(stats.ks_2samp(por_año[antes], por_año[despues]).statistic), 4)
            fila[f"psi_{antes}_{despues}"] = round(psi(por_año[antes], por_año[despues]), 4)
        filas.append(fila)
        p = np.linspace(0, 1, 101)
        for año, v in por_año.items():
            cuantiles += [{"variable": nombre, "año": año, "p": round(float(pi), 2), "valor": float(q)} for pi, q in zip(p, np.quantile(v, p))]

    semanal = usuario_semana.groupby(["año", "semana"]).agg(usuarios=("aristas", "size"), aristas=("aristas", "sum")).groupby("año").median()
    resumen = {
        **{f"evaluables_{a}": int(semanal.loc[a, "usuarios"]) for a in AÑOS_DERIVA},
        **{f"aristas_{a}": int(semanal.loc[a, "aristas"]) for a in AÑOS_DERIVA},
        "psi_max_2022_2023": max(f["psi_2022_2023"] for f in filas),
        "ks_max_2022_2023": max(f["ks_2022_2023"] for f in filas),
    }
    return {"deriva": filas, "deriva_cuantiles": cuantiles}, resumen


# Tabla de cierre del notebook 01 (N · Interpretar): hallazgo, evidencia, decisión y dónde está en el código
DECISIONES = [
    ("Cada par usuario–película aparece una sola vez", "0 pares repetidos (S)",
     "Se predicen enlaces nuevos: las candidatas son las películas conocidas que el usuario no ha calificado", "src/evaluacion.py"),
    ("La escala del rating cambió y casi todo es positivo", "medias estrellas desde 2003; 82 % ≥ 3 (S)",
     "Interacción = cualquier rating; grafo binario", "src/grafo.py"),
    ("La actividad no es estacionaria", "tres regímenes y picos de usuarios nuevos (E1)",
     "Partición temporal: entrenamiento hasta 2021, validación 2022, test 2023; para la semana w todo se calcula con datos anteriores a w", "src/protocolo.py"),
    ("La mayoría de las aristas viene de la ráfaga de alta", "65.6 % de los ratings en la semana de alta; 30–44 % con ambos extremos conocidos (E2)",
     "Se evalúan usuarios que regresan y películas conocidas (~1,000 usuarios por semana)", "GrafoTemporal.objetivos en src/grafo.py"),
    ("Los usuarios no tienen atributos y el arranque en frío es de usuarios", "sólo un id (O); 55–69 % de aristas con usuario nuevo (E2)",
     "GraphSAGE inductivo sin embeddings de ID (A9), con atributos de usuario calculados del grafo cada semana", "src/temporal.py"),
    ("La popularidad útil es reciente", "6–7 % frente a ~1 % (E3)",
     "Línea base: popularidad de la semana anterior. El modelo recibe la popularidad de las últimas 1, 4 y 12 semanas como atributo semanal",
     "src/lineas_base.py, src/temporal.py"),
    ("Hubs de películas con cola pesada", "α = 1.43 en el 66 % de las películas; Gini 0.95 (M1, E3)",
     "Agregación de vecinos por promedio; cobertura del catálogo en cada evaluación", "src/modelo.py, src/evaluacion.py"),
    ("Las películas nuevas casi no acumulan ratings y suelen ser títulos viejos", "mediana de 2 ratings en un año; 7 años tras el estreno (E4)",
     "Pregunta 2 (H2) con contenido de TMDB, por estratos de 0 a 19 ratings", "src/frio.py, src/h2.py"),
    ("Géneros completos; tags escasos y concentrados", "7.9 % de usuarios con tags (E5)",
     "Atributos de película: géneros, año y marca de año faltante; tags fuera", "_atributos_pelicula en src/grafo.py"),
    ("2022 representa a 2023", "PSI ≤ 0.004 y KS ≤ 0.03 de 2022 a 2023 (M2)",
     "Hiperparámetros elegidos sólo en validación; el test se mira una vez por configuración final", "src/ablacion.py"),
]


# Lo que el dashboard de claude.ai le da a la página: tokens de color, tipografía y espaciado
# (claro y oscuro) y la API `dash` (datos, colores de series, enlaces), aquí con datos fijos.
TOKENS = """
:root {
  --color-bg: #f7f7f5; --color-panel: #ffffff; --color-fg: #1f1e1c; --color-fg-muted: #5f5e5a;
  --color-border-line: #e3e2de; --color-ok: #1a7f52; --color-warn: #a86400; --color-bad: #c4382b;
  --serie-1: #2a78d6; --serie-2: #eb6834; --serie-3: #1baf7a; --serie-4: #eda100;
  --serie-5: #8a5cd6; --serie-6: #d6457a; --serie-7: #4b9fb5; --serie-8: #7d7a72;
  --cds-chart-grid: #ecebe7; --cds-chart-axis: #b9b8b3; --cds-chart-reference: #8a8984; --cds-chart-muted: #b4b2ab;
  --cds-surface-popover: #ffffff; --cds-border: #d9d8d3; --cds-text-secondary: #6b6a66;
  --cds-shadow-popover: 0 4px 16px rgba(0, 0, 0, .12);
  --font-anthropic-sans: "Segoe UI", system-ui, -apple-system, Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-anthropic-serif: Georgia, Cambria, "Times New Roman", serif;
  --cds-font-size-caption: 12px; --cds-font-size-body: 14px; --cds-font-size-heading: 16px; --cds-font-size-title: 24px;
  --cds-font-weight-medium: 600;
  --cds-gap-xs: 4px; --cds-gap-sm: 8px; --cds-gap-md: 16px; --cds-gap-lg: 24px; --cds-gap-xl: 40px;
  --cds-pad-xs: 4px; --cds-pad-sm: 8px; --cds-pad-md: 12px; --cds-pad-lg: 20px;
  --cds-radius: 10px; --cds-dur-slow: 300ms;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root {
    --color-bg: #171716; --color-panel: #21201e; --color-fg: #ecebe7; --color-fg-muted: #a5a39d;
    --color-border-line: #353431; --color-ok: #4cc38a; --color-warn: #e0a53a; --color-bad: #f07a6c;
    --serie-1: #5b9bf0; --serie-2: #f28a5c; --serie-3: #3cc896; --serie-4: #f2bd3d;
    --serie-5: #a684ec; --serie-6: #ea6f9b; --serie-7: #6fbad0; --serie-8: #a3a098;
    --cds-chart-grid: #2c2b28; --cds-chart-axis: #55534f; --cds-chart-reference: #8f8d87; --cds-chart-muted: #6c6a65;
    --cds-surface-popover: #2a2927; --cds-border: #45433f; --cds-text-secondary: #b2b0aa;
    --cds-shadow-popover: 0 4px 16px rgba(0, 0, 0, .5);
    color-scheme: dark;
  }
}
html, body { margin: 0; background: var(--color-bg); color: var(--color-fg); }
#dash-root { padding: 32px max(16px, 4vw) 48px; }
.eda-pie { max-width: 78rem; margin: 40px auto 0; font: 12px/1.5 var(--font-anthropic-sans); color: var(--color-fg-muted); }
"""

DASH = """
window.dash = (() => {
  const datos = window.DATOS_EDA;
  const funciones = [];
  const correr = () => funciones.forEach((fn) => fn());
  let espera;
  window.addEventListener('resize', () => { clearTimeout(espera); espera = setTimeout(correr, 150); });
  return {
    colors: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => `var(--serie-${i})`),
    data: (id) => (id in datos
      ? { status: 'ok', data: datos[id], columns: Object.keys(datos[id][0] || {}), refreshing: false, meta: [] }
      : { status: 'missing', data: [], columns: [], refreshing: false, meta: [] }),
    onData: (fn) => { funciones.push(fn); fn(); },
    setLink: (id) => history.replaceState(null, '', '#' + id),
    params: () => ({}), setParams: () => {}, resetParams: () => {},
  };
})();
"""


def html_autonomo():
    """Un solo archivo HTML con la página, los datos, d3 y la API `dash`; no necesita internet."""
    fuentes = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(SALIDA.glob("*.json"))}
    if not fuentes:
        raise FileNotFoundError(f"No hay JSON en {SALIDA}. Corre primero: python -m src.dashboard")
    en_script = lambda texto: texto.replace("</", "<\\/")  # que ningún texto cierre el <script> antes de tiempo
    html = "\n".join([
        "<!doctype html>",
        '<html lang="es">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>EDA MovieLens 32M</title>",
        f"<style>{TOKENS}</style>",
        f"<script>{D3.read_text(encoding='utf-8')}</script>",
        f"<script>window.DATOS_EDA = {en_script(json.dumps(fuentes, ensure_ascii=False, separators=(',', ':')))};</script>",
        f"<script>{DASH}</script>",
        "</head>",
        "<body>",
        '<div id="dash-root">',
        PAGINA.read_text(encoding="utf-8"),
        f'<p class="eda-pie">Versión autónoma del dashboard del EDA, generada el {time.strftime("%Y-%m-%d")} con '
        "python -m src.dashboard --html. Datos: MovieLens 32M (GroupLens), licencia sólo para investigación. "
        "Gráficos con d3 7.9.0 (ISC).</p>",
        "</div>",
        "</body>",
        "</html>",
    ])
    HTML_AUTONOMO.write_text(html, encoding="utf-8")
    registrar(f"{HTML_AUTONOMO} ({HTML_AUTONOMO.stat().st_size / 1e6:.1f} MB, {len(fuentes)} fuentes)")


def main():
    argumentos = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    argumentos.add_argument("--html", action="store_true", help="sólo armar el HTML autónomo con los JSON ya generados")
    if argumentos.parse_args().html:
        html_autonomo()
        return

    SALIDA.mkdir(parents=True, exist_ok=True)
    ratings, movies, tags, links, fechas = cargar()
    registrar(f"Datos cargados: {len(ratings):,} ratings")

    fuentes, resumen_os, grado_usuario, grado_pelicula = obtener_y_depurar(ratings, movies, tags, links, fechas)
    semanales, resumen_e12, con_historia = actividad(ratings, fechas)
    persistencia, resumen_e3 = popularidad(ratings, con_historia, grado_pelicula)
    contenido, resumen_e45 = peliculas_y_contenido(ratings, movies, tags, grado_usuario)
    potencia, resumen_m1 = ley_de_potencia(grado_usuario, grado_pelicula)
    derivas, resumen_m2 = deriva(ratings, con_historia)

    for nombre, filas in {**fuentes, **semanales, **persistencia, **contenido, **potencia, **derivas}.items():
        escribir(nombre, filas)
    escribir("resumen", [{**resumen_os, **resumen_e12, **resumen_e3, **resumen_e45, **resumen_m1, **resumen_m2}])
    escribir("decisiones", [{"n": n, "hallazgo": h, "evidencia": e, "decision": d, "donde": w}
                            for n, (h, e, d, w) in enumerate(DECISIONES, start=1)])
    registrar(f"Listo: {SALIDA}")


if __name__ == "__main__":
    main()
