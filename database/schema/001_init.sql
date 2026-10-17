BEGIN;

CREATE TABLE IF NOT EXISTS movies (
    movie_id        BIGINT PRIMARY KEY,
    title           TEXT NOT NULL,
    release_year    SMALLINT,
    genres          TEXT[] NOT NULL DEFAULT '{}',
    tmdb_id         BIGINT,
    poster_url      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_movies_tmdb_id
    ON movies (tmdb_id)
    WHERE tmdb_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_movies_title
    ON movies USING btree (title);

CREATE TABLE IF NOT EXISTS model_versions (
    model_version   VARCHAR(100) PRIMARY KEY,
    model_name      VARCHAR(100) NOT NULL DEFAULT 'GraphSAGE',
    status          VARCHAR(20) NOT NULL DEFAULT 'candidate'
                    CHECK (status IN ('candidate', 'champion', 'archived', 'failed')),
    artifact_uri    TEXT,
    training_run_id VARCHAR(150),
    cutoff_week     DATE,
    recall_at_k     DOUBLE PRECISION,
    ndcg_at_k       DOUBLE PRECISION,
    mrr             DOUBLE PRECISION,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    promoted_at     TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_model_versions_single_champion
    ON model_versions ((status))
    WHERE status = 'champion';

CREATE TABLE IF NOT EXISTS scoring_runs (
    scoring_run_id          BIGSERIAL PRIMARY KEY,
    model_version           VARCHAR(100) NOT NULL
                            REFERENCES model_versions(model_version)
                            ON UPDATE CASCADE ON DELETE RESTRICT,
    cutoff_week             DATE NOT NULL,
    source_uri              TEXT,
    output_uri              TEXT,
    status                  VARCHAR(20) NOT NULL DEFAULT 'running'
                            CHECK (status IN ('running', 'succeeded', 'failed')),
    users_scored            INTEGER CHECK (users_scored IS NULL OR users_scored >= 0),
    recommendations_written BIGINT CHECK (recommendations_written IS NULL OR recommendations_written >= 0),
    started_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at             TIMESTAMPTZ,
    error_message           TEXT,
    CONSTRAINT ck_scoring_runs_finished_at
        CHECK (finished_at IS NULL OR finished_at >= started_at),
    CONSTRAINT uq_scoring_run_model_week UNIQUE (model_version, cutoff_week)
);

CREATE INDEX IF NOT EXISTS ix_scoring_runs_cutoff_week
    ON scoring_runs (cutoff_week DESC);

CREATE TABLE IF NOT EXISTS recommendations (
    user_id         BIGINT NOT NULL,
    movie_id        BIGINT NOT NULL
                    REFERENCES movies(movie_id)
                    ON UPDATE CASCADE ON DELETE RESTRICT,
    rank            INTEGER NOT NULL CHECK (rank > 0),
    score           DOUBLE PRECISION NOT NULL,
    model_version   VARCHAR(100) NOT NULL
                    REFERENCES model_versions(model_version)
                    ON UPDATE CASCADE ON DELETE RESTRICT,
    cutoff_week     DATE NOT NULL,
    scoring_run_id  BIGINT
                    REFERENCES scoring_runs(scoring_run_id)
                    ON UPDATE CASCADE ON DELETE SET NULL,
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, cutoff_week, rank),
    CONSTRAINT uq_recommendation_movie_per_user_week
        UNIQUE (user_id, cutoff_week, movie_id)
);

CREATE INDEX IF NOT EXISTS ix_recommendations_user_week_rank
    ON recommendations (user_id, cutoff_week DESC, rank ASC);

CREATE INDEX IF NOT EXISTS ix_recommendations_model_version
    ON recommendations (model_version);

CREATE INDEX IF NOT EXISTS ix_recommendations_movie_id
    ON recommendations (movie_id);

COMMIT;
