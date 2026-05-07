"""Админские handlers заявок.

Файл отвечает за `/stats`, одобрение заявки, ввод цены, отклонение по готовой
причине, отмену админского действия и защиту админских команд.
"""

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from src.bot.loader import bot
from src.config import settings
from src.database import SessionLocal
from src.keyboards.admin_keyboards import (
    admin_approve_comment_keyboard,
    admin_cancel_action_keyboard,
    admin_order_keyboard,
    admin_order_status_keyboard,
    admin_paid_order_keyboard,
    admin_reject_reasons_keyboard,
)
from src.keyboards.user_keyboards import approved_order_keyboard, contact_admin_keyboard
from src.services.order_service import OrderService
from src.states.order_states import AdminOrderForm


router = Router(name="admin_orders")
logger = logging.getLogger(__name__)

REJECT_REASONS = {
    "rules": "Не прошёл правила",
    "insults": "Оскорбления запрещены",
    "spam": "Флуд / спам",
    "forbidden": "Запрещённый контент",
    "no_reason": "Без причины",
    "offtopic": "Не по теме",
    "bad_data": "Некорректные данные",
    "no_item": "Не нашли товар",
}


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
    logger.info(
        "Админ начал одобрение заявки",
        extra={"order_id": order_id, "admin_id": callback.from_user.id if callback.from_user else None},
    )

    if callback.message:
        action_message = await callback.message.answer(
            f"Введите цену для заявки #{order_id} в рублях.",
            reply_markup=admin_cancel_action_keyboard(order_id),
        )
        await state.update_data(action_message_id=action_message.message_id)
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

    # На этом шаге цену еще не сохраняем в БД окончательно: админ должен
    # следующим сообщением добавить комментарий или нажать "Без комментария".
    # Цена временно хранится в FSMContext, чтобы весь процесс одобрения
    # завершился одним согласованным update в сервисе.
    await state.update_data(pending_admin_price=int(raw_price))
    await state.set_state(AdminOrderForm.approve_comment)
    logger.info(
        "Админ ввёл цену для одобрения заявки",
        extra={
            "order_id": order_id,
            "admin_id": message.from_user.id if message.from_user else None,
            "price": int(raw_price),
        },
    )

    await _delete_action_message(message, state)
    action_message = await message.answer(
        f"Введите комментарий администратора для заявки #{order_id}.\n"
        "Он будет показан пользователю в поле «Комментарий администратора».",
        reply_markup=admin_approve_comment_keyboard(order_id),
    )
    await state.update_data(action_message_id=action_message.message_id)


@router.message(AdminOrderForm.approve_comment, F.chat.id == settings.admin_chat_id)
async def save_approve_comment(message: Message, state: FSMContext) -> None:
    # Этот handler принимает свободный комментарий к одобрению.
    # В отличие от причины отказа, комментарий не меняет смысл решения:
    # заявка всё равно становится waiting_payment, а текст просто поясняет цену
    # или условия заказа для пользователя.
    if not _is_admin_message(message):
        await message.answer("Недостаточно прав.")
        await state.clear()
        return

    if not message.text:
        await message.answer("Введите комментарий текстом или нажмите «Без комментария».")
        return

    await _finish_approval(message, state, message.text.strip(), message.from_user)


@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("admin:approve_comment_skip:")
)
async def skip_approve_comment(callback: CallbackQuery, state: FSMContext) -> None:
    # Кнопка пропуска закрывает второй шаг одобрения без сохранения текста.
    # Пользователь увидит "Комментарий администратора: не указан".
    if not _is_admin_callback(callback):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    order_id = _parse_order_id(callback.data or "")
    data = await state.get_data()
    if order_id is None or int(data.get("order_id", 0)) != order_id:
        await callback.answer("Некорректная заявка.", show_alert=True)
        return

    if not callback.message:
        await callback.answer("Не удалось завершить действие.", show_alert=True)
        return

    await _finish_approval(callback.message, state, None, callback.from_user)
    await callback.answer("Заявка одобрена без комментария.")


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
    if callback.message:
        action_message = await callback.message.answer(
            f"Выберите причину отклонения заявки #{order_id}.",
            reply_markup=admin_reject_reasons_keyboard(order_id),
        )
        await state.update_data(action_message_id=action_message.message_id)
    logger.info(
        "Админ начал отклонение заявки",
        extra={"order_id": order_id, "admin_id": callback.from_user.id if callback.from_user else None},
    )
    await callback.answer()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("admin:reject_reason:"))
