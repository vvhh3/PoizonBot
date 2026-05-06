from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.bot.loader import bot
from src.config import settings
from src.database import SessionLocal
from src.keyboards.user_keyboards import approved_order_keyboard
from src.services.order_service import OrderService
from src.states.order_states import AdminOrderForm


router = Router(name="admin_orders")


@router.message(Command("stats"), F.chat.id == settings.admin_chat_id)
async def stats_command(message: Message) -> None:
    if not _is_admin_message(message):
        await message.answer("Недостаточно прав.")
        return

    async with SessionLocal() as session:
        service = OrderService(session)
        stats = await service.get_stats()
        await message.answer(service.format_stats(stats))


@router.callback_query(lambda callback: callback.data and callback.data.startswith("admin:approve:"))
async def approve_order(callback: CallbackQuery, state: FSMContext) -> None:
    # Админские callback-кнопки должны работать только в ADMIN_CHAT_ID.
    # Это не дает пользователю вручную отправить callback_data и одобрить заявку.
    if not _is_admin_callback(callback):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    order_id = _parse_order_id(callback.data or "")
    if order_id is None:
        await callback.answer("Некорректная заявка.", show_alert=True)
        return

    await state.update_data(order_id=order_id)
    if callback.message:
        await state.update_data(
            admin_message_chat_id=callback.message.chat.id,
            admin_message_id=callback.message.message_id,
            admin_message_has_photo=bool(callback.message.photo),
        )
        await _remove_admin_order_buttons(callback.message)
    await state.set_state(AdminOrderForm.price)

    if callback.message:
        await callback.message.answer(f"Введите цену для заявки #{order_id} в рублях.")
    await callback.answer()


@router.message(AdminOrderForm.price, F.chat.id == settings.admin_chat_id)
async def save_admin_price(message: Message, state: FSMContext) -> None:
    if not _is_admin_message(message):
        await message.answer("Недостаточно прав.")
        await state.clear()
        return

    if not message.text:
        await message.answer("Введите цену числом.")
        return

    raw_price = message.text.strip().replace(" ", "")
    if not raw_price.isdigit():
        await message.answer("Введите цену числом, например: 12500.")
        return

    data = await state.get_data()
    order_id = int(data["order_id"])

    # Цена сохраняется в PostgreSQL, заявка переводится в waiting_payment,
    # а пользователю отправляется форма с кнопками оплаты/отказа/связи.
    async with SessionLocal() as session:
        service = OrderService(session)
        try:
            order = await service.set_admin_price(order_id, int(raw_price), message.from_user)
        except ValueError as error:
            await message.answer(str(error))
            await state.clear()
            return

        user_text = service.format_user_approval(order)
        admin_text = service.format_admin_order(order)

    await bot.send_message(
        chat_id=order.user_id,
        text=user_text,
        reply_markup=approved_order_keyboard(order.id),
    )
    await _edit_admin_order_card(state, admin_text)
    await message.answer(f"Заявка #{order.id} одобрена, цена отправлена пользователю.")
    await state.clear()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("admin:reject:"))
async def reject_order(callback: CallbackQuery, state: FSMContext) -> None:
    # После нажатия "Отклонить" админ вводит причину отдельным сообщением.
    # order_id временно хранится в FSMContext только до следующего ответа админа.
    if not _is_admin_callback(callback):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    order_id = _parse_order_id(callback.data or "")
    if order_id is None:
        await callback.answer("Некорректная заявка.", show_alert=True)
        return

    await state.update_data(order_id=order_id)
    if callback.message:
        await state.update_data(
            admin_message_chat_id=callback.message.chat.id,
            admin_message_id=callback.message.message_id,
            admin_message_has_photo=bool(callback.message.photo),
        )
        await _remove_admin_order_buttons(callback.message)
    await state.set_state(AdminOrderForm.reject_reason)

    if callback.message:
        await callback.message.answer(f"Введите причину отклонения заявки #{order_id}.")
    await callback.answer()


@router.message(AdminOrderForm.reject_reason, F.chat.id == settings.admin_chat_id)
async def save_reject_reason(message: Message, state: FSMContext) -> None:
    if not _is_admin_message(message):
        await message.answer("Недостаточно прав.")
        await state.clear()
        return

    if not message.text:
        await message.answer("Введите причину текстом.")
        return

    data = await state.get_data()
    order_id = int(data["order_id"])

    # Причина отказа сохраняется как admin_comment, статус становится rejected,
    # после чего пользователь получает сообщение с причиной.
    async with SessionLocal() as session:
        service = OrderService(session)
        try:
            order = await service.reject_by_admin(order_id, message.text.strip(), message.from_user)
        except ValueError as error:
            await message.answer(str(error))
            await state.clear()
            return

        user_text = service.format_user_rejection(order)
        admin_text = service.format_admin_order(order)

    await bot.send_message(chat_id=order.user_id, text=user_text)
    await _edit_admin_order_card(state, admin_text)
    await message.answer(f"Заявка #{order.id} отклонена, причина отправлена пользователю.")
    await state.clear()


def _is_admin_callback(callback: CallbackQuery) -> bool:
    if not callback.message or callback.message.chat.id != settings.admin_chat_id:
        return False
    if not callback.from_user:
        return False
    return _is_admin_user(callback.from_user.id)


def _is_admin_message(message: Message) -> bool:
    if message.chat.id != settings.admin_chat_id or not message.from_user:
        return False
    return _is_admin_user(message.from_user.id)


def _is_admin_user(user_id: int) -> bool:
    admin_ids = settings.admin_ids_list
    if not admin_ids:
        return True
    return user_id in admin_ids


def _parse_order_id(callback_data: str) -> int | None:
    raw_order_id = callback_data.rsplit(":", 1)[-1]
    if not raw_order_id.isdigit():
        return None
    return int(raw_order_id)


async def _edit_admin_order_card(state: FSMContext, text: str) -> None:
    data = await state.get_data()
    chat_id = data.get("admin_message_chat_id")
    message_id = data.get("admin_message_id")
    has_photo = bool(data.get("admin_message_has_photo"))

    if not chat_id or not message_id:
        return

    try:
        if has_photo:
            await bot.edit_message_caption(
                chat_id=int(chat_id),
                message_id=int(message_id),
                caption=text,
                reply_markup=None,
            )
        else:
            await bot.edit_message_text(
                chat_id=int(chat_id),
                message_id=int(message_id),
                text=text,
                reply_markup=None,
            )
    except TelegramBadRequest:
        return


async def _remove_admin_order_buttons(message: Message) -> None:
    try:
        await bot.edit_message_reply_markup(
            chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=None,
        )
    except TelegramBadRequest:
        return
