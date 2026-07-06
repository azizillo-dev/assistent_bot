"""
Telegram sender — Telethon orqali xabar yuboradi.
Har bir xabarga ko'rinmas Unicode belgilar qo'shiladi (spam filtriga emas).
Shrift uslublari qo'llab-quvvatlanadi.
"""
import asyncio
import logging
import random

from telethon.errors import (
    FloodWaitError,
    SlowModeWaitError,
    ChatWriteForbiddenError,
    ChannelPrivateError,
    UserBannedInChannelError,
    AuthKeyUnregisteredError,
    UserDeactivatedBanError,
    UserDeactivatedError,
    RPCError,
    ChatAdminRequiredError,
)

from sessions_mgr import session_manager

logger = logging.getLogger(__name__)

# Ko'rinmas zero-width belgilar
_ZW_CHARS = [
    "\u200b",  # zero width space
    "\u200c",  # zero width non-joiner
    "\u200d",  # zero width joiner
    "\u2060",  # word joiner
    "\ufeff",  # zero width no-break space
]

# ── Shrift uslublari ──────────────────────────────────────────────────────────

FONT_STYLES = {
    "none":       ("", ""),           # Oddiy matn
    "bold":       ("<b>", "</b>"),    # Qalin
    "italic":     ("<i>", "</i>"),    # Qiyshiq
    "mono":       ("<code>", "</code>"),  # Monospace
    "underline":  ("<u>", "</u>"),    # Tagiga chizilgan
    "strike":     ("<s>", "</s>"),    # O'chirilgan
    "bold_italic":("<b><i>", "</i></b>"),  # Qalin qiyshiq
}

FONT_LABELS = {
    "none":        "📝 Oddiy",
    "bold":        "𝗕 Qalin (Bold)",
    "italic":      "𝘐 Qiyshiq (Italic)",
    "mono":        "𝙼 Monospace",
    "underline":   "U̲ Tagiga chizilgan",
    "strike":      "S̶ O'chirilgan",
    "bold_italic": "𝙱𝙸 Qalin+Qiyshiq",
}


def apply_font(text: str, font_style: str) -> str:
    """Xabarga HTML shrift tegi qo'shadi."""
    style = FONT_STYLES.get(font_style, ("", ""))
    if style[0]:
        return f"{style[0]}{text}{style[1]}"
    return text


def _make_invisible_watermark(length: int = 8) -> str:
    return "".join(random.choices(_ZW_CHARS, k=length))


def _invisibilize(text: str) -> str:
    wm = _make_invisible_watermark(random.randint(6, 12))
    lines = text.split("\n")
    result_lines = []
    for i, line in enumerate(lines):
        if i > 0 and i % 3 == 0:
            result_lines.append(line + _make_invisible_watermark(3))
        else:
            result_lines.append(line)
    return "\n".join(result_lines) + wm


def _normalize_target(identifier: str):
    v = identifier.strip()
    if v.startswith("@"):
        return v
    try:
        return int(v)
    except ValueError:
        return v


class SendError(Exception):
    def __init__(self, reason: str, retryable: bool = False, wait_seconds: int = 0):
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable
        self.wait_seconds = wait_seconds


async def send_message(
    session_name: str,
    group_identifier: str,
    text: str,
    font_style: str = "none",
) -> tuple[int, int]:
    """
    Xabar yuboradi. (chat_id, message_id) qaytaradi. SendError — xato.
    """
    client = await session_manager.get_client(session_name)
    if not await client.is_user_authorized():
        raise SendError("Akkaunt avtorizatsiyadan o'tmagan", retryable=False)

    target = _normalize_target(group_identifier)
    styled_text = apply_font(text, font_style)
    invisib_text = _invisibilize(styled_text)

    # Yuborishdan oldin kichik tasodifiy kechikish (1-4 soniya)
    await asyncio.sleep(random.uniform(1.0, 4.0))

    try:
        msg = await client.send_message(target, invisib_text, parse_mode="html")
        chat_id = getattr(msg, "chat_id", 0) or getattr(msg, "peer_id", 0) or 0
        if hasattr(chat_id, "channel_id"):
            chat_id = int(f"-100{chat_id.channel_id}")
        elif hasattr(chat_id, "chat_id"):
            chat_id = int(f"-{chat_id.chat_id}")
        msg_id = getattr(msg, "id", 0)
        return int(chat_id), int(msg_id)

    except FloodWaitError as e:
        wait = int(getattr(e, "seconds", 60))
        logger.warning("[%s] FloodWait %ss — %s", session_name, wait, group_identifier)
        raise SendError(f"FloodWait {wait}s", retryable=True, wait_seconds=wait)

    except SlowModeWaitError as e:
        wait = int(getattr(e, "seconds", 30))
        logger.info("[%s] SlowMode %ss — %s", session_name, wait, group_identifier)
        raise SendError(f"SlowMode {wait}s", retryable=True, wait_seconds=wait)

    except (ChatWriteForbiddenError, ChannelPrivateError, ChatAdminRequiredError) as e:
        logger.warning("[%s] Yozish taqiqlangan: %s — %s", session_name, group_identifier, e)
        raise SendError("Yozish taqiqlangan", retryable=False)

    except UserBannedInChannelError as e:
        logger.warning("[%s] Kanalda ban: %s", session_name, group_identifier)
        raise SendError("Kanalda ban", retryable=False)

    except (AuthKeyUnregisteredError, UserDeactivatedBanError, UserDeactivatedError) as e:
        logger.error("[%s] Akkaunt muammosi: %s", session_name, e)
        raise SendError("Akkaunt muammosi", retryable=False)

    except RPCError as e:
        logger.warning("[%s] RPC xato %s: %s", session_name, group_identifier, e)
        raise SendError(f"RPC: {e}", retryable=True, wait_seconds=60)

    except Exception as e:
        logger.exception("[%s] Kutilmagan xato %s", session_name, group_identifier)
        raise SendError(f"Xato: {e}", retryable=True, wait_seconds=30)