async def reject_order_by_reason(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin_callback(callback):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    if not callback.data:
        await callback.answer("Некорректная команда.", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) != 4 or not parts[2].isdigit():
        await callback.answer("Некорректная команда.", show_alert=True)
        return

    order_id = int(parts[2])
    reason_code = parts[3]

    if reason_code == "back":
        await _cancel_admin_action(callback, state, order_id)
        return

    reason = REJECT_REASONS.get(reason_code)
    if not reason:
        await callback.answer("Некорректная причина.", show_alert=True)
        return

    async with SessionLocal() as session:
        service = OrderService(session)
        try:
            order = await service.reject_by_admin(order_id, reason, callback.from_user)
        except ValueError as error:
            await callback.answer(str(error), show_alert=True)
            await state.clear()
            return

        user_text = service.format_user_rejection(order)
        admin_text = service.format_admin_order(order)

    await bot.send_message(chat_id=order.user_id, text=user_text)
    await _edit_admin_order_card(state, admin_text)
    if callback.message:
        await _delete_message(callback.message)
    logger.info(
        "Админ отклонил заявку готовой причиной",
        extra={"order_id": order.id, "admin_id": callback.from_user.id if callback.from_user else None},
    )
    await callback.answer("Заявка отклонена.")
    await state.clear()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("admin:cancel:"))
async def cancel_admin_action(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin_callback(callback):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    order_id = _parse_order_id(callback.data or "")
    if order_id is None:
        await callback.answer("Некорректная заявка.", show_alert=True)
        return

    await _cancel_admin_action(callback, state, order_id)


@router.callback_query(lambda callback: callback.data and callback.data.startswith("admin:status:menu:"))
async def show_order_status_menu(callback: CallbackQuery) -> None:
    # После оплаты админы ведут заявку по логистическим статусам.
    # Эта кнопка не меняет данные, а только заменяет клавиатуру карточки
    # на список доступных статусов.
    if not _is_admin_callback(callback):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    order_id = _parse_order_id(callback.data or "")
    if order_id is None:
        await callback.answer("Некорректная заявка.", show_alert=True)
        return

    async with SessionLocal() as session:
        service = OrderService(session)
        order = await service.get_order(order_id)
        if not order:
            await callback.answer("Заявка не найдена.", show_alert=True)
            return

    if callback.message:
        try:
            await bot.edit_message_reply_markup(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                reply_markup=admin_order_status_keyboard(order.id, order.user_id),
            )
        except TelegramBadRequest:
            await callback.answer("Не удалось открыть меню статусов.", show_alert=True)
            return

    await callback.answer()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("admin:status:set:"))
async def set_order_status(callback: CallbackQuery) -> None:
    # Handler сохраняет выбранный админом статус доставки.
    # После успешного сохранения:
    # 1. админская карточка обновляется новым статусом;
    # 2. клавиатура снова становится компактной с кнопкой "Изменить статус";
    # 3. пользователь получает уведомление и кнопку связи с админом.
    if not _is_admin_callback(callback):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    parsed = _parse_status_callback(callback.data or "")
    if not parsed:
        await callback.answer("Некорректная команда.", show_alert=True)
        return

    order_id, new_status = parsed

    async with SessionLocal() as session:
        service = OrderService(session)
        try:
            order = await service.set_admin_managed_status(order_id, new_status, callback.from_user)
        except ValueError as error:
            await callback.answer(str(error), show_alert=True)
            return

        admin_text = service.format_admin_order(order)
        user_text = service.format_user_status_changed(order)

    if callback.message:
        await _edit_admin_message(
            callback.message,
            admin_text,
            admin_paid_order_keyboard(order.id, order.user_id),
        )

    await bot.send_message(
        chat_id=order.user_id,
        text=user_text,
        reply_markup=contact_admin_keyboard(),
    )
    logger.info(
        "Админ уведомил пользователя о новом статусе заявки",
        extra={
            "order_id": order.id,
            "admin_id": callback.from_user.id if callback.from_user else None,
            "new_status": order.status,
        },
    )
    await callback.answer("Статус заявки изменён.")


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
    await _delete_action_message(message, state)
    logger.info(
        "Админ отклонил заявку своей причиной",
        extra={"order_id": order.id, "admin_id": message.from_user.id if message.from_user else None},
    )
    await message.answer(f"Заявка #{order.id} отклонена, причина отправлена пользователю.")
    await state.clear()


