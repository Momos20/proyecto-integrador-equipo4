"""Comparadores de aprendizaje profundo frente a GraphSAGE (curso de Aprendizaje profundo).

Mismo protocolo que H1 (src/protocolo.py). Cada comparador se reentrena desde cero cada
4 semanas con las aristas de las últimas `ventana` semanas (como la MF-BPR) y, además,
entre reentrenamientos usa su actualización semanal natural (decisión D1a):
- NCF de dos torres: embeddings de ID de usuario y película, cada uno con un MLP de dos
  capas, y producto punto; pérdida BPR con negativos uniformes. Sin actualización semanal
  (sólo tiene IDs).
- LightGCN (He et al., 2020): embeddings de ID propagados K = 3 capas por el grafo
  normalizado D^-1/2 A D^-1/2, sin pesos ni no-linealidades; representación = promedio de
  las capas; pérdida BPR. Cada semana se vuelve a propagar por la instantánea de esa semana.
- Mult-VAE (Liang et al., 2018), en versión temporal: el codificador recibe el historial
  del usuario antes de la semana s (multi-hot normalizado, con dropout) y el decodificador
  da una distribución multinomial sobre las películas, que se ajusta a las que el usuario
  calificó en s; término KL con annealing lineal hasta β. Cada semana se codifica el
  historial de esa semana.
Las épocas se eligen en validación junto con la ventana y la dimensión (o β): se evalúa al
terminar cada valor de EPOCAS (parada temprana por Recall@20 en validación).

Uso, desde la raíz del proyecto (validación; ~6 horas en la RTX 4060):
    python -m src.comparadores
    python -m src.comparadores --modelos lightgcn
Test (una sola vez, con la mejor configuración de validación de cada modelo, por Recall@20):
    python -m src.comparadores --test
"""

import argparse
import json
import time

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from torch import nn

from src import datos
from src.grafo import CALIFICA, CALIFICADA_POR
from src.lineas_base import CADA_CUANTAS_SEMANAS
from src.protocolo import DISPOSITIVO, anotar_ablacion, evaluar_semanas, guardar, particion, registrar
from src.temporal import GrafoEnDispositivo

ETAPA = "dl_comparadores"
DIR_COMPARADORES = datos.RAIZ / "resultados" / "comparadores"
EPOCAS = (5, 10, 20, 40)
VENTANAS = (13, 26)
DIMENSIONES = (64, 128)
BETAS = (0.2, 1.0)
COMUN = {"lote": 65_536, "tasa_aprendizaje": 0.01, "regularizacion": 1e-5, "semilla": 0}
LIGHTGCN_CAPAS = 3
# 512 usuarios por paso y bf16 en el forward: con 1024 el pico pasa de ~5 GB y la GPU (8 GB, compartida)
# desborda a la RAM; cada época tiene 2 × ventana pasos, así cubre ~1 000 usuarios por semana objetivo.
VAE = {"oculta": 600, "latente": 200, "dropout": 0.5, "usuarios_por_paso": 512, "pasos_por_semana": 2, "tasa_aprendizaje": 0.001}


# ---------------------------------------------------------------- modelos

class NCFDosTorres(nn.Module):
    def __init__(self, n_usuarios, n_peliculas, dimension):
        super().__init__()
        self.usuario = nn.Embedding(n_usuarios, dimension)
        self.pelicula = nn.Embedding(n_peliculas, dimension)
        nn.init.normal_(self.usuario.weight, std=0.01)
        nn.init.normal_(self.pelicula.weight, std=0.01)
        self.torre_usuario = nn.Sequential(nn.Linear(dimension, dimension), nn.ReLU(), nn.Linear(dimension, dimension))
        self.torre_pelicula = nn.Sequential(nn.Linear(dimension, dimension), nn.ReLU(), nn.Linear(dimension, dimension))

    def representaciones(self, *_):
        return self.torre_usuario(self.usuario.weight), self.torre_pelicula(self.pelicula.weight)


class LightGCN(nn.Module):
    def __init__(self, n_usuarios, n_peliculas, dimension, capas=LIGHTGCN_CAPAS):
        super().__init__()
        self.usuario = nn.Embedding(n_usuarios, dimension)
        self.pelicula = nn.Embedding(n_peliculas, dimension)
        nn.init.normal_(self.usuario.weight, std=0.1)
        nn.init.normal_(self.pelicula.weight, std=0.1)
        self.capas = capas

    def representaciones(self, normalizada):
        """Promedio de las capas 0..K de la propagación por el grafo normalizado de una instantánea."""
        usuario_pelicula, pelicula_usuario = normalizada
        h_u, h_p = self.usuario.weight, self.pelicula.weight
        suma_u, suma_p = h_u, h_p
        for _ in range(self.capas):
            h_u, h_p = _Propagar.apply(h_p, usuario_pelicula, pelicula_usuario), _Propagar.apply(h_u, pelicula_usuario, usuario_pelicula)
            suma_u, suma_p = suma_u + h_u, suma_p + h_p
        return suma_u / (self.capas + 1), suma_p / (self.capas + 1)


