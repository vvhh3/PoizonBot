from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings
from src.models.order import Base


# Async engine хранит пул подключений к PostgreSQL.
# pool_pre_ping=True проверяет соединение перед использованием и помогает
# переживать разрывы соединения, которые иногда бывают на Railway.
engine = create_async_engine(settings.sqlalchemy_database_url, pool_pre_ping=True)

# Фабрика async-сессий. expire_on_commit=False оставляет поля моделей доступными
# после commit, поэтому handlers могут сразу использовать order.id/status/text.
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def create_tables() -> None:
    # Создает таблицы по SQLAlchemy-моделям, если их еще нет.
    # Это удобно для первого этапа без отдельной системы миграций.
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    # Закрывает пул соединений при остановке бота.
    await engine.dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    # Универсальный async generator для получения сессии.
    # Сейчас handlers используют SessionLocal напрямую, но эту функцию удобно
    # оставить для будущего DI/middleware слоя.
    async with SessionLocal() as session:
        yield session
