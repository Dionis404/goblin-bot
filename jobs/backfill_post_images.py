"""
Одноразовый бэкфилл картинок старых постов telegram_posts.

До миграции 009 картинка поста хранилась не байтами, а прямой ссылкой на
файл Telegram (image_url = https://api.telegram.org/file/bot<TOKEN>/...).
Такая ссылка "протухает" (file_path у Telegram не постоянный), а сам file_id
для этих старых записей никогда не сохранялся — поэтому автоматически
перекачать картинку по данным одной только БД нельзя.

Единственный способ достать файл заново — попросить у Telegram копию
исходного сообщения канала по его message_id (id поста в telegram_posts
совпадает с message_id, см. bot/channel.py): copy_message возвращает новое
сообщение с рабочим file_id на ту же картинку, даже если старый file_path
из этого file_id уже невалиден. Копия шлётся в личку админу
(NOTIFY_ADMIN_TELEGRAM_ID) — админ может удалить эти служебные сообщения
после прогона.

Требования:
- Бот должен быть жив и состоять в канале TELEGRAM_POSTS_CHANNEL.
- Исходное сообщение поста не должно быть удалено из канала — тогда для
  него copy_message вернёт ошибку и запись останется без картинки.
- Задан ADMIN_TELEGRAM_IDS (используем первого администратора).

Запуск: python -m jobs.backfill_post_images
"""
import asyncio
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.client.session.aiohttp import AiohttpSession

from shared import config, db

log = logging.getLogger(__name__)

DELAY_BETWEEN_POSTS_SEC = 1.0


async def run_backfill() -> dict:
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан")
    if config.NOTIFY_ADMIN_TELEGRAM_ID is None:
        raise RuntimeError("ADMIN_TELEGRAM_IDS пуст — некуда слать служебные копии")

    pool = await db.get_pool()
    rows = await pool.fetch(
        """
        SELECT id FROM telegram_posts
        WHERE image_url IS NOT NULL AND image_data IS NULL
        ORDER BY id
        """
    )
    post_ids = [r["id"] for r in rows]
    log.info("К бэкфиллу: %s постов", len(post_ids))

    session = AiohttpSession(proxy=config.TELEGRAM_PROXY) if config.TELEGRAM_PROXY else None
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )

    restored = 0
    failed = 0

    try:
        for post_id in post_ids:
            try:
                copied = await bot.copy_message(
                    chat_id=config.NOTIFY_ADMIN_TELEGRAM_ID,
                    from_chat_id=f"@{config.TELEGRAM_POSTS_CHANNEL}",
                    message_id=post_id,
                )
                photo = copied.photo[-1] if copied.photo else None
                if not photo:
                    log.warning("Пост %s: копия без фото, пропускаю", post_id)
                    failed += 1
                    continue

                buffer = await bot.download(photo.file_id)
                image_data = buffer.read()

                # Обновляем только картинку — текст/дату поста не трогаем,
                # они уже корректно сохранены исходным bot/channel.py.
                await pool.execute(
                    """
                    UPDATE telegram_posts
                    SET image_url = $2, image_data = $3, image_content_type = $4
                    WHERE id = $1
                    """,
                    post_id, f"/api/community/posts/{post_id}/image", image_data, "image/jpeg",
                )
                restored += 1
                log.info("Пост %s: картинка восстановлена", post_id)
            except Exception:
                log.exception("Пост %s: не удалось восстановить картинку", post_id)
                failed += 1

            await asyncio.sleep(DELAY_BETWEEN_POSTS_SEC)
    finally:
        await bot.session.close()

    log.info("Бэкфилл завершён: восстановлено %s, не удалось %s", restored, failed)
    return {"restored": restored, "failed": failed, "total": len(post_ids)}


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        await run_backfill()
    finally:
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
