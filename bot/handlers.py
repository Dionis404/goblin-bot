"""Хэндлеры aiogram: приём ID фермы, подтверждение, запись в БД."""
import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from bot import sfl_api
from bot.keyboards import confirm_keyboard
from shared import db

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
            f"Изменить привязанную ферму нельзя.",
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
            f"Теперь ты в сообществе GoblinCodex 🎉"
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
