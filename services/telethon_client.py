"""Optional Telethon (MTProto) client.

The main bot runs on the Bot API via aiogram. These MTProto app credentials
(API_ID / API_HASH) enable Telethon for capabilities the Bot API cannot provide,
such as acting as a user (userbot), performing full Telegram account
registration with the OTP/password from the provider, or calling raw API
methods. The client is constructed on demand and only connects when started.

Example (admin-only):
    client = await client_as_bot()
    me = await client.get_me()
    # ... do MTProto work ...
    await client.disconnect()
"""
from telethon import TelegramClient

from core.config import config

# Local session file (safe to keep in the workspace).
SESSION = "growixx_session"


def make_client() -> TelegramClient:
    """Return a TelegramClient wired with the app credentials."""
    if not config.API_ID or not config.API_HASH:
        raise RuntimeError("API_ID / API_HASH are missing in .env")
    return TelegramClient(SESSION, config.API_ID, config.API_HASH)


async def client_as_bot() -> TelegramClient:
    """Start the client logged in as the bot (uses BOT_TOKEN)."""
    client = make_client()
    await client.start(bot_token=config.BOT_TOKEN)
    return client
