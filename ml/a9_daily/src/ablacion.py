"""Ablación de la etapa 3: una cosa a la vez, en el orden del plan, elegida en validación.

Cada grupo prueba sus cambios partiendo de la mejor configuración hasta ese momento;
un cambio se queda sólo si mejora el Recall@20 promedio de las 52 semanas de
validación. Cada corrida es `python -m src.entrenamiento` y queda en resultados/ablacion.csv.
La ablación sin embeddings de ID (3e) se corre siempre, aunque no se quede.

Uso, desde la raíz del proyecto (~3 a 4 horas en la RTX 4060):
    python -m src.ablacion
"""

import subprocess
import sys

import pandas as pd

from src import datos
from src.entrenamiento import ETAPA, METRICA
from src.protocolo import registrar

GRUPOS = [
    ("3a atributos semanales", [("A1_atributos", ["atributos_semanales=true"])]),
    ("3b decaimiento temporal", [(f"A2_vida_media_{h}", [f"vida_media={h}"]) for h in (4, 13, 52)]),
    ("3c negativos difíciles", [("A3_neg_reciente", ["negativos=mezcla_reciente"]),
                                ("A3_neg_historica", ["negativos=mezcla_historica"])]),
    ("3d ventana de objetivos", [(f"A4_ventana_{v}", [f"ventana={v}"]) for v in (8, 13, 26)]),
    ("3d AdamW", [("A5_adamw", ["optimizador=adamw", "weight_decay=0.01"])]),
    ("3d dimensión 128", [("A6_dim128", ["dimension=128"])]),
    ("3d LayerNorm", [("A7_layernorm", ["normalizar=true"])]),
    ("3d dropout", [("A8_dropout", ["dropout=0.1"])]),
    ("3e sin embeddings de ID", [("A9_sin_id", ["usar_id=false"])]),
]


def valor(nombre):
    tabla = pd.read_csv(datos.RAIZ / "resultados" / "ablacion.csv")
    fila = tabla[(tabla["etapa"] == ETAPA) & (tabla["metodo"] == nombre) & (tabla["particion"] == "validacion")]
    return None if fila.empty else float(fila.iloc[-1][METRICA])


def correr(nombre, desde=None, cambios=()):
    """Corre (o reutiliza, si ya está en la tabla) una configuración."""
    if valor(nombre) is not None:
        registrar(f"{nombre}: ya estaba en la tabla ({METRICA} {valor(nombre):.4f})")
        return valor(nombre)
    comando = [sys.executable, "-W", "ignore", "-m", "src.entrenamiento", "--nombre", nombre]
    if desde:
        comando += ["--desde", desde, "--cambio", *cambios]
    with open(datos.RAIZ / "resultados" / "graphsage" / f"registro_{nombre}.txt", "w", encoding="utf-8") as registro:
        subprocess.run(comando, check=True, stdout=registro, stderr=subprocess.STDOUT, cwd=datos.RAIZ)
    registrar(f"{nombre}: {METRICA} {valor(nombre):.4f}")
    return valor(nombre)


def main():
    (datos.RAIZ / "resultados" / "graphsage").mkdir(parents=True, exist_ok=True)
    actual, mejor = "A0_base", correr("A0_base")
    for grupo, candidatos in GRUPOS:
        resultados = {nombre: correr(nombre, actual, cambios) for nombre, cambios in candidatos}
        ganador = max(resultados, key=resultados.get)
        if resultados[ganador] > mejor:
            registrar(f"[{grupo}] se queda {ganador}: {mejor:.4f} → {resultados[ganador]:.4f}")
            actual, mejor = ganador, resultados[ganador]
        else:
            registrar(f"[{grupo}] ningún cambio mejora; sigue {actual} ({mejor:.4f})")
    registrar(f"Mejor configuración en validación: {actual} ({METRICA} {mejor:.4f})")


if __name__ == "__main__":
    main()
