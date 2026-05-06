from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from src.keyboards.user_keyboards import contact_admin_text, start_keyboard


router = Router(name="start")


@router.message(CommandStart())
async def start_command(message: Message) -> None:
    await message.answer(
        "Здравствуйте! Здесь можно оформить заявку на заказ товара.",
        reply_markup=start_keyboard(),
    )


@router.callback_query(lambda callback: callback.data == "contact:admin")
async def contact_admin(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(contact_admin_text())
