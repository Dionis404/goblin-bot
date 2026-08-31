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
from shared import bot_settings, config, db, telegram_stats

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("goblin-bot")

TELEGRAM_STATS_INTERVAL_SEC = 900  # раз в 15 минут — данные не горят, на сайте свой кэш на 10 мин
TICKETS_LEADERBOARD_INTERVAL_SEC = 3600  # почасовой снэпшот мест отслеживаемых ферм
TOP500_SNAPSHOT_INTERVAL_SEC = 3600  # почасовой снэпшот всего топ-500 (для сайта/API)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
WEEKLY_NOTIFY_WEEKDAY = 0  # понедельник (datetime.weekday(): 0 = Monday)
WEEKLY_NOTIFY_HOUR = 3
WEEKLY_NOTIFY_CHECK_INTERVAL_SEC = 300  # как часто перепроверять, не пропущено ли окно
WEEKLY_NOTIFY_LAST_SENT_KEY = "tickets_weekly_notify_last_sent"


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


def _current_notify_window(now: datetime) -> str | None:
    """
    ID окна отправки (дата понедельника-триггера, YYYY-MM-DD), если сейчас
    >= 03:00 МСК текущей недели с ВС на ПН, иначе None (окно ещё не наступило).
    """
    days_since_monday = now.weekday() - WEEKLY_NOTIFY_WEEKDAY
    monday = (now - timedelta(days=days_since_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    trigger = monday.replace(hour=WEEKLY_NOTIFY_HOUR)
    if now < trigger:
        return None
    return monday.date().isoformat()


async def tickets_weekly_notify_loop(bot: Bot) -> None:
    """
    Раз в неделю (ночь с ВС на ПН, 03:00 МСК) шлёт отчёт по местам в группу.

    Устойчиво к рестартам процесса: вместо одного долгого sleep до целевого
    момента (который пропускает окно, если рестарт пришёлся рядом с 03:00),
    периодически проверяет, наступило ли уже окно этой недели и не отправлен
    ли отчёт за него — прогресс хранится в bot_settings, а не в памяти.
    """
    from jobs.tickets_weekly_notify import run_tickets_weekly_notify

    while True:
        window = _current_notify_window(datetime.now(MOSCOW_TZ))
        if window is not None:
            last_sent = await bot_settings.get_str(WEEKLY_NOTIFY_LAST_SENT_KEY)
            if last_sent != window:
                try:
                    await run_tickets_weekly_notify(bot)
                    await bot_settings.set_str(WEEKLY_NOTIFY_LAST_SENT_KEY, window)
                except Exception:
                    log.exception("Ошибка еженедельного уведомления о лидерборде тикетов")
        await asyncio.sleep(WEEKLY_NOTIFY_CHECK_INTERVAL_SEC)


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

    # Список команд для меню "☰" в Telegram — иначе игроки не узнают про /tracking_lb.
    # Старые команды могли быть заданы с другим scope (например, AllPrivateChats) —
    # такой scope перекрывает Default, поэтому очищаем оба явно перед записью новых.
    commands = [
        BotCommand(command="start", description="Привязать ферму"),
        BotCommand(command="tracking_lb", description="Отслеживание лидерборда тикетов"),
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
