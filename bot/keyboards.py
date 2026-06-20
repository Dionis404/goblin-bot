from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def confirm_keyboard(farm_id: int) -> InlineKeyboardMarkup:
    """Кнопки подтверждения привязки фермы."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, это я", callback_data=f"confirm:{farm_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Нет", callback_data="cancel"
                ),
            ]
        ]
    )
