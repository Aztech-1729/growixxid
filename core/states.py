from aiogram.fsm.state import State, StatesGroup

class SearchState(StatesGroup):
    waiting_for_service_query = State()
    waiting_for_order_query = State()
    waiting_for_ctry_query = State()
    waiting_for_grz_svc_query = State()
    waiting_for_grz_ctry_query = State()

class PayState(StatesGroup):
    waiting_for_amount = State()
    waiting_for_crypto_coin = State()

class AdminState(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_balance_change = State()
    waiting_for_margin = State()
