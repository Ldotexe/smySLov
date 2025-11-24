from aiogram.fsm.state import State, StatesGroup

class GameStates(StatesGroup):
    in_lobby = State()
    adding_cards = State()
    writing_answers = State()
    scoring = State()