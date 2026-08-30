"""Зеркалирование постов канала @URGSFL в таблицу telegram_posts.

Таблица живёт в той же БД sfl, что и остальные таблицы бота — используется
общий пул из shared/db.py, отдельное подключение не нужно.
"""
import re
from datetime import datetime

import asyncpg

from shared import db

# Посты-ссылки на блог/Teletype дублируют RSS-новости блога — не сохраняем их здесь.
TELETYPE_RE = re.compile(r"blog\.goblincodex\.fun|teletype\.in")


def is_teletype_link(text: str, link_preview_href: str = "") -> bool:
    return bool(TELETYPE_RE.search(text) or TELETYPE_RE.search(link_preview_href))


async def save_post(
    post_id: int,
    message_date: datetime,
    text: str,
    image_data: bytes | None = None,
    image_content_type: str | None = None,
) -> None:
    """
    Картинка (если есть) хранится байтами в самой БД, а не ссылкой на файл
    Telegram — такая ссылка "протухает" через некоторое время и содержит
    BOT_TOKEN в открытом виде. image_url собирается как относительный путь
    к goblin-api (GET /api/community/posts/{id}/image), сайт сам знает, как
    достучаться до этого эндпоинта (реверс-прокси внутри shared-net).
    """
    image_url = f"/api/community/posts/{post_id}/image" if image_data else None

    pool = await db.get_pool()
    await pool.execute(
        """
        INSERT INTO telegram_posts (id, message_date, text, image_url, image_data, image_content_type)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (id) DO UPDATE SET
            message_date        = EXCLUDED.message_date,
            text                = EXCLUDED.text,
            image_url           = EXCLUDED.image_url,
            image_data          = EXCLUDED.image_data,
            image_content_type  = EXCLUDED.image_content_type
        """,
        post_id, message_date, text, image_url, image_data, image_content_type,
    )


async def get_post_image(post_id: int) -> asyncpg.Record | None:
    pool = await db.get_pool()
    return await pool.fetchrow(
        "SELECT image_data, image_content_type FROM telegram_posts WHERE id = $1",
        post_id,
    )
