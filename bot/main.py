"""Точка входа Telegram-бота (aiogram 3, polling)."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from bot.handlers import router
from shared import config, db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("goblin-bot")


async def main():
    # Если задан прокси (Telegram заблокирован в РФ) — гоним трафик через него
    session = None
    if config.TELEGRAM_PROXY:
        session = AiohttpSession(proxy=config.TELEGRAM_PROXY)
        log.info("Использую прокси для Telegram: %s", config.TELEGRAM_PROXY)

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )
    dp = Dispatcher()
    dp.include_router(router)

    # Прогреваем пул соединений
    await db.get_pool()
    log.info("Бот запущен, начинаю polling…")
    try:
        await dp.start_polling(bot)
    finally:
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
