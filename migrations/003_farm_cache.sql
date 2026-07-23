-- Миграция 003: кэш ферм между goblin-api и внешним SFL API.
-- БД: sfl  |  Запускать под пользователем с правами CREATE TABLE.

CREATE TABLE IF NOT EXISTS farm_cache (
    farm_id            BIGINT PRIMARY KEY,
    data               JSONB NOT NULL,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_refreshing      BOOLEAN DEFAULT false,
    tracked            BOOLEAN DEFAULT true,
    first_seen         TIMESTAMPTZ DEFAULT now(),
    last_requested_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_farm_cache_tracked ON farm_cache (tracked);
