import asyncio
import logging

from aiogram import Dispatcher
from aiogram.types import ErrorEvent

from src.bot.loader import bot
from src.database import create_tables, dispose_engine
from src.handlers import admin_orders, start, user_orders


logger = logging.getLogger(__name__)


async def main() -> None:
    # Базовая настройка логов. Railway тоже читает stdout/stderr,
    # поэтому обычный logging подходит и для локального запуска, и для deploy.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # На первом этапе используем простое автосоздание таблиц.
    # Для production-проекта позже можно заменить это на Alembic-миграции.
    await create_tables()

    # Dispatcher принимает входящие обновления Telegram и передает их в handlers.
    # Роутеры разделены по зонам ответственности: старт, пользовательские заявки,
    # админские действия по заявкам.
    dp = Dispatcher()
    dp.include_router(start.router)
    dp.include_router(user_orders.router)
    dp.include_router(admin_orders.router)

    # Глобальный обработчик ошибок aiogram. Он не чинит ошибку сам,
    # но пишет traceback в логи и не оставляет исключения совсем без контекста.
    @dp.errors()
    async def errors_handler(event: ErrorEvent) -> bool:
        logger.exception("Unhandled update error", exc_info=event.exception)
        return True

    try:
        # Бот работает через polling, поэтому webhook удаляем.
        # drop_pending_updates=True сбрасывает старые сообщения, накопившиеся
        # пока бот был выключен.
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        # Корректно закрываем HTTP-сессию Telegram Bot API и соединения с БД.
        await bot.session.close()
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
