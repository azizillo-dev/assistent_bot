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

POLL_INTERVAL = 10  # har 10 soniyada tekshiradi (1 daqiqalik aylanmalar aniqligi uchun)


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

        campaign_id = camp["id"]
        text = camp["message_text"]
        interval = camp["interval_min"]
        # Akkauntlar orasidagi interval (soniyada), default 2s (50+ akkaunt uchun float ham qo'llab-quvvatlanadi)
        acc_interval_s = float(camp.get("acc_interval_s", 2))
        if not acc_interval_s or acc_interval_s < 0.5:
            acc_interval_s = 1.0
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

            # 1. Muted (uyquga yuborilgan) guruhni tekshiramiz
            mute_setting = db.get_setting(f"mute_group_{group_id}")
            if mute_setting:
                try:
                    import time as time_mod
                    if float(mute_setting) > time_mod.time():
                        timer_skip += 1
                        continue
                except Exception:
                    pass

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
                    sent_ok += 1
                    # Akkauntlar orasida qo'lda belgilangan kechikish
                    await asyncio.sleep(acc_interval_s)

                except SendError as e:
                    # Agar Slow Mode yoki flood kutish bo'lsa -> XATO EMAS (`skip / timer_skip`) deb hisoblaymiz!
                    if e.retryable and e.wait_seconds > 0:
                        retry_time = datetime.utcnow() + timedelta(seconds=e.wait_seconds + 5)
                        self._group_retry_at[group_id] = retry_time
                        timer_skip += 1
                        logger.info("Guruh %s — SlowMode/Flood, %ss kutamiz (Xato logga yozilmaydi)", identifier, e.wait_seconds)
                        break

                    # Haqiqiy (fatal) xatolik
                    err_str = str(e)
                    db.log_send(campaign_id, acc["id"], group_id, "failed", err_str)
                    sent_fail += 1

                    # 1. Akkaunt sessiyasi o'chgan bo'lsa -> avtomatik inactive qilish va ogohlantirish
                    if any(k in err_str for k in ["AuthKeyUnregistered", "AuthKeyInvalid", "SessionRevoked", "avtorizatsiyadan o'tmagan"]):
                        db.deactivate_account(acc["id"])
                        logger.warning("Akkaunt %s (%s) avtorizatsiyadan o'tmagan, to'xtatildi", acc["id"], session_name)
                        if db.should_send_notification(camp["user_id"], "account_error", acc["id"], cooldown_hours=24):
                            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                            err_text = (
                                f"🔴 <b>Sessiyasi o'chgan akkaunt aniqlandi!</b>\n\n"
                                f"📱 Akkaunt raqami: <b>{acc.get('phone', session_name)}</b>\n"
                                f"❌ Xato: <b>Telegram ushbu akkauntning sessiyasini o'chirib yuborgan (avtorizatsiya kuygan).</b>\n\n"
                                f"💡 <i>Ushbu akkaunt boshqa xatolar keltirib chiqarmasligi uchun avtomatik to'xtatildi. Uni ro'yxatdan o'chirib, qaytadan ulashingiz mumkin:</i>"
                            )
                            kb = InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="🗑 Bu akkauntni ro'yxatdan o'chirish", callback_data=f"err_del_acc_{acc['id']}")]
                            ])
                            try:
                                await self.bot.send_message(camp["user_id"], err_text, reply_markup=kb)
                                db.record_notification(camp["user_id"], "account_error", acc["id"])
                            except Exception:
                                pass
                        continue

                    # 2. Guruh yopiq yoki Banned bo'lsa -> aqlli ogohlantirish (action button bilan)
                    if any(k in err_str for k in ["Yozish taqiqlangan", "ChatWriteForbidden", "Kanalda ban", "UserBannedInChannel"]):
                        if db.should_send_notification(camp["user_id"], "group_error", group_id, cooldown_hours=12):
                            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                            err_text = (
                                f"⚠️ <b>Kampaniyada muammoli guruh aniqlandi!</b>\n\n"
                                f"📢 Kampaniya: <b>{camp['name']}</b>\n"
                                f"👥 Guruh: <b>{identifier}</b>\n"
                                f"❌ Xato sababi: <b>{err_str}</b> *(Masalan, guruh yozishni yopgan yoki sizni ban qilgan)*\n\n"
                                f"💡 <i>Har daqiqada xato beravermasligi va statistikangiz (❌ failed) ko'paymasligi uchun bu guruhni ro'yxatdan o'chirishingiz yoki 24 soatga uyqu rejimiga qo'yishingizni so'raymiz:</i>"
                            )
                            kb = InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="🗑 Guruhni ro'yxatdan o'chirish (Tozalash)", callback_data=f"err_del_grp_{group_id}")],
                                [InlineKeyboardButton(text="💤 24 soatga uyqu rejimiga qo'yish", callback_data=f"err_mute_grp_{group_id}")]
                            ])
                            try:
                                await self.bot.send_message(camp["user_id"], err_text, reply_markup=kb)
                                db.record_notification(camp["user_id"], "group_error", group_id)
                            except Exception:
                                pass

        logger.info(
            "Kampaniya '%s' [%s] — yuborildi: %d, xato: %d, timer: %d",
            camp["name"], campaign_id, sent_ok, sent_fail, timer_skip,
        )

