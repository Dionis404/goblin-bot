-- Миграция 013: заявки на вступление в чат сообщества (bot/join_verify.py).
-- Бот шлёт заявителю правила + эмодзи-капчу и проверяет подписку на канал,
-- одобряет после правильного ответа и подписки. Таблица нужна, чтобы таймауты (24 ч) и напоминания переживали
-- рестарты бота. Одна строка на (чат, человек): повторная заявка её обновляет.

CREATE TABLE IF NOT EXISTS chat_join_requests (
    chat_id             BIGINT      NOT NULL,
    user_id             BIGINT      NOT NULL,
    user_chat_id        BIGINT      NOT NULL,
    username            TEXT,
    full_name           TEXT,
    -- pending | approved | declined | expired | unreachable | processed
    status              TEXT        NOT NULL DEFAULT 'pending',
    correct_emoji       TEXT        NOT NULL,
    attempts            INT         NOT NULL DEFAULT 0,
    -- капча (согласие с правилами) пройдена, ждём подписку на канал
    captcha_passed      BOOLEAN     NOT NULL DEFAULT false,
    message_id          BIGINT,
    requested_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    reminded_at         TIMESTAMPTZ,
    reminder_delivered  BOOLEAN,
    decided_at          TIMESTAMPTZ,
    PRIMARY KEY (chat_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_chat_join_requests_pending
    ON chat_join_requests (requested_at) WHERE status = 'pending';
