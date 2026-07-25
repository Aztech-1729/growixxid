"""Utility to automatically create Telegram .session files."""
import os
import asyncio
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError

from core.config import config


class SessionMakerError(Exception):
    pass


class AutoSessionManager:
    def __init__(self, phone_number: str):
        self.phone_number = phone_number.replace("+", "").strip()
        self.session_name = f"sess_{self.phone_number}"
        self.session_dir = "sessions"
        os.makedirs(self.session_dir, exist_ok=True)
        self.session_path = os.path.join(self.session_dir, self.session_name)
        
        if not config.API_ID or not config.API_HASH:
            raise SessionMakerError("API_ID and API_HASH are not configured in .env")
            
        self.client = TelegramClient(
            self.session_path,
            int(config.API_ID),
            config.API_HASH,
            device_model="Desktop",
            app_version="1.0",
        )
        self.phone_code_hash = None
        self.session_string = None

    async def connect_and_send_code(self) -> str:
        """Connect to TG and request the OTP. Returns the phone_code_hash."""
        await self.client.connect()
        try:
            sent_code = await self.client.send_code_request(self.phone_number)
            self.phone_code_hash = sent_code.phone_code_hash
            return self.phone_code_hash
        except Exception as e:
            await self.client.disconnect()
            raise SessionMakerError(f"Failed to request code from Telegram: {e}")

    async def sign_in_and_get_file(self, otp: str, password: str = None) -> str:
        """Submit OTP (and optionally 2FA password) and return the path to the completed .session file."""
        if not self.phone_code_hash:
            raise SessionMakerError("Must call connect_and_send_code first.")
            
        try:
            await self.client.sign_in(self.phone_number, code=otp, phone_code_hash=self.phone_code_hash)
        except SessionPasswordNeededError:
            if password:
                try:
                    await asyncio.sleep(2)
                    await self.client.sign_in(password=password)
                except Exception as e:
                    await self.client.disconnect()
                    raise SessionMakerError(f"Invalid 2FA Password provided by supplier: {e}")
            else:
                await self.client.disconnect()
                raise SessionMakerError("2FA Password is required for this number, but none was provided by the supplier.")
        except (PhoneCodeInvalidError, PhoneCodeExpiredError) as e:
            await self.client.disconnect()
            raise SessionMakerError(f"OTP is invalid or expired: {e}")
        except Exception as e:
            await self.client.disconnect()
            raise SessionMakerError(f"Failed to sign in: {e}")

        # Successfully signed in, disconnect to ensure DB is written
        await self.client.disconnect()
        
        # Telethon creates the file at `sessions/sess_123456.session`
        file_path = f"{self.session_path}.session"
        if not os.path.exists(file_path):
            raise SessionMakerError("Session file was not generated properly.")
            
        return file_path

    def cleanup(self):
        """Remove the generated session file if it exists."""
        file_path = f"{self.session_path}.session"
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
