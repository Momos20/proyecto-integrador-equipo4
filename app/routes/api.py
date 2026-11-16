"""API para el catálogo público y las interacciones/recomendaciones autenticadas."""
import json

from flask import Blueprint, current_app, g, jsonify, request, session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.db import database_is_ready
from app.services.auth_service import (
    csrf_token, get_account, login_required, requires_csrf,
    start_session, verify_credentials,
)
from app.services.catalog_service import get_catalog
from app.services.clickstream_service import emit_interaction_event
from app.services.interaction_service import create_interaction, get_recent_interactions, get_watchlist
from app.services.recommendation_service import get_recommendations

api_bp = Blueprint("api", __name__, url_prefix="/api")
ALLOWED_INTERACTIONS = {"like", "dislike", "rating", "watchlist", "watchlist_remove", "view_details"}


def _csrf_error():
    return jsonify(error="invalid_csrf", message="Actualiza la página e inténtalo de nuevo."), 403


@api_bp.get("/auth/me")
def auth_me():
    token = csrf_token()
    try:
        account = get_account()
    except SQLAlchemyError:
        return jsonify(error="database_unavailable", message="Base de datos no disponible."), 503
    return jsonify(authenticated=bool(account), user=account, csrf_token=token)


@api_bp.post("/auth/login")
def auth_login():
    if not requires_csrf():
        return _csrf_error()
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(error="invalid_payload"), 400
    username = str(data.get("username", "")).strip()
    password = data.get("password", "")
    if not isinstance(password, str) or len(username) > 80 or len(password) > 256:
        return jsonify(error="invalid_credentials", message="Credenciales inválidas."), 400
    try:
        user = verify_credentials(username, password)
    except SQLAlchemyError:
        return jsonify(error="database_unavailable", message="Base de datos no disponible."), 503
    if user is None:
        return jsonify(error="invalid_credentials", message="Usuario o contraseña incorrectos."), 401
    token = start_session(user)
    return jsonify(authenticated=True, user=user, csrf_token=token)


@api_bp.post("/auth/logout")
def auth_logout():
    if not requires_csrf():
        return _csrf_error()
    session.clear()
    return jsonify(authenticated=False, csrf_token=csrf_token())


