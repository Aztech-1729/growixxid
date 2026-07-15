"""Force-join middleware: requires users to be members of the channel."""
import time

from aiogram import BaseMiddleware
from aiogram.enums import ChatMemberStatus
from aiogram.types import CallbackQuery, Message

from config import config
from keyboards import kb_join


class ForceJoinMiddleware(BaseMiddleware):
    def __init__(self):
        self.cache: dict = {}
        self.ttl = 60  # seconds

    async def __call__(self, handler, event, data):
        bot = data["bot"]
        user = data.get("event_from_user")

        # No user context (e.g. chat_member updates) -> let through
        if user is None:
            return await handler(event, data)

        # Admins are exempt so the owner can always operate
        if user.id in config.ADMIN_IDS:
            return await handler(event, data)

        # Always let the re-check callback run so join verification works
        if isinstance(event, CallbackQuery) and event.data == "join_check":
            return await handler(event, data)

        now = time.time()
        cached = self.cache.get(user.id)
        if cached and now - cached[1] < self.ttl and cached[0]:
            return await handler(event, data)

        try:
            member = await bot.get_chat_member("@" + config.FORCE_JOIN_CHANNEL, user.id)
            is_member = member.status not in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED)
        except Exception as e:
            # Could not verify membership. Most common cause: the bot is not an
            # administrator of the channel (so Telegram returns
            # "member list is inaccessible"). Fail OPEN so users are never
            # permanently trapped at the join screen; the operator should make
            # @%s an admin for the gate to actually enforce.
            import logging
            logging.warning(
                "ForceJoin: cannot verify membership in @%s (%s). Failing open.",
                config.FORCE_JOIN_CHANNEL, e,
            )
            return await handler(event, data)

        if is_member:
            self.cache[user.id] = (True, now)
        else:
            self.cache.pop(user.id, None)

        if not is_member:
            await self._ask(event, bot)
            return

        return await handler(event, data)

    async def _ask(self, event, bot) -> None:
        text = (
            "🔒 <b>Join required</b>\n\n"
            f"Please join our channel to use the bot:\n{config.channel_link}"
        )
        kb = kb_join()
        if isinstance(event, Message):
            await event.answer(text, reply_markup=kb, parse_mode="HTML")
        elif isinstance(event, CallbackQuery):
            await event.answer()
            try:
                await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                await bot.send_message(event.from_user.id, text, reply_markup=kb, parse_mode="HTML")