class _Propagar(torch.autograd.Function):
    """A · x con A dispersa; el backward usa la transpuesta ya construida (como en src/modelo.py)."""

    @staticmethod
    def forward(ctx, x, matriz, transpuesta):
        ctx.transpuesta = transpuesta
        return torch.sparse.mm(matriz, x)

    @staticmethod
    def backward(ctx, gradiente):
        return torch.sparse.mm(ctx.transpuesta, gradiente), None, None


def grafo_normalizado(en_gpu, semana):
    """(usuarios × películas, películas × usuarios) con pesos 1/√(grado_u · grado_p), aristas < semana."""
    adyacencias = en_gpu.adyacencias(semana)
    normalizadas = {}
    for relacion, (filas_n, columnas_n) in ((CALIFICADA_POR, (en_gpu.n_usuarios, en_gpu.n_peliculas)),
                                            (CALIFICA, (en_gpu.n_peliculas, en_gpu.n_usuarios))):
        matriz = adyacencias[relacion]
        inicio = matriz.crow_indices()
        grado_fila = (inicio[1:] - inicio[:-1]).float()
        columnas = matriz.col_indices()
        grado_columna = torch.bincount(columnas, minlength=columnas_n).float()
        fila = torch.repeat_interleave(torch.arange(filas_n, device=columnas.device), inicio[1:] - inicio[:-1])
        valores = 1 / torch.sqrt(grado_fila[fila] * grado_columna[columnas])
        normalizadas[relacion] = torch.sparse_csr_tensor(inicio, columnas, valores, size=matriz.shape, check_invariants=False)
    return normalizadas[CALIFICADA_POR], normalizadas[CALIFICA]


class MultVAE(nn.Module):
    def __init__(self, n_peliculas, oculta=VAE["oculta"], latente=VAE["latente"], dropout=VAE["dropout"]):
        super().__init__()
        self.codificador = nn.Linear(n_peliculas, oculta)
        self.media_y_varianza = nn.Linear(oculta, 2 * latente)
        self.decodificador = nn.Sequential(nn.Linear(latente, oculta), nn.Tanh(), nn.Linear(oculta, n_peliculas))
        self.dropout = nn.Dropout(dropout)

    def forward(self, historial):
        """Logits sobre las películas y KL, a partir del historial multi-hot (filas = usuarios)."""
        x = self.dropout(F.normalize(historial, dim=1))
        media, log_varianza = self.media_y_varianza(torch.tanh(self.codificador(x))).chunk(2, dim=1)
        z = media + torch.randn_like(media) * torch.exp(0.5 * log_varianza) if self.training else media
        kl = -0.5 * torch.sum(1 + log_varianza - media ** 2 - log_varianza.exp(), dim=1).mean()
        return self.decodificador(z), kl


def historial_denso(adyacencias, usuarios):
    """Filas multi-hot (en GPU) del historial de `usuarios` en una instantánea (aristas anteriores)."""
    matriz = adyacencias[CALIFICADA_POR]
    inicio, columnas = matriz.crow_indices(), matriz.col_indices()
    desde, cuantas = inicio[usuarios], inicio[usuarios + 1] - inicio[usuarios]
    fila = torch.repeat_interleave(torch.arange(len(usuarios), device=usuarios.device), cuantas)
    posicion = torch.repeat_interleave(desde - torch.cumsum(cuantas, 0) + cuantas, cuantas) + torch.arange(int(cuantas.sum()), device=usuarios.device)
    denso = torch.zeros(len(usuarios), matriz.shape[1], device=usuarios.device)
    denso[fila, columnas[posicion]] = 1
    return denso


# ---------------------------------------------------------------- entrenamiento

