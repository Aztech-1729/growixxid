# 𝙂𝙍𝙊𝙒𝙄𝙓𝙓 !! Acc Store Bot

Async Telegram/WhatsApp **account/number store bot** that sells Telegram &
WhatsApp activation numbers/OTPs via number-activation supplier APIs, with
force-join gating, MongoDB storage (indexed), Bot API 9.4 styled buttons
(primary/success/danger on every button), background OTP polling, and a
Razorpay auto-payment/wallet system.

## Suppliers (all wired)
| Supplier | Button | Numbers | Telegram | WhatsApp | Notes |
|---|---|---|---|---|---|
| **VNHOTP** (primary) | Telegram / WhatsApp / WhatsApp 2 | global | ✅ `/tg/*` | ✅ `/wp/*`, `/wp2/*` | funded ($10.33) |
| **TigerSMS** | 🐯 TigerSMS (India ₹10) | global | ✅ | ✅ | cheapest India TG ~₹10; fund to enable |

Both number suppliers are driven through one generic catalog/order/OTP flow
(`handlers/alt.py` + `suppliers.py`), so adding a new provider is just a new
adapter + a registry entry.

## Stack
- **aiogram 3** — Bot API, async; native `ButtonStyle` (primary/success/danger)
- **Motor** — async MongoDB (users, orders, settings, transactions + indexes)
- **httpx** — async HTTP to all supplier APIs (retries + backoff)
- **aiohttp** — Razorpay webhook server (same event loop as the bot)
- **razorpay** — hosted payment links + webhook credit
- **python-dotenv** — config from `.env`

## Setup
```bash
cd growixx_bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# fill .env with real values, then:
python main.py
```

## Config (.env)
| Key | Purpose |
|---|---|
| `BOT_TOKEN` / `BOT_USERNAME` | Telegram bot token + username |
| `VNHOTP_API_KEY` / `VNHOTP_BASE` | Primary provider key + base URL |
| `TIGERSMS_API_KEY` | TigerSMS key (SMS-Activate style) |
| `MONGO_URI` / `MONGO_DB` | MongoDB connection + DB name |
| `FORCE_JOIN_CHANNEL` | Channel username users must join |
| `ADMIN_IDS` | Comma-separated admin Telegram IDs |
| `OTP_POLL_INTERVAL` / `OTP_TIMEOUT` | OTP polling tuning (seconds) |
| `CURRENCY` / `CURRENCY_INR` | Display symbols |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | Razorpay live keys |
| `RAZORPAY_WEBHOOK_SECRET` | Webhook HMAC secret (empty = tolerant mode) |
| `PAYMENT_BASE_URL` / `USD_INR_RATE` / `WEB_PORT` | Payment page, FX rate, web port |

## Features
- 🔒 **Force-join**: users must be in the channel (fails OPEN if the bot is not
  a channel admin, so users are never trapped — make the bot admin to enforce).
- 🛒 **Browse Numbers**: VNHOTP (TG / WA / WA2) + TigerSMS, live country list & prices (INR).
- ✅ **Buy flow**: styled confirm → real `place_order`/`getNumber` → background OTP poll.
- 📲 **Auto OTP delivery**: the message updates automatically when the code arrives.
- 💸 **Refunds**: cancellable supplier orders can be cancelled & refunded
  (Telegram cannot be cancelled on VNHOTP/TigerSMS; TigerSMS WA can).
- 📜 **Order history**: persisted in MongoDB.
- 👑 **Admin**: `/admin` (live balance for ALL suppliers + stats), `/broadcast <text>`.
- 💰 **Wallet / Razorpay**: Add Funds (₹1/10/50/100/500) → hosted payment link
  → wallet auto-credited on `payment_link.paid` webhook.

## Important notes
- Supplier APIs are **poll-only** (no provider webhooks) → OTP is fetched by
  polling until delivered or the timeout expires.
- **Fund each supplier** before placing real orders (VNHOTP funded; TigerSMS needs funding).
- **Telegram orders cannot be cancelled/refunded** on VNHOTP/TigerSMS.
- Razorpay webhook needs a public URL (`growix.aegiscloud.in/webhook/razorpay`)
  → only fires on a public deployment, not the sandbox.
