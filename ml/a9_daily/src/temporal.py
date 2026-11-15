"""El tiempo dentro del modelo: instantáneas con decaimiento y atributos que cambian cada semana.

Todo lo de la semana w se calcula sólo con las aristas anteriores a w (semana < w).

Atributos semanales de cada película (5):
    log(1 + ratings en la última semana), log(1 + ratings en las últimas 4 semanas),
    log(1 + ratings en las últimas 12 semanas), log(1 + semanas desde su primer rating)
    y 1 si ya tenía algún rating (0 si todavía no existe para el modelo).
Atributos semanales de cada usuario (4 + géneros):
    actividad: log(1 + ratings totales), log(1 + ratings en las últimas 4 semanas);
    recencia: log(1 + semanas desde su último rating), log(1 + semanas desde su primer rating);
    perfil de géneros: fracción de sus ratings en cada género (multi-hot de movies.csv).
Un usuario o película sin historia antes de w tiene todos sus atributos en 0.

Pesos de arista con decaimiento: una arista de la semana s, vista desde la instantánea
de la semana w, pesa 0.5 ** ((w - s) / vida_media). Con vida_media = None todas pesan 1.
"""

import torch

from src.grafo import CALIFICA, CALIFICADA_POR

N_ATRIBUTOS_PELICULA = 5
N_ATRIBUTOS_USUARIO_BASE = 4