@api_bp.get("/catalog")
def catalog():
    try:
        limit = int(request.args.get("limit", "24"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        return jsonify(error="invalid_pagination"), 400
    if not 1 <= limit <= 48 or not 0 <= offset <= 100000:
        return jsonify(error="invalid_pagination"), 400
    genre = request.args.get("genre", "").strip() or None
    search = request.args.get("search", "").strip() or None
    if (genre and len(genre) > 40) or (search and len(search) > 100):
        return jsonify(error="invalid_query"), 400
    try:
        return jsonify(get_catalog(limit=limit, offset=offset, genre=genre, search=search))
    except SQLAlchemyError:
        return jsonify(error="database_unavailable"), 503


@api_bp.get("/recommendations")
@login_required
def recommendations():
    return _get_my_recommendations()


@api_bp.get("/recommendations/<int:user_id>")
@login_required
def recommendations_compat(user_id):
    # Compatibilidad con rutas anteriores sin permitir la lectura de cuentas ajenas.
    if user_id != g.account["movielens_user_id"]:
        return jsonify(error="forbidden", message="No puedes consultar recomendaciones de otra cuenta."), 403
    return _get_my_recommendations()


def _get_my_recommendations():
    try:
        limit = int(request.args.get("limit", "10"))
    except ValueError:
        return jsonify(error="invalid_limit"), 400
    if not 1 <= limit <= 50:
        return jsonify(error="invalid_limit"), 400
    try:
        payload = get_recommendations(user_id=g.account["movielens_user_id"], limit=limit)
    except SQLAlchemyError:
        return jsonify(error="database_unavailable"), 503
    if payload is None:
        return jsonify(error="no_recommendations", message="A9 todavía no tiene un ranking publicado para tu cuenta."), 404
    return jsonify(payload)


@api_bp.post("/interactions")
@login_required
def interactions_create():
    if not requires_csrf():
        return _csrf_error()
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify(error="invalid_payload"), 400
    if "user_id" in payload and payload["user_id"] != g.account["movielens_user_id"]:
        return jsonify(error="forbidden", message="No puedes registrar eventos por otro usuario."), 403
    try:
        movie_id = int(payload.get("movie_id"))
    except (TypeError, ValueError):
        return jsonify(error="invalid_payload", message="movie_id debe ser entero."), 400
    if movie_id <= 0:
        return jsonify(error="invalid_payload", message="movie_id debe ser positivo."), 400
    interaction_type = str(payload.get("interaction_type", "")).strip().lower()
    if interaction_type not in ALLOWED_INTERACTIONS:
        return jsonify(error="invalid_interaction_type"), 400
    rating = payload.get("rating")
    if interaction_type == "rating":
        try:
            rating = float(rating)
        except (TypeError, ValueError):
            return jsonify(error="invalid_rating"), 400
        if not (0.5 <= rating <= 5.0 and (rating * 2).is_integer()):
            return jsonify(error="invalid_rating"), 400
    else:
        rating = None
    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict) or len(json.dumps(metadata)) > 3000:
        return jsonify(error="invalid_metadata"), 400
    user_id = int(g.account["movielens_user_id"])
    try:
        interaction = create_interaction(
            user_id=user_id, movie_id=movie_id, interaction_type=interaction_type,
            rating=rating, metadata=json.dumps(metadata),
        )
    except IntegrityError:
        return jsonify(error="unknown_movie", message="La película no existe en el catálogo."), 400
    except SQLAlchemyError:
        return jsonify(error="database_unavailable", message="No fue posible guardar la interacción."), 503
    stream_event = None
    try:
        stream_event = emit_interaction_event(
            user_id=user_id, movie_id=movie_id, interaction_type=interaction_type,
            rating=rating, metadata=metadata, request_id=request.headers.get("X-Request-ID"),
        )
    except OSError:
        current_app.logger.exception("No se pudo escribir en clickstream.log")
    return jsonify(interaction=interaction, stream_event={
        "event_id": stream_event["event_id"], "event_at": stream_event["event_at"], "logged": True,
    } if stream_event else {"logged": False}), 201


@api_bp.get("/watchlist")
@login_required
def watchlist():
    """Mi lista activa: el último evento de cada película determina si permanece guardada."""
    try:
        limit = int(request.args.get("limit", "500"))
    except ValueError:
        return jsonify(error="invalid_limit"), 400
    if not 1 <= limit <= 1000:
        return jsonify(error="invalid_limit"), 400
    try:
        movies = get_watchlist(g.account["movielens_user_id"], limit=limit)
    except SQLAlchemyError:
        return jsonify(error="database_unavailable"), 503
    return jsonify(user_id=g.account["movielens_user_id"], count=len(movies), movies=movies)


@api_bp.get("/interactions")
@login_required
def interactions_recent():
    return _get_recent()


@api_bp.get("/interactions/<int:user_id>")
@login_required
def interactions_recent_compat(user_id):
    if user_id != g.account["movielens_user_id"]:
        return jsonify(error="forbidden"), 403
    return _get_recent()


def _get_recent():
    try:
        limit = int(request.args.get("limit", "20"))
    except ValueError:
        return jsonify(error="invalid_limit"), 400
    if not 1 <= limit <= 100:
        return jsonify(error="invalid_limit"), 400
    try:
        rows = get_recent_interactions(g.account["movielens_user_id"], limit=limit)
    except SQLAlchemyError:
        return jsonify(error="database_unavailable"), 503
    return jsonify(user_id=g.account["movielens_user_id"], count=len(rows), interactions=rows)


@api_bp.get("/ready")
def ready():
    state = database_is_ready()
    return jsonify(status="ready" if state else "not_ready", database="ok" if state else "unavailable"), 200 if state else 503
