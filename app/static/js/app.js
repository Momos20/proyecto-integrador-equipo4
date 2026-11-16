"use strict";

// CineGraph: películas leídas de PostgreSQL (catálogo verificado MovieLens 32M).
// Nunca insertamos títulos, pósteres ni rankings de prueba en el cliente.
const $ = (id) => document.getElementById(id);
const state = { user: null, csrf: null, catalog: new Map(), ranking: null, busy: false };
const rails = [
  { id: "new", title: "Recién llegadas al catálogo", genre: null },
  { id: "action", title: "Acción y aventura", genre: "Action" },
  { id: "scifi", title: "Ciencia ficción", genre: "Sci-Fi" },
  { id: "drama", title: "Historias que emocionan", genre: "Drama" },
  { id: "comedy", title: "Para reír un rato", genre: "Comedy" },
];
let toastTimer;
function safe(value) { return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;"); }
function posterUrl(candidate) {
  if (!candidate || typeof candidate !== "string") return null;
  try { const u = new URL(candidate); if (u.protocol === "https:" && (u.hostname === "image.tmdb.org" || u.hostname.endsWith(".themoviedb.org"))) return u.href; }
  catch (_error) { /* La fuente no tiene imagen válida */ }
  return null;
}
function toast(message) { $("toast").textContent = message; $("toast").classList.add("visible");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => $("toast").classList.remove("visible"), 3500); }
async function request(url, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (options.method && options.method !== "GET") headers["X-CSRF-Token"] = state.csrf || "";
  const response = await fetch(url, { credentials: "same-origin", ...options, headers });
  const data = await response.json();
  if (!response.ok) { const error = new Error(data.message || "No se pudo completar la solicitud."); error.status = response.status; throw error; }
  return data;
}
function showLogin() { $("loginModal").hidden = false; document.body.classList.add("modal-open"); $("loginError").hidden = true; $("loginUsername").focus(); }
function hideLogin() { $("loginModal").hidden = true; document.body.classList.remove("modal-open"); $("loginPassword").value = ""; }
function renderAuth() {
  $("openLogin").hidden = Boolean(state.user);
  $("logoutButton").hidden = !state.user;
  $("accountName").hidden = !state.user;
  $("accountName").textContent = state.user ? state.user.username : "";
  $("heroAccount").textContent = state.user
    ? `Hola, ${state.user.username}. Tu experiencia está vinculada exclusivamente a tu perfil.`
    : "Explora el catálogo. Inicia sesión para guardar tus gustos y ver tu selección personal.";
}
function movieCard(movie, {rank = false, surface = "catalog"} = {}) {
  const img = posterUrl(movie.poster_url);
  const title = safe(movie.title);
  const genre = safe((movie.genres || []).slice(0, 2).join(" · ") || "Película");
  const art = img ? `<img src="${safe(img)}" alt="Póster de ${title}" loading="lazy" decoding="async">` : "";
  return `<article class="movie-card" data-movie-id="${Number(movie.movie_id)}" data-rank="${rank ? Number(movie.rank) : ""}" data-surface="${safe(surface)}">
    <div class="poster"><div class="poster-fallback" aria-hidden="true"><span>CG</span><strong>${title}</strong></div>${art}
       ${rank ? `<span class="poster-rank">${Number(movie.rank)}</span>` : ""}
       <div class="card-hover"><span class="card-hover-title">${title}</span><span class="card-hover-meta">${safe(movie.release_year || "")} · ${genre}</span></div>
    </div>
    <div class="movie-info"><h3>${title}</h3><span>${safe(movie.release_year || "")} · ${genre}</span></div>
    <div class="movie-actions">
      <button type="button" class="feedback-button" data-action="like" aria-label="Me gusta ${title}">♥ Me gusta</button>
      <button type="button" class="feedback-button" data-action="watchlist" aria-label="Añadir ${title} a mi lista">＋ Mi lista</button>
      <label class="rating-control">Calificar <select data-action="rating" aria-label="Calificar ${title}">
        <option value="">Estrellas</option>${[5,4.5,4,3.5,3,2.5,2,1.5,1,0.5].map(n=>`<option value="${n}">${n} ★</option>`).join("")}
      </select></label>
    </div></article>`;
}
function makeShelf(key, name, movies) {
  const section = document.createElement("section");
  section.className = "catalog-row";
  section.innerHTML = `<div class="row-heading"><h3>${safe(name)}</h3><div class="row-controls"><button type="button" class="shelf-arrow" data-direction="-1" aria-label="Ver películas anteriores">‹</button><button type="button" class="shelf-arrow" data-direction="1" aria-label="Ver más películas">›</button></div></div><div class="shelf-track" id="rail-${safe(key)}" tabindex="0" aria-label="${safe(name)}">${movies.map(movie=>movieCard(movie)).join("")}</div>`;
  return section;
}
async function loadCatalog() {
  const container = $("catalogShelves");
  // La portada permanece visible; no presentar tarjetas de error si no hay catálogo.
  $("catalogo").hidden = true;
  container.replaceChildren();
  const results = await Promise.allSettled(rails.map(async (row) => {
    const query = new URLSearchParams({ limit: "18" });
    if (row.genre) query.set("genre", row.genre);
    const data = await request(`/api/catalog?${query}`);
    if (!data.ready) return {row, ready: false, movies: []};
    for (const movie of data.movies) state.catalog.set(Number(movie.movie_id), movie);
    return {row, ready: true, movies: data.movies};
  }));
  let loaded = 0; let pendingSetup = false;
  for (const r of results) {
    if (r.status !== "fulfilled") continue;
    const { row, ready, movies } = r.value;
    if (!ready) { pendingSetup = true; continue; }
    if (movies.length) { container.appendChild(makeShelf(row.id, row.title, movies)); loaded++; }
  }
  $("catalogStatus").hidden = true;
  $("catalogo").hidden = loaded === 0;
  // No fabricar películas ni mostrar una estantería vacía como si fuese contenido.
  if (!loaded) console.info(pendingSetup
    ? "CineGraph: el catálogo original todavía no se ha importado."
    : "CineGraph: el catálogo no está disponible.");
}
async function loadRecommendations() {
  $("paraTi").hidden = true;
  $("personalRail").hidden = true;
  $("personalEmpty").hidden = false;
  state.ranking = null;
  if (!state.user) { $("personalEmpty").textContent = "Inicia sesión para consultar tu selección personal."; return; }
  $("personalEmpty").textContent = "Consultando tus recomendaciones…";
  try {
    const data = await request("/api/recommendations?limit=10");
    if (data.model?.version !== "a9-miguel-diario" || !Array.isArray(data.recommendations) || !data.recommendations.length) throw new Error("No hay predicciones A9 publicadas para tu cuenta.");
    state.ranking = data;
    for (const movie of data.recommendations) state.catalog.set(Number(movie.movie_id), movie);
    $("personalRail").innerHTML = data.recommendations.map(m => movieCard(m,{rank:true,surface:"a9"})).join("");
    $("personalRail").hidden = false;
    $("personalEmpty").hidden = true;
    $("paraTi").hidden = false;
    $("personalInfo").textContent = `GraphSAGE A9 · corte ${data.cutoff_date} · datos reales`;
  } catch (error) {
    $("personalEmpty").textContent = error.status === 404
      ? "Todavía no se han publicado recomendaciones de GraphSAGE A9 para este usuario. Puedes explorar el catálogo mientras tanto."
      : "No fue posible consultar el ranking de tu cuenta. Vuelve a intentarlo más tarde.";
  }
}
async function loadWatchlist() {
  $("miLista").hidden = true;
  $("watchlistRail").hidden = true;
  $("watchlistEmpty").hidden = false;
  if (!state.user) { $("watchlistEmpty").textContent = "Inicia sesión para ver tu lista."; return; }
  try {
    const result = await request("/api/interactions?limit=100");
    const seen = new Set(); const list = [];
    for (const row of result.interactions) {
      if (row.interaction_type !== "watchlist" || seen.has(Number(row.movie_id))) continue;
      seen.add(Number(row.movie_id));
      list.push(state.catalog.get(Number(row.movie_id)) || {movie_id:row.movie_id,title:row.title,genres:[],release_year:null,poster_url:null});
    }
    if (!list.length) { $("watchlistEmpty").textContent = "Las películas que guardes aparecerán aquí."; return; }
    $("watchlistRail").innerHTML = list.map(m => movieCard(m,{surface:"watchlist"})).join("");
    $("watchlistRail").hidden = false; $("watchlistEmpty").hidden = true;
    $("miLista").hidden = false;
  } catch (_error) { $("watchlistEmpty").textContent = "No fue posible consultar tu lista."; }
}
async function sendInteraction(card, action, rating, control) {
  if (!state.user) { showLogin(); return; }
  if (state.busy) return;
  state.busy = true; if (control) control.disabled = true;
  try {
    const isA9 = card.dataset.surface === "a9" && Boolean(state.ranking);
    const metadata = { surface: isA9 ? "top10_a9" : "catalog",
      model_version: isA9 ? "a9-miguel-diario" : null,
      position: isA9 ? Number(card.dataset.rank) : null,
      cutoff_date: isA9 ? state.ranking.cutoff_date : null };
    if (isA9) metadata.recommendation_id = `${state.user.movielens_user_id}:${metadata.cutoff_date}:${metadata.position}`;
    const response = await request("/api/interactions", { method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({movie_id:Number(card.dataset.movieId), interaction_type:action, rating, metadata}) });
    if (!response.interaction) throw new Error("La interacción no quedó registrada.");
    if (control?.tagName === "BUTTON") { control.classList.add("is-selected"); control.setAttribute("aria-pressed", "true"); }
    toast(action === "watchlist" ? "Guardada en tu lista." : action === "rating" ? "Calificación guardada." : "Tu preferencia quedó guardada.");
    if (action === "watchlist") await loadWatchlist();
  } catch (error) { toast(error.message || "No se pudo guardar la interacción."); }
  finally { state.busy = false; if (control) control.disabled = false; }
}

