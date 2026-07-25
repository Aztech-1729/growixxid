"""Utility to automatically create Telegram .session files."""
import os
import asyncio
import sqlite3
import base64
import struct
from pathlib import Path
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError
from telethon.sessions import StringSession as TelethonStringSession

from core.config import config


class SessionMakerError(Exception):
    pass


def _telethon_to_pyrogram_string(telethon_session_path: str) -> str | None:
    """Convert a Telethon .session file to a Pyrogram-compatible session string."""
    try:
        conn = sqlite3.connect(telethon_session_path)
        cursor = conn.cursor()
        cursor.execute("SELECT dc_id, auth_key FROM sessions LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        dc_id, auth_key = row
        payload = struct.pack("B", dc_id) + bytes(auth_key) + struct.pack("B", 0)
        return base64.urlsafe_b64encode(payload).decode()
    except Exception:
        return None


def _create_pyrogram_session_file(telethon_session_path: str, output_path: str) -> str | None:
    """Create a Pyrogram-compatible .session file from a Telethon .session file.
    Returns the export session string, or None on failure."""
    try:
        from pyrogram.storage import FileStorage

        conn = sqlite3.connect(telethon_session_path)
        cursor = conn.cursor()
        cursor.execute("SELECT dc_id, auth_key FROM sessions LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        dc_id, auth_key = row

        name = Path(output_path).stem
        workdir = Path(output_path).parent
        workdir.mkdir(parents=True, exist_ok=True)

        async def _make():
            fs = FileStorage(name, workdir)
            await fs.open()
            await fs.dc_id(dc_id)
            await fs.auth_key(bytes(auth_key))
            await fs.test_mode(False)
            await fs.api_id(int(config.API_ID))
            await fs.user_id(0)
            await fs.save()
            pg_string = await fs.export_session_string()
            await fs.close()
            return pg_string

        return asyncio.run(_make())
    except Exception:
        return None


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
        self.pyrogram_string = None
        self.pyrogram_session_path = None

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

        # Export session string (Telethon format)
        self.session_string = TelethonStringSession.save(self.client.session)
        
        await self.client.disconnect()
        
        telethon_path = f"{self.session_path}.session"
        if not os.path.exists(telethon_path):
            raise SessionMakerError("Session file was not generated properly.")
        
        # Also generate Pyrogram-compatible session
        try:
            pyro_name = f"pyro_{self.session_name}"
            pyro_path = os.path.join(self.session_dir, f"{pyro_name}.session")
            pg_string = _create_pyrogram_session_file(telethon_path, pyro_path)
            if pg_string:
                self.pyrogram_string = pg_string
                self.pyrogram_session_path = pyro_path
        except Exception:
            pass  # Non-critical; Telethon session file is still available
            
        return telethon_path

    def cleanup(self):
        """Remove the generated session files."""
        for path in [f"{self.session_path}.session", self.pyrogram_session_path] if hasattr(self, 'pyrogram_session_path') else [f"{self.session_path}.session"]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
