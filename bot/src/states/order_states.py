from aiogram.fsm.state import State, StatesGroup


class OrderForm(StatesGroup):
    # FSM-состояния пользователя при заполнении черновика заявки.
    # Каждая inline-кнопка переводит пользователя в одно из этих состояний,
    # следующий ответ сохраняется в PostgreSQL и состояние очищается.
    address = State()
    product_type = State()
    size = State()
    link = State()
    photo = State()
    comment = State()


class AdminOrderForm(StatesGroup):
    # FSM-состояния админа. После нажатия "Одобрить" бот ждет цену,
    # после "Отклонить" ждет текст причины отказа.
    price = State()
    reject_reason = State()
