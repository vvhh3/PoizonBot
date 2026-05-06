"""Создание экземпляра aiogram Bot.

Bot создаётся один раз и переиспользуется во всех handlers для отправки
сообщений пользователям и в админ-чат.
"""

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.config import settings


bot = Bot(
    token=settings.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
