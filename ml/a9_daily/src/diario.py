"""Horizonte diario: GraphSAGE A9 (entrenado por semanas) cortado en cualquier día.

Para el día d (UTC, como datos.semana) el modelo ve sólo los ratings anteriores a d y
ordena las películas para lo que el usuario califica el día d. Objetivos, candidatas e
historial son los del protocolo semanal con el día en lugar de la semana: usuarios con
algún rating antes de d, películas con algún rating antes de d, y fuera las que el
usuario ya calificó antes de d.

Cómo se corta en un día sin reentrenar. A9 no tiene embeddings de ID, así que sus pesos
no dependen de la fecha: sólo la instantánea y los atributos semanales. Para el día d se
usan semanas móviles que terminan el día anterior a d: la arista del día t cae en la
semana s(t) = ⌊(t − r) / 7⌋, con r = d mod 7, y la semana de corte es c = ⌊d / 7⌋.
Entonces c − s(t) = ⌈(d − t) / 7⌉ si t < d, y s(t) ≥ c si t ≥ d. Con esas semanas,
src/temporal.py calcula todo igual que siempre: "la última semana" son los 7 días antes de
d, "las últimas 4" los 28, "semanas desde el último rating" es ⌈días / 7⌉, etc. Si d es
lunes, las semanas móviles son las del calendario corridas en una y las entradas son
exactamente las de la instantánea semanal (tests/test_diario.py lo verifica).

Validación del horizonte diario, con los pesos guardados de A9 (corrida de validación:
objetivos hasta la semana del 27-dic-2021): los 364 días de las 52 semanas de validación,
del 03-ene-2022 al 01-ene-2023. Se comparan
- A9 con corte diario (lo de arriba);
- A9 con corte semanal: lo que vería el sistema si sólo se recalcula los lunes
  (instantánea, atributos, candidatas e historial del lunes de la semana de d);
- popularidad del día anterior y de los 7 días anteriores.
La unidad es el día: Wilcoxon por día, IC con bootstrap de bloques de 7 días y Holm sobre
{Recall@10, NDCG@10, Recall@20, NDCG@20} × referencias. El test (2023) no se toca aquí.

Uso, desde la raíz del proyecto (GPU si hay):
    python -m src.diario
"""

import copy
import time

import pandas as pd
import torch

from src import datos
from src.estadistica import bootstrap_media, comparar
from src.evaluacion import KS, evaluar_semana, nombres_metricas, puntuar_con_embeddings, puntuar_por_popularidad
from src.grafo import CALIFICADA_POR
from src.protocolo import DISPOSITIVO, anotar_ablacion, particion, registrar
from src.temporal import GrafoEnDispositivo, _matriz_csr

ETAPA = "5_diario"
DIR_DIARIO = datos.RAIZ / "resultados" / "diario"
METRICAS = ["recall@10", "ndcg@10", "recall@20", "ndcg@20"]
BLOQUE = 7  # días por bloque en el bootstrap


def dia_de_fecha(fecha):
    """Índice de día UTC (días desde el 1-ene-1970) de una fecha como '2023-06-15'."""
    instante = pd.Timestamp(fecha)
    if instante.tzinfo is not None:
        instante = instante.tz_convert("UTC").tz_localize(None)
    return int(instante.timestamp()) // datos.SEGUNDOS_POR_DIA  # Timestamp sin zona = UTC


def fecha_de_dia(dia):
    return str(pd.to_datetime(dia * datos.SEGUNDOS_POR_DIA, unit="s").date())


def lunes(dia):
    """Día del lunes de la semana del calendario (la de datos.semana) que contiene `dia`."""
    return dia - (dia + 3) % 7


def semana_movil(dias, dia_corte):
    """Semana móvil de cada día, vista desde `dia_corte`: ⌊(t − r) / 7⌋ con r = dia_corte mod 7."""
    return torch.div(dias - dia_corte % 7, 7, rounding_mode="floor")