class GrafoEnDispositivo:
    """Copia de las aristas de un GrafoTemporal en GPU, para armar cada semana en milisegundos."""

    def __init__(self, grafo, dispositivo):
        self.dispositivo = dispositivo
        self.n_usuarios, self.n_peliculas = grafo.n_usuarios, grafo.n_peliculas
        self.por_usuario = tuple(t.to(dispositivo) for t in grafo._por_usuario)    # (usuario, película, semana)
        self.por_pelicula = tuple(t.to(dispositivo) for t in grafo._por_pelicula)  # (película, usuario, semana)
        self.atributos_estaticos = grafo.atributos_pelicula.to(dispositivo)        # géneros, año, falta año
        self.generos = self.atributos_estaticos[:, :-2]
        # Sólo se comparan con "< semana", así que dependen únicamente de datos anteriores a esa semana
        self.semana_alta_usuario = torch.from_numpy(grafo.semana_alta_usuario).to(dispositivo)
        self.semana_alta_pelicula = torch.from_numpy(grafo.semana_alta_pelicula).to(dispositivo)
        self.n_atributos_usuario = N_ATRIBUTOS_USUARIO_BASE + self.generos.shape[1]

    def adyacencias(self, semana_corte, vida_media=None):
        """Como GrafoTemporal.adyacencias, en GPU y con pesos de decaimiento opcionales."""
        return {
            CALIFICA: _matriz_csr(*self.por_pelicula, semana_corte, self.n_peliculas, self.n_usuarios, vida_media),
            CALIFICADA_POR: _matriz_csr(*self.por_usuario, semana_corte, self.n_usuarios, self.n_peliculas, vida_media),
        }

    def atributos(self, semana_corte):
        """Atributos semanales {"usuario": [n_usuarios, 24], "pelicula": [n_peliculas, 5]} para la semana."""
        pelicula, _, semana_p = self.por_pelicula
        anterior = semana_p < semana_corte
        conteo = lambda semanas: torch.bincount(pelicula[anterior & (semana_p >= semana_corte - semanas)], minlength=self.n_peliculas)
        primera_p = _primera_semana(pelicula[anterior], semana_p[anterior], self.n_peliculas)
        conocida = primera_p < semana_corte
        atributos_pelicula = torch.stack([
            torch.log1p(conteo(1).float()), torch.log1p(conteo(4).float()), torch.log1p(conteo(12).float()),
            torch.where(conocida, torch.log1p((semana_corte - primera_p).float()), 0.0), conocida.float(),
        ], dim=1)

        usuario, _, semana_u = self.por_usuario
        anterior = semana_u < semana_corte
        usuario, semana_u = usuario[anterior], semana_u[anterior]
        total = torch.bincount(usuario, minlength=self.n_usuarios).float()
        recientes = torch.bincount(usuario[semana_u >= semana_corte - 4], minlength=self.n_usuarios).float()
        primera_u = _primera_semana(usuario, semana_u, self.n_usuarios)
        ultima_u = torch.full((self.n_usuarios,), -1, dtype=semana_u.dtype, device=self.dispositivo)
        ultima_u.scatter_reduce_(0, usuario, semana_u, reduce="amax")
        con_historia = total > 0
        desde = lambda s: torch.where(con_historia, torch.log1p((semana_corte - s).float()), 0.0)
        # Historial (usuarios × películas, unos) · géneros: sin materializar una fila por rating
        historial = _matriz_csr(*self.por_usuario, semana_corte, self.n_usuarios, self.n_peliculas, None)
        perfil = torch.sparse.mm(historial, self.generos) / total.clamp(min=1)[:, None]
        atributos_usuario = torch.cat([
            torch.stack([torch.log1p(total), torch.log1p(recientes), desde(ultima_u), desde(primera_u)], dim=1), perfil,
        ], dim=1)
        return {"usuario": atributos_usuario, "pelicula": atributos_pelicula}

    def objetivos(self, semana_objetivo, incluir_nuevas=False):
        """Como GrafoTemporal.objetivos (sin el conteo de excluidas), en GPU.

        Con `incluir_nuevas`, también las aristas hacia películas que entran esa semana
        (para entrenar el arranque en frío); el usuario siempre debe tener historia.
        """
        usuario, pelicula, semana = self.por_usuario
        en_la_semana = semana == semana_objetivo
        usuario, pelicula = usuario[en_la_semana], pelicula[en_la_semana]
        con_historia = self.semana_alta_usuario[usuario] < semana_objetivo
        if not incluir_nuevas:
            con_historia &= self.semana_alta_pelicula[pelicula] < semana_objetivo
        return usuario[con_historia], pelicula[con_historia]

    def peliculas_nuevas(self, semana):
        """Películas que reciben su primer rating en `semana` (las candidatas del estrato 0)."""
        return torch.nonzero(self.semana_alta_pelicula == semana).flatten()

    def peliculas_conocidas(self, semana_corte):
        return torch.nonzero(self.semana_alta_pelicula < semana_corte).flatten()

    def popularidad(self, semana_corte, semanas_atras=None):
        """Como GrafoTemporal.popularidad, en GPU."""
        pelicula, _, semana = self.por_pelicula
        vigente = semana < semana_corte
        if semanas_atras is not None:
            vigente &= semana >= semana_corte - semanas_atras
        return torch.bincount(pelicula[vigente], minlength=self.n_peliculas).float()


def pesos_decaimiento(semana_arista, semana_corte, vida_media):
    """0.5 ** ((semana_corte - semana_arista) / vida_media); 1 para todas si vida_media es None."""
    if vida_media is None:
        return torch.ones(len(semana_arista), device=semana_arista.device)
    return torch.pow(0.5, (semana_corte - semana_arista).float() / vida_media)


def _primera_semana(nodo, semana, n_nodos):
    primera = torch.full((n_nodos,), torch.iinfo(semana.dtype).max, dtype=semana.dtype, device=semana.device)
    return primera.scatter_reduce_(0, nodo, semana, reduce="amin")


def _matriz_csr(filas, columnas, semana, semana_corte, n_filas, n_columnas, vida_media):
    vigente = semana < semana_corte
    filas, columnas = filas[vigente], columnas[vigente]
    inicio_fila = torch.zeros(n_filas + 1, dtype=torch.int64, device=filas.device)
    inicio_fila[1:] = torch.cumsum(torch.bincount(filas, minlength=n_filas), dim=0)
    return torch.sparse_csr_tensor(inicio_fila, columnas, pesos_decaimiento(semana[vigente], semana_corte, vida_media),
                                   size=(n_filas, n_columnas), check_invariants=False)
