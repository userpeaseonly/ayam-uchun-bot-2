from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):
    waiting_for_test_input = State()


class StudentStates(StatesGroup):
    waiting_for_test_code = State()
    waiting_for_answers = State()
    confirming_submission = State()
