"""GraphSAGE heterogéneo para el grafo bipartito usuario–película (PyTorch Geometric).

Entrada de cada nodo (Hamilton et al., 2017), según la configuración:
- Embedding propio aprendido por ID (`usar_id`). Sin él, el modelo es totalmente
  inductivo: usuarios y películas nuevos se representan sólo con atributos y vecinos.
- Proyección lineal de sus atributos: las películas tienen géneros y año (fijos) y,
  opcionalmente, atributos semanales; los usuarios, sólo atributos semanales.
Cada capa tiene un SAGEConv por tipo de arista, así que usuarios y películas usan pesos
distintos. Entre capas: LayerNorm opcional, ReLU y dropout. El promedio de vecinos usa
los valores de la matriz de adyacencia como pesos (1 = promedio simple; con decaimiento
temporal, las aristas recientes pesan más).
El puntaje de un par (usuario, película) es el producto punto de sus representaciones.
"""

import torch
from torch import nn
from torch_geometric.nn import HeteroConv, SAGEConv

from src.grafo import CALIFICA, CALIFICADA_POR


class SAGEHeterogeneo(nn.Module):
    def __init__(self, n_usuarios, n_peliculas, atributos_pelicula, dimension=64, capas=2,
                 n_semanales_usuario=0, n_semanales_pelicula=0, usar_id=True, normalizar=False, dropout=0.0):
        super().__init__()
        if not usar_id and n_semanales_usuario == 0:
            raise ValueError("Sin embeddings de ID, los usuarios necesitan atributos semanales")
        self.register_buffer("atributos_pelicula", atributos_pelicula)
        self.usar_id = usar_id
        self.n_semanales_pelicula = n_semanales_pelicula
        if usar_id:
            self.embedding_usuario = nn.Embedding(n_usuarios, dimension)
            self.embedding_pelicula = nn.Embedding(n_peliculas, dimension)
            # Embeddings pequeños al inicio: un usuario que nunca recibió gradiente
            # depende casi sólo de sus vecinos, no de ruido aleatorio.
            nn.init.normal_(self.embedding_usuario.weight, std=0.01)
            nn.init.normal_(self.embedding_pelicula.weight, std=0.01)
        self.proyeccion_atributos = nn.Linear(atributos_pelicula.shape[1] + n_semanales_pelicula, dimension)
        self.proyeccion_usuario = nn.Linear(n_semanales_usuario, dimension) if n_semanales_usuario else None

        self.capas = nn.ModuleList(
            HeteroConv({CALIFICA: SAGEConvPromedio(dimension, dimension), CALIFICADA_POR: SAGEConvPromedio(dimension, dimension)})
            for _ in range(capas)
        )
        self.normas = nn.ModuleList(
            nn.ModuleDict({"usuario": nn.LayerNorm(dimension), "pelicula": nn.LayerNorm(dimension)})
            for _ in range(capas - 1)
        ) if normalizar else None
        self.dropout = nn.Dropout(dropout)

    def forward(self, adyacencias, semanales=None):
        """Representaciones de todos los usuarios y películas a partir de una instantánea.

        `semanales` = {"usuario": [n_usuarios, a], "pelicula": [n_peliculas, b]} con los
        atributos de la semana de la instantánea (o None si el modelo no los usa).
        """
        # Cada relación recibe su matriz y la de la relación inversa, que es su transpuesta
        pares = {
            CALIFICA: (adyacencias[CALIFICA], adyacencias[CALIFICADA_POR]),
            CALIFICADA_POR: (adyacencias[CALIFICADA_POR], adyacencias[CALIFICA]),
        }
        atributos_pelicula = self.atributos_pelicula
        if self.n_semanales_pelicula:
            atributos_pelicula = torch.cat([atributos_pelicula, semanales["pelicula"]], dim=1)
        x = {"usuario": 0, "pelicula": self.proyeccion_atributos(atributos_pelicula)}
        if self.proyeccion_usuario is not None:
            x["usuario"] = self.proyeccion_usuario(semanales["usuario"])
        if self.usar_id:
            x["usuario"] = x["usuario"] + self.embedding_usuario.weight
            x["pelicula"] = x["pelicula"] + self.embedding_pelicula.weight

        for i, capa in enumerate(self.capas):
            x = capa(x, pares)
            if i < len(self.capas) - 1:
                if self.normas is not None:
                    x = {tipo: self.normas[i][tipo](h) for tipo, h in x.items()}
                x = {tipo: self.dropout(torch.relu(h)) for tipo, h in x.items()}
        return x["usuario"], x["pelicula"]


