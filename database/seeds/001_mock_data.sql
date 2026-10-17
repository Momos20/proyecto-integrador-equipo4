BEGIN;

INSERT INTO movies (movie_id, title, release_year, genres, tmdb_id) VALUES
    (2571, 'The Matrix', 1999, ARRAY['Action','Sci-Fi'], 603),
    (2959, 'Fight Club', 1999, ARRAY['Drama'], 550),
    (4993, 'The Lord of the Rings: The Fellowship of the Ring', 2001, ARRAY['Adventure','Fantasy'], 120),
    (5952, 'The Lord of the Rings: The Two Towers', 2002, ARRAY['Adventure','Fantasy'], 121),
    (7153, 'The Lord of the Rings: The Return of the King', 2003, ARRAY['Adventure','Fantasy'], 122),
    (79132, 'Inception', 2010, ARRAY['Action','Sci-Fi','Thriller'], 27205),
    (58559, 'The Dark Knight', 2008, ARRAY['Action','Crime','Drama'], 155),
    (318, 'The Shawshank Redemption', 1994, ARRAY['Crime','Drama'], 278),
    (356, 'Forrest Gump', 1994, ARRAY['Comedy','Drama','Romance'], 13),
    (296, 'Pulp Fiction', 1994, ARRAY['Comedy','Crime','Drama','Thriller'], 680)
ON CONFLICT (movie_id) DO UPDATE SET
    title = EXCLUDED.title,
    release_year = EXCLUDED.release_year,
    genres = EXCLUDED.genres,
    tmdb_id = EXCLUDED.tmdb_id,
    updated_at = NOW();

INSERT INTO model_versions (
    model_version, model_name, status, artifact_uri, cutoff_week,
    recall_at_k, ndcg_at_k, mrr
) VALUES (
    'baseline-v0',
    'PopularityBaseline',
    'champion',
    'local://mock/baseline-v0',
    DATE '2026-10-12',
    0.1200,
    0.0900,
    0.0800
)
ON CONFLICT (model_version) DO NOTHING;

INSERT INTO scoring_runs (
    model_version, cutoff_week, source_uri, output_uri, status,
    users_scored, recommendations_written, finished_at
) VALUES (
    'baseline-v0',
    DATE '2026-10-12',
    'local://mock/features',
    'local://mock/predictions',
    'succeeded',
    1,
    10,
    NOW()
)
ON CONFLICT (model_version, cutoff_week) DO UPDATE SET
    status = EXCLUDED.status,
    users_scored = EXCLUDED.users_scored,
    recommendations_written = EXCLUDED.recommendations_written,
    finished_at = EXCLUDED.finished_at;

WITH run AS (
    SELECT scoring_run_id
    FROM scoring_runs
    WHERE model_version = 'baseline-v0'
      AND cutoff_week = DATE '2026-10-12'
)
INSERT INTO recommendations (
    user_id, movie_id, rank, score, model_version,
    cutoff_week, scoring_run_id
)
SELECT 414, x.movie_id, x.rank, x.score, 'baseline-v0',
       DATE '2026-10-12', run.scoring_run_id
FROM run
CROSS JOIN (VALUES
    (2571::BIGINT, 1, 0.973::DOUBLE PRECISION),
    (2959::BIGINT, 2, 0.951::DOUBLE PRECISION),
    (4993::BIGINT, 3, 0.944::DOUBLE PRECISION),
    (79132::BIGINT, 4, 0.928::DOUBLE PRECISION),
    (58559::BIGINT, 5, 0.913::DOUBLE PRECISION),
    (7153::BIGINT, 6, 0.901::DOUBLE PRECISION),
    (5952::BIGINT, 7, 0.894::DOUBLE PRECISION),
    (318::BIGINT, 8, 0.882::DOUBLE PRECISION),
    (356::BIGINT, 9, 0.871::DOUBLE PRECISION),
    (296::BIGINT, 10, 0.859::DOUBLE PRECISION)
) AS x(movie_id, rank, score)
ON CONFLICT (user_id, cutoff_week, rank) DO UPDATE SET
    movie_id = EXCLUDED.movie_id,
    score = EXCLUDED.score,
    model_version = EXCLUDED.model_version,
    scoring_run_id = EXCLUDED.scoring_run_id,
    generated_at = NOW();

COMMIT;
