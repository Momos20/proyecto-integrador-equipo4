import json

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.db import database_is_ready
from app.services.interaction_service import create_interaction, get_recent_interactions
from app.services.recommendation_service import get_recommendations


api_bp = Blueprint("api", __name__, url_prefix="/api")

ALLOWED_INTERACTIONS = {"like", "dislike", "rating", "watchlist", "view_details"}


@api_bp.get("/recommendations/<int:user_id>")
def recommendations(user_id: int):
    if user_id <= 0:
        return jsonify(error="invalid_user_id", message="El user_id debe ser mayor que cero."), 400

    try:
        limit = int(request.args.get("limit", "10"))
    except ValueError:
        return jsonify(error="invalid_limit", message="El parámetro limit debe ser un entero."), 400

    if limit < 1 or limit > 50:
        return jsonify(error="invalid_limit", message="limit debe estar entre 1 y 50."), 400

    try:
        payload = get_recommendations(user_id=user_id, limit=limit)
    except SQLAlchemyError:
        return (
            jsonify(
                error="database_unavailable",
                message="No fue posible consultar las recomendaciones en este momento.",
            ),
            503,
        )

    if payload is None:
        return (
            jsonify(
                error="no_recommendations",
                message="No hay recomendaciones disponibles para este usuario.",
                user_id=user_id,
            ),
            404,
        )

    return jsonify(payload)


@api_bp.post("/interactions")
def interactions_create():
    payload = request.get_json(silent=True) or {}

    try:
        user_id = int(payload.get("user_id"))
        movie_id = int(payload.get("movie_id"))
    except (TypeError, ValueError):
        return jsonify(error="invalid_payload", message="user_id y movie_id deben ser enteros."), 400

    if user_id <= 0 or movie_id <= 0:
        return jsonify(error="invalid_payload", message="user_id y movie_id deben ser mayores que cero."), 400

    interaction_type = str(payload.get("interaction_type", "")).strip().lower()
    if interaction_type not in ALLOWED_INTERACTIONS:
        return (
            jsonify(
                error="invalid_interaction_type",
                message=f"interaction_type debe ser uno de: {', '.join(sorted(ALLOWED_INTERACTIONS))}.",
            ),
            400,
        )

    rating = payload.get("rating")
    if interaction_type == "rating":
        try:
            rating = float(rating)
        except (TypeError, ValueError):
            return jsonify(error="invalid_rating", message="rating es obligatorio para una calificación."), 400

        if rating < 0.5 or rating > 5.0 or not (rating * 2).is_integer():
            return jsonify(error="invalid_rating", message="rating debe estar entre 0.5 y 5.0 en pasos de 0.5."), 400
    else:
        rating = None

    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        return jsonify(error="invalid_metadata", message="metadata debe ser un objeto JSON."), 400

    try:
        interaction = create_interaction(
            user_id=user_id,
            movie_id=movie_id,
            interaction_type=interaction_type,
            rating=rating,
            metadata=json.dumps(metadata),
        )
    except IntegrityError:
        return jsonify(error="unknown_movie", message="La película indicada no existe en el catálogo."), 400
    except SQLAlchemyError:
        return jsonify(error="database_unavailable", message="No fue posible guardar la interacción."), 503

    return jsonify(interaction=interaction), 201


@api_bp.get("/interactions/<int:user_id>")
def interactions_recent(user_id: int):
    if user_id <= 0:
        return jsonify(error="invalid_user_id", message="El user_id debe ser mayor que cero."), 400

    try:
        limit = int(request.args.get("limit", "20"))
    except ValueError:
        return jsonify(error="invalid_limit", message="limit debe ser un entero."), 400

    if limit < 1 or limit > 100:
        return jsonify(error="invalid_limit", message="limit debe estar entre 1 y 100."), 400

    try:
        items = get_recent_interactions(user_id=user_id, limit=limit)
    except SQLAlchemyError:
        return jsonify(error="database_unavailable", message="No fue posible consultar las interacciones."), 503

    return jsonify(user_id=user_id, count=len(items), interactions=items)


@api_bp.get("/ready")
def ready():
    ready_state = database_is_ready()
    return (
        jsonify(
            status="ready" if ready_state else "not_ready",
            database="ok" if ready_state else "unavailable",
        ),
        200 if ready_state else 503,
    )
