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
import html
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from shared import bot_settings, config, db, game_updates
from shared.text import split_message

log = logging.getLogger(__name__)

LAST_SENT_RELEASE_URL_KEY = "game_update_last_sent_url"

# Готовый (уже переведённый) текст последнего релиза: если отправка упала
# сетевой ошибкой и цикл повторит попытку через минуту — не платим за
# AI-перевод того же changelog'а повторно.
_message_cache: dict[str, str] = {}


async def _get_message(release: dict) -> str:
    url = release["url"]
    if url not in _message_cache:
        _message_cache.clear()
        _message_cache[url] = await game_updates.build_update_message(release)
    return _message_cache[url]


async def _send(bot: Bot, text: str) -> None:
    """
    Шлёт уведомление; если Telegram не принял HTML ("can't parse entities"
    и прочие TelegramBadRequest) — повторяет тем же текстом без разметки.
    Если и так не принял — сдаётся: ошибка в содержимом, повтор не поможет,
    а вечный ретрай раз в минуту только засоряет логи.
    """
    for chunk in split_message(text):
        try:
            await bot.send_message(config.GAME_UPDATE_NOTIFY_CHAT_ID, chunk)
            continue
        except TelegramBadRequest:
            log.warning("Telegram не принял HTML-уведомление о версии игры, шлю без разметки",
                        exc_info=True)

        try:
            await bot.send_message(
                config.GAME_UPDATE_NOTIFY_CHAT_ID, html.unescape(chunk), parse_mode=None
            )
        except TelegramBadRequest:
            log.exception("Не удалось отправить уведомление о версии игры даже без разметки — пропускаю")


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

    text = await _get_message(release)
    await _send(bot, text)
    await bot_settings.set_str(LAST_SENT_RELEASE_URL_KEY, release["url"])
    _message_cache.clear()

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