class DosTorres(nn.Module):
    """Recomendador sólo de contenido (referencia de H2), con el mismo producto punto y la misma pérdida.

    La película se representa sólo con sus atributos de contenido; el usuario, con el
    promedio de la proyección del contenido de las películas que ya calificó. No hay
    propagación por el grafo, embeddings de ID ni atributos de popularidad: lo único que
    usa de las interacciones es el historial del propio usuario.
    """

    def __init__(self, atributos_pelicula, dimension=64, dropout=0.0):
        super().__init__()
        self.register_buffer("atributos_pelicula", atributos_pelicula)
        self.proyeccion = nn.Linear(atributos_pelicula.shape[1], dimension)
        self.torre_usuario = nn.Sequential(nn.ReLU(), nn.Dropout(dropout), nn.Linear(dimension, dimension))
        self.torre_pelicula = nn.Sequential(nn.ReLU(), nn.Dropout(dropout), nn.Linear(dimension, dimension))

    def forward(self, adyacencias, semanales=None):
        h = self.proyeccion(self.atributos_pelicula)
        perfil = _PromedioVecinos.apply(h, adyacencias[CALIFICADA_POR], adyacencias[CALIFICA])  # promedio del historial
        return self.torre_usuario(perfil), self.torre_pelicula(h)


class SAGEConvPromedio(SAGEConv):
    """El SAGEConv de PyG con agregación promedio, con un backward más rápido en CPU.

    Calcula lin_l(promedio de vecinos) + lin_r(nodo). Con matrices de unos es lo mismo
    que `SAGEConv(aggr="mean")`; con pesos, el promedio es ponderado. PyG reconstruye la
    matriz transpuesta en cada backward (~4 s por capa con 32M aristas); aquí se
    reutiliza la de la relación inversa, que ya existe. tests/test_modelo.py lo verifica.
    """

    def forward(self, x, adyacencia):
        x_origen, x_destino = x
        adj_t, adj = adyacencia  # adj_t: filas = destino; adj: su transpuesta (mismos pesos)
        return self.lin_l(_PromedioVecinos.apply(x_origen, adj_t, adj)) + self.lin_r(x_destino)


PESO_MINIMO = 1e-12  # suma de pesos por debajo de la cual un nodo se trata como sin vecinos


class _PromedioVecinos(torch.autograd.Function):
    """Promedio ponderado de los vecinos: (A x) / (A 1), con A = adj_t y su transpuesta adj.

    Un nodo sin vecinos, o cuyos pesos suman menos de PESO_MINIMO (con decaimiento, sólo
    aristas muy viejas), recibe 0. Sin ese umbral, una suma de ~1e-40 (subnormal en
    float32) vuelve infinito el gradiente / suma del backward, y infinito · 0 = NaN.
    """

    @staticmethod
    def forward(ctx, x_origen, adj_t, adj):
        unos = torch.ones(adj_t.shape[1], 1, dtype=x_origen.dtype, device=x_origen.device)
        suma = torch.sparse.mm(adj_t, unos)
        inversa = torch.where(suma > PESO_MINIMO, 1 / suma.clamp(min=PESO_MINIMO), torch.zeros_like(suma))
        ctx.adj, ctx.inversa = adj, inversa
        return torch.sparse.mm(adj_t, x_origen) * inversa

    @staticmethod
    def backward(ctx, gradiente):
        return torch.sparse.mm(ctx.adj, gradiente * ctx.inversa), None, None
