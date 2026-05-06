from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.order import Order, OrderStatus


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_draft(self, user_id: int, username: str | None) -> Order:
        order = Order(
            user_id=user_id,
            username=username,
            status=OrderStatus.DRAFT.value,
        )
        self.session.add(order)
        await self.session.commit()
        await self.session.refresh(order)
        return order

    async def create_sent(
        self,
        user_id: int,
        username: str | None,
        address: str | None,
        product_type: str | None,
        size: str | None,
        link: str | None,
        photo_file_id: str | None,
        comment: str | None,
    ) -> Order:
        order = Order(
            user_id=user_id,
            username=username,
            address=address,
            product_type=product_type,
            size=size,
            link=link,
            photo_file_id=photo_file_id,
            comment=comment,
            status=OrderStatus.SENT_TO_ADMIN.value,
        )
        self.session.add(order)
        await self.session.commit()
        await self.session.refresh(order)
        return order

    async def get_by_id(self, order_id: int) -> Order | None:
        return await self.session.get(Order, order_id)

    async def get_user_draft(self, user_id: int) -> Order | None:
        result = await self.session.execute(
            select(Order)
            .where(Order.user_id == user_id, Order.status == OrderStatus.DRAFT.value)
            .order_by(Order.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: int, limit: int = 10) -> list[Order]:
        result = await self.session.execute(
            select(Order)
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_by_status(self) -> dict[str, int]:
        result = await self.session.execute(
            select(Order.status, func.count(Order.id)).group_by(Order.status)
        )
        return {status: count for status, count in result.all()}

    async def update(self, order: Order, **fields: Any) -> Order:
        for key, value in fields.items():
            setattr(order, key, value)

        await self.session.commit()
        await self.session.refresh(order)
        return order
