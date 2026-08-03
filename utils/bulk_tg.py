"""Bulk Telegram session purchase.

Flow for TG accounts:
  1. Buyer picks a country -> bot asks "how many sessions?" (1-20, quick picks)
  2. Buyer picks a number -> bot shows a confirm card with TOTAL price + Buy button
  3. Buyer taps Buy -> N orders placed simultaneously, N pollers run in parallel,
     each auto-login builds a session zip and delivers it.
"""
import asyncio
import json
import logging
import os
import time
import zipfile

from aiogram import Router, F
from aiogram.enums import ButtonStyle
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.states import BulkState

router = Router()

MAX_QTY = 20

_EXECUTORS = {}


class SessionCollector:
    """Collects built session files from parallel pollers and ships ONE zip.

    Each parallel poller calls ``add()`` with its .session path + metadata;
    when every order is accounted for, a single zip containing all
    ``<phone>.session`` + ``<phone>.json`` files is sent to the buyer.
    """

    def __init__(self, bot, chat_id, total: int, service_name: str = "Telegram"):
        self.bot = bot
        self.chat_id = chat_id
        self.total = total
        self.service_name = service_name
        self.lock = asyncio.Lock()
        self.files = []  # (session_path, phone)
        self.metas = []  # meta dicts (for .json files)
        self.notes = []  # human-readable per-session lines
        self.done = 0
        self.failed = 0
        self.finished = False

    async def add(self, session_path, meta: dict, note: str = "") -> None:
        async with self.lock:
            self.files.append((session_path, meta.get("phone", "")))
            self.metas.append(meta)
            if note:
                self.notes.append(note)
            self.done += 1
            if self.done + self.failed >= self.total:
                await self._finish()

    async def fail(self, note: str = "") -> None:
        async with self.lock:
            if note:
                self.notes.append(note)
            self.failed += 1
            if self.done + self.failed >= self.total:
                await self._finish()

    async def _finish(self) -> None:
        if self.finished:
            return
        self.finished = True
        try:
            zip_path = os.path.join("sessions", f"bulk_{int(time.time())}.zip")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for session_path, phone in self.files:
                    if os.path.exists(session_path):
                        zf.write(session_path, f"{phone}.session")
                for meta in self.metas:
                    phone = meta.get("phone", "")
                    zf.writestr(f"{phone}.json", json.dumps(meta, indent=2, ensure_ascii=False))

            caption = (
                f"🎉 <b>Bulk Sessions Ready!</b>\n\n"
                f"{self.done}/{self.total} sessions in <b>one zip</b>\n\n"
                + "\n".join(self.notes)
            )
            if self.failed:
                caption += f"\n\n⚠️ {self.failed} session(s) failed."

            from aiogram.types import FSInputFile
            await self.bot.send_document(
                chat_id=self.chat_id,
                document=FSInputFile(zip_path),
                caption=caption,
                parse_mode="HTML",
            )
        except Exception:
            logging.exception("SessionCollector failed to ship zip")


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


def _confirm_kb(qty: int, total_str: str):
    b = InlineKeyboardBuilder()
    b.button(text=f"✅ Buy {qty} sessions ({total_str})", callback_data="bulkbuy:confirm",
             style=ButtonStyle.SUCCESS)
    b.button(text="❌ Cancel", callback_data="bulkqty:cancel", style=ButtonStyle.DANGER)
    b.adjust(1)
    return b.as_markup()


async def ask_tg_quantity(call: CallbackQuery, state: FSMContext, ctx: dict) -> None:
    """Step 1: prompt the buyer for how many TG sessions they want."""
    ctx["chat_id"] = call.message.chat.id
    ctx["msg_id"] = call.message.message_id
    await state.set_state(BulkState.waiting_for_qty)
    await state.set_data(ctx)
    text = (
        f"🎟 <b>Bulk Telegram Sessions</b>\n\n"
        f"{ctx.get('service_name', 'Telegram')} · {ctx.get('country_name', '')}\n"
        f"Price: <b>{ctx.get('display_price', '')}</b> per session\n\n"
        f"How many sessions do you want to buy? (1–{MAX_QTY})"
    )
    try:
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=_qty_kb())
    except Exception as e:
        # If the old message can't be edited, send a fresh prompt instead of
        # silently doing nothing (which looked like a dead button).
        try:
            new_msg = await call.message.answer(text, parse_mode="HTML", reply_markup=_qty_kb())
            # Point future edits at the NEW message so quantity taps work.
            ctx["chat_id"] = new_msg.chat.id
            ctx["msg_id"] = new_msg.message_id
            await state.set_data(ctx)
        except Exception:
            import logging
            logging.exception("ask_tg_quantity: could not show quantity prompt")


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


def _fmt_total(ctx: dict, qty: int) -> str:
    inr = float(ctx.get("inr", 0))
    total = inr * qty
    if "$" in ctx.get("display_price", ""):
        return f"${total:.2f}"
    return f"₹{total:.2f}"


async def _goto_confirm(src, state: FSMContext, qty: int):
    """Step 2: show confirm card with TOTAL price + Buy button."""
    ctx = await state.get_data()
    ctx["qty"] = qty
    await state.set_data(ctx)
    total_str = _fmt_total(ctx, qty)
    text = (
        f"🧾 <b>Confirm Bulk Order</b>\n\n"
        f"{ctx.get('service_name', 'Telegram')} · {ctx.get('country_name', '')}\n"
        f"Price: {ctx.get('display_price', '')} × {qty}\n"
        f"<b>Total: {total_str}</b>"
    )
    try:
        bot = src.bot
        await bot.edit_message_text(
            text, chat_id=ctx["chat_id"], message_id=ctx["msg_id"],
            parse_mode="HTML", reply_markup=_confirm_kb(qty, total_str))
    except Exception as e:
        import logging
        logging.exception("_goto_confirm: edit failed (qty=%s): %s", qty, e)
        try:
            await send_msg(src, text, parse_mode="HTML", reply_markup=_confirm_kb(qty, total_str))
        except Exception:
            logging.exception("_goto_confirm: fallback send also failed")


@router.callback_query(F.data == "bulkbuy:confirm")
async def cb_bulk_confirm(call: CallbackQuery, state: FSMContext):
    await call.answer("🛒 Purchasing...")
    await _run_bulk(call, state)


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
    await _goto_confirm(call, state, qty)


@router.message(BulkState.waiting_for_qty)
async def msg_bulk_qty(message: Message, state: FSMContext):
    qty = _parse_qty(message.text)
    if qty is None:
        await message.answer(f"❌ Send a valid number between 1 and {MAX_QTY}.")
        return
    await _goto_confirm(message, state, qty)


async def _run_bulk(src, state: FSMContext):
    ctx = await state.get_data()
    qty = ctx.get("qty")
    await state.clear()
    if not qty:
        await send_msg(src, "❌ Session expired. Please start again.")
        return
    fn = _EXECUTORS.get(ctx.get("supplier"))
    if not fn:
        await send_msg(src, "❌ Session expired. Please start again.")
        return
    try:
        await fn(src, ctx, qty)
    except Exception:
        logging.exception("Bulk TG purchase failed")
        await send_msg(src, "❌ Bulk purchase failed. Please try again.")
