"""
Проверка вступающих в чат сообщества (JOIN_VERIFY_CHAT_ID).

Человек подаёт заявку -> бот пишет ему в личку ссылку на правила и
эмодзи-капчу ("нажми 🌽" среди трёх вариантов) -> правильный ответ =
согласие с правилами -> проверка подписки на REQUIRED_CHANNEL (если не
подписан — кнопки "Подписаться" / "Я подписался") -> бот одобряет заявку.
MAX_ATTEMPTS неверных ответов — отказ (заявку можно подать заново). Без
ответа: через REMIND_AFTER — напоминание, через EXPIRE_AFTER — отказ и
уведомление админу.

Ограничение Telegram: по user_chat_id из заявки бот может писать человеку
только 5 минут, если тот сам не запускал бота. Первое сообщение уходит
сразу, а напоминание — best effort: не доставилось — админ увидит это в
уведомлении о таймауте.

Нужно: в группе включено "Одобрение новых участников", бот — админ с правом
"Приглашать пользователей", "chat_join_request" в allowed_updates; для
проверки подписки бот — админ REQUIRED_CHANNEL.
"""
import html
import logging
import random
import time
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, ChatJoinRequest, InlineKeyboardButton, InlineKeyboardMarkup

from shared import config, db, join_requests
from shared.text import esc

router = Router()
log = logging.getLogger(__name__)

router.chat_join_request.filter(F.chat.id == config.JOIN_VERIFY_CHAT_ID)

EMOJI_POOL = ["🌻", "🍄", "🥕", "🌽", "🍓", "🐔", "🐄", "🍎", "🥔", "🌾"]
CHOICES = 3
MAX_ATTEMPTS = 3
REMIND_AFTER = timedelta(hours=12)
EXPIRE_AFTER = timedelta(hours=24)


def _new_challenge() -> tuple[str, list[str]]:
    """(правильный эмодзи, варианты в случайном порядке)."""
    options = random.sample(EMOJI_POOL, CHOICES)
    return random.choice(options), options


def _keyboard(chat_id: int, options: list[str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=emoji, callback_data=f"join:{chat_id}:{emoji}")
            for emoji in options
        ]]
    )


def _rules_line() -> str:
    if config.CHAT_RULES_URL:
        return f"📜 Перед входом прочитай <a href=\"{html.escape(config.CHAT_RULES_URL)}\">правила чата</a>."
    return "📜 Перед входом ознакомься с правилами чата."


def _channel_line() -> str:
    if not config.REQUIRED_CHANNEL:
        return ""
    return f"📢 Для входа нужна подписка на канал @{esc(config.REQUIRED_CHANNEL)}.\n\n"


def _challenge_text(chat_title: str | None, correct: str, note: str = "") -> str:
    chat = f"«{esc(chat_title)}»" if chat_title else "сообщества"
    return (
        f"👋 Привет! Ты подал заявку в чат {chat}.\n\n"
        f"{_rules_line()}\n\n"
        f"{_channel_line()}"
        f"Если ознакомился и согласен с правилами — нажми <b>{correct}</b> ниже.\n"
        f"⏳ Заявка действует 24 часа."
        + (f"\n\n{note}" if note else "")
    )


def _who(username: str | None, full_name: str | None, user_id: int) -> str:
    name = f"@{esc(username)}" if username else esc(full_name, empty="без имени")
    return f"{name} (<code>{user_id}</code>)"


async def _notify_admin(bot: Bot, text: str) -> None:
    if config.NOTIFY_ADMIN_TELEGRAM_ID is None:
        return
    try:
        await bot.send_message(config.NOTIFY_ADMIN_TELEGRAM_ID, text)
    except Exception:
        log.exception("Не удалось отправить админу уведомление о заявке в чат")


