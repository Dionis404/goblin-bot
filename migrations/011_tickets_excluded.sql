-- Миграция 011: постоянное исключение "мёртвых" ферм из почасового опроса
-- лидерборда тикетов — если последний известный ранг фермы был ниже
-- TICKETS_EXCLUDE_RANK (см. shared/tickets_leaderboard.py), запрашивать её
-- каждый час не имеет смысла и только жжёт rate limit API.
-- БД: sfl  |  Запускать под пользователем с правами ALTER TABLE.

ALTER TABLE farmers ADD COLUMN IF NOT EXISTS tickets_excluded BOOLEAN NOT NULL DEFAULT false;