class GrafoDiario:
    """Las aristas de un GrafoTemporal(con_dias=True) en un dispositivo, para cortar en cualquier día."""

    def __init__(self, grafo, dispositivo):
        if grafo.dia_por_usuario is None:
            raise ValueError("El grafo necesita los días: GrafoTemporal(con_dias=True)")
        self.semanal = GrafoEnDispositivo(grafo, dispositivo)
        self.dispositivo = dispositivo
        self.n_usuarios, self.n_peliculas = grafo.n_usuarios, grafo.n_peliculas
        self.n_atributos_usuario = self.semanal.n_atributos_usuario
        self.dia_por_usuario = grafo.dia_por_usuario.to(dispositivo)    # mismo orden que semanal.por_usuario
        self.dia_por_pelicula = grafo.dia_por_pelicula.to(dispositivo)  # mismo orden que semanal.por_pelicula
        self.dia_alta_usuario = torch.from_numpy(grafo.dia_alta_usuario).to(dispositivo)
        self.dia_alta_pelicula = torch.from_numpy(grafo.dia_alta_pelicula).to(dispositivo)

    def en_semanas(self, dia_corte):
        """(vista, semana_corte): un GrafoEnDispositivo con las semanas móviles de `dia_corte`.

        `vista.adyacencias(semana_corte)` y `vista.atributos(semana_corte)` son la instantánea
        y los atributos con los ratings anteriores a `dia_corte`, y sirven tal cual para
        src.entrenamiento.representaciones(modelo, vista, semana_corte, config).
        """
        vista = copy.copy(self.semanal)
        usuario, pelicula, _ = self.semanal.por_usuario
        vista.por_usuario = (usuario, pelicula, semana_movil(self.dia_por_usuario, dia_corte))
        pelicula, usuario, _ = self.semanal.por_pelicula
        vista.por_pelicula = (pelicula, usuario, semana_movil(self.dia_por_pelicula, dia_corte))
        vista.semana_alta_usuario = semana_movil(self.dia_alta_usuario, dia_corte)
        vista.semana_alta_pelicula = semana_movil(self.dia_alta_pelicula, dia_corte)
        return vista, dia_corte // 7

    def objetivos(self, dia_objetivo):
        """Aristas del día entre un usuario con historia y una película conocida antes de ese día.

        Devuelve (usuarios, películas, excluidas) en CPU, como GrafoTemporal.objetivos.
        """
        usuario, pelicula, _ = self.semanal.por_usuario
        en_el_dia = self.dia_por_usuario == dia_objetivo
        usuario, pelicula = usuario[en_el_dia], pelicula[en_el_dia]
        con_historia = (self.dia_alta_usuario[usuario] < dia_objetivo) & (self.dia_alta_pelicula[pelicula] < dia_objetivo)
        return usuario[con_historia].cpu(), pelicula[con_historia].cpu(), int((~con_historia).sum())

    def calificadas_el_dia(self, dia):
        """Todas las aristas (usuarios, películas) de ese día, en CPU (para marcar aciertos)."""
        usuario, pelicula, _ = self.semanal.por_usuario
        en_el_dia = self.dia_por_usuario == dia
        return usuario[en_el_dia].cpu(), pelicula[en_el_dia].cpu()

    def peliculas_conocidas(self, dia_corte):
        """Índices (en CPU) de las películas con algún rating antes de `dia_corte`."""
        return torch.nonzero(self.dia_alta_pelicula < dia_corte).flatten().cpu()

    def historial(self, dia_corte):
        """Matriz usuarios × películas (CSR, en CPU) con un 1 por cada rating anterior a `dia_corte`."""
        usuario, pelicula, _ = self.semanal.por_usuario
        return _matriz_csr(usuario, pelicula, self.dia_por_usuario, dia_corte, self.n_usuarios, self.n_peliculas, None).cpu()

    def popularidad(self, dia_corte, dias_atras=None):
        """Ratings de cada película antes de `dia_corte` (sólo los últimos `dias_atras` días, si se da)."""
        pelicula, _, _ = self.semanal.por_pelicula
        vigente = self.dia_por_pelicula < dia_corte
        if dias_atras is not None:
            vigente &= self.dia_por_pelicula >= dia_corte - dias_atras
        return torch.bincount(pelicula[vigente], minlength=self.n_peliculas).float()


