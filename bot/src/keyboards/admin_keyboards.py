from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def admin_order_keyboard(order_id: int, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Одобрить", callback_data=f"admin:approve:{order_id}"),
                InlineKeyboardButton(text="Отклонить", callback_data=f"admin:reject:{order_id}"),
            ],
            [
                InlineKeyboardButton(
                    text="Связаться с пользователем",
                    url=f"tg://user?id={user_id}",
                )
            ],
        ]
    )
