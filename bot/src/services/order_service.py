from datetime import datetime, timezone
from html import escape

from aiogram.types import User
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.order import Order, OrderStatus
from src.repositories.order_repository import OrderRepository
from src.services.payment_service import PaymentService


class OrderService:
    # Сервис содержит бизнес-правила заявок.
    # Handlers отвечают за Telegram-сообщения, repository отвечает за SQL,
    # а здесь проверяются статусы, владелец заявки и обязательные поля.
    def __init__(self, session: AsyncSession) -> None:
        self.repository = OrderRepository(session)
        self.payment_service = PaymentService()

    async def create_draft(self, user: User) -> Order:
        # У пользователя может быть только один активный черновик.
        # Если draft уже есть, возвращаем его, чтобы не плодить пустые заявки.
        draft = await self.repository.get_user_draft(user.id)
        if draft:
            return draft

        return await self.repository.create_draft(
            user_id=user.id,
            username=user.username,
        )

    async def get_order(self, order_id: int) -> Order | None:
        return await self.repository.get_by_id(order_id)

    async def list_user_orders(self, user_id: int) -> list[Order]:
        return await self.repository.list_by_user(user_id)

    async def get_stats(self) -> dict[str, int]:
        return await self.repository.count_by_status()

    async def create_from_draft(self, user: User, draft: dict) -> Order:
        return await self.repository.create_sent(
            user_id=user.id,
            username=user.username,
            address=draft.get("address"),
            product_type=draft.get("product_type"),
            size=draft.get("size"),
            link=draft.get("link"),
            photo_file_id=draft.get("photo_file_id"),
            comment=draft.get("comment"),
        )

    async def update_draft_field(
        self,
        order_id: int,
        user_id: int,
        field: str,
        value: str,
    ) -> Order:
        order = await self._get_owned_draft(order_id, user_id)
        return await self.repository.update(order, **{field: value})

    async def cancel_draft(self, order_id: int, user_id: int) -> Order:
        order = await self._get_owned_draft(order_id, user_id)
        return await self.repository.update(order, status=OrderStatus.CANCELLED.value)

    async def submit(self, order_id: int, user_id: int) -> tuple[Order, list[str]]:
        # Возвращаем список незаполненных полей вместо исключения:
        # handler покажет пользователю конкретную ошибку в alert.
        order = await self._get_owned_draft(order_id, user_id)
        missing_fields = self.get_missing_required_fields(order)
        if missing_fields:
            return order, missing_fields

        order = await self.repository.update(order, status=OrderStatus.SENT_TO_ADMIN.value)
        return order, []

    async def set_admin_price(self, order_id: int, price: int, admin: User) -> Order:
        # Одобрение на первом этапе фактически переводит заявку сразу
        # в waiting_payment, потому что пользователь уже может перейти к оплате.
        order = await self._get_admin_order(order_id)
        payment_url = self.payment_service.build_payment_url(order)
        return await self.repository.update(
            order,
            admin_price=price,
            payment_url=payment_url,
            status=OrderStatus.WAITING_PAYMENT.value,
            processed_by_id=admin.id,
            processed_by_username=admin.username,
            processed_at=datetime.now(timezone.utc),
        )

    async def reject_by_admin(self, order_id: int, reason: str, admin: User) -> Order:
        order = await self._get_admin_order(order_id)
        return await self.repository.update(
            order,
            admin_comment=reason,
            status=OrderStatus.REJECTED.value,
            processed_by_id=admin.id,
            processed_by_username=admin.username,
            processed_at=datetime.now(timezone.utc),
        )

    async def cancel_after_approval(
        self,
        order_id: int,
        user_id: int,
    ) -> Order:
        order = await self.repository.get_by_id(order_id)
        if not order or order.user_id != user_id:
            raise ValueError("Заявка не найдена.")
        if order.status not in {OrderStatus.WAITING_PAYMENT.value, OrderStatus.APPROVED.value}:
            raise ValueError("Эту заявку нельзя отменить.")
        return await self.repository.update(order, status=OrderStatus.CANCELLED.value)

    async def ensure_payment_url(self, order_id: int, user_id: int) -> Order:
        order = await self.repository.get_by_id(order_id)
        if not order or order.user_id != user_id:
            raise ValueError("Заявка не найдена.")
        if order.status != OrderStatus.WAITING_PAYMENT.value:
            raise ValueError("Оплата для этой заявки недоступна.")
        if order.payment_url:
            return order
        return await self.repository.update(
            order,
            payment_url=self.payment_service.build_payment_url(order),
        )

    def get_missing_required_fields(self, order: Order) -> list[str]:
        # Обязательные поля: address, product_type, size и хотя бы одно
        # из двух доказательств товара: ссылка или фото.
        missing = []
        if not order.address:
            missing.append("адрес")
        if not order.product_type:
            missing.append("тип товара")
        if not order.size:
            missing.append("размер")
        if not order.link and not order.photo_file_id:
            missing.append("ссылка или фото")
        return missing

    def get_missing_required_draft_fields(self, draft: dict) -> list[str]:
        missing = []
        if not draft.get("address"):
            missing.append("адрес")
        if not draft.get("product_type"):
            missing.append("тип товара")
        if not draft.get("size"):
            missing.append("размер")
        if not draft.get("link") and not draft.get("photo_file_id"):
            missing.append("ссылка или фото")
        return missing

    def format_draft_menu(self, draft: dict) -> str:
        return (
            "<b>Ваша заявка</b>\n\n"
            "Статус: черновик\n"
            f"Адрес: {self._value(draft.get('address'))}\n"
            f"Тип товара: {self._value(draft.get('product_type'))}\n"
            f"Размер: {self._value(draft.get('size'))}\n"
            f"Ссылка: {self._value(draft.get('link'))}\n"
            f"Фото: {'загружено' if draft.get('photo_file_id') else 'не загружено'}\n"
            f"Комментарий: {self._value(draft.get('comment'))}"
        )

    def format_order_menu(self, order: Order) -> str:
        return (
            "<b>Ваша заявка</b>\n\n"
            f"ID заявки: <code>{order.id}</code>\n"
            f"Статус: {self._status_title(order.status)}\n"
            f"Адрес: {self._value(order.address)}\n"
            f"Тип товара: {self._value(order.product_type)}\n"
            f"Размер: {self._value(order.size)}\n"
            f"Ссылка: {self._value(order.link)}\n"
            f"Фото: {'загружено' if order.photo_file_id else 'не загружено'}\n"
            f"Комментарий: {self._value(order.comment)}"
        )

    def format_admin_order(self, order: Order) -> str:
        username = f"@{order.username}" if order.username else "не указан"
        return (
            f"<b>Новая заявка #{order.id}</b>\n\n"
            f"Telegram ID пользователя: <code>{order.user_id}</code>\n"
            f"Username пользователя: {escape(username)}\n"
            f"Адрес: {self._value(order.address)}\n"
            f"Тип товара: {self._value(order.product_type)}\n"
            f"Размер: {self._value(order.size)}\n"
            f"Ссылка: {self._value(order.link)}\n"
            f"Фото: {'есть' if order.photo_file_id else 'нет'}\n"
            f"Комментарий: {self._value(order.comment)}\n"
            f"Причина решения: {self._value(order.admin_comment)}\n"
            f"Статус: {self._status_title(order.status)}\n"
            f"Решение принял: {self._processed_by(order)}\n"
            f"Когда обработана: {self._processed_at(order)}"
        )

    def format_user_approval(self, order: Order) -> str:
        return (
            "<b>Ваша заявка одобрена</b>\n\n"
            f"ID заявки: <code>{order.id}</code>\n"
            f"Статус: {self._status_title(order.status)}\n"
            f"Адрес: {self._value(order.address)}\n"
            f"Тип товара: {self._value(order.product_type)}\n"
            f"Размер: {self._value(order.size)}\n"
            f"Ссылка: {self._value(order.link)}\n"
            f"Фото: {'загружено' if order.photo_file_id else 'не загружено'}\n"
            f"Комментарий: {self._value(order.comment)}\n"
            f"Цена: {order.admin_price} ₽\n"
            f"Комментарий администратора: {self._value(order.admin_comment)}"
        )

    def format_user_rejection(self, order: Order) -> str:
        return (
            "<b>Ваша заявка отклонена</b>\n\n"
            f"ID заявки: <code>{order.id}</code>\n"
            f"Статус: {self._status_title(order.status)}\n"
            f"Адрес: {self._value(order.address)}\n"
            f"Тип товара: {self._value(order.product_type)}\n"
            f"Размер: {self._value(order.size)}\n"
            f"Ссылка: {self._value(order.link)}\n"
            f"Фото: {'загружено' if order.photo_file_id else 'не загружено'}\n"
            f"Комментарий: {self._value(order.comment)}\n"
            f"Причина: {self._value(order.admin_comment)}"
        )

    def format_user_orders(self, orders: list[Order]) -> str:
        if not orders:
            return "У вас пока нет заявок."

        lines = ["<b>Ваши заявки</b>"]
        for order in orders:
            lines.append(
                f"Статус: {self._status_title(order.status)}. "
                f"Тип товара: {self._value(order.product_type)}. "
                f"Размер: {self._value(order.size)}."
            )
        return "\n".join(lines)

    def format_stats(self, stats: dict[str, int]) -> str:
        total = sum(stats.values())
        lines = [f"<b>Статистика заявок</b>", f"Всего: {total}"]

        for status in OrderStatus:
            lines.append(f"{self._status_title(status.value)}: {stats.get(status.value, 0)}")

        return "\n".join(lines)

    async def _get_owned_draft(self, order_id: int, user_id: int) -> Order:
        order = await self.repository.get_by_id(order_id)
        if not order or order.user_id != user_id:
            raise ValueError("Заявка не найдена.")
        if order.status != OrderStatus.DRAFT.value:
            raise ValueError("Эту заявку уже нельзя редактировать.")
        return order

    async def _get_admin_order(self, order_id: int) -> Order:
        order = await self.repository.get_by_id(order_id)
        if not order:
            raise ValueError("Заявка не найдена.")
        if order.status not in {OrderStatus.SENT_TO_ADMIN.value, OrderStatus.WAITING_PAYMENT.value}:
            raise ValueError("Сейчас с этой заявкой нельзя выполнить действие.")
        return order

    def _value(self, value: str | int | None) -> str:
        if value is None or value == "":
            return "не указан"
        return escape(str(value))

    def _status_title(self, status: str) -> str:
        titles = {
            OrderStatus.DRAFT.value: "черновик",
            OrderStatus.SENT_TO_ADMIN.value: "отправлена админам",
            OrderStatus.APPROVED.value: "одобрена",
            OrderStatus.REJECTED.value: "отклонена",
            OrderStatus.WAITING_PAYMENT.value: "ожидает оплату",
            OrderStatus.PAID.value: "оплачена",
            OrderStatus.CANCELLED.value: "отменена",
        }
        return titles.get(status, status)

    def _processed_by(self, order: Order) -> str:
        if order.processed_by_username:
            return escape(f"@{order.processed_by_username}")
        if order.processed_by_id:
            return f"<code>{order.processed_by_id}</code>"
        return "ещё не назначен"

    def _processed_at(self, order: Order) -> str:
        if not order.processed_at:
            return "ещё не обработана"
        return order.processed_at.strftime("%d.%m.%Y %H:%M")
