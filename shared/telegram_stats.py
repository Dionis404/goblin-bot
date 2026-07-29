"""Количество подписчиков канала @URGSFL (таблица telegram_stats), читается сайтом."""
from shared import db


async def save_telegram_subscriber_count(channel: str, count: int) -> None:
    pool = await db.get_pool()
    await pool.execute(
        """
        INSERT INTO telegram_stats (channel, subscribers, updated_at)
        VALUES ($1, $2, now())
        ON CONFLICT (channel) DO UPDATE SET
            subscribers = EXCLUDED.subscribers,
            updated_at  = EXCLUDED.updated_at
        """,
        channel, count,
    )
