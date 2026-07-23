"""Приём постов канала @URGSFL через long-polling (channel_post) и запись в telegram_posts.

Раньше эту работу делал вебхук на сайте goblincodex — он конфликтовал с polling
этого бота (TelegramConflictError), поэтому перенесён сюда.
"""
import logging

from aiogram import F, Router
from aiogram.types import Message

from shared import config, telegram_posts

router = Router()
log = logging.getLogger(__name__)

router.channel_post.filter(F.chat.username == config.TELEGRAM_POSTS_CHANNEL)


@router.channel_post()
async def handle_channel_post(message: Message):
    text = message.text or message.caption or ""
    text = text.strip()
    if not text:
        # Служебное сообщение без текста (например, смена фото канала) — пропускаем
        return

    link_preview_href = ""
    if message.link_preview_options and message.link_preview_options.url:
        link_preview_href = message.link_preview_options.url

    if telegram_posts.is_teletype_link(text, link_preview_href):
        return

    image_url = None
    photo = message.photo[-1] if message.photo else None
    if photo:
        try:
            file = await message.bot.get_file(photo.file_id)
            image_url = f"https://api.telegram.org/file/bot{config.BOT_TOKEN}/{file.file_path}"
        except Exception:
            log.exception("Не удалось получить файл фото для поста %s", message.message_id)

    try:
        await telegram_posts.save_post(
            post_id=message.message_id,
            message_date=message.date,
            text=text,
            image_url=image_url,
        )
        log.info("Сохранён пост канала #%s (%s)", message.message_id, message.date)
    except Exception:
        log.exception("Ошибка сохранения поста канала #%s", message.message_id)
