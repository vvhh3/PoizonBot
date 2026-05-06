from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.bot.loader import bot
from src.config import settings
from src.database import SessionLocal
from src.keyboards.admin_keyboards import admin_order_keyboard
from src.keyboards.user_keyboards import (
    order_menu_keyboard,
    payment_keyboard,
    user_orders_keyboard,
)
from src.services.order_service import OrderService
from src.states.order_states import OrderForm


router = Router(name="user_orders")

# Текстовые подсказки для каждого поля заявки.
# Ключи совпадают с именами полей в модели/сервисе и используются в callback_data.
FIELD_PROMPTS = {
    "address": "Введите адрес доставки.",
    "product_type": "Введите тип товара. Например: одежда, кроссовки, аксессуары.",
    "size": "Введите размер.",
    "link": "Отправьте ссылку на товар.",
    "photo": "Отправьте фото товара.",
    "comment": "Введите комментарий к заявке.",
}

# Связка "поле заявки -> FSM-состояние".
# Когда пользователь нажимает inline-кнопку, мы сохраняем order_id и field
# в FSMContext, переводим пользователя в нужное состояние и ждем следующий input.
FIELD_STATES = {
    "address": OrderForm.address,
    "product_type": OrderForm.product_type,
    "size": OrderForm.size,
    "link": OrderForm.link,
    "photo": OrderForm.photo,
    "comment": OrderForm.comment,
}


@router.callback_query(F.data == "order:create")
async def create_order(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer("Не удалось создать заявку.", show_alert=True)
        return

    # Создаем новый draft или возвращаем уже существующий draft пользователя.
    # Заявка сразу хранится в PostgreSQL, в памяти ничего не держим.
    async with SessionLocal() as session:
        service = OrderService(session)
        order = await service.create_draft(callback.from_user)
        await callback.message.answer(
            service.format_order_menu(order),
            reply_markup=order_menu_keyboard(order.id),
        )

    await callback.answer()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("order:edit:"))
async def edit_order_field(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data or not callback.from_user:
        await callback.answer("Некорректная команда.", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Некорректная команда.", show_alert=True)
        return

    _, _, raw_order_id, field = parts
    if field not in FIELD_STATES or not raw_order_id.isdigit():
        await callback.answer("Некорректное поле заявки.", show_alert=True)
        return

    order_id = int(raw_order_id)

    # Перед переходом в FSM проверяем, что заявка принадлежит пользователю
    # и все еще находится в статусе draft.
    async with SessionLocal() as session:
        service = OrderService(session)
        order = await service.get_order(order_id)
        if not order or order.user_id != callback.from_user.id:
            await callback.answer("Заявка не найдена.", show_alert=True)
            return
        if order.status != "draft":
            await callback.answer("Эту заявку уже нельзя редактировать.", show_alert=True)
            return

    await state.update_data(order_id=order_id, field=field)
    if callback.message:
        await state.update_data(
            menu_chat_id=callback.message.chat.id,
            menu_message_id=callback.message.message_id,
        )
    await state.set_state(FIELD_STATES[field])

    if callback.message:
        await callback.message.answer(FIELD_PROMPTS[field])
    await callback.answer()


@router.message(OrderForm.address)
@router.message(OrderForm.product_type)
@router.message(OrderForm.size)
@router.message(OrderForm.link)
@router.message(OrderForm.comment)
async def save_text_field(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = int(data["order_id"])
    field = str(data["field"])

    if not message.from_user or not message.text:
        await message.answer("Отправьте текстовое значение.")
        return

    # Сохраняем введенный текст в конкретное поле заявки.
    # Поле берется из FSMContext, поэтому один handler обслуживает сразу
    # address/product_type/size/link/comment.
    async with SessionLocal() as session:
        service = OrderService(session)
        try:
            order = await service.update_draft_field(
                order_id=order_id,
                user_id=message.from_user.id,
                field=field,
                value=message.text.strip(),
            )
        except ValueError as error:
            await message.answer(str(error))
            await state.clear()
            return

        await _edit_source_order_menu(message, state, service, order)

    await state.clear()


@router.message(OrderForm.photo)
async def save_photo_field(message: Message, state: FSMContext) -> None:
    if not message.from_user or not message.photo:
        await message.answer("Отправьте фото товара.")
        return

    data = await state.get_data()
    order_id = int(data["order_id"])
    photo_file_id = message.photo[-1].file_id

    # Берем самое большое фото из массива Telegram и сохраняем file_id.
    # Сам файл не скачиваем: Telegram file_id достаточно для повторной отправки.
    async with SessionLocal() as session:
        service = OrderService(session)
        try:
            order = await service.update_draft_field(
                order_id=order_id,
                user_id=message.from_user.id,
                field="photo_file_id",
                value=photo_file_id,
            )
        except ValueError as error:
            await message.answer(str(error))
            await state.clear()
            return

        await _edit_source_order_menu(message, state, service, order)

    await state.clear()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("order:submit:"))
async def submit_order(callback: CallbackQuery) -> None:
    if not callback.data or not callback.from_user or not callback.message:
        await callback.answer("Некорректная команда.", show_alert=True)
        return

    order_id = _parse_order_id(callback.data)
    if order_id is None:
        await callback.answer("Некорректная заявка.", show_alert=True)
        return

    # submit внутри сервиса проверяет обязательные поля и владельца заявки.
    # Если все ок, статус меняется на sent_to_admin.
    async with SessionLocal() as session:
        service = OrderService(session)
        try:
            order, missing_fields = await service.submit(order_id, callback.from_user.id)
        except ValueError as error:
            await callback.answer(str(error), show_alert=True)
            return

        if missing_fields:
            await callback.answer(
                "Заполните обязательные поля: " + ", ".join(missing_fields),
                show_alert=True,
            )
            return

        admin_text = service.format_admin_order(order)
        admin_keyboard = admin_order_keyboard(order.id, order.user_id)

    if order.photo_file_id:
        await bot.send_photo(
            chat_id=settings.admin_chat_id,
            photo=order.photo_file_id,
            caption=admin_text,
            reply_markup=admin_keyboard,
        )
    else:
        await bot.send_message(
            chat_id=settings.admin_chat_id,
            text=admin_text,
            reply_markup=admin_keyboard,
        )

    await callback.message.edit_text(service.format_order_menu(order), reply_markup=None)
    await callback.message.answer("Заявка отправлена администраторам.")
    await callback.answer()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("order:cancel:"))
async def cancel_draft(callback: CallbackQuery) -> None:
    if not callback.data or not callback.from_user:
        await callback.answer("Некорректная команда.", show_alert=True)
        return

    order_id = _parse_order_id(callback.data)
    if order_id is None:
        await callback.answer("Некорректная заявка.", show_alert=True)
        return

    async with SessionLocal() as session:
        service = OrderService(session)
        try:
            order = await service.cancel_draft(order_id, callback.from_user.id)
        except ValueError as error:
            await callback.answer(str(error), show_alert=True)
            return

    if callback.message:
        async with SessionLocal() as session:
            service = OrderService(session)
            await callback.message.edit_text(service.format_order_menu(order), reply_markup=None)
    await callback.answer()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("order:reject:"))