def entrenar_bpr(modelo, en_gpu, grafo, semana_corte, ventana, epocas_a_guardar, lightgcn=False, config=COMUN):
    """NCF o LightGCN con BPR sobre las aristas de [corte − ventana, corte). Devuelve estados por época y curva."""
    torch.manual_seed(config["semilla"])
    usuarios, peliculas = (t.to(DISPOSITIVO) for t in grafo.aristas(semana_corte - ventana, semana_corte))
    conocidas = grafo.peliculas_conocidas(semana_corte).to(DISPOSITIVO)
    normalizada = grafo_normalizado(en_gpu, semana_corte) if lightgcn else None
    optimizador = torch.optim.Adam(modelo.parameters(), lr=config["tasa_aprendizaje"])
    guardados, curva = {}, []
    for epoca in range(1, max(epocas_a_guardar) + 1):
        orden, perdidas = torch.randperm(len(usuarios), device=DISPOSITIVO), []
        for inicio in range(0, len(orden), config["lote"]):
            lote = orden[inicio:inicio + config["lote"]]
            u, p = usuarios[lote], peliculas[lote]
            n = conocidas[torch.randint(len(conocidas), (len(lote),), device=DISPOSITIVO)]
            z_u, z_p = modelo.representaciones(normalizada)
            perdida = -F.logsigmoid((z_u[u] * z_p[p]).sum(1) - (z_u[u] * z_p[n]).sum(1)).mean()
            e0 = modelo.usuario.weight[u].square().sum(1) + modelo.pelicula.weight[p].square().sum(1) + modelo.pelicula.weight[n].square().sum(1)
            perdida = perdida + config["regularizacion"] * e0.mean()
            optimizador.zero_grad()
            perdida.backward()
            optimizador.step()
            perdidas.append(perdida.item())
        curva.append({"epoca": epoca, "perdida": float(np.mean(perdidas))})
        if epoca in epocas_a_guardar:
            guardados[epoca] = {k: v.detach().clone() for k, v in modelo.state_dict().items()}
    return guardados, curva


def entrenar_vae(modelo, en_gpu, semana_corte, ventana, epocas_a_guardar, beta, config=COMUN):
    """Mult-VAE temporal: una época = 2 × `ventana` pasos; cada paso, una semana objetivo al azar."""
    torch.manual_seed(config["semilla"])
    azar = np.random.default_rng(config["semilla"])
    optimizador = torch.optim.Adam(modelo.parameters(), lr=VAE["tasa_aprendizaje"])
    pasos_por_epoca = VAE["pasos_por_semana"] * ventana
    pasos_totales, paso = max(epocas_a_guardar) * pasos_por_epoca, 0
    guardados, curva = {}, []
    for epoca in range(1, max(epocas_a_guardar) + 1):
        perdidas = []
        for _ in range(pasos_por_epoca):
            semana = int(azar.integers(semana_corte - ventana, semana_corte))
            usuarios, peliculas = en_gpu.objetivos(semana)
            if len(usuarios) == 0:
                continue
            unicos, fila = torch.unique(usuarios, return_inverse=True)  # fila: posición de cada arista en `unicos`
            if len(unicos) > VAE["usuarios_por_paso"]:
                elegidos = torch.randperm(len(unicos), device=DISPOSITIVO)[:VAE["usuarios_por_paso"]]
                nueva_fila = torch.full((len(unicos),), -1, device=DISPOSITIVO, dtype=torch.long)
                nueva_fila[elegidos] = torch.arange(len(elegidos), device=DISPOSITIVO)
                fila = nueva_fila[fila]
                dentro = fila >= 0
                fila, peliculas, unicos = fila[dentro], peliculas[dentro], unicos[elegidos]
            objetivo = torch.zeros(len(unicos), en_gpu.n_peliculas, device=DISPOSITIVO)
            objetivo[fila, peliculas] = 1
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=DISPOSITIVO.type == "cuda"):
                logits, kl = modelo(historial_denso(en_gpu.adyacencias(semana), unicos))
            verosimilitud = -(F.log_softmax(logits.float(), dim=1) * objetivo).sum(1).mean()
            kl = kl.float()
            paso += 1
            perdida = verosimilitud + beta * min(1.0, paso / pasos_totales) * kl  # annealing lineal hasta β
            optimizador.zero_grad()
            perdida.backward()
            optimizador.step()
            perdidas.append(perdida.item())
        curva.append({"epoca": epoca, "perdida": float(np.mean(perdidas))})
        if epoca in epocas_a_guardar:
            guardados[epoca] = {k: v.detach().clone() for k, v in modelo.state_dict().items()}
    return guardados, curva


def puntuador(nombre_modelo, modelo, en_gpu):
    """Puntuador semanal con la actualización natural de cada comparador (pesos ya cargados)."""
    @torch.no_grad()
    def de_semana(semana, _):
        modelo.eval()
        if nombre_modelo == "mult_vae":
            adyacencias = en_gpu.adyacencias(semana)
            return lambda usuarios: modelo(historial_denso(adyacencias, usuarios.to(DISPOSITIVO)))[0]
        normalizada = grafo_normalizado(en_gpu, semana) if nombre_modelo == "lightgcn" else None
        z_u, z_p = modelo.representaciones(normalizada)
        return lambda usuarios: z_u[usuarios.to(DISPOSITIVO)] @ z_p.T
    return de_semana


