"""
Уведомление в Telegram о новой версии игры Sunflower Land.

Перенос n8n-workflow "Уведомление о новой версии игры": вместо RSS-триггера
на вебхуке — поллинг атом-фида релизов раз в минуту (см. run_game_update_notify_loop
из bot/main.py). Дедупликация от повторной отправки одного и того же релиза
(в т.ч. при рестарте процесса) — через bot_settings, как в tickets_weekly_notify.

Запуск:
  python -m jobs.game_update_notify
  или run_game_update_notify_loop(bot) из планировщика бота.
"""
import asyncio
import logging

from aiogram import Bot

from shared import bot_settings, config, db, game_updates

log = logging.getLogger(__name__)

LAST_SENT_RELEASE_URL_KEY = "game_update_last_sent_url"


async def check_and_notify(bot: Bot) -> dict:
    """Проверяет фид релизов и, если появился новый — шлёт уведомление в чат."""
    if config.GAME_UPDATE_NOTIFY_CHAT_ID is None:
        log.warning("GAME_UPDATE_NOTIFY_CHAT_ID не задан — уведомление о версии игры пропущено")
        return {"sent": False, "reason": "no_chat_id"}

    try:
        release = await game_updates.fetch_latest_release()
    except game_updates.NoReleasesFound:
        return {"sent": False, "reason": "no_releases"}

    last_sent_url = await bot_settings.get_str(LAST_SENT_RELEASE_URL_KEY)
    if release["url"] == last_sent_url:
        return {"sent": False, "reason": "already_sent"}

    text = await game_updates.build_update_message(release)
    await bot.send_message(config.GAME_UPDATE_NOTIFY_CHAT_ID, text)
    await bot_settings.set_str(LAST_SENT_RELEASE_URL_KEY, release["url"])

    log.info("Отправлено уведомление о новой версии игры: %s", release["name"])
    return {"sent": True, "release": release["name"]}


async def run_game_update_notify_loop(bot: Bot) -> None:
    """Периодически проверяет фид релизов и шлёт уведомление о новой версии."""
    while True:
        try:
            await check_and_notify(bot)
        except Exception:
            log.exception("Ошибка проверки обновления версии игры")
        await asyncio.sleep(config.GAME_UPDATE_POLL_INTERVAL_SEC)


async def _main() -> None:
    from aiogram import Bot

    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=config.BOT_TOKEN)
    try:
        await check_and_notify(bot)
    finally:
        await bot.session.close()
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
