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

const palette = [
    ["#312e81", "#7c3aed", "#0f172a"],
    ["#7f1d1d", "#be123c", "#18181b"],
    ["#164e63", "#0891b2", "#0f172a"],
    ["#3f3f46", "#52525b", "#09090b"],
    ["#581c87", "#a21caf", "#111827"],
    ["#064e3b", "#047857", "#111827"],
    ["#78350f", "#b45309", "#18181b"],
];

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function posterGradient(movieId) {
    const colors = palette[Math.abs(Number(movieId)) % palette.length];
    return `linear-gradient(145deg, ${colors[0]} 0%, ${colors[1]} 48%, ${colors[2]} 100%)`;
}

function shortPosterTitle(title) {
    const clean = String(title).replace(/\s*\([^)]*\)\s*$/, "");
    return clean.length > 38 ? `${clean.slice(0, 35)}…` : clean;
}

function showToast(message) {
    toast.textContent = message;
    toast.classList.add("visible");
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => toast.classList.remove("visible"), 3200);
}

function setLoading(isLoading) {
    loadingSection.hidden = !isLoading;
    submitButton.disabled = isLoading;
    submitButton.querySelector("span").textContent = isLoading ? "Calculando…" : "Descubrir mi Top 10";
    if (isLoading) {
        resultsSection.hidden = true;
        emptyState.hidden = true;
    }
}

function renderRecommendations(data) {
    document.getElementById("resultCount").textContent = data.count;
    document.getElementById("resultUser").textContent = data.user_id;
    document.getElementById("modelName").textContent = data.model?.name || "—";
    document.getElementById("modelVersion").textContent = data.model?.version || "—";
    document.getElementById("cutoffWeek").textContent = data.cutoff_week || "—";

    movieGrid.innerHTML = data.recommendations.map((movie) => {
        const genres = (movie.genres || []).slice(0, 3)
            .map((genre) => `<span class="genre-chip">${escapeHtml(genre)}</span>`)
            .join("");
        const score = `${Math.round(Number(movie.score) * 100)}% match`;
        const background = posterGradient(movie.movie_id);

        return `
            <article class="movie-card">
                <div class="poster" style="--poster-gradient:${background}">
                    <span class="rank-badge">#${movie.rank}</span>
                    <span class="score-badge">${score}</span>
                    <div class="poster-title">${escapeHtml(shortPosterTitle(movie.title))}</div>
                </div>
                <div class="movie-info">
                    <h3 class="movie-title" title="${escapeHtml(movie.title)}">${escapeHtml(movie.title)}</h3>
                    <span class="movie-year">${movie.release_year || "Año n/d"}</span>
                    <div class="genre-list">${genres}</div>
                </div>
            </article>`;
    }).join("");

    emptyState.hidden = true;
    resultsSection.hidden = false;
    resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadRecommendations(userId) {
    const numericId = Number(userId);
    if (!Number.isInteger(numericId) || numericId <= 0) {
        showToast("Ingresa un identificador de usuario válido.");
        userInput.focus();
        return;
    }

    setLoading(true);
    try {
        const response = await fetch(`/api/recommendations/${numericId}?limit=10`, {
            headers: { "Accept": "application/json" },
        });
        const data = await response.json();

        if (response.status === 404) {
            resultsSection.hidden = true;
            emptyState.hidden = false;
            emptyState.scrollIntoView({ behavior: "smooth", block: "center" });
            return;
        }

        if (!response.ok) {
            throw new Error(data.message || "No fue posible cargar las recomendaciones.");
        }

        renderRecommendations(data);
    } catch (error) {
        showToast(error.message || "Ocurrió un error inesperado.");
    } finally {
        setLoading(false);
    }
}

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
