-- Миграция 012: таймаут лока is_refreshing в farm_cache.
-- Если процесс goblin-api перезапускался посреди обновления фермы, флаг
-- is_refreshing навсегда оставался true, и ферма больше никогда не
-- обновлялась через /farm, /farms. Теперь лок считается протухшим через
-- REFRESH_LOCK_TIMEOUT (см. shared/farm_cache.py) после refresh_started_at.
-- БД: sfl  |  Запускать под пользователем с правами ALTER TABLE.

ALTER TABLE farm_cache ADD COLUMN IF NOT EXISTS refresh_started_at TIMESTAMPTZ;

-- Разово снимаем уже зависшие локи (до миграции их не с чем было сравнивать)
UPDATE farm_cache SET is_refreshing = false WHERE is_refreshing = true;
