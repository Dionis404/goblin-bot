"""Хэндлеры aiogram: приём ID фермы, подтверждение, запись в БД."""
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from bot import sfl_api
from bot.keyboards import confirm_keyboard, menu_keyboard
from bot.subscriber_notify import SETTING_KEY as SUBSCRIBER_NOTIFY_KEY
from shared import bot_settings, config, db, tickets_leaderboard

router = Router()
log = logging.getLogger(__name__)

# Бот обрабатывает сообщения ТОЛЬКО в личке — в группах молчит
router.message.filter(F.chat.type == "private")


def _fmt_num(value, digits: int = 2) -> str:
    """Аккуратное форматирование чисел для вывода."""
    if value is None:
        return "—"
    return f"{value:,.{digits}f}".replace(",", " ")


@router.message(CommandStart())
async def cmd_start(message: Message):
    existing = await db.get_farmer_by_telegram(message.from_user.id)
    if existing:
        await message.answer(
            f"Ты уже привязал ферму <b>#{existing['farm_id']}</b> "
            f"(<b>{existing['game_username'] or 'без ника'}</b>).\n"
            f"Изменить привязанную ферму нельзя.\n\n"
            f"Отслеживание лидерборда тикетов — команда /tracking_lb.",
            reply_markup=menu_keyboard(existing["tickets_tracked"]),
        )
        return

    await message.answer(
        "👋 Привет! Это бот сообщества <a href=\"https://t.me/URGSFL\">URG SunflowerLand</a>.\n\n"
        "Чтобы привязать свою ферму Sunflower Land, пришли мне "
        "<b>номер фермы</b> (например: <code>62559</code>).\n\n"
        "⚠️ Привязать можно только одну ферму, и <b>изменить её потом нельзя</b>.\n\n"
        "🔒 Ваши данные хранятся на сервере в России, не используются в коммерческих целях "
        "и предназначены исключительно для сайта <b>goblincodex.fun</b>."
    )


@router.message(F.text.regexp(r"^\s*\d+\s*$"))
async def handle_farm_id(message: Message):
    # Уже привязан?
    if await db.get_farmer_by_telegram(message.from_user.id):
        existing = await db.get_farmer_by_telegram(message.from_user.id)
        await message.answer(
            f"У тебя уже привязана ферма <b>#{existing['farm_id']}</b>. "
            f"Изменить её нельзя."
        )
        return

    farm_id = int(message.text.strip())

    # Ферма уже занята другим пользователем?
    if await db.get_farmer_by_farm(farm_id):
        await message.answer(
            f"⚠️ Ферма <b>#{farm_id}</b> уже привязана другим игроком."
        )
        return

    # Anti-spam: один пользователь не чаще, чем раз в N секунд
    from bot.throttle import user_cooldown
    wait = user_cooldown.check(message.from_user.id)
    if wait > 0:
        await message.answer(
            f"⏳ Слишком часто. Подожди {int(wait) + 1} сек и попробуй снова."
        )
        return

    status_msg = await message.answer("🔍 Проверяю ферму…")
    try:
        farm = await sfl_api.fetch_farm(farm_id)
    except sfl_api.FarmNotFound:
        await status_msg.edit_text(
            f"❌ Ферма <b>#{farm_id}</b> не найдена. Проверь номер и попробуй снова."
        )
        return
    except sfl_api.RateLimited:
        await status_msg.edit_text(
            "⚠️ Сейчас слишком много запросов к игре. Попробуй через минуту."
        )
        return
    except Exception as e:
        log.exception("Ошибка запроса к SFL API")
        await status_msg.edit_text(
            "⚠️ Не удалось проверить ферму (ошибка соединения с игрой). "
            "Попробуй ещё раз через минуту."
        )
        return

    username = farm["username"] or "без ника"
    await status_msg.edit_text(
        f"Ферма <b>{farm_id}</b>\n"
        f"Ник <b>{username}</b>\n\n"
        f"⚠️ <b>ВНИМАНИЕ!</b> Изменить номер фермы в будущем нельзя.\n"
        f"Добавляйте только свой номер фермы!\n\n"
        f"Это твоя ферма?",
        reply_markup=confirm_keyboard(farm_id),
    )


@router.callback_query(F.data.startswith("confirm:"))
async def confirm_farm(callback: CallbackQuery):
    farm_id = int(callback.data.split(":", 1)[1])

    # Перепроверяем перед записью (могли привязать в другом чате)
    if await db.get_farmer_by_telegram(callback.from_user.id):
        await callback.message.edit_text("У тебя уже привязана ферма. Изменить нельзя.")
        await callback.answer()
        return

    # Дёргаем актуальные данные ещё раз — чтобы записать свежие XP/баланс
    try:
        farm = await sfl_api.fetch_farm(farm_id)
    except Exception:
        await callback.answer("Ошибка проверки фермы, попробуй снова", show_alert=True)
        return

    status = await db.insert_farmer(
        telegram_id=callback.from_user.id,
        telegram_username=callback.from_user.username,
        farm_id=farm_id,
        game_username=farm["username"],
        xp=farm["xp"],
        balance=farm["balance"],
        coins=farm["coins"],
        farm_url=farm["farm_url"],
    )

    if status == "ok":
        await callback.message.edit_text(
            f"✅ Готово! Ферма <b>#{farm_id}</b> "
            f"(<b>{farm['username'] or 'без ника'}</b>) привязана к тебе.\n\n"
            f"Теперь ты в сообществе GoblinCodex 🎉\n\n"
            f"Отслеживание лидерборда тикетов — команда /tracking_lb.",
            reply_markup=menu_keyboard(tickets_tracked=False),
        )
    elif status == "telegram_taken":
        await callback.message.edit_text("У тебя уже привязана ферма. Изменить нельзя.")
    elif status == "farm_taken":
        await callback.message.edit_text(
            f"⚠️ Ферма <b>#{farm_id}</b> уже привязана другим игроком."
        )
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def cancel(callback: CallbackQuery):
    await callback.message.edit_text(
        "Окей, отменил. Пришли номер фермы заново, когда будешь готов."
    )
    await callback.answer()