def evaluar_dias(grafo, diario, dias, puntuador_de_dia, metodo, corte_semanal=False):
    """Como protocolo.evaluar_semanas, por día. `puntuador_de_dia(dia)` devuelve `puntuar(usuarios)`.

    Con `corte_semanal`, el historial que se excluye y las candidatas son los del lunes de la
    semana del día (lo que sabría un sistema que sólo se actualiza los lunes); los objetivos
    son siempre los del día. Los días sin objetivos (nadie con historia calificó nada) se
    saltan; son los mismos para todos los métodos.
    """
    resumenes, tablas = [], []
    for dia in dias:
        objetivos = diario.objetivos(dia)
        if len(objetivos[0]) == 0:
            registrar(f"  {metodo}: {fecha_de_dia(dia)} sin objetivos, se salta")
            continue
        corte = lunes(dia) if corte_semanal else dia
        resumen, por_usuario = evaluar_semana(grafo, dia, {CALIFICADA_POR: diario.historial(corte)}, puntuador_de_dia(dia),
                                              candidatas=diario.peliculas_conocidas(corte), objetivos=objetivos)
        resumenes.append({"dia": dia, "fecha": fecha_de_dia(dia), **resumen})
        tablas.append(por_usuario.rename(columns={"semana": "dia"}))
    por_dia, por_usuario = pd.DataFrame(resumenes), pd.concat(tablas, ignore_index=True)
    por_dia.insert(0, "metodo", metodo)
    por_usuario.insert(0, "metodo", metodo)
    return por_dia, por_usuario


def dias_de_validacion(grafo):
    """Los días de las 52 semanas de validación (03-ene-2022 a 01-ene-2023)."""
    semanas = particion(grafo)["validacion"]
    return list(range(semanas[0] * 7 - 3, semanas[-1] * 7 - 3 + 7))


def comprobar_lunes(diario, modelo, config, dia):
    """Diferencia máxima entre las representaciones con corte diario y semanal en un lunes (debe ser ~0)."""
    from src.entrenamiento import representaciones

    with torch.no_grad():
        vista, corte = diario.en_semanas(dia)
        diaria = representaciones(modelo, vista, corte, config)
        semanal = representaciones(modelo, diario.semanal, datos.semana(dia * datos.SEGUNDOS_POR_DIA), config)
    return max(float((a - b).abs().max()) for a, b in zip(diaria, semanal))


