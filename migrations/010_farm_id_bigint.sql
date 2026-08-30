-- Миграция 010: farm_id в SFL давно перевалил за диапазон int32 (реальные ID вида
-- 1429214903236188), а farmers.farm_id и ticket_leaderboard_snapshots.farm_id были
-- объявлены как INTEGER. Из-за этого /tickets_check падал на asyncpg.DataError
-- ("value out of int32 range") при чтении снэпшотов для таких ферм.
-- БД: sfl  |  Запускать под пользователем с правами ALTER TABLE.

ALTER TABLE farmers ALTER COLUMN farm_id TYPE BIGINT;
ALTER TABLE ticket_leaderboard_snapshots ALTER COLUMN farm_id TYPE BIGINT;
