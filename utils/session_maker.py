"""Utility to automatically create Telegram .session files."""
import os
import io
import time
import zipfile
import asyncio
import sqlite3
import base64
import struct
import json
from pathlib import Path
from telethon import TelegramClient, functions, types
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError
from telethon.sessions import StringSession as TelethonStringSession

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
        self.code_sent_via = None  # "app" or "sms"
        self.user_info = {}  # id / first_name / last_name after sign-in

    async def connect_and_send_code(self) -> str:
        """Connect to TG and request the OTP. Returns the phone_code_hash."""
        await self.client.connect()
        try:
            sent_code = await self.client.send_code_request(self.phone_number)
            self.phone_code_hash = sent_code.phone_code_hash
            
            # Detect how the code was sent
            if isinstance(sent_code.type, types.auth.SentCodeTypeApp):
                self.code_sent_via = "app"
                # Try to force SMS delivery via ResendCodeRequest
                try:
                    await self.client(functions.auth.ResendCodeRequest(
                        phone_number=self.phone_number,
                        phone_code_hash=self.phone_code_hash
                    ))
                    self.code_sent_via = "sms"
                except Exception:
                    pass  # SMS delivery may not be available
            elif isinstance(sent_code.type, types.auth.SentCodeTypeSms):
                self.code_sent_via = "sms"
            else:
                self.code_sent_via = "sms"
                
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

        # Capture account info while still authorized
        try:
            me = await self.client.get_me()
            self.user_info = {
                "id": getattr(me, "id", None),
                "first_name": getattr(me, "first_name", "") or "",
                "last_name": getattr(me, "last_name", "") or "",
                "lang_code": getattr(me, "lang_code", "en") or "en",
                "premium": bool(getattr(me, "premium", False)),
                "username": getattr(me, "username", None),
            }
        except Exception:
            pass

        await self.client.disconnect()
        
        telethon_path = f"{self.session_path}.session"
        if not os.path.exists(telethon_path):
            raise SessionMakerError("Session file was not generated properly.")

        return telethon_path

    def build_package(self, password: str = None) -> str:
        """Build a reference-style delivery zip: <phone>.session + <phone>.json.
        Returns the path to the zip file."""
        telethon_path = f"{self.session_path}.session"
        if not os.path.exists(telethon_path):
            raise SessionMakerError("Session file not found; cannot build package.")

        phone = self.phone_number
        now = int(time.time())

        # Read dc_id + auth_key for mtp_data
        dc_id = 2
        auth_key = b""
        try:
            conn = sqlite3.connect(telethon_path)
            cur = conn.cursor()
            row = cur.execute("SELECT dc_id, auth_key FROM sessions LIMIT 1").fetchone()
            conn.close()
            if row:
                dc_id, auth_key = row[0], bytes(row[1])
        except Exception:
            pass

        mtp_payload = struct.pack("B", dc_id) + auth_key + struct.pack("B", 0)
        mtp_data = base64.urlsafe_b64encode(mtp_payload).decode()

        meta = {
            "session_file": phone,
            "phone": phone,
            "register_time": now,
            "app_id": int(config.API_ID),
            "api_id": int(config.API_ID),
            "app_hash": config.API_HASH,
            "api_hash": config.API_HASH,
            "system_version": "SDK 30",
            "sdk": "SDK 30",
            "app_version": "12.8.3 (69229)",
            "device_model": "Desktop",
            "device": "Desktop",
            "last_check_time": now,
            "first_name": self.user_info.get("first_name", ""),
            "last_name": self.user_info.get("last_name", ""),
            "sex": "",
            "lang_code": self.user_info.get("lang_code", "en"),
            "lang_pack": "android",
            "system_lang_code": "en",
            "system_lang_pack": "en",
            "two_fa": password or "",
            "twoFA": password or "",
            "device_token": "",
            "push_auth_key": "",
            "installer": "com.google.android.packageinstaller",
            "package_id": "org.telegram.messenger.web",
            "tz_offset": 0,
            "perf_cat": 1,
            "new_reg": False,
            "id": self.user_info.get("id"),
            "trust": False,
            "premium": self.user_info.get("premium", False),
            "mtp_data": mtp_data,
            "ab_group": "a",
            "session_string": self.session_string or "",
        }

        json_name = f"{phone}.json"
        session_name = f"{phone}.session"
        zip_path = os.path.join(self.session_dir, f"{phone}.zip")

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(json_name, json.dumps(meta, indent=2, ensure_ascii=False))
            zf.write(telethon_path, session_name)

        return zip_path

    def cleanup(self):
        """Remove the generated session files."""
        paths = [f"{self.session_path}.session"]
        if hasattr(self, "zip_path") and self.zip_path:
            paths.append(self.zip_path)
        for path in paths:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
