-- Se ejecuta manualmente mediante el bootstrap local. No borra las interacciones.
BEGIN;

CREATE TABLE IF NOT EXISTS app_users (
    account_id BIGSERIAL PRIMARY KEY,
    username VARCHAR(80) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    movielens_user_id BIGINT NOT NULL UNIQUE CHECK (movielens_user_id > 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_app_users_username_casefold
    ON app_users (lower(username));

CREATE TABLE IF NOT EXISTS catalog_imports (
    dataset_name VARCHAR(80) PRIMARY KEY,
    movies_md5 VARCHAR(32) NOT NULL,
    verified_rows INTEGER NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
