BEGIN;

CREATE TABLE IF NOT EXISTS user_interactions (
    interaction_id   BIGSERIAL PRIMARY KEY,
    user_id          BIGINT NOT NULL,
    movie_id         BIGINT NOT NULL
                     REFERENCES movies(movie_id)
                     ON UPDATE CASCADE ON DELETE RESTRICT,
    interaction_type VARCHAR(30) NOT NULL
                     CHECK (interaction_type IN ('like', 'dislike', 'rating', 'watchlist', 'view_details')),
    rating           NUMERIC(2,1),
    source            VARCHAR(30) NOT NULL DEFAULT 'cinegraph',
    event_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_user_interactions_rating
        CHECK (
            (interaction_type = 'rating' AND rating BETWEEN 0.5 AND 5.0)
            OR
            (interaction_type <> 'rating' AND rating IS NULL)
        )
);

CREATE INDEX IF NOT EXISTS ix_user_interactions_user_event
    ON user_interactions (user_id, event_at DESC);

CREATE INDEX IF NOT EXISTS ix_user_interactions_movie_event
    ON user_interactions (movie_id, event_at DESC);

CREATE INDEX IF NOT EXISTS ix_user_interactions_type_event
    ON user_interactions (interaction_type, event_at DESC);

COMMIT;
