"""Entrypoint for the GROWIXX Acc Store Bot."""
import asyncio

from aiohttp import web
from aiogram import Bot, Dispatcher

from config import config
from db import _client as mongo_client, init_indexes
from handlers import setup_handlers
from middlewares import ForceJoinMiddleware
from suppliers import tigersms
from vnhotp import vnhotp
from web import make_app, set_bot


async def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is missing in .env")
    if not config.MONGO_URI:
        raise SystemExit("MONGO_URI is missing in .env")
    if not config.API_KEY:
        raise SystemExit("VNHOTP_API_KEY is missing in .env")

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()

    # Force users to join the channel before using the bot
    dp.update.middleware(ForceJoinMiddleware())
    setup_handlers(dp)

    await init_indexes()

    # Razorpay webhook server (same event loop as the bot)
    set_bot(bot)
    app = make_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.WEB_PORT)
    await site.start()
    print(f"✅ Webhook server listening on :{config.WEB_PORT}")

    print("✅ GROWIXX bot started. Polling...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await vnhotp.close()
        await tigersms.close()
        mongo_client.close()


if __name__ == "__main__":
    asyncio.run(main())