async def _finish_approval(
    message: Message,
    state: FSMContext,
    admin_comment: str | None,
    admin: User,
) -> None:
    # Финальная точка одобрения заявки.
    #
    # Здесь сходятся оба варианта второго шага:
    # 1. админ написал комментарий текстом;
    # 2. админ нажал "Без комментария".
    #
    # Только здесь сохраняем цену и комментарий в БД, переводим заявку
    # в waiting_payment, обновляем админскую карточку и отправляем пользователю
    # сообщение с кнопкой оплаты. Так админ не отправит пользователю неполную
    # заявку, где цена уже есть, а комментарий еще не обработан.
    data = await state.get_data()
    order_id = int(data["order_id"])
    price = int(data["pending_admin_price"])

    async with SessionLocal() as session:
        service = OrderService(session)
        try:
            order = await service.set_admin_price(order_id, price, admin_comment, admin)
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
    await _delete_action_message(message, state)
    logger.info(
        "Админ завершил одобрение заявки",
        extra={
            "order_id": order.id,
            "admin_id": admin.id,
            "price": price,
            "has_admin_comment": bool(admin_comment),
        },
    )
    await message.answer(f"Заявка #{order.id} одобрена, цена и комментарий отправлены пользователю.")
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


def _parse_status_callback(callback_data: str) -> tuple[int, str] | None:
    parts = callback_data.split(":")
    if len(parts) != 5 or not parts[3].isdigit():
        return None
    return int(parts[3]), parts[4]


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


async def _edit_admin_message(
    message: Message,
    text: str,
    reply_markup,
) -> None:
    # Один helper для редактирования админской карточки и с фото, и без фото.
    # Telegram различает текстовые сообщения и подписи к фото, поэтому приходится
    # выбирать edit_message_caption или edit_message_text по факту наличия photo.
    try:
        if message.photo:
            await bot.edit_message_caption(
                chat_id=message.chat.id,
                message_id=message.message_id,
                caption=text,
                reply_markup=reply_markup,
            )
        else:
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=message.message_id,
                text=text,
                reply_markup=reply_markup,
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


async def _cancel_admin_action(
    callback: CallbackQuery,
    state: FSMContext,
    order_id: int,
) -> None:
    async with SessionLocal() as session:
        service = OrderService(session)
        order = await service.get_order(order_id)
        if not order:
            await callback.answer("Заявка не найдена.", show_alert=True)
            await state.clear()
            return

    data = await state.get_data()
    chat_id = data.get("admin_message_chat_id")
    message_id = data.get("admin_message_id")

    if chat_id and message_id:
        try:
            await bot.edit_message_reply_markup(
                chat_id=int(chat_id),
                message_id=int(message_id),
                reply_markup=admin_order_keyboard(order.id, order.user_id),
            )
        except TelegramBadRequest:
            pass

    if callback.message:
        await _delete_message(callback.message)

    await state.clear()
    await callback.answer("Действие отменено.")


async def _delete_action_message(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    action_message_id = data.get("action_message_id")
    if not action_message_id:
        return

    try:
        await bot.delete_message(message.chat.id, int(action_message_id))
    except TelegramBadRequest:
        return


async def _delete_message(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        return
