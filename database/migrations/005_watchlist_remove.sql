-- CineGraph: migración idempotente para bases ya inicializadas.
-- Ejecutar antes de activar el backend actualizado:
-- docker compose exec -T db psql -v ON_ERROR_STOP=1 -U recommender -d recommender < database/migrations/005_watchlist_remove.sql
-- No borra el historial; cada quitar/volver a añadir queda registrado.
BEGIN;
ALTER TABLE user_interactions
    DROP CONSTRAINT IF EXISTS user_interactions_interaction_type_check;
ALTER TABLE user_interactions
    ADD CONSTRAINT user_interactions_interaction_type_check
    CHECK (interaction_type IN ('like', 'dislike', 'rating', 'watchlist',
                                'watchlist_remove', 'view_details'));
CREATE INDEX IF NOT EXISTS ix_user_interactions_watchlist_latest
    ON user_interactions (user_id, movie_id, event_at DESC, interaction_id DESC)
    WHERE interaction_type IN ('watchlist', 'watchlist_remove');
COMMIT;