async def user_reject_approved_order(callback: CallbackQuery) -> None:
    if not callback.data or not callback.from_user:
        await callback.answer("Некорректная команда.", show_alert=True)
        return

    order_id = _parse_order_id(callback.data)
    if order_id is None:
        await callback.answer("Некорректная заявка.", show_alert=True)
        return

    async with SessionLocal() as session:
        service = OrderService(session)
        try:
            order = await service.cancel_after_approval(order_id, callback.from_user.id)
        except ValueError as error:
            await callback.answer(str(error), show_alert=True)
            return

    await bot.send_message(
        chat_id=settings.admin_chat_id,
        text=f"Пользователь отказался от заявки #{order.id}.",
    )
    if callback.message:
        async with SessionLocal() as session:
            service = OrderService(session)
            await callback.message.edit_text(service.format_order_menu(order), reply_markup=None)
    await callback.answer()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("order:pay:"))
async def pay_order(callback: CallbackQuery) -> None:
    if not callback.data or not callback.from_user or not callback.message:
        await callback.answer("Некорректная команда.", show_alert=True)
        return

    order_id = _parse_order_id(callback.data)
    if order_id is None:
        await callback.answer("Некорректная заявка.", show_alert=True)
        return

    async with SessionLocal() as session:
        service = OrderService(session)
        try:
            order = await service.ensure_payment_url(order_id, callback.from_user.id)
        except ValueError as error:
            await callback.answer(str(error), show_alert=True)
            return

    await callback.message.answer(
        "Оплата заявки.",
        reply_markup=payment_keyboard(order.payment_url or ""),
    )
    await callback.answer()


@router.message(Command("orders"))
async def my_orders_command(message: Message) -> None:
    if not message.from_user:
        await message.answer("Не удалось найти пользователя.")
        return

    async with SessionLocal() as session:
        service = OrderService(session)
        orders = await service.list_user_orders(message.from_user.id)
        await message.answer(
            service.format_user_orders(orders),
            reply_markup=user_orders_keyboard(orders),
        )


@router.callback_query(F.data == "order:list")
async def my_orders_callback(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer("Не удалось открыть заявки.", show_alert=True)
        return

    async with SessionLocal() as session:
        service = OrderService(session)
        orders = await service.list_user_orders(callback.from_user.id)
        await callback.message.answer(
            service.format_user_orders(orders),
            reply_markup=user_orders_keyboard(orders),
        )

    await callback.answer()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("order:view:"))
async def view_order(callback: CallbackQuery) -> None:
    if not callback.data or not callback.from_user or not callback.message:
        await callback.answer("Некорректная команда.", show_alert=True)
        return

    order_id = _parse_order_id(callback.data)
    if order_id is None:
        await callback.answer("Некорректная заявка.", show_alert=True)
        return

    async with SessionLocal() as session:
        service = OrderService(session)
        order = await service.get_order(order_id)
        if not order or order.user_id != callback.from_user.id:
            await callback.answer("Заявка не найдена.", show_alert=True)
            return

        if order.status == "draft":
            await callback.message.answer(
                service.format_order_menu(order),
                reply_markup=order_menu_keyboard(order.id),
            )
        else:
            await callback.message.answer(service.format_order_menu(order))

    await callback.answer()


def _parse_order_id(callback_data: str) -> int | None:
    raw_order_id = callback_data.rsplit(":", 1)[-1]
    if not raw_order_id.isdigit():
        return None
    return int(raw_order_id)


async def _edit_source_order_menu(
    message: Message,
    state: FSMContext,
    service: OrderService,
    order,
) -> None:
    data = await state.get_data()
    chat_id = data.get("menu_chat_id")
    message_id = data.get("menu_message_id")

    if not chat_id or not message_id:
        await message.answer(
            service.format_order_menu(order),
            reply_markup=order_menu_keyboard(order.id),
        )
        return

    try:
        await bot.edit_message_text(
            chat_id=int(chat_id),
            message_id=int(message_id),
            text=service.format_order_menu(order),
            reply_markup=order_menu_keyboard(order.id),
        )
    except TelegramBadRequest:
        await message.answer(
            service.format_order_menu(order),
            reply_markup=order_menu_keyboard(order.id),
        )

    await message.answer("Сохранено.")
