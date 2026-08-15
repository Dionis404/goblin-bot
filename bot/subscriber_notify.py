"""Уведомления админу в личку о подписке/отписке от канала @URGSFL.

Требует, чтобы бот был администратором канала — иначе Telegram не присылает
my_chat_member/chat_member апдейты по отдельным участникам.
Включается/выключается командой /subscriber_notify (см. bot/handlers.py).
"""
import logging

from aiogram import F, Router
from aiogram.types import ChatMemberUpdated

from shared import bot_settings, config

router = Router()
log = logging.getLogger(__name__)

router.chat_member.filter(F.chat.username == config.TELEGRAM_POSTS_CHANNEL)

SETTING_KEY = "subscriber_notify_enabled"

# Статусы, при переходе в которые считаем "подписался" / "отписался"
SUBSCRIBED_STATUSES = {"member"}
UNSUBSCRIBED_STATUSES = {"left", "kicked"}


def _display_name(update: ChatMemberUpdated) -> str:
    user = update.new_chat_member.user
    if user.username:
        return f"@{user.username}"
    return user.full_name


@router.chat_member()
async def handle_chat_member_update(update: ChatMemberUpdated):
    if config.NOTIFY_ADMIN_TELEGRAM_ID is None:
        return

    if not await bot_settings.get_bool(SETTING_KEY, default=True):
        return

    old_status = update.old_chat_member.status
    new_status = update.new_chat_member.status

    if old_status not in SUBSCRIBED_STATUSES and new_status in SUBSCRIBED_STATUSES:
        text = f"➕ Новый подписчик канала @{config.TELEGRAM_POSTS_CHANNEL}: {_display_name(update)}"
    elif old_status in SUBSCRIBED_STATUSES and new_status in UNSUBSCRIBED_STATUSES:
        text = f"➖ Отписался от канала @{config.TELEGRAM_POSTS_CHANNEL}: {_display_name(update)}"
    else:
        return

    try:
        await update.bot.send_message(config.NOTIFY_ADMIN_TELEGRAM_ID, text)
    except Exception:
        log.exception("Не удалось отправить уведомление о подписчике админу")
