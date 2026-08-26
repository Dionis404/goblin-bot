"""Точка входа Telegram-бота (aiogram 3, polling)."""
import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeDefault

from bot.channel import router as channel_router
from bot.handlers import router
from bot.subscriber_notify import router as subscriber_notify_router
from shared import config, db, telegram_stats

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("goblin-bot")

TELEGRAM_STATS_INTERVAL_SEC = 900  # раз в 15 минут — данные не горят, на сайте свой кэш на 10 мин
TICKETS_LEADERBOARD_INTERVAL_SEC = 3600  # почасовой снэпшот мест отслеживаемых ферм
TOP500_SNAPSHOT_INTERVAL_SEC = 3600  # почасовой снэпшот всего топ-500 (для сайта/API)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
WEEKLY_NOTIFY_WEEKDAY = 0  # понедельник (datetime.weekday(): 0 = Monday)
WEEKLY_NOTIFY_HOUR = 3


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


async def tickets_leaderboard_loop() -> None:
    """Почасовой сбор точного места отслеживаемых ферм в лидерборде тикетов."""
    from jobs.tickets_leaderboard import run_tickets_leaderboard

    while True:
        try:
            await run_tickets_leaderboard()
        except Exception:
            log.exception("Ошибка почасового снэпшота лидерборда тикетов")
        await asyncio.sleep(TICKETS_LEADERBOARD_INTERVAL_SEC)


async def top500_snapshot_loop() -> None:
    """Почасовой снэпшот всего глобального топ-500 (не зависит от tracked-ферм)."""
    from jobs.top500_snapshot import run_top500_snapshot

    while True:
        try:
            await run_top500_snapshot()
        except Exception:
            log.exception("Ошибка почасового снэпшота топ-500")
        await asyncio.sleep(TOP500_SNAPSHOT_INTERVAL_SEC)


def _seconds_until_next_weekly_notify(now: datetime) -> float:
    """Секунды до ближайших 03:00 МСК понедельника (ночь с ВС на ПН)."""
    target = now.replace(hour=WEEKLY_NOTIFY_HOUR, minute=0, second=0, microsecond=0)
    days_ahead = (WEEKLY_NOTIFY_WEEKDAY - now.weekday()) % 7
    target += timedelta(days=days_ahead)
    if target <= now:
        target += timedelta(days=7)
    return (target - now).total_seconds()


async def tickets_weekly_notify_loop(bot: Bot) -> None:
    """Раз в неделю (ночь с ВС на ПН, 03:00 МСК) шлёт отчёт по местам в группу."""
    from jobs.tickets_weekly_notify import run_tickets_weekly_notify

    while True:
        wait = _seconds_until_next_weekly_notify(datetime.now(MOSCOW_TZ))
        await asyncio.sleep(wait)
        try:
            await run_tickets_weekly_notify(bot)
        except Exception:
            log.exception("Ошибка еженедельного уведомления о лидерборде тикетов")
        # небольшая пауза, чтобы не сработать повторно в ту же минуту при дрифте
        await asyncio.sleep(60)


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
    dp.include_router(subscriber_notify_router)

    # Список команд для меню "☰" в Telegram — иначе игроки не узнают про /menu.
    # Старые команды могли быть заданы с другим scope (например, AllPrivateChats) —
    # такой scope перекрывает Default, поэтому очищаем оба явно перед записью новых.
    commands = [
        BotCommand(command="start", description="Привязать ферму"),
        BotCommand(command="menu", description="Меню: отслеживание лидерборда тикетов"),
    ]
    await bot.delete_my_commands(scope=BotCommandScopeDefault())
    await bot.delete_my_commands(scope=BotCommandScopeAllPrivateChats())
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    await bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())

    # Прогреваем пул соединений
    await db.get_pool()

    stats_task = asyncio.create_task(refresh_telegram_stats_loop(bot))
    tickets_task = asyncio.create_task(tickets_leaderboard_loop())
    top500_task = asyncio.create_task(top500_snapshot_loop())
    weekly_notify_task = asyncio.create_task(tickets_weekly_notify_loop(bot))

    log.info("Бот запущен, начинаю polling…")
    try:
        await dp.start_polling(
            bot, allowed_updates=["message", "callback_query", "channel_post", "chat_member"]
        )
    finally:
        stats_task.cancel()
        tickets_task.cancel()
        top500_task.cancel()
        weekly_notify_task.cancel()
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