def crear(nombre_modelo, grafo, dimension):
    if nombre_modelo == "ncf":
        return NCFDosTorres(grafo.n_usuarios, grafo.n_peliculas, dimension).to(DISPOSITIVO)
    if nombre_modelo == "lightgcn":
        return LightGCN(grafo.n_usuarios, grafo.n_peliculas, dimension).to(DISPOSITIVO)
    return MultVAE(grafo.n_peliculas).to(DISPOSITIVO)


def evaluar_con_reentrenamiento(nombre_modelo, grafo, en_gpu, semanas, ventana, parametro, epocas=EPOCAS):
    """Reentrena cada 4 semanas y evalúa cada bloque con cada número de épocas.

    `parametro` es la dimensión (NCF, LightGCN) o β (Mult-VAE).
    Devuelve ({épocas: (por_semana, por_usuario)}, curva de pérdida del primer reentrenamiento).
    """
    resultados = {e: ([], []) for e in epocas}
    curva_primera = None
    for inicio in range(0, len(semanas), CADA_CUANTAS_SEMANAS):
        bloque = semanas[inicio:inicio + CADA_CUANTAS_SEMANAS]
        t = time.time()
        modelo = crear(nombre_modelo, grafo, parametro if nombre_modelo != "mult_vae" else None)
        if nombre_modelo == "mult_vae":
            guardados, curva = entrenar_vae(modelo, en_gpu, bloque[0], ventana, epocas, beta=parametro)
        else:
            guardados, curva = entrenar_bpr(modelo, en_gpu, grafo, bloque[0], ventana, epocas, lightgcn=nombre_modelo == "lightgcn")
        curva_primera = curva_primera or curva
        for e, estado in guardados.items():
            modelo.load_state_dict(estado)
            por_semana, por_usuario = evaluar_semanas(grafo, bloque, puntuador(nombre_modelo, modelo, en_gpu), f"{nombre_modelo}_e{e}")
            resultados[e][0].append(por_semana)
            resultados[e][1].append(por_usuario)
        registrar(f"  {nombre_modelo} v{ventana} p{parametro}: reentrenamiento en {bloque[0]}, pérdida final {curva[-1]['perdida']:.4f}, {time.time() - t:.0f} s")
        del modelo, guardados
        torch.cuda.empty_cache()
    return {e: (pd.concat(s, ignore_index=True), pd.concat(u, ignore_index=True)) for e, (s, u) in resultados.items()}, curva_primera


def nombre_corrida(nombre_modelo, ventana, parametro, epocas):
    clave = "b" if nombre_modelo == "mult_vae" else "d"
    return f"{nombre_modelo}_v{ventana}_{clave}{parametro}_e{epocas}"


def mejores_de_validacion(modelos=("ncf", "lightgcn", "mult_vae")):
    """{modelo: fila de la tabla de ablación} con el mayor Recall@20 en validación."""
    tabla = pd.read_csv(datos.RAIZ / "resultados" / "ablacion.csv")
    tabla = tabla[(tabla["etapa"] == ETAPA) & (tabla["particion"] == "validacion")]
    return {m: tabla.loc[tabla[tabla["metodo"].str.startswith(f"{m}_v")]["recall@20"].idxmax()] for m in modelos}


def correr_test(grafo, en_gpu):
    """Cada comparador con su mejor configuración de validación, una vez en las 40 semanas de test."""
    semanas = particion(grafo)["test"]
    for nombre_modelo, fila in mejores_de_validacion().items():
        config = json.loads(fila["configuracion"])
        parametro = config["beta"] if nombre_modelo == "mult_vae" else config["dimension"]
        inicio = time.time()
        resultados, _ = evaluar_con_reentrenamiento(nombre_modelo, grafo, en_gpu, semanas, config["ventana"], parametro, epocas=(config["epocas"],))
        por_semana, por_usuario = resultados[config["epocas"]]
        guardar(por_semana, por_usuario, fila["metodo"], "test")
        anotar_ablacion(ETAPA, fila["metodo"], config, por_semana, "test", time.time() - inicio)
        registrar(f"{fila['metodo']} test: recall@20 {por_semana['recall@20'].mean():.4f} ndcg@20 {por_semana['ndcg@20'].mean():.4f}")


