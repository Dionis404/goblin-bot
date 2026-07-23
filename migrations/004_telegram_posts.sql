-- Миграция 004: посты канала @URGSFL, зеркалируемые ботом через polling.
-- БД: sfl  |  Запускать под пользователем с правами CREATE TABLE.

CREATE TABLE IF NOT EXISTS telegram_posts (
    id            BIGINT PRIMARY KEY,
    message_date  TIMESTAMPTZ NOT NULL,
    text          TEXT NOT NULL,
    image_url     TEXT,
    created_at    TIMESTAMPTZ DEFAULT now()
);
