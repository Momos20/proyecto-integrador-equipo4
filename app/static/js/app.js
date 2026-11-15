"use strict";

// CineGraph UI. Ranking comes only from the API; curated image paths are
// illustrative fallbacks for the ten demo movies, not model predictions.
const form = document.getElementById("recommendationForm");
const userInput = document.getElementById("userId");
const submitButton = document.getElementById("submitButton");
const demoButton = document.getElementById("demoButton");
const emptyDemoButton = document.getElementById("emptyDemoButton");
const resultsSection = document.getElementById("resultsSection");
const loadingSection = document.getElementById("loadingSection");
const emptyState = document.getElementById("emptyState");
const movieGrid = document.getElementById("movieGrid");
const toast = document.getElementById("toast");
const servingNotice = document.getElementById("servingNotice");
const movieFilter = document.getElementById("movieFilter");
const visibleCount = document.getElementById("visibleCount");

const DEMO_POSTERS = Object.freeze({
    2571: "f89U3ADr1oiB1s9GkdPOEpXUk5H.jpg",
    2959: "pB8BM7pdSp6B6Ih7QZ4DrQ3PmJK.jpg",
    4993: "6oom5QYQ2yQTMJIbnvbkBL9cHo6.jpg",
    5952: "5VTN0pR8gcqV3EPUHHfMGnJYN9L.jpg",
    7153: "rCzpDGLbOoPwLjy3OAm5NUPOTrC.jpg",
    79132: "oYuLEt3zVCKq57qu2F8dT7NIa6f.jpg",
    58559: "qJ2tW6WMUDux911r6m7haRef0WH.jpg",
    318: "q6y0Go1tsGEsmtFryDOJo3dEmqu.jpg",
    356: "arw2vcBveWOVZr6pxd9XTd1TdQa.jpg",
    296: "d5iIlFn5s0ImszYzBPb8JPIfbXD.jpg",
});

let activeUserId = null;
let activeRecommendationContext = null;
let currentRecommendations = [];
let toastTimer;

function escapeHtml(value) {
    return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function safePosterUrl(movie) {
    const candidate = movie.poster_url;
    if (typeof candidate === "string") {
        try {
            const parsed = new URL(candidate, window.location.href);
            if (parsed.protocol === "https:" && (parsed.hostname === "image.tmdb.org" ||
                parsed.hostname.endsWith(".themoviedb.org"))) return parsed.href;
        } catch (_error) {
            // Invalid image URLs fall back to curated artwork.
        }
    }
    const file = DEMO_POSTERS[Number(movie.movie_id)];
    return file ? `https://image.tmdb.org/t/p/w500/${file}` : "";
}

function showToast(message) {
    toast.textContent = message;
    toast.classList.add("visible");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.remove("visible"), 3400);
}

function setLoading(isLoading) {
    loadingSection.hidden = !isLoading;
    submitButton.disabled = isLoading;
    submitButton.querySelector("span").textContent = isLoading ? "Buscando…" : "Descubrir mi Top 10";
    if (isLoading) {
        resultsSection.hidden = true;
        emptyState.hidden = true;
    }
}

function interactionMetadata(card) {
    const position = Number(card?.dataset.rank || 0) || null;
    const cutoffDate = activeRecommendationContext?.cutoffDate || null;
    const modelVersion = activeRecommendationContext?.modelVersion || null;
    return {
        recommendation_id: cutoffDate && position ? `${activeUserId}:${cutoffDate}:${position}` : null,
        model_version: modelVersion,
        position,
        cutoff_date: cutoffDate,
        surface: "top10",
    };
}

