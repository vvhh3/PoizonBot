"""Пользовательские handlers заявок.

Файл отвечает за оформление заявки, FSM-заполнение полей, просмотр своих заявок,
переход к оплате и отказ пользователя после одобрения.
"""

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.bot.loader import bot
from src.config import settings
from src.database import SessionLocal
from src.keyboards.admin_keyboards import admin_order_keyboard, admin_paid_order_keyboard
from src.keyboards.user_keyboards import (
    approved_order_keyboard,
    draft_order_menu_keyboard,
    order_menu_keyboard,
    payment_keyboard,
    user_orders_keyboard,
)
from src.services.order_service import OrderService
from src.states.order_states import OrderForm


router = Router(name="user_orders")
logger = logging.getLogger(__name__)

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
async def create_order(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer("Не удалось создать заявку.", show_alert=True)
        return

    draft = {
        "address": None,
        "product_type": None,
        "size": None,
        "link": None,
        "photo_file_id": None,
        "comment": None,
    }
    await state.clear()
    await state.update_data(draft=draft)
    logger.info(
        "Пользователь начал оформление черновика заявки",
        extra={"user_id": callback.from_user.id},
    )

    async with SessionLocal() as session:
        service = OrderService(session)
        try:
            await callback.message.edit_text(
                service.format_draft_menu(draft),
                reply_markup=draft_order_menu_keyboard(),
            )
        except TelegramBadRequest:
            await callback.message.answer(
                service.format_draft_menu(draft),
                reply_markup=draft_order_menu_keyboard(),
            )

    await callback.answer()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("draft:edit:"))
