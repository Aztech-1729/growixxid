"""Central configuration loaded from .env (python-dotenv)."""
import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    BOT_USERNAME = os.getenv("BOT_USERNAME", "Growixx_otp_bot")
    API_ID = int(os.getenv("API_ID", "0"))
    API_HASH = os.getenv("API_HASH", "")

    # Primary provider
    API_KEY = os.getenv("VNHOTP_API_KEY", "")
    API_BASE = os.getenv("VNHOTP_BASE", "https://api.vnhotp.com").rstrip("/")

    # Alternate suppliers
    TIGERSMS_API_KEY = os.getenv("TIGERSMS_API_KEY", "")
    GRIZZLY_API_KEY = os.getenv("GRIZZLY_API_KEY", "")

    MONGO_URI = os.getenv("MONGO_URI", "")
    MONGO_DB = os.getenv("MONGO_DB", "growixxstore")

    FORCE_JOIN_CHANNEL = os.getenv("FORCE_JOIN_CHANNEL", "Growixx_store").lstrip("@")
    ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

    OTP_POLL_INTERVAL = float(os.getenv("OTP_POLL_INTERVAL", "5"))
    OTP_TIMEOUT = int(os.getenv("OTP_TIMEOUT", "180"))
    CURRENCY = os.getenv("CURRENCY", "$")
    CURRENCY_INR = os.getenv("CURRENCY_INR", "₹")

    # Razorpay / webhook
    RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
    RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    PAYMENT_BASE_URL = os.getenv("PAYMENT_BASE_URL", "")
    USD_INR_RATE = float(os.getenv("USD_INR_RATE", "83.0"))
    WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
    START_IMAGE = os.getenv("START_IMAGE", "start.jpg")


    @property
    def channel_link(self) -> str:
        return f"https://t.me/{self.FORCE_JOIN_CHANNEL}"

    @property
    def logo_domains(self) -> dict:
        return {
            "tg": "telegram.org",
            "wa": "whatsapp.com",
            "wb": "wechat.com",
            "vk": "vk.com",
            "ok": "ok.ru",
            "go": "google.com",
            "ya": "yandex.com",
            "av": "avito.ru",
            "ma": "mail.ru",
            "fb": "facebook.com",
            "ub": "uber.com",
            "sn": "snapchat.com",
            "vi": "viber.com",
            "me": "messenger.com",
            "sk": "skype.com",
        }

    def logo_url(self, service_key: str) -> str | None:
        domain = self.logo_domains.get(service_key)
        if domain:
            return f"https://logo.debounce.com/{domain}"
        return None


config = Config()
