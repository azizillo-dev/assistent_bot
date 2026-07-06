"""
Scheduler — har N minutda kampaniyalarni ishga tushiradi.
Timer bor guruhga yubora olmasa, keyinroq qayta urinadi.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot

import db
from sender import send_message, SendError
from sessions_mgr import session_manager

logger = logging.getLogger(__name__)

POLL_INTERVAL = 20  # har 20 soniyada tekshiradi


class CampaignScheduler:
    def __init__(self, bot: Bot):
        self.bot = bot
        self._running = False
        # Guruh timer kutish vaqtlari: {group_id: datetime}
        self._group_retry_at: dict[int, datetime] = {}

    def stop(self):
        self._running = False

    async def close_sessions(self):
        await session_manager.disconnect_all()

    async def run(self):
        self._running = True
        logger.info("Scheduler ishga tushdi")
        asyncio.create_task(self._cleanup_old_messages_loop())
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Scheduler xatosi")
            await asyncio.sleep(POLL_INTERVAL)
        logger.info("Scheduler to'xtatildi")

    async def _tick(self):
        if db.get_setting("global_pause", "0") == "1":
            return

        campaigns = db.get_due_campaigns()
        if not campaigns:
            return

        for camp in campaigns:
            asyncio.create_task(self._run_campaign(dict(camp)))

    async def _run_campaign(self, camp: dict):
        if db.is_user_paused(camp["user_id"]):
            logger.info("Foydalanuvchi %s pauzada, kampaniya '%s' o'tkazilmoqda", camp["user_id"], camp["name"])
            return

        user_set = db.get_user_settings(camp["user_id"])
        if user_set.get("night_mode", 0) == 1:
            current_hour = datetime.utcnow().hour
            local_hour = (current_hour + 5) % 24
            if 0 <= local_hour < 6:
                logger.info("Tungi rejim yoqilgan (soat %02d:00), kampaniya '%s' tonggacha pauzada", local_hour, camp["name"])
                return
        campaign_id = camp["id"]
        text = camp["message_text"]
        interval = camp["interval_min"]
        # Akkauntlar orasidagi interval (soniyada), default 2s
        acc_interval_s = camp.get("acc_interval_s", 2)
        if not acc_interval_s or acc_interval_s < 1:
            acc_interval_s = 2
        font_style = camp.get("font_style", "none") or "none"

        # next_run ni darhol yangilaymiz
        next_run = (datetime.utcnow() + timedelta(minutes=interval)).strftime("%Y-%m-%d %H:%M:%S")
        db.update_campaign_field(campaign_id, "next_run", next_run)
        db.update_campaign_field(campaign_id, "last_run", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))

        accounts = db.get_campaign_accounts(campaign_id)
        groups = db.get_campaign_groups(campaign_id)

        if not accounts:
            logger.warning("Kampaniya %s — akkaunt yo'q", campaign_id)
            return
        if not groups:
            logger.warning("Kampaniya %s — guruh yo'q", campaign_id)
            return

        sent_ok = 0
        sent_fail = 0
        timer_skip = 0
        now = datetime.utcnow()

        for grp in groups:
            group_id = grp["id"]
            identifier = grp["identifier"]

            # Timer tekshiruvi
            retry_at = self._group_retry_at.get(group_id)
            if retry_at and now < retry_at:
                timer_skip += 1
                logger.info("Guruh %s (%s) — timer, %ss qoldi", group_id, identifier,
                            int((retry_at - now).total_seconds()))
                continue

            # Har bir akkauntdan yuborish
            for acc in accounts:
                session_name = acc["session_name"]
                try:
                    chat_id, msg_id = await send_message(session_name, identifier, text, font_style)
                    db.log_send(campaign_id, acc["id"], group_id, "sent")
                    if user_set.get("auto_delete_24h", 1) == 1 and chat_id != 0 and msg_id != 0:
                        db.save_sent_message(camp["user_id"], session_name, chat_id, msg_id)
                    sent_ok += 1
                    # Akkauntlar orasida qo'lda belgilangan kechikish
                    await asyncio.sleep(acc_interval_s)

                except SendError as e:
                    db.log_send(campaign_id, acc["id"], group_id, "failed", str(e))
                    sent_fail += 1

                    if e.retryable and e.wait_seconds > 0:
                        retry_time = datetime.utcnow() + timedelta(seconds=e.wait_seconds + 10)
                        self._group_retry_at[group_id] = retry_time
                        logger.info("Guruh %s — %ss kutamiz", identifier, e.wait_seconds)
                        break

        logger.info(
            "Kampaniya '%s' [%s] — yuborildi: %d, xato: %d, timer: %d",
            camp["name"], campaign_id, sent_ok, sent_fail, timer_skip,
        )

    async def _cleanup_old_messages_loop(self):
        logger.info("24 soatlik xabarlarni tozalovchi fon vazifasi ishga tushdi")
        while self._running:
            try:
                old_msgs = db.get_old_sent_messages(hours=24, limit=300)
                if old_msgs:
                    logger.info("%d ta eski xabar tozalash uchun topildi", len(old_msgs))
                    grouped = {}
                    for m in old_msgs:
                        key = (m["session_name"], m["chat_id"])
                        grouped.setdefault(key, []).append(m)

                    deleted_ids = []
                    for (session_name, chat_id), msgs in grouped.items():
                        try:
                            client = await session_manager.get_client(session_name)
                            if await client.is_user_authorized():
                                msg_ids = [m["message_id"] for m in msgs]
                                await client.delete_messages(chat_id, msg_ids)
                                deleted_ids.extend([m["id"] for m in msgs])
                                await asyncio.sleep(1)
                        except Exception as e:
                            logger.warning("[%s] Eski xabarlarni o'chirishda xato: %s", session_name, e)
                            deleted_ids.extend([m["id"] for m in msgs])

                    if deleted_ids:
                        db.delete_sent_messages_records(deleted_ids)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Eski xabarlarni tozalashda xato")

            await asyncio.sleep(3600)
