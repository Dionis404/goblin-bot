"""Тесты для bot/handlers.py: разбор номера фермы и админский /unlink."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot import handlers

ADMIN_ID = 1000


@pytest.mark.parametrize("raw, expected", [
    ("62559", 62559),
    ("  42 ", 42),
    ("0", None),
    (str(2**63), None),
    ("12a", None),
])
def test_parse_farm_id(raw, expected):
    assert handlers._parse_farm_id(raw) == expected


def _farmer(**overrides):
    row = {
        "farm_id": 77, "telegram_id": 555, "telegram_username": "squatter",
        "game_username": "<b>Evil</b>", "tickets_tracked": False,
        "created_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def _callback(data: str, user_id: int):
    callback = MagicMock()
    callback.data = data
    callback.from_user.id = user_id
    callback.answer = AsyncMock()
    callback.message.edit_text = AsyncMock()
    callback.bot.send_message = AsyncMock()
    return callback


def test_farmer_card_escapes_game_username():
    card = handlers._farmer_card(_farmer())
    assert "<b>Evil</b>" not in card
    assert "&lt;b&gt;Evil&lt;/b&gt;" in card


@pytest.mark.asyncio
async def test_unlink_callback_ignored_for_non_admin(monkeypatch):
    monkeypatch.setattr(handlers.config, "ADMIN_TELEGRAM_IDS", {ADMIN_ID})
    delete = AsyncMock()
    with patch("bot.handlers.db.delete_farmer_by_farm", delete):
        await handlers.confirm_unlink(_callback("unlink:77:silent", user_id=1))

    delete.assert_not_called()


@pytest.mark.asyncio
async def test_unlink_callback_deletes_and_notifies(monkeypatch):
    monkeypatch.setattr(handlers.config, "ADMIN_TELEGRAM_IDS", {ADMIN_ID})
    callback = _callback("unlink:77:notify", user_id=ADMIN_ID)
    delete = AsyncMock(return_value=_farmer())

    with patch("bot.handlers.db.delete_farmer_by_farm", delete):
        await handlers.confirm_unlink(callback)

    delete.assert_awaited_once_with(77)
    assert callback.bot.send_message.await_args.args[0] == 555  # бывший владелец привязки
    assert "снята" in callback.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_unlink_callback_silent_does_not_notify(monkeypatch):
    monkeypatch.setattr(handlers.config, "ADMIN_TELEGRAM_IDS", {ADMIN_ID})
    callback = _callback("unlink:77:silent", user_id=ADMIN_ID)

    with patch("bot.handlers.db.delete_farmer_by_farm", AsyncMock(return_value=_farmer())):
        await handlers.confirm_unlink(callback)

    callback.bot.send_message.assert_not_called()


@pytest.fixture
def fresh_dispute_cooldown(monkeypatch):
    from bot import throttle
    from shared.throttle import UserCooldown

    monkeypatch.setattr(throttle, "dispute_cooldown", UserCooldown(seconds=600))


@pytest.mark.asyncio
async def test_dispute_sends_admin_card_with_unlink_buttons(monkeypatch, fresh_dispute_cooldown):
    monkeypatch.setattr(handlers.config, "NOTIFY_ADMIN_TELEGRAM_ID", ADMIN_ID)
    callback = _callback("dispute:77", user_id=42)
    callback.from_user.username = "real_owner"

    with patch("bot.handlers.db.get_farmer_by_farm", AsyncMock(return_value=_farmer())):
        await handlers.dispute_farm(callback)

    args, kwargs = callback.bot.send_message.await_args
    assert args[0] == ADMIN_ID
    assert "@real_owner" in args[1] and "@squatter" in args[1]
    buttons = [b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert "unlink:77:notify" in buttons
    assert "отправлена" in callback.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_dispute_is_rate_limited(monkeypatch, fresh_dispute_cooldown):
    monkeypatch.setattr(handlers.config, "NOTIFY_ADMIN_TELEGRAM_ID", ADMIN_ID)
    callback = _callback("dispute:77", user_id=42)
    callback.from_user.username = None
    callback.from_user.full_name = "Owner"

    with patch("bot.handlers.db.get_farmer_by_farm", AsyncMock(return_value=_farmer())):
        await handlers.dispute_farm(callback)
        await handlers.dispute_farm(callback)

    assert callback.bot.send_message.await_count == 1


@pytest.mark.asyncio
async def test_dispute_on_already_freed_farm_does_not_bother_admin(monkeypatch, fresh_dispute_cooldown):
    monkeypatch.setattr(handlers.config, "NOTIFY_ADMIN_TELEGRAM_ID", ADMIN_ID)
    callback = _callback("dispute:77", user_id=42)

    with patch("bot.handlers.db.get_farmer_by_farm", AsyncMock(return_value=None)):
        await handlers.dispute_farm(callback)

    callback.bot.send_message.assert_not_called()
    assert "свободна" in callback.message.edit_text.await_args.args[0]
