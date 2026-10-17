from flask import Blueprint, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from app.db import database_is_ready
from app.services.recommendation_service import get_recommendations


api_bp = Blueprint("api", __name__, url_prefix="/api")


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