def main():
    from src.entrenamiento import representaciones
    from src.grafo import GrafoTemporal
    from src.recomendar import CARPETA_A9, cargar_a9

    inicio = time.time()
    grafo = GrafoTemporal(con_dias=True)
    diario = GrafoDiario(grafo, DISPOSITIVO)
    modelo, config = cargar_a9(grafo, diario)
    dias = dias_de_validacion(grafo)
    registrar(f"Grafo y A9 cargados en {time.time() - inicio:.0f} s. Dispositivo {DISPOSITIVO}. "
              f"Validación diaria: {len(dias)} días, {fecha_de_dia(dias[0])} a {fecha_de_dia(dias[-1])}")
    registrar(f"Lunes {fecha_de_dia(dias[0])}: diferencia máxima entre representaciones diarias y semanales "
              f"{comprobar_lunes(diario, modelo, config, dias[0]):.1e}")

    @torch.no_grad()
    def a9_diario(dia):
        vista, corte = diario.en_semanas(dia)
        return puntuar_con_embeddings(*representaciones(modelo, vista, corte, config))

    semanales = {}

    @torch.no_grad()
    def a9_semanal(dia):
        semana = datos.semana(dia * datos.SEGUNDOS_POR_DIA)
        if semana not in semanales:
            semanales.clear()
            semanales[semana] = representaciones(modelo, diario.semanal, semana, config)
        return puntuar_con_embeddings(*semanales[semana])

    metodos = {
        "A9 corte diario": ("a9_corte_diario", a9_diario, False),
        "A9 corte semanal": ("a9_corte_semanal", a9_semanal, True),
        "Popularidad día anterior": ("popularidad_dia_anterior", lambda d: puntuar_por_popularidad(diario.popularidad(d, 1)), False),
        "Popularidad 7 días": ("popularidad_7_dias", lambda d: puntuar_por_popularidad(diario.popularidad(d, 7)), False),
    }
    carpeta = DIR_DIARIO / "validacion"
    carpeta.mkdir(parents=True, exist_ok=True)
    tablas, filas = [], []
    for nombre, (archivo, puntuador, corte_semanal) in metodos.items():
        comienzo = time.time()
        por_dia, por_usuario = evaluar_dias(grafo, diario, dias, puntuador, nombre, corte_semanal)
        por_dia.to_csv(carpeta / f"{archivo}_dias.csv", index=False)
        por_usuario.to_parquet(carpeta / f"{archivo}_usuarios.parquet", index=False)
        registro = {"horizonte": "dia", "corte": "semanal" if corte_semanal else "diario", "metodo": archivo,
                    "pesos": (CARPETA_A9 / "modelo.pt").relative_to(datos.RAIZ).as_posix() if archivo.startswith("a9") else None,
                    **(config if archivo.startswith("a9") else {})}
        anotar_ablacion(ETAPA, archivo, registro, por_dia, "validacion", time.time() - comienzo)
        fila = {"metodo": nombre, "dias": len(por_dia), "usuarios_por_dia": por_dia["usuarios"].mean(),
                **{m: por_dia[m].mean() for m in nombres_metricas() + [f"cobertura@{k}" for k in KS]}}
        for metrica in METRICAS:
            fila[f"ic_bajo_{metrica}"], fila[f"ic_alto_{metrica}"] = bootstrap_media(por_dia[metrica], bloque=BLOQUE)
        filas.append(fila)
        tablas.append(por_dia)
        registrar(f"{nombre}: " + " ".join(f"{m} {fila[m]:.4f}" for m in METRICAS + ["mrr"]) + f" | {time.time() - comienzo:.0f} s")

    resumen = pd.DataFrame(filas)
    resumen.to_csv(DIR_DIARIO / "validacion_resumen.csv", index=False)
    largo = pd.concat(tablas).rename(columns={"dia": "semana"})  # comparar() usa la columna "semana" como unidad
    comparacion = comparar(largo, "A9 corte diario", [m for m in metodos if m != "A9 corte diario"], METRICAS, bloque=BLOQUE)
    comparacion = comparacion.rename(columns={"semanas": "dias", "semanas_gana": "dias_gana"})
    comparacion.to_csv(DIR_DIARIO / "validacion_comparacion.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 30, "display.float_format", "{:.4f}".format):
        registrar("Resumen (promedio por día):\n" + resumen[["metodo", "dias", "usuarios_por_dia", *METRICAS, "hitrate@10", "mrr"]].to_string(index=False))
        registrar("A9 corte diario contra cada referencia:\n" + comparacion[
            ["referencia", "metrica", "media_modelo", "media_referencia", "diferencia", "ic_bajo", "ic_alto", "dias_gana", "p_holm"]
        ].to_string(index=False))
    registrar(f"Listo en {(time.time() - inicio) / 60:.1f} min")


if __name__ == "__main__":
    main()
