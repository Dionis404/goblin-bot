"""Тесты для bot/join_verify.py: капча, одобрение, отказы и таймауты заявок в чат."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot import join_verify

CHAT_ID = -100123
USER_ID = 42
ADMIN_ID = 1000


def _row(**overrides):
    row = {
        "chat_id": CHAT_ID, "user_id": USER_ID, "user_chat_id": USER_ID,
        "username": "newbie", "full_name": "New Bie", "status": "pending",
        "correct_emoji": "🌽", "attempts": 0, "captcha_passed": False, "message_id": 7,
        "requested_at": datetime.now(timezone.utc), "reminded_at": None,
        "reminder_delivered": None,
    }
    row.update(overrides)
    return row


def _callback(emoji: str):
    callback = MagicMock()
    callback.data = f"join:{CHAT_ID}:{emoji}"
    callback.from_user.id = USER_ID
    callback.answer = AsyncMock()
    callback.message.edit_text = AsyncMock()
    return callback


@pytest.fixture
def jr():
    """Подменённый слой БД shared.join_requests."""
    mocks = dict(
        upsert_pending=AsyncMock(), get=AsyncMock(), set_message_id=AsyncMock(),
        register_wrong_answer=AsyncMock(), finish=AsyncMock(return_value=True),
        mark_captcha_passed=AsyncMock(),
        mark_status=AsyncMock(), list_due_reminders=AsyncMock(return_value=[]),
        mark_reminded=AsyncMock(), list_expired=AsyncMock(return_value=[]),
    )
    with patch("bot.join_verify.db.get_pool", AsyncMock()), \
         patch.multiple("bot.join_verify.join_requests", **mocks):
        yield mocks


@pytest.fixture(autouse=True)
def _admin(monkeypatch):
    monkeypatch.setattr(join_verify.config, "NOTIFY_ADMIN_TELEGRAM_ID", ADMIN_ID)
    monkeypatch.setattr(join_verify.config, "CHAT_RULES_URL", "https://goblincodex.fun/rules")
    monkeypatch.setattr(join_verify.config, "REQUIRED_CHANNEL", "URGSFL")
    monkeypatch.setattr(join_verify, "_last_sub_error_notice", 0.0)


def _bot(subscribed: bool = True):
    bot = AsyncMock()
    bot.get_chat_member.return_value = MagicMock(status="member" if subscribed else "left")
    return bot


def test_challenge_has_correct_emoji_among_distinct_options():
    correct, options = join_verify._new_challenge()
    assert correct in options
    assert len(set(options)) == join_verify.CHOICES


@pytest.mark.asyncio
async def test_join_request_sends_rules_and_captcha(jr):
    request = MagicMock()
    request.chat.id, request.chat.title = CHAT_ID, "URG <SFL>"
    request.from_user.id, request.from_user.username = USER_ID, "newbie"
    request.user_chat_id = USER_ID
    bot = AsyncMock()
    bot.send_message.return_value = MagicMock(message_id=7)

    await join_verify.handle_join_request(request, bot)

    to_user, to_admin = bot.send_message.await_args_list
    text = to_user.args[1]
    assert to_user.args[0] == USER_ID
    assert "https://goblincodex.fun/rules" in text
    assert "URG &lt;SFL&gt;" in text
    correct = jr["upsert_pending"].await_args.args[-1]
    buttons = to_user.kwargs["reply_markup"].inline_keyboard[0]
    assert f"join:{CHAT_ID}:{correct}" in [b.callback_data for b in buttons]
    jr["set_message_id"].assert_awaited_once()
    # админ узнаёт о каждой новой заявке
    assert to_admin.args[0] == ADMIN_ID
    assert "Новая заявка" in to_admin.args[1] and "@newbie" in to_admin.args[1]


@pytest.mark.asyncio
async def test_join_request_to_unverified_chat_notifies_admin(jr, monkeypatch):
    monkeypatch.setattr(join_verify.config, "JOIN_VERIFY_CHAT_ID", None)
    request = MagicMock()
    request.chat.id, request.chat.title = -100999, "Другой чат"
    request.from_user.id, request.from_user.username = USER_ID, "newbie"
    bot = AsyncMock()

    await join_verify.handle_unverified_join_request(request, bot)

    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.args[0] == ADMIN_ID
    text = bot.send_message.await_args.args[1]
    assert "-100999" in text and "не задан" in text
    jr["upsert_pending"].assert_not_called()


@pytest.mark.asyncio
async def test_unreachable_user_is_reported_to_admin(jr):
    request = MagicMock()
    request.chat.id, request.from_user.id, request.user_chat_id = CHAT_ID, USER_ID, USER_ID
    request.from_user.username = "newbie"
    bot = AsyncMock()
    bot.send_message.side_effect = [RuntimeError("Forbidden"), None]

    await join_verify.handle_join_request(request, bot)

    assert jr["finish"].await_args.args[-1] == "unreachable"
    assert bot.send_message.await_args.args[0] == ADMIN_ID


@pytest.mark.asyncio
async def test_correct_emoji_approves(jr):
    jr["get"].return_value = _row()
    bot = _bot()
    callback = _callback("🌽")

    await join_verify.handle_join_answer(callback, bot)

    bot.approve_chat_join_request.assert_awaited_once_with(CHAT_ID, USER_ID)
    assert "одобрена" in callback.message.edit_text.await_args.args[0]
    assert bot.send_message.await_args.args[0] == ADMIN_ID
    assert "принят в чат" in bot.send_message.await_args.args[1]


@pytest.mark.asyncio
async def test_double_click_does_not_approve_twice(jr):
    jr["get"].return_value = _row()
    jr["finish"].return_value = False  # заявку уже закрыл первый клик
    bot = _bot()

    await join_verify.handle_join_answer(_callback("🌽"), bot)

    bot.approve_chat_join_request.assert_not_called()


@pytest.mark.asyncio
async def test_failed_approve_notifies_admin(jr):
    jr["get"].return_value = _row()
    bot = _bot()
    bot.approve_chat_join_request.side_effect = RuntimeError("HIDE_REQUESTER_MISSING")

    await join_verify.handle_join_answer(_callback("🌽"), bot)

    assert jr["mark_status"].await_args.args[-1] == "processed"
    assert bot.send_message.await_args.args[0] == ADMIN_ID


@pytest.mark.asyncio
async def test_wrong_emoji_gives_new_challenge(jr):
    jr["get"].return_value = _row()
    jr["register_wrong_answer"].return_value = 1
    bot = AsyncMock()
    callback = _callback("🍄")

    await join_verify.handle_join_answer(callback, bot)

    bot.approve_chat_join_request.assert_not_called()
    bot.decline_chat_join_request.assert_not_called()
    assert "Осталось попыток: 2" in callback.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_third_wrong_answer_declines_and_notifies_admin(jr):
    jr["get"].return_value = _row(attempts=2)
    jr["register_wrong_answer"].return_value = join_verify.MAX_ATTEMPTS
    bot = AsyncMock()

    await join_verify.handle_join_answer(_callback("🍄"), bot)

    bot.decline_chat_join_request.assert_awaited_once_with(CHAT_ID, USER_ID)
    assert bot.send_message.await_args.args[0] == ADMIN_ID


@pytest.mark.asyncio
async def test_answer_to_closed_request_is_ignored(jr):
    jr["get"].return_value = _row(status="approved")
    bot = AsyncMock()
    callback = _callback("🌽")

    await join_verify.handle_join_answer(callback, bot)

    bot.approve_chat_join_request.assert_not_called()
    assert "уже обработана" in callback.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_reminder_is_sent_and_recorded(jr):
    now = datetime.now(timezone.utc)
    jr["list_due_reminders"].return_value = [_row(requested_at=now - timedelta(hours=13))]
    bot = AsyncMock()

    result = await join_verify.process_timeouts(bot, now=now)

    assert result["reminded"] == 1
    assert "~11 ч" in bot.send_message.await_args.args[1]
    assert jr["mark_reminded"].await_args.args[-1] is True


@pytest.mark.asyncio
async def test_undelivered_reminder_is_recorded_as_such(jr):
    now = datetime.now(timezone.utc)
    jr["list_due_reminders"].return_value = [_row(requested_at=now - timedelta(hours=13))]
    bot = AsyncMock()
    bot.send_message.side_effect = RuntimeError("Forbidden: bot can't initiate conversation")

    await join_verify.process_timeouts(bot, now=now)

    assert jr["mark_reminded"].await_args.args[-1] is False


@pytest.mark.asyncio
async def test_expired_request_is_declined_and_admin_notified(jr):
    now = datetime.now(timezone.utc)
    jr["list_expired"].return_value = [
        _row(requested_at=now - timedelta(hours=25), reminder_delivered=False)
    ]
    bot = AsyncMock()

    result = await join_verify.process_timeouts(bot, now=now)

    assert result["expired"] == 1
    assert jr["finish"].await_args.args[-1] == "expired"
    bot.decline_chat_join_request.assert_awaited_once_with(CHAT_ID, USER_ID)
    bot.edit_message_text.assert_awaited_once()
    admin_text = bot.send_message.await_args.args[1]
    assert bot.send_message.await_args.args[0] == ADMIN_ID
    assert "не доставлено" in admin_text


@pytest.mark.asyncio
async def test_correct_emoji_without_subscription_asks_to_subscribe(jr):
    jr["get"].return_value = _row()
    bot = _bot(subscribed=False)
    callback = _callback("🌽")

    await join_verify.handle_join_answer(callback, bot)

    jr["mark_captcha_passed"].assert_awaited_once()
    bot.approve_chat_join_request.assert_not_called()
    bot.get_chat_member.assert_awaited_once_with("@URGSFL", USER_ID)
    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    buttons = [b for row in markup.inline_keyboard for b in row]
    assert buttons[0].url == "https://t.me/URGSFL"
    assert buttons[1].callback_data == f"joinsub:{CHAT_ID}"


@pytest.mark.asyncio
async def test_subscribed_click_approves_after_subscription(jr):
    jr["get"].return_value = _row(captcha_passed=True)
    bot = _bot(subscribed=True)
    callback = _callback("x")
    callback.data = f"joinsub:{CHAT_ID}"

    await join_verify.handle_subscribed_click(callback, bot)

    bot.approve_chat_join_request.assert_awaited_once_with(CHAT_ID, USER_ID)


@pytest.mark.asyncio
async def test_subscribed_click_without_subscription_shows_alert(jr):
    jr["get"].return_value = _row(captcha_passed=True)
    bot = _bot(subscribed=False)
    callback = _callback("x")
    callback.data = f"joinsub:{CHAT_ID}"

    await join_verify.handle_subscribed_click(callback, bot)

    bot.approve_chat_join_request.assert_not_called()
    callback.answer.assert_awaited_once()
    assert callback.answer.await_args.kwargs["show_alert"] is True


@pytest.mark.asyncio
async def test_subscribed_click_before_captcha_is_ignored(jr):
    jr["get"].return_value = _row(captcha_passed=False)
    bot = _bot(subscribed=True)
    callback = _callback("x")
    callback.data = f"joinsub:{CHAT_ID}"

    await join_verify.handle_subscribed_click(callback, bot)

    bot.approve_chat_join_request.assert_not_called()


@pytest.mark.asyncio
async def test_restricted_member_counts_as_subscribed():
    bot = AsyncMock()
    bot.get_chat_member.return_value = MagicMock(status="restricted", is_member=True)
    assert await join_verify._is_subscribed(bot, USER_ID) is True
    bot.get_chat_member.return_value = MagicMock(status="kicked")
    assert await join_verify._is_subscribed(bot, USER_ID) is False


@pytest.mark.asyncio
async def test_subscription_check_error_notifies_admin_once(jr):
    jr["get"].return_value = _row()
    bot = _bot()
    bot.get_chat_member.side_effect = RuntimeError("member list is inaccessible")

    await join_verify.handle_join_answer(_callback("🌽"), bot)
    await join_verify.handle_join_answer(_callback("🌽"), bot)

    bot.approve_chat_join_request.assert_not_called()
    admin_messages = [c for c in bot.send_message.await_args_list if c.args[0] == ADMIN_ID]
    assert len(admin_messages) == 1  # не спамим админа на каждую заявку


@pytest.mark.asyncio
async def test_expired_after_captcha_reports_missing_subscription(jr):
    now = datetime.now(timezone.utc)
    jr["list_expired"].return_value = [
        _row(requested_at=now - timedelta(hours=25), captcha_passed=True)
    ]
    bot = AsyncMock()

    await join_verify.process_timeouts(bot, now=now)

    assert "нет подписки на @URGSFL" in bot.send_message.await_args.args[1]