$("openLogin").addEventListener("click", showLogin);
$("closeLogin").addEventListener("click", hideLogin);
document.querySelector("[data-close-login]").addEventListener("click", hideLogin);
document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("loginModal").hidden) hideLogin(); });
$("loginForm").addEventListener("submit", async e => {
  e.preventDefault(); $("loginSubmit").disabled = true; $("loginError").hidden = true;
  try {
    const data = await request("/api/auth/login", { method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({username:$("loginUsername").value,password:$("loginPassword").value}) });
    state.user = data.user; state.csrf = data.csrf_token;
    hideLogin(); renderAuth();
    // Tras entrar, presentar la portada cinematográfica de Inicio, no las secciones vacías.
    if (window.location.hash) window.history.replaceState(null, "", window.location.pathname + window.location.search);
    window.scrollTo({ top: 0, behavior: "smooth" });
    await Promise.all([loadRecommendations(), loadWatchlist()]);
    toast(`Bienvenido, ${state.user.username}.`);
  } catch (error) { $("loginError").textContent = error.message; $("loginError").hidden = false; }
  finally { $("loginSubmit").disabled = false; }
});
$("logoutButton").addEventListener("click", async () => {
  try { const data = await request("/api/auth/logout",{method:"POST"});state.csrf=data.csrf_token;
    state.user=null;state.ranking=null;renderAuth();await Promise.all([loadRecommendations(),loadWatchlist()]);toast("Sesión cerrada."); }
  catch(e){ toast(e.message); }
});
document.addEventListener("click", (event) => {
  const nav = event.target.closest(".shelf-arrow");
  if (nav) { const track = nav.closest(".catalog-row")?.querySelector(".shelf-track");
    if (track) track.scrollBy({left:Number(nav.dataset.direction)*track.clientWidth*.83,behavior:"smooth"}); return; }
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const card = button.closest(".movie-card");
  if (card) sendInteraction(card,button.dataset.action,null,button);
});
document.addEventListener("change", (event) => {
  const select = event.target.closest('select[data-action="rating"]');
  if (!select || !select.value) return;
  const card = select.closest(".movie-card");
  if (card) sendInteraction(card,"rating",Number(select.value),select);
});
document.addEventListener("error", (event) => {
  if (event.target instanceof HTMLImageElement && event.target.closest(".poster")) event.target.remove();
},true);
window.addEventListener("scroll", () => $("topbar").classList.toggle("is-scrolled", window.scrollY > 24), {passive:true});
(async () => {
  try { const data = await request("/api/auth/me"); state.csrf = data.csrf_token; state.user = data.user || null; }
  catch (_error) { $("catalogStatus").textContent = "El servidor aún no está preparado. Ejecuta el bootstrap local."; }
  renderAuth();
  // Reapertura de sesión: la experiencia comienza en la portada, sin saltar a estanterías.
  if (state.user && !window.location.hash) window.scrollTo(0, 0);
  await loadCatalog();
  await Promise.all([loadRecommendations(),loadWatchlist()]);
})();
