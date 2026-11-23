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


@pytest.mark.asyncio
async def test_tickets_check_shows_collector_summary_only(monkeypatch):
    """Сбор лидерборда делает sfl-collector — /tickets_check показывает только сводку."""
    monkeypatch.setattr(handlers.config, "ADMIN_TELEGRAM_IDS", {ADMIN_ID})

    message = MagicMock()
    message.from_user.id = ADMIN_ID
    status_msg = MagicMock()
    status_msg.edit_text = AsyncMock()
    message.answer = AsyncMock(return_value=status_msg)

    with patch("bot.handlers.db.get_pool", AsyncMock()), \
         patch("bot.handlers.tickets_leaderboard.get_tracked_farmers", AsyncMock(return_value=[])):
        await handlers.tickets_check(message)

    assert "sfl-collector" in status_msg.edit_text.await_args.args[0]


# --- Отслеживание тикетов: тоггл, команды, уведомление админа ---

def _message(user_id: int, username: str | None = "player"):
    message = MagicMock()
    message.from_user.id = user_id
    message.from_user.username = username
    message.from_user.full_name = "Player One"
    message.answer = AsyncMock()
    message.bot.send_message = AsyncMock()
    return message


@pytest.mark.asyncio
async def test_tracking_toggle_notifies_admin(monkeypatch):
    """Кнопка вкл/выкл отслеживания шлёт уведомление админу."""
    monkeypatch.setattr(handlers.config, "NOTIFY_ADMIN_TELEGRAM_ID", ADMIN_ID)
    callback = _callback("tickets_tracking:on", user_id=42)
    callback.from_user.username = "newbie"
    callback.from_user.full_name = "New Bee"
    set_tracking = AsyncMock()

    with patch("bot.handlers.db.get_farmer_by_telegram", AsyncMock(return_value=_farmer())), \
         patch("bot.handlers.db.get_pool", AsyncMock()), \
         patch("bot.handlers.tickets_leaderboard.set_tracking", set_tracking):
        await handlers.toggle_tickets_tracking(callback)

    set_tracking.assert_awaited_once()
    notify = callback.bot.send_message.await_args
    assert notify.args[0] == ADMIN_ID
    assert "включил" in notify.args[1]
    assert "#77" in notify.args[1]
    assert "включено" in callback.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_tracking_off_notifies_admin(monkeypatch):
    monkeypatch.setattr(handlers.config, "NOTIFY_ADMIN_TELEGRAM_ID", ADMIN_ID)
    callback = _callback("tickets_tracking:off", user_id=42)
    callback.from_user.username = "newbie"
    callback.from_user.full_name = "New Bee"

    with patch("bot.handlers.db.get_farmer_by_telegram", AsyncMock(return_value=_farmer())), \
         patch("bot.handlers.db.get_pool", AsyncMock()), \
         patch("bot.handlers.tickets_leaderboard.set_tracking", AsyncMock()):
        await handlers.toggle_tickets_tracking(callback)

    assert "выключил" in callback.bot.send_message.await_args.args[1]
    assert "выключено" in callback.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_tracking_on_without_farmer_asks_to_bind(monkeypatch):
    monkeypatch.setattr(handlers.config, "NOTIFY_ADMIN_TELEGRAM_ID", ADMIN_ID)
    message = _message(user_id=42)

    with patch("bot.handlers.db.get_farmer_by_telegram", AsyncMock(return_value=None)):
        await handlers.cmd_tracking_on(message)

    assert "привязать" in message.answer.await_args.args[0]
    message.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_tracking_on_enables_and_notifies(monkeypatch):
    monkeypatch.setattr(handlers.config, "NOTIFY_ADMIN_TELEGRAM_ID", ADMIN_ID)
    message = _message(user_id=42)
    set_tracking = AsyncMock()

    with patch("bot.handlers.db.get_farmer_by_telegram", AsyncMock(return_value=_farmer())), \
         patch("bot.handlers.db.get_pool", AsyncMock()), \
         patch("bot.handlers.tickets_leaderboard.set_tracking", set_tracking):
        await handlers.cmd_tracking_on(message)

    assert set_tracking.await_args.args[2] is True
    assert "включено" in message.answer.await_args.args[0]
    assert message.bot.send_message.await_args.args[0] == ADMIN_ID