def comparar_test():
    """A9 contra cada comparador en test: Wilcoxon, IC por bloques y Holm en una familia aparte
    ({Recall@20, NDCG@20} × {Mult-VAE, NCF, LightGCN}, 6 pruebas). Escribe comparacion_test.csv."""
    from src.estadistica import comparar
    from src.protocolo import DIR_RESULTADOS

    nombres = {"ncf": "NCF de dos torres", "lightgcn": "LightGCN", "mult_vae": "Mult-VAE"}
    carpeta = DIR_RESULTADOS / "test"
    tablas = [pd.read_csv(carpeta / "A9_sin_id_semanas.csv").assign(metodo="GraphSAGE (A9)")]
    for modelo, fila in mejores_de_validacion().items():
        tablas.append(pd.read_csv(carpeta / f"{fila['metodo']}_semanas.csv").assign(metodo=nombres[modelo]))
    largo = pd.concat(tablas)
    resumen = largo.groupby("metodo")[["recall@10", "recall@20", "recall@50", "ndcg@20", "hitrate@20", "mrr", "cobertura@20"]].mean()
    comparacion = comparar(largo, "GraphSAGE (A9)", list(nombres.values()), ["recall@20", "ndcg@20"])
    resumen.to_csv(DIR_COMPARADORES / "resumen_test.csv")
    comparacion.to_csv(DIR_COMPARADORES / "comparacion_test.csv", index=False)
    return resumen, comparacion


def main():
    from src.grafo import GrafoTemporal

    argumentos = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    argumentos.add_argument("--modelos", nargs="+", default=["ncf", "lightgcn", "mult_vae"])
    argumentos.add_argument("--test", action="store_true", help="mejor configuración de cada modelo, una vez en test")
    argumentos.add_argument("--comparar", action="store_true", help="contraste A9 vs comparadores en test (familia de Holm aparte)")
    leidos = argumentos.parse_args()
    if leidos.comparar:
        resumen, comparacion = comparar_test()
        with pd.option_context("display.width", 250, "display.max_columns", 30, "display.float_format", "{:.4f}".format):
            print(resumen.to_string(), "\n")
            print(comparacion[["referencia", "metrica", "media_modelo", "media_referencia", "diferencia", "ic_bajo", "ic_alto",
                               "semanas_gana", "p", "p_holm", "significativa"]].to_string(index=False))
        return

    grafo = GrafoTemporal()
    en_gpu = GrafoEnDispositivo(grafo, DISPOSITIVO)
    DIR_COMPARADORES.mkdir(parents=True, exist_ok=True)
    if leidos.test:
        correr_test(grafo, en_gpu)
        return
    registrar(f"Comparadores DL, validación: {len(semanas)} semanas. Dispositivo: {DISPOSITIVO}")
    tabla = pd.read_csv(datos.RAIZ / "resultados" / "ablacion.csv")
    hechas = set(tabla.loc[(tabla["etapa"] == ETAPA) & (tabla["particion"] == "validacion"), "metodo"])
    for nombre_modelo in leidos.modelos:
        for ventana in VENTANAS:
            for parametro in (BETAS if nombre_modelo == "mult_vae" else DIMENSIONES):
                if nombre_corrida(nombre_modelo, ventana, parametro, max(EPOCAS)) in hechas:
                    registrar(f"{nombre_modelo} v{ventana} p{parametro}: ya estaba en la tabla")
                    continue
                inicio = time.time()
                resultados, curva = evaluar_con_reentrenamiento(nombre_modelo, grafo, en_gpu, semanas, ventana, parametro)
                for epocas, (por_semana, por_usuario) in resultados.items():
                    nombre = nombre_corrida(nombre_modelo, ventana, parametro, epocas)
                    config = {"modelo": nombre_modelo, "ventana": ventana, ("beta" if nombre_modelo == "mult_vae" else "dimension"): parametro,
                              "epocas": epocas, "reentrenamiento_cada": CADA_CUANTAS_SEMANAS, **COMUN,
                              **({"vae": VAE} if nombre_modelo == "mult_vae" else {}),
                              **({"capas": LIGHTGCN_CAPAS} if nombre_modelo == "lightgcn" else {})}
                    guardar(por_semana, por_usuario, nombre, "validacion")
                    anotar_ablacion(ETAPA, nombre, config, por_semana, "validacion", time.time() - inicio)
                    registrar(f"{nombre}: recall@20 {por_semana['recall@20'].mean():.4f} ndcg@20 {por_semana['ndcg@20'].mean():.4f}")
                pd.DataFrame(curva).to_csv(DIR_COMPARADORES / f"curva_{nombre_corrida(nombre_modelo, ventana, parametro, 'todas')}.csv", index=False)


if __name__ == "__main__":
    main()
