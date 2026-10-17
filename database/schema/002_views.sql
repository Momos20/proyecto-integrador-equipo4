CREATE OR REPLACE VIEW latest_recommendations AS
WITH latest_week AS (
    SELECT user_id, MAX(cutoff_week) AS cutoff_week
    FROM recommendations
    GROUP BY user_id
)
SELECT
    r.user_id,
    r.movie_id,
    m.title,
    m.release_year,
    m.genres,
    m.poster_url,
    r.rank,
    r.score,
    r.model_version,
    r.cutoff_week,
    r.generated_at
FROM recommendations r
JOIN latest_week lw
  ON lw.user_id = r.user_id
 AND lw.cutoff_week = r.cutoff_week
JOIN movies m
  ON m.movie_id = r.movie_id;
