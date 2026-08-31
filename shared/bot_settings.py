"""Key-value настройки бота (таблица bot_settings), например тогглы уведомлений."""
from shared import db


async def get_bool(key: str, default: bool) -> bool:
    pool = await db.get_pool()
    value = await pool.fetchval("SELECT value FROM bot_settings WHERE key = $1", key)
    if value is None:
        return default
    return value == "true"


async def set_bool(key: str, value: bool) -> None:
    pool = await db.get_pool()
    await pool.execute(
        """
        INSERT INTO bot_settings (key, value, updated_at)
        VALUES ($1, $2, now())
        ON CONFLICT (key) DO UPDATE SET
            value      = EXCLUDED.value,
            updated_at = EXCLUDED.updated_at
        """,
        key, "true" if value else "false",
    )


async def get_str(key: str) -> str | None:
    pool = await db.get_pool()
    return await pool.fetchval("SELECT value FROM bot_settings WHERE key = $1", key)


async def set_str(key: str, value: str) -> None:
    pool = await db.get_pool()
    await pool.execute(
        """
        INSERT INTO bot_settings (key, value, updated_at)
        VALUES ($1, $2, now())
        ON CONFLICT (key) DO UPDATE SET
            value      = EXCLUDED.value,
            updated_at = EXCLUDED.updated_at
        """,
        key, value,
    )
