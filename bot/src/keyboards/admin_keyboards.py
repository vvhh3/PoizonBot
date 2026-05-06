"""Inline-клавиатуры для администраторов.

Здесь находятся кнопки одобрения/отклонения заявки, отмены действия
и готовые причины отказа.
"""

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


def admin_cancel_action_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отменить действие", callback_data=f"admin:cancel:{order_id}")],
        ]
    )


def admin_reject_reasons_keyboard(order_id: int) -> InlineKeyboardMarkup:
    reasons = [
        ("Не прошёл правила", "rules"),
        ("Оскорбления запрещены", "insults"),
        ("Флуд / спам", "spam"),
        ("Запрещённый контент", "forbidden"),
        ("Без причины", "no_reason"),
        ("Не по теме", "offtopic"),
        ("Некорректные данные", "bad_data"),
        ("Назад", "back"),
    ]

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=f"admin:reject_reason:{order_id}:{code}")]
            for text, code in reasons
        ]
    )
