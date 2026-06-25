from aiogram.fsm.state import State, StatesGroup


class AuthStates(StatesGroup):
    waiting_for_code = State()


class BroadcastStates(StatesGroup):
    waiting_for_content = State()
    confirm = State()


class AskStates(StatesGroup):
    choosing_anonymity = State()
    waiting_for_question = State()


class AnswerStates(StatesGroup):
    waiting_for_answer = State()


class DirectMessageStates(StatesGroup):
    waiting_for_recipient = State()
    waiting_for_content = State()
    confirm = State()


class GroupBroadcastStates(StatesGroup):
    waiting_for_content = State()
    confirm = State()
