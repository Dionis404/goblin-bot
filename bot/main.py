"""Точка входа Telegram-бота (aiogram 3, polling)."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from bot.channel import router as channel_router
from bot.handlers import router
from shared import config, db, telegram_stats

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("goblin-bot")

TELEGRAM_STATS_INTERVAL_SEC = 900  # раз в 15 минут — данные не горят, на сайте свой кэш на 10 мин


async def refresh_telegram_stats_loop(bot: Bot) -> None:
    """Периодически считает подписчиков канала и пишет в telegram_stats."""
    while True:
        try:
            count = await bot.get_chat_member_count(f"@{config.TELEGRAM_POSTS_CHANNEL}")
            await telegram_stats.save_telegram_subscriber_count(
                config.TELEGRAM_POSTS_CHANNEL, count
            )
            log.info("Обновлена статистика канала @%s: %s подписчиков",
                      config.TELEGRAM_POSTS_CHANNEL, count)
        except Exception:
            log.exception("Ошибка обновления статистики канала @%s", config.TELEGRAM_POSTS_CHANNEL)
        await asyncio.sleep(TELEGRAM_STATS_INTERVAL_SEC)


async def main():
    if not config.BOT_TOKEN:
        raise RuntimeError(
            "Переменная BOT_TOKEN не задана. "
            "Локально — в .env, на сервере — в переменных стека Portainer."
        )

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
    dp.include_router(channel_router)

    # Прогреваем пул соединений
    await db.get_pool()

    stats_task = asyncio.create_task(refresh_telegram_stats_loop(bot))

    log.info("Бот запущен, начинаю polling…")
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query", "channel_post"])
    finally:
        stats_task.cancel()
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
