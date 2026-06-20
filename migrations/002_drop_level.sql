-- Миграция 002: убираем колонку level.
-- Уровень вычисляется на сайте из xp, в БД не хранится.
-- Выполнять под пользователем с правами на ALTER (admin), БД sfl.

ALTER TABLE farmers DROP COLUMN IF EXISTS level;
