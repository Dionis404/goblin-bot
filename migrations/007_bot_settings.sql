-- Миграция 007: key-value настройки бота (например, тоггл уведомлений о подписчиках).
-- БД: sfl  |  Запускать под пользователем с правами CREATE TABLE.

CREATE TABLE IF NOT EXISTS bot_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
