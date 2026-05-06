from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.config import settings
from src.models.order import Order


def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Оформить заявку",
                    callback_data="order:create",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Мои заявки",
                    callback_data="order:list",
                )
            ],
        ]
    )


def order_menu_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Адрес", callback_data=f"order:edit:{order_id}:address"),
                InlineKeyboardButton(text="Тип товара", callback_data=f"order:edit:{order_id}:product_type"),
            ],
            [
                InlineKeyboardButton(text="Размер", callback_data=f"order:edit:{order_id}:size"),
                InlineKeyboardButton(text="Ссылка", callback_data=f"order:edit:{order_id}:link"),
            ],
            [
                InlineKeyboardButton(text="Фото", callback_data=f"order:edit:{order_id}:photo"),
                InlineKeyboardButton(text="Комментарий", callback_data=f"order:edit:{order_id}:comment"),
            ],
            [
                InlineKeyboardButton(text="Отправить заявку", callback_data=f"order:submit:{order_id}"),
            ],
            [
                InlineKeyboardButton(text="Отменить заявку", callback_data=f"order:cancel:{order_id}"),
            ],
        ]
    )


def approved_order_keyboard(order_id: int, payment_url: str | None = None) -> InlineKeyboardMarkup:
    payment_button = (
        InlineKeyboardButton(text="Оплатить", url=payment_url)
        if payment_url
        else InlineKeyboardButton(text="Оплатить", callback_data=f"order:pay:{order_id}")
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [payment_button],
            [
                InlineKeyboardButton(text="Отказаться", callback_data=f"order:reject:{order_id}"),
                InlineKeyboardButton(text="Связаться с админом", callback_data="contact:admin"),
            ],
        ]
    )


def payment_keyboard(payment_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Перейти к оплате", url=payment_url)],
            [InlineKeyboardButton(text="Связаться с админом", callback_data="contact:admin")],
        ]
    )


def user_orders_keyboard(
    orders: list[Order],
    selected_order_id: int | None = None,
) -> InlineKeyboardMarkup:
    rows = []
    for order in orders:
        title = order.product_type or "заявку"
        prefix = "Выбрана" if order.id == selected_order_id else "Открыть"
        rows.append(
            [InlineKeyboardButton(text=f"{prefix}: {title}", callback_data=f"order:view:{order.id}")]
        )
    rows.append([InlineKeyboardButton(text="Оформить заявку", callback_data="order:create")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def contact_admin_text() -> str:
    return f"Напишите менеджеру: @{settings.admin_username.lstrip('@')}"
