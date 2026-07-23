"""Зеркалирование постов канала @URGSFL в БД сайта goblincodex (таблица telegram_posts).

Отдельный пул соединений: таблица живёт в БД goblincodex (хост postgres),
а не в sfl (хост postgres-main), которую использует остальной бот.
"""
import re
from datetime import datetime

import asyncpg

from shared import config

_pool: asyncpg.Pool | None = None

# Посты-ссылки на блог/Teletype дублируют RSS-новости блога — не сохраняем их здесь.
TELETYPE_RE = re.compile(r"blog\.goblincodex\.fun|teletype\.in")


async def get_pool() -> asyncpg.Pool:
    """Ленивая инициализация пула соединений к БД goblincodex."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            host=config.GOBLINCODEX_DB_HOST,
            port=config.GOBLINCODEX_DB_PORT,
            database=config.GOBLINCODEX_DB_NAME,
            user=config.GOBLINCODEX_DB_USER,
            password=config.GOBLINCODEX_DB_PASSWORD,
            min_size=1,
            max_size=5,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def is_teletype_link(text: str, link_preview_href: str = "") -> bool:
    return bool(TELETYPE_RE.search(text) or TELETYPE_RE.search(link_preview_href))


async def save_post(
    post_id: int,
    message_date: datetime,
    text: str,
    image_url: str | None,
) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO telegram_posts (id, message_date, text, image_url)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (id) DO UPDATE SET
            message_date = EXCLUDED.message_date,
            text         = EXCLUDED.text,
            image_url    = EXCLUDED.image_url
        """,
        post_id, message_date, text, image_url,
    )
