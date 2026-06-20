-- Миграция 001: таблица фермеров сообщества GoblinCodex
-- БД: sfl  |  Запускать под пользователем goblin
-- Привязка 1-к-1: один Telegram = одна ферма, изменить нельзя (UNIQUE + логика бота)

CREATE TABLE IF NOT EXISTS farmers (
    id                SERIAL PRIMARY KEY,
    telegram_id       BIGINT      UNIQUE NOT NULL,  -- кто привязал (необратимо)
    telegram_username TEXT,                          -- ник в ТГ (@..., может быть NULL)
    farm_id           INTEGER     UNIQUE NOT NULL,   -- номер фермы (одна ферма = один владелец)
    game_username     TEXT,                          -- ник в игре (farm.username, может быть NULL)
    xp                NUMERIC,                        -- farm.bumpkin.experience (level считает сайт)
    balance           NUMERIC,                        -- farm.balance (FLOWER)
    coins             NUMERIC,                        -- farm.coins
    farm_url          TEXT,                           -- ссылка на ферму
    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_farmers_farm_id ON farmers (farm_id);
CREATE INDEX IF NOT EXISTS idx_farmers_telegram_id ON farmers (telegram_id);
