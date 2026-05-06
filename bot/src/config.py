from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Все значения берутся из переменных окружения.
    # Локально pydantic-settings дополнительно читает файл .env.
    bot_token: str = Field(alias="BOT_TOKEN")
    admin_chat_id: int = Field(alias="ADMIN_CHAT_ID")
    database_url: str = Field(alias="DATABASE_URL")
    admin_username: str = Field(default="admin_username", alias="ADMIN_USERNAME")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def sqlalchemy_database_url(self) -> str:
        # Railway и некоторые хостинги часто выдают DATABASE_URL в формате
        # postgresql:// или postgres://. Для SQLAlchemy async нужен драйвер
        # postgresql+asyncpg://, поэтому нормализуем URL в одном месте.
        if self.database_url.startswith("postgres://"):
            return self.database_url.replace("postgres://", "postgresql+asyncpg://", 1)
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self.database_url


# Единственный объект настроек, который импортируется в остальных модулях.
settings = Settings()