@router.message(Command("refresh_lp"))
async def refresh_lp(message: Message):
    if message.from_user.id not in config.ADMIN_TELEGRAM_IDS:
        return

    status_msg = await message.answer("🔄 Собираю лидерборд LP (может занять минуту)…")
    try:
        from jobs.lp_leaderboard import run_lp_leaderboard
        result = await run_lp_leaderboard()
    except Exception:
        log.exception("Ошибка обновления LP-лидерборда")
        await status_msg.edit_text("⚠️ Не удалось обновить лидерборд, смотри логи.")
        return

    await status_msg.edit_text(
        f"✅ Лидерборд обновлён.\n"
        f"Кошельков: <b>{result['wallets']}</b>\n"
        f"Блок: <code>{result['block']}</code>\n"
        f"TVL: <b>${result['total_tvl']:,.0f}</b>".replace(",", " ")
    )


@router.message(Command("backfill_post_images"))
async def backfill_post_images(message: Message):
    if message.from_user.id not in config.ADMIN_TELEGRAM_IDS:
        return

    status_msg = await message.answer(
        "🔄 Восстанавливаю картинки старых постов (пришлю копии постов сюда же, может занять время)…"
    )
    try:
        from jobs.backfill_post_images import run_backfill
        result = await run_backfill(message.bot)
    except Exception:
        log.exception("Ошибка бэкфилла картинок постов")
        await status_msg.edit_text("⚠️ Не удалось выполнить бэкфилл, смотри логи.")
        return

    await status_msg.edit_text(
        f"✅ Бэкфилл завершён.\n"
        f"Восстановлено: <b>{result['restored']}</b>\n"
        f"Не удалось: <b>{result['failed']}</b>\n"
        f"Всего к обработке: <b>{result['total']}</b>"
    )


@router.message(Command("tracking_lb"))
async def cmd_tracking_lb(message: Message):
    farmer = await db.get_farmer_by_telegram(message.from_user.id)
    if not farmer:
        await message.answer(
            "У тебя ещё нет привязанной фермы. Пришли номер фермы, чтобы привязать её."
        )
        return

    status = "включено ✅" if farmer["tickets_tracked"] else "выключено"
    await message.answer(
        f"🎟 Отслеживание лидерборда тикетов — ферма <b>#{farmer['farm_id']}</b>\n\n"
        f"Статус: <b>{status}</b>\n"
        f"Если ферма в топ-1200, место будет попадать в еженедельный отчёт в группе.",
        reply_markup=menu_keyboard(farmer["tickets_tracked"]),
    )


@router.callback_query(F.data.startswith("tickets_tracking:"))
async def toggle_tickets_tracking(callback: CallbackQuery):
    farmer = await db.get_farmer_by_telegram(callback.from_user.id)
    if not farmer:
        await callback.answer("Сначала привяжи ферму", show_alert=True)
        return

    enabled = callback.data.split(":", 1)[1] == "on"
    pool = await db.get_pool()
    await tickets_leaderboard.set_tracking(pool, callback.from_user.id, enabled)

    status = "включено ✅" if enabled else "выключено"
    await callback.message.edit_text(
        f"🎟 Отслеживание лидерборда тикетов — ферма <b>#{farmer['farm_id']}</b>\n\n"
        f"Статус: <b>{status}</b>\n"
        f"Если ферма в топ-1200, место будет попадать в еженедельный отчёт в группе.",
        reply_markup=menu_keyboard(enabled),
    )
    await callback.answer()


@router.message(Command("subscriber_notify"))
async def subscriber_notify_toggle(message: Message):
    if config.NOTIFY_ADMIN_TELEGRAM_ID is None or message.from_user.id != config.NOTIFY_ADMIN_TELEGRAM_ID:
        return

    args = message.text.split(maxsplit=1)
    arg = args[1].strip().lower() if len(args) > 1 else ""

    if arg not in ("on", "off"):
        enabled = await bot_settings.get_bool(SUBSCRIBER_NOTIFY_KEY, default=True)
        await message.answer(
            f"Уведомления о подписке/отписке от @{config.TELEGRAM_POSTS_CHANNEL}: "
            f"<b>{'включены' if enabled else 'выключены'}</b>.\n"
            f"Переключить: /subscriber_notify on|off"
        )
        return

    await bot_settings.set_bool(SUBSCRIBER_NOTIFY_KEY, arg == "on")
    await message.answer(
        f"{'✅ Включил' if arg == 'on' else '🔕 Выключил'} уведомления о подписке/отписке "
        f"от @{config.TELEGRAM_POSTS_CHANNEL}."
    )


@router.message()
async def handle_unknown(message: Message):
    await message.answer(
        "🤖 Я пока не умею общаться с фермерами и давать советы — "
        "но в нашем чате тебе точно помогут!\n\n"
        "👉 <a href=\"https://t.me/+hSm5ZeGb7ohhYzhi\">Присоединиться к чату</a>"
    )