@router.chat_join_request()
async def handle_join_request(request: ChatJoinRequest, bot: Bot):
    user = request.from_user
    correct, options = _new_challenge()
    pool = await db.get_pool()
    await join_requests.upsert_pending(
        pool, request.chat.id, user.id, request.user_chat_id,
        user.username, user.full_name, correct,
    )

    try:
        sent = await bot.send_message(
            request.user_chat_id,
            _challenge_text(request.chat.title, correct),
            reply_markup=_keyboard(request.chat.id, options),
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.warning("Не удалось написать заявителю %s", user.id, exc_info=True)
        await join_requests.finish(pool, request.chat.id, user.id, "unreachable")
        await _notify_admin(
            bot,
            f"⚠️ Не удалось написать подавшему заявку {_who(user.username, user.full_name, user.id)}: "
            f"<code>{esc(type(e).__name__)}</code>.\n"
            f"Заявка ждёт ручного решения в настройках группы.",
        )
        return

    await join_requests.set_message_id(pool, request.chat.id, user.id, sent.message_id)


@router.callback_query(F.data.startswith("join:"))
async def handle_join_answer(callback: CallbackQuery, bot: Bot):
    try:
        _, raw_chat_id, emoji = callback.data.split(":", 2)
        chat_id = int(raw_chat_id)
    except ValueError:
        await callback.answer()
        return

    row = await _get_pending(callback, chat_id)
    if row is None:
        return
    if row["captcha_passed"]:
        await callback.answer()  # старая кнопка капчи после того, как правила уже приняты
        return

    if emoji == row["correct_emoji"]:
        pool = await db.get_pool()
        await join_requests.mark_captcha_passed(pool, chat_id, row["user_id"])
        await _approve_if_subscribed(callback, bot, row)
    else:
        await _wrong_answer(callback, bot, row)
    await callback.answer()


@router.callback_query(F.data.startswith("joinsub:"))
async def handle_subscribed_click(callback: CallbackQuery, bot: Bot):
    """Кнопка "✅ Я подписался" — повторная проверка подписки."""
    try:
        chat_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return

    row = await _get_pending(callback, chat_id)
    if row is None:
        return
    if not row["captcha_passed"]:
        await callback.answer()
        return

    if await _approve_if_subscribed(callback, bot, row, repeated=True):
        await callback.answer()


async def _get_pending(callback: CallbackQuery, chat_id: int):
    """Заявка нажавшего (ключ — его user_id, чужую не достать) или None, если закрыта."""
    pool = await db.get_pool()
    row = await join_requests.get(pool, chat_id, callback.from_user.id)
    if row is None or row["status"] != "pending":
        await callback.message.edit_text("Эта заявка уже обработана. Если нужно — подай новую.")
        await callback.answer()
        return None
    return row


async def _is_subscribed(bot: Bot, user_id: int) -> bool:
    """Подписан ли на REQUIRED_CHANNEL. Ошибку API пробрасывает — решает вызывающий."""
    member = await bot.get_chat_member(f"@{config.REQUIRED_CHANNEL}", user_id)
    if member.status in ("creator", "administrator", "member"):
        return True
    # restricted — участник с ограничениями, но всё ещё в канале
    return member.status == "restricted" and bool(getattr(member, "is_member", False))


SUB_ERROR_NOTICE_INTERVAL_SEC = 3600
_last_sub_error_notice = 0.0


def _sub_error_notice_due() -> bool:
    """
    Ошибка проверки подписки обычно системная (бот не админ канала) и бьёт по
    всем заявкам сразу — шлём админу не чаще раза в час, а не на каждую.
    """
    global _last_sub_error_notice
    now = time.monotonic()
    if _last_sub_error_notice and now - _last_sub_error_notice < SUB_ERROR_NOTICE_INTERVAL_SEC:
        return False
    _last_sub_error_notice = now
    return True


def _subscribe_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"📢 Подписаться на @{config.REQUIRED_CHANNEL}",
                url=f"https://t.me/{config.REQUIRED_CHANNEL}",
            )],
            [InlineKeyboardButton(text="✅ Я подписался", callback_data=f"joinsub:{chat_id}")],
        ]
    )


async def _approve_if_subscribed(
    callback: CallbackQuery, bot: Bot, row, repeated: bool = False
) -> bool:
    """
    Одобряет заявку, если подписка есть (или проверка выключена). Иначе
    показывает кнопки подписки. Возвращает False, если сам уже ответил на
    callback (alert), — тогда вызывающему не нужно вызывать callback.answer().
    """
    if config.REQUIRED_CHANNEL:
        try:
            subscribed = await _is_subscribed(bot, row["user_id"])
        except Exception as e:
            log.warning("Не удалось проверить подписку %s на канал", row["user_id"], exc_info=True)
            await callback.message.edit_text(
                "⚠️ Не получилось проверить подписку на канал. Попробуй через минуту.",
                reply_markup=_subscribe_keyboard(row["chat_id"]),
            )
            if _sub_error_notice_due():
                await _notify_admin(
                    bot,
                    f"⚠️ Не удалось проверить подписку на @{esc(config.REQUIRED_CHANNEL)} "
                    f"(бот — админ канала?): <code>{esc(str(e))}</code>\n"
                    f"Следующее такое уведомление — не раньше чем через час.",
                )
            return True

        if not subscribed:
            if repeated:
                await callback.answer(
                    f"Подписка на @{config.REQUIRED_CHANNEL} пока не видна. "
                    f"Подпишись и нажми ещё раз.",
                    show_alert=True,
                )
                return False
            await callback.message.edit_text(
                f"👍 Правила приняты! Остался последний шаг — подпишись на канал "
                f"@{esc(config.REQUIRED_CHANNEL)} и нажми «Я подписался».",
                reply_markup=_subscribe_keyboard(row["chat_id"]),
            )
            return True

    await _approve(callback, bot, row)
    return True


