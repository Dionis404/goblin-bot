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


def dispute_keyboard(farm_id: int) -> InlineKeyboardMarkup:
    """Кнопка жалобы, когда ферму уже привязал кто-то другой."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚩 Это моя ферма — сообщить админу",
                    callback_data=f"dispute:{farm_id}",
                )
            ]
        ]
    )


def unlink_keyboard(farm_id: int) -> InlineKeyboardMarkup:
    """Подтверждение админского /unlink — защита от опечатки в номере фермы."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 Отвязать", callback_data=f"unlink:{farm_id}:silent"
                ),
                InlineKeyboardButton(
                    text="🗑 Отвязать и уведомить", callback_data=f"unlink:{farm_id}:notify"
                ),
            ],
            [
                InlineKeyboardButton(text="❌ Отмена", callback_data="unlink_cancel"),
            ],
        ]
    )


def menu_keyboard(tickets_tracked: bool) -> InlineKeyboardMarkup:
    """Главное меню фермера: тоггл отслеживания лидерборда тикетов."""
    label = "🎟 Отключить отслеживание тикетов" if tickets_tracked else "🎟 Включить отслеживание тикетов"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"tickets_tracking:{'off' if tickets_tracked else 'on'}",
                )
            ]
        ]
    )
