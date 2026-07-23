"""Зеркалирование постов канала @URGSFL в таблицу telegram_posts.

Таблица живёт в той же БД sfl, что и остальные таблицы бота — используется
общий пул из shared/db.py, отдельное подключение не нужно.
"""
import re
from datetime import datetime

from shared import db

# Посты-ссылки на блог/Teletype дублируют RSS-новости блога — не сохраняем их здесь.
TELETYPE_RE = re.compile(r"blog\.goblincodex\.fun|teletype\.in")


def is_teletype_link(text: str, link_preview_href: str = "") -> bool:
    return bool(TELETYPE_RE.search(text) or TELETYPE_RE.search(link_preview_href))


async def save_post(
    post_id: int,
    message_date: datetime,
    text: str,
    image_url: str | None,
) -> None:
    pool = await db.get_pool()
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
