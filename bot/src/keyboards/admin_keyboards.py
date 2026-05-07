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


def admin_paid_order_keyboard(order_id: int, user_id: int) -> InlineKeyboardMarkup:
    # Эта клавиатура появляется у админов после оплаты заявки.
    # В отличие от первичной карточки тут уже нельзя одобрять/отклонять:
    # деньги условно получены, дальше админ ведет заказ по статусам доставки.
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Изменить статус", callback_data=f"admin:status:menu:{order_id}")],
            [
                InlineKeyboardButton(
                    text="Связаться с пользователем",
                    url=f"tg://user?id={user_id}",
                )
            ],
        ]
    )


def admin_order_status_keyboard(order_id: int, user_id: int) -> InlineKeyboardMarkup:
    # Меню статусов показывается после нажатия "Изменить статус".
    # callback_data содержит order_id и новый статус, чтобы handler мог
    # сохранить выбранный статус и уведомить владельца заявки.
    statuses = [
        ("В пути", "in_transit"),
        ("Пришла", "arrived"),
        ("Задерживается", "delayed"),
        ("Отменена", "cancelled"),
        ("Отдана человеку", "handed_over"),
    ]

    rows = [
        [InlineKeyboardButton(text=text, callback_data=f"admin:status:set:{order_id}:{status}")]
        for text, status in statuses
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text="Связаться с пользователем",
                url=f"tg://user?id={user_id}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_cancel_action_keyboard(order_id: int) -> InlineKeyboardMarkup:
    # Общая клавиатура отмены используется на шагах ввода цены и комментария.
    # order_id кладем в callback_data, чтобы можно было вернуть кнопки именно
    # на той админской карточке, с которой началось действие.
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отменить действие", callback_data=f"admin:cancel:{order_id}")],
        ]
    )


def admin_approve_comment_keyboard(order_id: int) -> InlineKeyboardMarkup:
    # На шаге комментария админ может либо написать текст, либо пропустить поле.
    # Кнопка "Без комментария" нужна, чтобы одобрение не зависало, если пояснение
    # к заявке не требуется.
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Без комментария",
                    callback_data=f"admin:approve_comment_skip:{order_id}",
                )
            ],
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