@pytest.mark.asyncio
async def test_tracked_top_ignored_for_non_admin():
    message = _message(user_id=1)
    await handlers.cmd_tracked_top(message)
    message.answer.assert_not_called()


@pytest.mark.asyncio
async def test_tracked_top_lists_in_and_out_of_top500(monkeypatch):
    monkeypatch.setattr(handlers.config, "ADMIN_TELEGRAM_IDS", {ADMIN_ID})
    message = _message(user_id=ADMIN_ID)
    taken = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    rows = [
        {"farm_id": 77, "telegram_username": "squatter", "tickets_excluded": False,
         "top500_rank": 5, "top500_tickets": 120, "top500_taken_at": taken},
        {"farm_id": 88, "telegram_username": None, "tickets_excluded": True,
         "top500_rank": None, "top500_tickets": None, "top500_taken_at": taken},
    ]

    with patch("bot.handlers.db.get_pool", AsyncMock()), \
         patch("bot.handlers.tickets_leaderboard.get_tracked_with_top500",
               AsyncMock(return_value=rows)):
        await handlers.cmd_tracked_top(message)

    text = message.answer.await_args.args[0]
    assert "#5" in text and "120" in text
    assert "вне топ-500" in text
    assert "1</b> из 2" in text


# --- Админский /track ---

@pytest.mark.asyncio
async def test_track_ignored_for_non_admin():
    message = _message(user_id=1)
    message.text = "/track 77 on"
    await handlers.cmd_track(message)
    message.answer.assert_not_called()


@pytest.mark.asyncio
async def test_track_shows_status_without_on_off(monkeypatch):
    monkeypatch.setattr(handlers.config, "ADMIN_TELEGRAM_IDS", {ADMIN_ID})
    message = _message(user_id=ADMIN_ID)
    message.text = "/track 77"

    with patch("bot.handlers.db.get_farmer_by_farm", AsyncMock(return_value=_farmer())), \
         patch("bot.handlers.db.get_farmer_by_telegram", AsyncMock(return_value=None)):
        await handlers.cmd_track(message)

    assert "Отслеживание тикетов: выкл" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_track_on_sets_flag_and_notifies_player(monkeypatch):
    monkeypatch.setattr(handlers.config, "ADMIN_TELEGRAM_IDS", {ADMIN_ID})
    message = _message(user_id=ADMIN_ID)
    message.text = "/track @squatter on"
    set_tracking = AsyncMock()

    with patch("bot.handlers.db.get_farmer_by_telegram_username",
               AsyncMock(return_value=_farmer())), \
         patch("bot.handlers.db.get_pool", AsyncMock()), \
         patch("bot.handlers.tickets_leaderboard.set_tracking", set_tracking):
        await handlers.cmd_track(message)

    set_tracking.assert_awaited_once()
    assert set_tracking.await_args.args[1:] == (555, True)
    assert "включено" in message.answer.await_args.args[0]
    # игрок получил уведомление
    player_msg = message.bot.send_message.await_args
    assert player_msg.args[0] == 555
    assert "Админ изменил настройку" in player_msg.args[1]


@pytest.mark.asyncio
async def test_track_rejects_bad_flag(monkeypatch):
    monkeypatch.setattr(handlers.config, "ADMIN_TELEGRAM_IDS", {ADMIN_ID})
    message = _message(user_id=ADMIN_ID)
    message.text = "/track 77 maybe"
    await handlers.cmd_track(message)
    assert "on или off" in message.answer.await_args.args[0]
