# Telegram-бот для заявок на товары

Python-бот на aiogram 3 для оформления заявок на заказ товаров. Заявки хранятся в PostgreSQL, бот работает через polling.

## Стек

- Python 3.11+
- aiogram 3
- PostgreSQL
- SQLAlchemy async
- asyncpg
- pydantic-settings
- Railway

## Структура

```text
src/
  main.py
  config.py
  database.py
  bot/
  handlers/
  keyboards/
  services/
  repositories/
  models/
  states/
```

## Локальный запуск

Создайте и активируйте виртуальное окружение:

```bash
python -m venv .venv
source .venv/bin/activate
```

Для Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Установите зависимости:

```bash
pip install -r requirements.txt
```

Создайте `.env` по примеру `.env.example`:

```env
BOT_TOKEN=token_from_botfather
ADMIN_CHAT_ID=-1001234567890
DATABASE_URL=postgresql://user:password@localhost:5432/poizon_bot
ADMIN_USERNAME=admin_username
```

Для тестов вне Railway `DATABASE_URL` можно не указывать. Тогда бот попробует подключиться к локальному PostgreSQL:

```text
postgresql://postgres:postgres@localhost:5432/poizon_bot
```

В этом случае локально должна существовать база `poizon_bot`, пользователь `postgres` с паролем `postgres`, и PostgreSQL должен быть запущен.

Запустите бота из папки `bot`:

```bash
python -m src.main
```

Таблицы создаются автоматически при старте.

## Railway

`Procfile` — это файл-инструкция для Railway/Heroku-подобных платформ. Он говорит платформе, какой процесс нужно поднять после деплоя.

В этом проекте `Procfile` содержит:

```text
worker: python -m src.main
```

`worker` означает фоновый процесс без HTTP-сервера. Это подходит для Telegram-бота на polling, потому что он сам постоянно опрашивает Telegram API.

1. Создайте PostgreSQL service в Railway.
2. Добавьте переменные окружения:
   - `BOT_TOKEN`
   - `ADMIN_CHAT_ID`
   - `DATABASE_URL`
   - `ADMIN_USERNAME`
3. Убедитесь, что Railway запускает проект из папки `bot`.
4. Procfile уже содержит команду:

```text
worker: python -m src.main
```

## Сценарий работы

Пользователь нажимает `Оформить заявку`, бот создаёт черновик со статусом `draft` и показывает меню заявки. Поля редактируются через FSM и сразу сохраняются в PostgreSQL.

После отправки бот проверяет обязательные поля: адрес, тип товара, размер, ссылка или фото. Если всё заполнено, заявка получает статус `sent_to_admin` и отправляется в админ-чат.

Администратор может одобрить заявку, указать цену, отклонить заявку с причиной или связаться с пользователем. После одобрения пользователь получает цену и кнопки оплаты, отказа и связи с админом.

Оплата пока реализована как заглушка в `src/services/payment_service.py`.
