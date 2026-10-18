"""Хранилище заявок на вступление в чат (таблица chat_join_requests)."""
from datetime import datetime

import asyncpg


async def upsert_pending(
    pool: asyncpg.Pool,
    chat_id: int,
    user_id: int,
    user_chat_id: int,
    username: str | None,
    full_name: str | None,
    correct_emoji: str,
) -> None:
    """Новая заявка (или повторная после отказа/таймаута) — начинается с чистого листа."""
    await pool.execute(
        """
        INSERT INTO chat_join_requests
            (chat_id, user_id, user_chat_id, username, full_name, status, correct_emoji,
             attempts, captcha_passed, message_id, requested_at, reminded_at,
             reminder_delivered, decided_at)
        VALUES ($1, $2, $3, $4, $5, 'pending', $6, 0, false, NULL, now(), NULL, NULL, NULL)
        ON CONFLICT (chat_id, user_id) DO UPDATE SET
            user_chat_id = EXCLUDED.user_chat_id,
            username = EXCLUDED.username,
            full_name = EXCLUDED.full_name,
            status = 'pending',
            correct_emoji = EXCLUDED.correct_emoji,
            attempts = 0,
            captcha_passed = false,
            message_id = NULL,
            requested_at = now(),
            reminded_at = NULL,
            reminder_delivered = NULL,
            decided_at = NULL
        """,
        chat_id, user_id, user_chat_id, username, full_name, correct_emoji,
    )


async def get(pool: asyncpg.Pool, chat_id: int, user_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow(
        "SELECT * FROM chat_join_requests WHERE chat_id = $1 AND user_id = $2",
        chat_id, user_id,
    )


async def set_message_id(pool: asyncpg.Pool, chat_id: int, user_id: int, message_id: int) -> None:
    await pool.execute(
        "UPDATE chat_join_requests SET message_id = $3 WHERE chat_id = $1 AND user_id = $2",
        chat_id, user_id, message_id,
    )


async def mark_captcha_passed(pool: asyncpg.Pool, chat_id: int, user_id: int) -> None:
    """Правила приняты — дальше заявка ждёт только подписку на канал."""
    await pool.execute(
        "UPDATE chat_join_requests SET captcha_passed = true WHERE chat_id = $1 AND user_id = $2",
        chat_id, user_id,
    )


async def register_wrong_answer(
    pool: asyncpg.Pool, chat_id: int, user_id: int, new_correct_emoji: str
) -> int:
    """Неверный ответ: +1 попытка и новая капча. Возвращает число попыток."""
    return await pool.fetchval(
        """
        UPDATE chat_join_requests
        SET attempts = attempts + 1, correct_emoji = $3
        WHERE chat_id = $1 AND user_id = $2
        RETURNING attempts
        """,
        chat_id, user_id, new_correct_emoji,
    )


async def finish(pool: asyncpg.Pool, chat_id: int, user_id: int, status: str) -> bool:
    """
    Закрывает заявку, если она ещё pending. Возвращает False, если её уже
    закрыли параллельно (двойной клик, таймаут в тот же момент) — тогда
    вызывающий не должен повторно одобрять/отклонять.
    """
    result = await pool.execute(
        """
        UPDATE chat_join_requests SET status = $3, decided_at = now()
        WHERE chat_id = $1 AND user_id = $2 AND status = 'pending'
        """,
        chat_id, user_id, status,
    )
    return result.split()[-1] != "0"


async def mark_status(pool: asyncpg.Pool, chat_id: int, user_id: int, status: str) -> None:
    """Безусловно меняет статус (например, approved -> processed, если Telegram не принял approve)."""
    await pool.execute(
        "UPDATE chat_join_requests SET status = $3 WHERE chat_id = $1 AND user_id = $2",
        chat_id, user_id, status,
    )


async def list_due_reminders(pool: asyncpg.Pool, older_than: datetime) -> list[asyncpg.Record]:
    return await pool.fetch(
        """
        SELECT * FROM chat_join_requests
        WHERE status = 'pending' AND reminded_at IS NULL AND requested_at <= $1
        """,
        older_than,
    )


async def mark_reminded(pool: asyncpg.Pool, chat_id: int, user_id: int, delivered: bool) -> None:
    await pool.execute(
        """
        UPDATE chat_join_requests SET reminded_at = now(), reminder_delivered = $3
        WHERE chat_id = $1 AND user_id = $2
        """,
        chat_id, user_id, delivered,
    )


async def list_expired(pool: asyncpg.Pool, older_than: datetime) -> list[asyncpg.Record]:
    return await pool.fetch(
        "SELECT * FROM chat_join_requests WHERE status = 'pending' AND requested_at <= $1",
        older_than,
    )
