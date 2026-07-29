-- Миграция 006: количество подписчиков канала @URGSFL (для сайта goblincodex.fun).
-- БД: sfl  |  Запускать под пользователем с правами CREATE TABLE.

CREATE TABLE IF NOT EXISTS telegram_stats (
    channel        TEXT PRIMARY KEY,
    subscribers    INT NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
