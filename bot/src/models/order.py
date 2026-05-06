"""Модель заявки и enum статусов.

Таблица `orders` хранит только реальные заявки, которые уже отправлены
администраторам или были обработаны. Временный черновик до отправки живёт в FSM.
"""

from datetime import datetime
from enum import StrEnum
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class OrderStatus(StrEnum):
    DRAFT = "draft"
    SENT_TO_ADMIN = "sent_to_admin"
    APPROVED = "approved"
    REJECTED = "rejected"
    WAITING_PAYMENT = "waiting_payment"
    PAID = "paid"
    CANCELLED = "cancelled"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    product_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    size: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    photo_file_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default=OrderStatus.DRAFT.value,
        server_default=OrderStatus.DRAFT.value,
        index=True,
        nullable=False,
    )
    admin_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    admin_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processed_by_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    processed_by_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
