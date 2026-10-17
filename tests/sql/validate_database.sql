DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'movies'
    ) THEN
        RAISE EXCEPTION 'movies table is missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'recommendations'
    ) THEN
        RAISE EXCEPTION 'recommendations table is missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'model_versions'
    ) THEN
        RAISE EXCEPTION 'model_versions table is missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'scoring_runs'
    ) THEN
        RAISE EXCEPTION 'scoring_runs table is missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.views
        WHERE table_schema = 'public' AND table_name = 'latest_recommendations'
    ) THEN
        RAISE EXCEPTION 'latest_recommendations view is missing';
    END IF;

    IF (SELECT COUNT(*) FROM latest_recommendations WHERE user_id = 414) <> 10 THEN
        RAISE EXCEPTION 'expected 10 mock recommendations for user 414';
    END IF;

    IF (SELECT MIN(rank) FROM latest_recommendations WHERE user_id = 414) <> 1
       OR (SELECT MAX(rank) FROM latest_recommendations WHERE user_id = 414) <> 10 THEN
        RAISE EXCEPTION 'mock recommendation ranks must span 1..10';
    END IF;

    IF (SELECT COUNT(*) FROM model_versions WHERE status = 'champion') <> 1 THEN
        RAISE EXCEPTION 'expected exactly one champion model';
    END IF;
END
$$;

SELECT user_id, rank, movie_id, title, score, model_version, cutoff_week
FROM latest_recommendations
WHERE user_id = 414
ORDER BY rank;
