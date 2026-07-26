-- Миграция 005: лидерборд LP-провайдеров пула Uniswap v3 (Base).
-- БД: sfl  |  Запускать под пользователем с правами CREATE TABLE.

CREATE TABLE IF NOT EXISTS lp_current (
    owner       TEXT PRIMARY KEY,
    rank        INT,
    prev_rank   INT,          -- ранг с прошлого обновления, для алертов
    value_usd   NUMERIC,
    positions   INT,
    farm_id     INT,          -- потом
    updated_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_lp_current_rank ON lp_current (rank);

CREATE TABLE IF NOT EXISTS lp_meta (   -- одна строка
    updated_at        TIMESTAMPTZ,
    block             BIGINT,
    flower_price_usd  NUMERIC,
    total_tvl         NUMERIC,
    wallets           INT
);
