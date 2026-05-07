"""FSM-состояния aiogram.

FSM используется, когда бот ждёт следующий ответ пользователя или админа:
например адрес заявки, фото товара или цену от администратора.
"""

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
    # FSM-состояния админа.
    #
    # price:
    #   админ нажал "Одобрить", бот запомнил order_id и ждет цену заявки.
    #
    # approve_comment:
    #   цена уже введена и лежит во временном FSMContext, бот ждет комментарий
    #   администратора. Этот комментарий потом увидит пользователь в поле
    #   "Комментарий администратора".
    #
    # reject_reason:
    #   админ отклоняет заявку и бот ждет текст причины отказа.
    price = State()
    approve_comment = State()
    reject_reason = State()
