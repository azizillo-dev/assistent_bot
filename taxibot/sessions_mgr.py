"""
Telethon session manager — har bir akkaunt uchun alohida session.
"""
import os
import logging
from typing import Dict

from telethon import TelegramClient

import config

logger = logging.getLogger(__name__)


def _fix_session_db(session_path: str):
    db_file = session_path if session_path.endswith(".session") else session_path + ".session"
    if os.path.exists(db_file):
        try:
            import sqlite3
            with sqlite3.connect(db_file) as conn:
                cols = [c[1] for c in conn.execute("PRAGMA table_info(sessions)").fetchall()]
                standard_cols = {"dc_id", "server_address", "port", "auth_key", "takeout_id"}
                for col in cols:
                    if col not in standard_cols:
                        try:
                            conn.execute(f"ALTER TABLE sessions DROP COLUMN {col}")
                        except Exception:
                            pass
                conn.commit()
        except Exception as e:
            logger.warning("Session db fix xatosi (%s): %s", db_file, e)


def _make_client(session_name: str) -> TelegramClient:
    path = os.path.join(config.SESSION_DIR, session_name)
    _fix_session_db(path)
    return TelegramClient(
        path,
        config.API_ID,
        config.API_HASH,
        device_model="Samsung Galaxy S24",
        system_version="Android 14",
        app_version="10.14.5",
        lang_code="uz",
        system_lang_code="uz",
    )


class SessionManager:
    def __init__(self):
        self._clients: Dict[str, TelegramClient] = {}

    async def get_client(self, session_name: str) -> TelegramClient:
        client = self._clients.get(session_name)
        if client is None:
            client = _make_client(session_name)
            self._clients[session_name] = client
        if not client.is_connected():
            await client.connect()
        return client

    async def fresh_client(self, session_name: str) -> TelegramClient:
        """Login uchun yangi client — eski session faylini o'chiradi."""
        import asyncio
        old = self._clients.pop(session_name, None)
        if old and old.is_connected():
            try:
                await old.disconnect()
            except Exception:
                pass
        await asyncio.sleep(0.3)

        session_path = os.path.join(config.SESSION_DIR, f"{session_name}.session")
        for p in (session_path, session_path + "-journal"):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception as e:
                    logger.warning("session fayl o'chirishda xato: %s", e)

        client = _make_client(session_name)
        self._clients[session_name] = client
        await client.connect()
        return client

    async def is_authorized(self, session_name: str) -> bool:
        try:
            client = await self.get_client(session_name)
            return await client.is_user_authorized()
        except Exception:
            return False

    async def get_me(self, session_name: str):
        try:
            client = await self.get_client(session_name)
            if not await client.is_user_authorized():
                return None
            return await client.get_me()
        except Exception:
            return None

    async def logout(self, session_name: str):
        client = self._clients.pop(session_name, None)
        if client:
            try:
                if client.is_connected():
                    await client.log_out()
            except Exception:
                pass
        session_path = os.path.join(config.SESSION_DIR, f"{session_name}.session")
        for p in (session_path, session_path + "-journal"):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    async def disconnect_all(self):
        for client in list(self._clients.values()):
            try:
                if client.is_connected():
                    await client.disconnect()
            except Exception:
                pass
        self._clients.clear()


# Global instance
session_manager = SessionManager()