async function saveInteraction(movieId, interactionType, rating = null, button = null, card = null) {
    if (!activeUserId) {
        showToast("Primero carga las recomendaciones de un usuario.");
        return;
    }
    const sourceCard = card || button?.closest(".movie-card") || null;
    if (button) button.disabled = true;
    try {
        const response = await fetch("/api/interactions", {
            method: "POST",
            headers: {"Content-Type": "application/json", "Accept": "application/json"},
            body: JSON.stringify({
                user_id: activeUserId,
                movie_id: Number(movieId),
                interaction_type: interactionType,
                rating,
                metadata: interactionMetadata(sourceCard),
            }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || "No se pudo guardar tu interacción.");
        if (button) {
            if (interactionType === "like" || interactionType === "dislike") {
                sourceCard.querySelectorAll('[data-action="like"],[data-action="dislike"]')
                    .forEach((item) => {
                        item.classList.remove("is-selected");
                        item.setAttribute("aria-pressed", "false");
                    });
            }
            button.classList.add("is-selected");
            button.setAttribute("aria-pressed", "true");
        }
        const labels = {
            like: "¡Guardado! Te interesa esta película.",
            dislike: "Tu preferencia quedó registrada.",
            watchlist: "Película agregada a tu lista.",
            rating: `Calificación de ${rating} estrellas guardada.`,
        };
        showToast(labels[interactionType] || "Interacción guardada.");
    } catch (error) {
        showToast(error.message || "No fue posible guardar la interacción.");
    } finally {
        if (button) button.disabled = false;
    }
}

function cardMarkup(movie) {
    const genres = (movie.genres || []).slice(0, 2)
        .map((genre) => `<span class="genre-chip">${escapeHtml(genre)}</span>`).join("");
    const numericScore = Number(movie.score);
    const score = Number.isFinite(numericScore) ? numericScore.toFixed(3) : "n/d";
    const poster = safePosterUrl(movie);
    const image = poster
        ? `<img src="${escapeHtml(poster)}" loading="lazy" decoding="async" alt="Póster de ${escapeHtml(movie.title)}">`
        : "";
    return `<article class="movie-card" data-movie-id="${escapeHtml(movie.movie_id)}" data-rank="${escapeHtml(movie.rank)}">
        <div class="poster">
          <div class="poster-fallback" aria-hidden="true">${escapeHtml(movie.title)}</div>
          ${image}
          <span class="poster-rank">#${escapeHtml(movie.rank)}</span>
          <span class="poster-score">Score ${score}</span>
        </div>
        <div class="movie-info">
          <h3 class="movie-title" title="${escapeHtml(movie.title)}">${escapeHtml(movie.title)}</h3>
          <span class="movie-year">${escapeHtml(movie.release_year || "Año n/d")}</span>
          <div class="genre-list">${genres}</div>
        </div>
        <div class="movie-actions">
          <button type="button" class="feedback-button" data-action="like" aria-pressed="false" aria-label="Me interesa ${escapeHtml(movie.title)}">♥ Me gusta</button>
          <button type="button" class="feedback-button is-negative" data-action="dislike" aria-pressed="false" aria-label="No me interesa ${escapeHtml(movie.title)}">✕ No me gusta</button>
          <button type="button" class="feedback-button" data-action="watchlist" aria-pressed="false" aria-label="Agregar ${escapeHtml(movie.title)} a mi lista">＋ Mi lista</button>
          <label class="rating-control">Calificar
            <select data-action="rating" aria-label="Calificar ${escapeHtml(movie.title)}">
              <option value="">Elegir estrellas</option>
              <option value="5">★★★★★ (5)</option>
              <option value="4.5">4,5 ★</option>
              <option value="4">4 ★</option>
              <option value="3.5">3,5 ★</option>
              <option value="3">3 ★</option>
              <option value="2.5">2,5 ★</option>
              <option value="2">2 ★</option>
              <option value="1.5">1,5 ★</option>
              <option value="1">1 ★</option>
              <option value="0.5">0,5 ★</option>
            </select>
          </label>
        </div>
      </article>`;
}

function filterMovies() {
    const q = movieFilter.value.trim().toLocaleLowerCase("es");
    const selection = currentRecommendations.filter((movie) => {
        const haystack = [movie.title, ...(movie.genres || []), movie.release_year].join(" ").toLocaleLowerCase("es");
        return haystack.includes(q);
    });
    visibleCount.textContent = selection.length;
    movieGrid.innerHTML = selection.length
        ? selection.map(cardMarkup).join("")
        : '<p class="no-results">No encontramos películas con ese nombre en tu Top 10.</p>';
}

function renderRecommendations(data) {
    activeUserId = data.user_id;
    activeRecommendationContext = {
        modelVersion: data.model?.version || null,
        cutoffDate: data.cutoff_date || data.cutoff_week || null,
    };
    currentRecommendations = Array.isArray(data.recommendations) ? data.recommendations : [];
    document.getElementById("resultCount").textContent = data.count;
    document.getElementById("resultUser").textContent = data.user_id;
    const name = (data.model?.name || "").toLowerCase();
    const version = (data.model?.version || "").toLowerCase();
    const demo = version === "baseline-v0" || name === "popularitybaseline";
    document.getElementById("modelName").textContent = demo ? "Datos de prueba" : (data.model?.name || "—");
    document.getElementById("modelVersion").textContent = demo ? "Demostración" : (data.model?.version || "—");
    document.getElementById("cutoffWeek").textContent = activeRecommendationContext.cutoffDate || "—";
    servingNotice.hidden = false;
    servingNotice.textContent = demo
        ? "Top-10 de demostración. Estas películas NO fueron recomendadas por GraphSAGE A9_sin_id; el modelo aún está pendiente de integración."
        : "Estas recomendaciones vienen del modelo indicado. Los scores son valores de ranking, no probabilidades calibradas.";
    movieFilter.value = "";
    filterMovies();
    emptyState.hidden = true;
    resultsSection.hidden = false;
    resultsSection.scrollIntoView({behavior: "smooth", block: "start"});
}

async function loadRecommendations(userId) {
    const numericId = Number(userId);
    if (!Number.isSafeInteger(numericId) || numericId <= 0) {
        showToast("Ingresa un identificador de usuario válido.");
        userInput.focus();
        return;
    }
    setLoading(true);
    try {
        const response = await fetch(`/api/recommendations/${numericId}?limit=10`, {
            headers: {"Accept": "application/json"},
        });
        const data = await response.json();
        if (response.status === 404) {
            activeUserId = null;
            currentRecommendations = [];
            resultsSection.hidden = true;
            emptyState.hidden = false;
            emptyState.scrollIntoView({behavior: "smooth", block: "center"});
            return;
        }
        if (!response.ok) throw new Error(data.message || "No fue posible obtener el ranking.");
        renderRecommendations(data);
    } catch (error) {
        showToast(error.message || "Ocurrió un error inesperado.");
    } finally {
        setLoading(false);
    }
}

movieGrid.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const card = button.closest(".movie-card");
    if (!card) return;
    saveInteraction(card.dataset.movieId, button.dataset.action, null, button, card);
});

movieGrid.addEventListener("change", (event) => {
    const select = event.target.closest('select[data-action="rating"]');
    if (!select || !select.value) return;
    const card = select.closest(".movie-card");
    if (card) saveInteraction(card.dataset.movieId, "rating", Number(select.value), null, card);
});

movieFilter.addEventListener("input", filterMovies);
function runDemo() {
    userInput.value = window.CINEGRAPH_DEMO_USER || 414;
    loadRecommendations(userInput.value);
}
form.addEventListener("submit", (event) => {
    event.preventDefault();
    loadRecommendations(userInput.value);
});
demoButton.addEventListener("click", runDemo);
emptyDemoButton.addEventListener("click", runDemo);


// Broken remote poster URLs should never leave visible broken-image icons.
document.addEventListener("error", (event) => {
    if (event.target instanceof HTMLImageElement &&
        event.target.matches(".editorial-image img, .poster img")) {
        event.target.remove();
    }
}, true);
