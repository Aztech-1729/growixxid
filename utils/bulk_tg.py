"""Bulk Telegram session purchase.

On TG confirm the bot asks how many sessions the buyer wants, then places that
many orders, starts one OTP poller per number (parallel auto-login) and each
poller delivers its own session zip as soon as it is ready.
"""
import asyncio
import logging

from aiogram import Router, F
from aiogram.enums import ButtonStyle
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.states import BulkState

router = Router()

MAX_QTY = 20

_EXECUTORS = {}


def register_executor(supplier: str, fn) -> None:
    _EXECUTORS[supplier] = fn


def _qty_kb():
    b = InlineKeyboardBuilder()
    for n in (1, 2, 3, 5, 10):
        b.button(text=str(n), callback_data=f"bulkqty:{n}", style=ButtonStyle.SUCCESS)
    b.button(text="✏️ Custom", callback_data="bulkqty:custom", style=ButtonStyle.PRIMARY)
    b.button(text="❌ Cancel", callback_data="bulkqty:cancel", style=ButtonStyle.DANGER)
    b.adjust(5, 1, 1)
    return b.as_markup()


async def ask_tg_quantity(call: CallbackQuery, state: FSMContext, ctx: dict) -> None:
    """Prompt the buyer for how many TG sessions they want."""
    await state.set_state(BulkState.waiting_for_qty)
    await state.set_data(ctx)
    try:
        await call.message.edit_text(
            f"🎟 <b>Bulk Telegram Sessions</b>\n\n"
            f"{ctx.get('service_name', 'Telegram')} · {ctx.get('country_name', '')}\n"
            f"Price: <b>{ctx.get('display_price', '')}</b> per session\n\n"
            f"How many sessions do you want to buy? (1–{MAX_QTY})",
            parse_mode="HTML", reply_markup=_qty_kb())
    except Exception:
        pass


def src_info(src):
    """Normalize CallbackQuery / Message -> (bot, user_id, chat_id)."""
    if isinstance(src, CallbackQuery):
        return src.bot, src.from_user.id, src.message.chat.id
    return src.bot, src.from_user.id, src.chat.id


async def send_msg(src, text, **kw):
    if isinstance(src, CallbackQuery):
        return await src.message.answer(text, **kw)
    return await src.answer(text, **kw)


def _parse_qty(text):
    if not text:
        return None
    try:
        q = int(text.strip())
    except ValueError:
        return None
    if q < 1 or q > MAX_QTY:
        return None
    return q


@router.callback_query(F.data.startswith("bulkqty:"))
async def cb_bulk_qty(call: CallbackQuery, state: FSMContext):
    await call.answer()
    choice = call.data.split(":", 1)[1]
    if choice == "cancel":
        await state.clear()
        try:
            await call.message.edit_text("❌ Purchase cancelled.", reply_markup=None)
        except Exception:
            pass
        return
    if choice == "custom":
        await call.message.answer("📝 Send the number of sessions (e.g. 1, 5, 10):")
        return
    try:
        qty = int(choice)
    except ValueError:
        return
    await _run_bulk(call, state, qty)


@router.message(BulkState.waiting_for_qty)
async def msg_bulk_qty(message: Message, state: FSMContext):
    qty = _parse_qty(message.text)
    if qty is None:
        await message.answer(f"❌ Send a valid number between 1 and {MAX_QTY}.")
        return
    await _run_bulk(message, state, qty)


async def _run_bulk(src, state: FSMContext, qty: int):
    ctx = await state.get_data()
    await state.clear()
    fn = _EXECUTORS.get(ctx.get("supplier"))
    if not fn:
        await send_msg(src, "❌ Session expired. Please start again.")
        return
    try:
        await fn(src, ctx, qty)
    except Exception:
        logging.exception("Bulk TG purchase failed")
        await send_msg(src, "❌ Bulk purchase failed. Please try again.")