async def edit_draft_field(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data or not callback.message:
        await callback.answer("Некорректная команда.", show_alert=True)
        return

    field = callback.data.rsplit(":", 1)[-1]
    if field not in FIELD_STATES:
        await callback.answer("Некорректное поле заявки.", show_alert=True)
        return

    await state.update_data(
        field=field,
        menu_chat_id=callback.message.chat.id,
        menu_message_id=callback.message.message_id,
    )
    await state.set_state(FIELD_STATES[field])
    prompt_message = await callback.message.answer(FIELD_PROMPTS[field])
    await state.update_data(prompt_message_id=prompt_message.message_id)
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
        prompt_message = await callback.message.answer(FIELD_PROMPTS[field])
        await state.update_data(prompt_message_id=prompt_message.message_id)
    await callback.answer()


@router.message(OrderForm.address)
@router.message(OrderForm.product_type)
@router.message(OrderForm.size)
@router.message(OrderForm.link)
@router.message(OrderForm.comment)
async def save_text_field(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    field = str(data["field"])

    if not message.from_user or not message.text:
        await message.answer("Отправьте текстовое значение.")
        return

    draft = data.get("draft")
    if isinstance(draft, dict):
        draft[field] = message.text.strip()
        await state.update_data(draft=draft)
        async with SessionLocal() as session:
            service = OrderService(session)
            await _edit_source_draft_menu(message, state, service, draft)
        await _cleanup_field_messages(message, state)
        await state.update_data(draft=draft)
        return

    order_id = int(data["order_id"])

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
        await _cleanup_field_messages(message, state)

    await state.clear()


@router.message(OrderForm.photo)
async def save_photo_field(message: Message, state: FSMContext) -> None:
    if not message.from_user or not message.photo:
        await message.answer("Отправьте фото товара.")
        return

    data = await state.get_data()
    photo_file_id = message.photo[-1].file_id

    draft = data.get("draft")
    if isinstance(draft, dict):
        draft["photo_file_id"] = photo_file_id
        await state.update_data(draft=draft)
        async with SessionLocal() as session:
            service = OrderService(session)
            await _edit_source_draft_menu(message, state, service, draft)
        await _cleanup_field_messages(message, state)
        await state.update_data(draft=draft)
        return

    order_id = int(data["order_id"])

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
        await _cleanup_field_messages(message, state)

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
            logger.info(
                "Пользователь попытался отправить незаполненную заявку",
                extra={
                    "order_id": order.id,
                    "user_id": callback.from_user.id,
                    "missing_fields": ",".join(missing_fields),
                },
            )
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
    logger.info(
        "Пользователь отправил сохранённый черновик заявки",
        extra={"order_id": order.id, "user_id": callback.from_user.id},
    )
    await callback.answer()


@router.callback_query(F.data == "draft:submit")
async def submit_draft_order(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer("Некорректная команда.", show_alert=True)
        return

    data = await state.get_data()
    draft = data.get("draft")
    if not isinstance(draft, dict):
        await callback.answer("Черновик не найден.", show_alert=True)
        return

    async with SessionLocal() as session:
        service = OrderService(session)
        missing_fields = service.get_missing_required_draft_fields(draft)
        if missing_fields:
            logger.info(
                "Пользователь попытался отправить незаполненный FSM-черновик",
                extra={
                    "user_id": callback.from_user.id,
                    "missing_fields": ",".join(missing_fields),
                },
            )
            await callback.answer(
                "Заполните обязательные поля: " + ", ".join(missing_fields),
                show_alert=True,
            )
            return

        order = await service.create_from_draft(callback.from_user, draft)
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
    await state.clear()
    logger.info(
        "Пользователь отправил FSM-черновик заявки",
        extra={"order_id": order.id, "user_id": callback.from_user.id},
    )
    await callback.answer()


@router.callback_query(F.data == "draft:cancel")
async def cancel_unsent_draft(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message:
        await callback.message.edit_text("Заявка отменена.")
    await state.clear()
    if callback.from_user:
        logger.info(
            "Пользователь отменил неотправленный FSM-черновик",
            extra={"user_id": callback.from_user.id},
        )
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
    logger.info(
        "Пользователь отменил черновик заявки",
        extra={"order_id": order.id, "user_id": callback.from_user.id},
    )
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
            order = await service.cancel_after_approval(
                order_id,
                callback.from_user.id,
            )
        except ValueError as error:
            await callback.answer(str(error), show_alert=True)
            return

        user_text = service.format_order_menu(order)

    await bot.send_message(
        chat_id=settings.admin_chat_id,
        text=f"Пользователь отказался от заявки #{order.id}.",
    )

    if callback.message:
        await callback.message.edit_text(user_text, reply_markup=None)
    logger.info(
        "Пользователь отказался от одобренной заявки",
        extra={"order_id": order.id, "user_id": callback.from_user.id},
    )
    await callback.answer()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("order:pay:"))
async def pay_order(callback: CallbackQuery, state: FSMContext) -> None:
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

        order_text = service.format_user_approval(order)

    await callback.message.edit_text(order_text, reply_markup=None)
    await callback.message.answer(
        f"Оплата заявки <code>{order.id}</code>.",
        reply_markup=payment_keyboard(order.id, order.payment_url),
    )
    await state.update_data(
        payment_order_id=order.id,
        payment_order_chat_id=callback.message.chat.id,
        payment_order_message_id=callback.message.message_id,
    )
    logger.info(
        "Пользователь открыл оплату заявки",
        extra={"order_id": order.id, "user_id": callback.from_user.id},
    )
    await callback.answer()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("payment:dev_success:"))
async def dev_payment_success(callback: CallbackQuery, state: FSMContext) -> None:
    # Dev-заглушка оплаты.
    #
    # В локальном режиме кнопка "Тестовая оплата" имитирует успешный платеж:
    # заявка сразу получает статус paid, пользователь видит обновленную карточку,
    # а админ-чат получает уведомление. В production сервис запретит этот путь,
    # потому что реальные оплаты должны подтверждаться webhook'ом провайдера.
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
            order = await service.mark_paid_by_dev_stub(order_id, callback.from_user.id)
        except ValueError as error:
            await callback.answer(str(error), show_alert=True)
            return

        user_text = service.format_order_menu(order)

    if callback.message:
        await callback.message.edit_text(
            f"Тестовая оплата заявки <code>{order.id}</code> прошла успешно.",
            reply_markup=None,
        )
        await callback.message.answer(user_text)

    await _send_paid_order_to_admins(order)
    logger.info(
        "Пользователь завершил оплату через dev-заглушку",
        extra={"order_id": order.id, "user_id": callback.from_user.id},
    )
    await state.clear()
    await callback.answer("Тестовая оплата прошла.")


@router.callback_query(F.data == "payment:back")
async def payment_back(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.from_user:
        await callback.answer("Некорректная команда.", show_alert=True)
        return

    data = await state.get_data()
    order_id = data.get("payment_order_id")
    order_message_id = data.get("payment_order_message_id")
    order_chat_id = data.get("payment_order_chat_id")

    if not order_id or not order_message_id or not order_chat_id:
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        await callback.answer()
        return

    async with SessionLocal() as session:
        service = OrderService(session)
        order = await service.get_order(int(order_id))
        if not order or order.user_id != callback.from_user.id:
            await callback.answer("Заявка не найдена.", show_alert=True)
            return

        try:
            await bot.edit_message_text(
                chat_id=int(order_chat_id),
                message_id=int(order_message_id),
                text=service.format_user_approval(order),
                reply_markup=approved_order_keyboard(order.id),
            )
        except TelegramBadRequest:
            pass

    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await state.clear()
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
            "Выберите заявку:" if orders else "У вас пока нет заявок.",
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
        await callback.message.edit_text(
            "Выберите заявку:" if orders else "У вас пока нет заявок.",
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
        orders = await service.list_user_orders(callback.from_user.id)
        order = await service.get_order(order_id)
        if not order or order.user_id != callback.from_user.id:
            await callback.answer("Заявка не найдена.", show_alert=True)
            return

        await callback.message.edit_text(
            service.format_order_menu(order),
            reply_markup=user_orders_keyboard(orders, selected_order_id=order.id),
        )

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


async def _edit_source_draft_menu(
    message: Message,
    state: FSMContext,
    service: OrderService,
    draft: dict,
) -> None:
    data = await state.get_data()
    chat_id = data.get("menu_chat_id")
    message_id = data.get("menu_message_id")

    if not chat_id or not message_id:
        await message.answer(
            service.format_draft_menu(draft),
            reply_markup=draft_order_menu_keyboard(),
        )
        return

    try:
        await bot.edit_message_text(
            chat_id=int(chat_id),
            message_id=int(message_id),
            text=service.format_draft_menu(draft),
            reply_markup=draft_order_menu_keyboard(),
        )
    except TelegramBadRequest:
        await message.answer(
            service.format_draft_menu(draft),
            reply_markup=draft_order_menu_keyboard(),
        )


async def _send_paid_order_to_admins(order) -> None:
    # Единая отправка оплаченной заявки админам.
    #
    # Сейчас helper вызывает dev-заглушка оплаты.
    #
    # Когда появится официальный платежный webhook, из него нужно будет вызвать
    # такую же отправку после подтверждения payment.succeeded.
    async with SessionLocal() as session:
        service = OrderService(session)
        fresh_order = await service.get_order(order.id)
        if not fresh_order:
            return

        admin_text = service.format_admin_order(fresh_order)
        admin_keyboard = admin_paid_order_keyboard(fresh_order.id, fresh_order.user_id)

    if fresh_order.photo_file_id:
        await bot.send_photo(
            chat_id=settings.admin_chat_id,
            photo=fresh_order.photo_file_id,
            caption=admin_text,
            reply_markup=admin_keyboard,
        )
    else:
        await bot.send_message(
            chat_id=settings.admin_chat_id,
            text=admin_text,
            reply_markup=admin_keyboard,
        )


async def _cleanup_field_messages(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    prompt_message_id = data.get("prompt_message_id")

    if prompt_message_id:
        try:
            await bot.delete_message(message.chat.id, int(prompt_message_id))
        except TelegramBadRequest:
            pass

    try:
        await message.delete()
    except TelegramBadRequest:
        pass
