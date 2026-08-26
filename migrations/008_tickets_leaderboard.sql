-- Миграция 008: отслеживание места фермера в лидерборде тикетов SFL.
-- БД: sfl  |  Запускать под пользователем с правами CREATE TABLE / ALTER TABLE.

ALTER TABLE farmers ADD COLUMN IF NOT EXISTS tickets_tracked BOOLEAN NOT NULL DEFAULT false;

-- Полная история почасовых снэпшотов места в лидерборде тикетов.
-- Пишется только если farm_id попал в ответ API (см. shared/tickets_leaderboard.py)
-- и rank <= 1200 — иначе строка не создаётся вовсе.
CREATE TABLE IF NOT EXISTS ticket_leaderboard_snapshots (
    id           SERIAL PRIMARY KEY,
    farm_id      INTEGER     NOT NULL,
    rank         INTEGER     NOT NULL,
    tickets      INTEGER     NOT NULL,
    game_username TEXT,
    taken_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ticket_snapshots_farm_taken
    ON ticket_leaderboard_snapshots (farm_id, taken_at DESC);

-- Полная история почасовых снэпшотов глобального топ-500 лидерборда тикетов.
-- Не зависит от tracked-фермеров — нужна для сайта/API (полная выдача борда).
CREATE TABLE IF NOT EXISTS top500_snapshots (
    id            SERIAL PRIMARY KEY,
    rank          INTEGER     NOT NULL,
    farm_id       BIGINT      NOT NULL,
    game_username TEXT,
    tickets       INTEGER     NOT NULL,
    taken_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_top500_snapshots_taken_at ON top500_snapshots (taken_at DESC);
CREATE INDEX IF NOT EXISTS idx_top500_snapshots_taken_rank ON top500_snapshots (taken_at, rank);