async def _approve(callback: CallbackQuery, bot: Bot, row) -> None:
    pool = await db.get_pool()
    if not await join_requests.finish(pool, row["chat_id"], row["user_id"], "approved"):
        return  # двойной клик: заявку уже закрыли

    try:
        await bot.approve_chat_join_request(row["chat_id"], row["user_id"])
    except Exception as e:
        # Чаще всего — заявку уже обработал админ вручную
        log.warning("approve_chat_join_request для %s не прошёл", row["user_id"], exc_info=True)
        await join_requests.mark_status(pool, row["chat_id"], row["user_id"], "processed")
        await callback.message.edit_text(
            "Не получилось принять заявку автоматически — возможно, её уже обработал админ. "
            "Если ты ещё не в чате, подай заявку снова."
        )
        await _notify_admin(
            bot,
            f"⚠️ Не удалось одобрить заявку {_who(row['username'], row['full_name'], row['user_id'])} "
            f"после подтверждения правил: <code>{esc(str(e))}</code>",
        )
        return

    await callback.message.edit_text("✅ Спасибо! Заявка одобрена — добро пожаловать в чат 🎉")


async def _wrong_answer(callback: CallbackQuery, bot: Bot, row) -> None:
    pool = await db.get_pool()
    correct, options = _new_challenge()
    attempts = await join_requests.register_wrong_answer(pool, row["chat_id"], row["user_id"], correct)

    if attempts < MAX_ATTEMPTS:
        left = MAX_ATTEMPTS - attempts
        await callback.message.edit_text(
            _challenge_text(None, correct, note=f"❌ Не тот эмодзи. Осталось попыток: {left}."),
            reply_markup=_keyboard(row["chat_id"], options),
            disable_web_page_preview=True,
        )
        return

    if not await join_requests.finish(pool, row["chat_id"], row["user_id"], "declined"):
        return
    decline_error = await _decline(bot, row)
    await callback.message.edit_text(
        "❌ Неверный ответ трижды — заявка отклонена. Можешь подать её снова."
    )
    await _notify_admin(
        bot,
        f"🚫 Заявка {_who(row['username'], row['full_name'], row['user_id'])} отклонена: "
        f"{MAX_ATTEMPTS} неверных ответа на капчу (возможно, бот)." + decline_error,
    )


async def _decline(bot: Bot, row) -> str:
    """Отклоняет заявку в Telegram; возвращает пометку об ошибке для админа (или "")."""
    try:
        await bot.decline_chat_join_request(row["chat_id"], row["user_id"])
        return ""
    except Exception as e:
        log.warning("decline_chat_join_request для %s не прошёл", row["user_id"], exc_info=True)
        return f"\n⚠️ Отклонить в Telegram не удалось: <code>{esc(str(e))}</code>"


async def process_timeouts(bot: Bot, now: datetime | None = None) -> dict:
    """Напоминания через REMIND_AFTER и отказ через EXPIRE_AFTER (из фонового цикла бота)."""
    now = now or datetime.now(timezone.utc)
    pool = await db.get_pool()
    reminded = expired = 0

    for row in await join_requests.list_due_reminders(pool, now - REMIND_AFTER):
        if row["requested_at"] <= now - EXPIRE_AFTER:
            continue  # уже пора отклонять — напоминать поздно
        hours_left = max(1, int((row["requested_at"] + EXPIRE_AFTER - now).total_seconds() // 3600))
        next_step = (
            f"Подпишись на канал @{esc(config.REQUIRED_CHANNEL)} и нажми «Я подписался» в сообщении выше."
            if row["captcha_passed"]
            else "Выбери нужный эмодзи в сообщении выше."
        )
        try:
            await bot.send_message(
                row["user_chat_id"],
                f"⏰ Напоминаю: твоя заявка в чат ждёт подтверждения ещё ~{hours_left} ч.\n{next_step}",
            )
            delivered = True
        except Exception:
            # Ожидаемо, если человек не запускал бота (окно 5 минут истекло)
            log.info("Напоминание заявителю %s не доставлено", row["user_id"], exc_info=True)
            delivered = False
        await join_requests.mark_reminded(pool, row["chat_id"], row["user_id"], delivered)
        reminded += 1

    for row in await join_requests.list_expired(pool, now - EXPIRE_AFTER):
        if not await join_requests.finish(pool, row["chat_id"], row["user_id"], "expired"):
            continue
        decline_error = await _decline(bot, row)
        if row["message_id"]:
            try:
                await bot.edit_message_text(
                    "⌛ Время на подтверждение вышло — заявка отклонена. Можешь подать её снова.",
                    chat_id=row["user_chat_id"], message_id=row["message_id"],
                )
            except Exception:
                log.info("Не удалось обновить сообщение заявителю %s", row["user_id"], exc_info=True)

        reminder = {
            None: "не отправлялось",
            True: "доставлено",
            False: "не доставлено (человек не запускал бота)",
        }[row["reminder_delivered"]]
        stage = (
            f"правила приняты, но нет подписки на @{esc(config.REQUIRED_CHANNEL)}"
            if row["captcha_passed"]
            else "правила не подтверждены"
        )
        await _notify_admin(
            bot,
            f"⌛ Заявка {_who(row['username'], row['full_name'], row['user_id'])} истекла "
            f"и отклонена: {stage}.\nНапоминание: {reminder}." + decline_error,
        )
        expired += 1

    return {"reminded": reminded, "expired": expired}
