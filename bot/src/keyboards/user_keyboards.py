from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.config import settings


def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Оформить заявку",
                    callback_data="order:create",
                )
            ]
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


def contact_admin_text() -> str:
    return f"Напишите менеджеру: @{settings.admin_username.lstrip('@')}"
