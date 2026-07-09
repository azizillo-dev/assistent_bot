"""
Bot handlerlari — faqat ruxsat etilgan 5 ta user uchun.
Yangiliklar:
  1. Shrift tanlash (bold, italic, mono, underline, strike, bold+italic)
  2. Akkauntlar orasidagi intervalni qo'lda belgilash
  3. Barcha kampaniyalar matnini 1 urinishda o'zgartirish
"""
import asyncio
import logging
import re
import html as html_lib
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import db
from sender import FONT_LABELS, FONT_STYLES
from sessions_mgr import session_manager

logger = logging.getLogger(__name__)
router = Router()

# ── Ruxsat filtri va Middleware ────────────────────────────────────────────────

@router.message.outer_middleware()
async def user_info_msg_mw(handler, event: Message, data: dict):
    if event.from_user:
        db.update_user_info(event.from_user.id, event.from_user.full_name, event.from_user.username)
    return await handler(event, data)


@router.callback_query.outer_middleware()
async def user_info_cq_mw(handler, event: CallbackQuery, data: dict):
    if event.from_user:
        db.update_user_info(event.from_user.id, event.from_user.full_name, event.from_user.username)
    return await handler(event, data)


def allowed(user_id: int) -> bool:
    return db.is_user_allowed(user_id) and not db.is_user_paused(user_id)


def access_denied(user_id: int = 0):
    if user_id and db.is_user_paused(user_id):
        return "⚠️ <b>Sizning hisobingiz vaqtincha to'xtatilgan (pauza qilingan).</b>\n\nIltimos, bot ma'muriyati bilan bog'laning."
    return "⛔ Sizga ruxsat yo'q."


SUPER_ADMINS: set[int] = set()


def check_admin(user_id: int) -> bool:
    return user_id in SUPER_ADMINS or allowed(user_id)


def get_max_accounts() -> int:
    try:
        return int(db.get_setting("max_accounts", str(getattr(config, "MAX_ACCOUNTS_PER_USER", 20))))
    except ValueError:
        return 20


def get_message_html(msg: Message) -> str:
    """
    Xabarning HTML matnini olib beradi (Premium emojilar va formatlashlar saqlanadi).
    Qo'lda yozilgan HTML teglari (<, >, &) bo'lsa, ularni ham to'g'ri ko'rsatadi.
    """
    text = msg.html_text or msg.text or msg.caption or ""
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return text


def preview_text(text: str, max_len: int = 200) -> str:
    """HTML teglardan tozalangan xavfsiz qisqa ko'rinish (preview) tayyorlaydi."""
    clean = re.sub(r'<[^>]+>', '', text)
    clean = html_lib.unescape(clean)
    if len(clean) > max_len:
        clean = clean[:max_len] + "..."
    return html_lib.escape(clean)


# ── FSM States ────────────────────────────────────────────────────────────────

class AdminStates(StatesGroup):
    waiting_password = State()
    waiting_add_id   = State()
    waiting_del_id   = State()
    waiting_limit    = State()
    waiting_new_pass = State()
    waiting_new_help = State()

class LoginStates(StatesGroup):
    waiting_phone = State()
    waiting_code  = State()
    waiting_pass  = State()

class GroupStates(StatesGroup):
    waiting_identifier = State()

class CampaignStates(StatesGroup):
    waiting_name         = State()
    waiting_text         = State()
    waiting_interval     = State()
    waiting_acc_interval = State()
    choosing_font        = State()
    choosing_accounts    = State()
    choosing_groups      = State()

class EditStates(StatesGroup):
    waiting_new_text         = State()
    waiting_new_interval     = State()
    waiting_new_acc_interval = State()
    waiting_bulk_text        = State()   # Barcha kampaniyalar uchun


# ── Klaviatura ────────────────────────────────────────────────────────────────

def main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Akkauntlar"), KeyboardButton(text="👥 Guruhlar")],
            [KeyboardButton(text="📢 Kampaniyalar"), KeyboardButton(text="ℹ️ Holat")],
        ],
        resize_keyboard=True,
    )


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True,
    )


def ik(*buttons: tuple) -> InlineKeyboardMarkup:
    """Inline keyboard yasash: [(text, callback), ...]"""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=c)] for t, c in buttons]
    )


def font_kb(current: str = "none") -> InlineKeyboardMarkup:
    """Shrift tanlash klaviaturasi."""
    buttons = []
    for key, label in FONT_LABELS.items():
        mark = "✅ " if key == current else ""
        buttons.append((f"{mark}{label}", f"font_sel_{key}"))
    buttons.append(("✅ Tayyor", "font_done"))
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=c)] for t, c in buttons]
    )


# ── /start ────────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(msg: Message):
    if not allowed(msg.from_user.id):
        await msg.answer(access_denied(msg.from_user.id))
        return
    await msg.answer(
        "✅ <b>AutoPost Bot</b>\n\n"
        "Akkauntlaringizni ulab, guruhlar va kampaniyalar yarating.\n"
        "Bot har belgilangan vaqtda avtomatik xabar yuboradi.",
        reply_markup=main_kb(),
    )


@router.message(Command("cancel", "bekor", "orqaga"))
@router.message(F.text.in_({"❌ Bekor qilish", "◀️ Orqaga", "/cancel", "/bekor", "/orqaga"}))
async def global_cancel_handler(msg: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await msg.answer("Hozir hech qanday jarayonda emassiz.", reply_markup=main_kb())
        return
    await state.clear()
    
    if current_state in (AdminStates.waiting_add_id.state, AdminStates.waiting_limit.state, AdminStates.waiting_new_pass.state, AdminStates.waiting_new_help.state) and check_admin(msg.from_user.id):
        await msg.answer("❌ Jarayon bekor qilindi. Admin panelga qaytdingiz.", reply_markup=ReplyKeyboardRemove())
        await show_admin_panel(msg)
    else:
        await msg.answer("❌ Jarayon bekor qilindi. Asosiy menyuga qaytdingiz.", reply_markup=main_kb())


@router.message(Command("statistika", "stats", "stat"))
async def cmd_statistika(msg: Message):
    if not allowed(msg.from_user.id):
        return
    stats = db.get_statistics(msg.from_user.id)
    text = (
        "<b>📊 AvtoPost Statistika</b>\n\n"
        f"📱 Akkauntlar: <b>{stats['acc_total']} ta</b> ({stats['acc_active']} ta aktiv)\n"
        f"👥 Guruhlar: <b>{stats['grp_total']} ta</b>\n"
        f"📢 Kampaniyalar: <b>{stats['camp_total']} ta</b> ({stats['camp_active']} ta aktiv)\n\n"
        f"📨 Bugun yuborildi: <b>{stats['sent_today']} ta</b> ✅ | <b>{stats['failed_today']} ta</b> ❌\n"
        f"📦 Jami yuborilgan: <b>{stats['sent_total']} ta</b> ✅ | <b>{stats['failed_total']} ta</b> ❌\n"
    )
    if stats["recent_errors"]:
        text += "\n<b>⚠️ So'nggi xatoliklar (Oxirgi 5 ta):</b>\n"
        for err in stats["recent_errors"]:
            text += f"• <code>[{err['sent_at']}]</code> {err['group']}: <i>{err['error'][:40]}</i>\n"
    else:
        text += "\n✨ So'nggi paytlarda hech qanday xatolik qayd etilmagan."
        
    await msg.answer(text, reply_markup=main_kb())


DEFAULT_HELP_TEXT = """<b>ℹ️ AutoPost Bot — To'liq Qo'llanma va Yo'riqnoma</b>

Bu bot Telegram akkauntlaringiz orqali ko'plab guruhlarga avtomatlashtirilgan tarzda reklama va e'lonlar tarqatish uchun mo'ljallangan.

<b>1️⃣ QANDAY BOSHLASH KERAK?</b>
• <b>📱 Akkauntlar:</b> Bu bo'limga kirib, "➕ Yangi akkaunt qo'shish" tugmasini bosing. Telefon raqamingizni (masalan: <i>+998901234567</i>) kiriting va Telegramdan kelgan tasdiqlash kodini yuboring.
• <b>👥 Guruhlar:</b> "➕ Yangi guruh qo'shish" orqali e'lon tarqatiladigan guruhlarning linkini (masalan: <i>@guruh_linki</i>) yoki ID raqamini (<i>-100...</i>) qo'shing.
• <b>📢 Kampaniyalar:</b> Akkauntlar va guruhlarni tayyorlab bo'lgach, "➕ Yangi kampaniya" yarating. Unga nom, xabar matni, har necha daqiqada yuborilishi (interval) va qaysi akkaunt/guruhlar qatnashishini belgilab, <b>🟢 Ishga tushiring</b>!

<b>2️⃣ MUHIM QOIDALAR VA E'TIBOR BERISH KERAK BO'LGAN JIHATLAR!</b>
⚠️ <b>Yopiq va taqiqlangan guruhlar:</b> Botga qo'shilgan guruhlarda yozish yopib qo'yilmaganiga (yada faqat adminlar yozadigan emasligiga) va sizning akkauntingiz u guruhda ban bo'lmaganiga ishonch hosil qiling! Yopiq guruhlar xabar yuborishda xatolik yuzaga keltirib, loglarda ❌ to'planib qolishiga sabab bo'ladi.
⚠️ <b>Sessiyalar faolligi:</b> Ulangan akkauntlaringizni Telegramdan "Boshqa qurilmalardan chiqish" qilib yubormang! Agar sessiyadan o'chib ketsa, "📱 Akkauntlar" bo'limidan eski akkauntni o'chirib, qayta ulab oling.
⚠️ <b>Spamblock va Limitlar:</b> Telegram bitta akkauntdan juda tez va juda ko'p xabar yozishni cheklashi (spamblock) mumkin. Shuning uchun:
  • Bir necha akkaunt (masalan 3-5 ta) ulab qo'ying, shunda bot yuklamani akkauntlarga taqsimlaydi;
  • Kampaniya intervalini juda qisqa (masalan 1-2 daqiqa) qilmang, o'rtacha 15-30 daqiqa eng xavfsiz va samarali interval hisoblanadi.

<b>3️⃣ HOLAT VA NAZORAT</b>
• <b>ℹ️ Holat:</b> Bu bo'lim orqali qaysi kampaniya qachon ishlashi, bugun nechta xabar muvaffaqiyatli (✅) va nechta xato (❌) ketganini nazorat qilib borishingiz mumkin."""


@router.message(Command("yordam", "help"))
async def cmd_yordam(msg: Message):
    if not allowed(msg.from_user.id):
        return
    text = db.get_setting("help_text", DEFAULT_HELP_TEXT)
    await msg.answer(text, reply_markup=main_kb())


# ── AKKAUNTLAR ────────────────────────────────────────────────────────────────

@router.message(F.text == "📱 Akkauntlar")
async def menu_accounts(msg: Message):
    if not allowed(msg.from_user.id):
        return
    uid = msg.from_user.id
    accs = db.get_accounts(uid)
    count = len(accs)

    text = f"<b>📱 Akkauntlar</b> ({count}/{get_max_accounts()})\n\n"
    if accs:
        for a in accs:
            text += f"• {a['name'] or a['phone']} — <code>{a['phone']}</code>\n"
    else:
        text += "Hali akkaunt ulanmagan.\n"

    buttons = []
    if count < get_max_accounts():
        buttons.append(("➕ Akkaunt ulash", "acc_add"))
    if accs:
        buttons.append(("🗑 Akkaunt o'chirish", "acc_del_list"))
    await msg.answer(text, reply_markup=ik(*buttons) if buttons else None)


@router.callback_query(F.data == "acc_add")
async def acc_add_start(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    await cq.message.answer("📞 Telefon raqamingizni kiriting (+998901234567):", reply_markup=cancel_kb())
    await state.set_state(LoginStates.waiting_phone)
    await cq.answer()


@router.message(LoginStates.waiting_phone)
async def login_phone(msg: Message, state: FSMContext):
    if not allowed(msg.from_user.id):
        return
    phone = msg.text.strip()
    if not re.match(r"^\+\d{9,15}$", phone):
        await msg.answer("❌ Noto'g'ri format. +998901234567 shaklida kiriting:")
        return

    uid = msg.from_user.id
    if db.count_accounts(uid) >= get_max_accounts():
        await msg.answer(f"❌ Maksimal {get_max_accounts()} ta akkaunt.")
        await state.clear()
        return

    session_name = f"user{uid}_acc{phone.replace('+','').replace(' ','')}"
    await state.update_data(phone=phone, session_name=session_name)

    wait_msg = await msg.answer("⏳ Kod yuborilmoqda...")
    try:
        client = await session_manager.fresh_client(session_name)
        result = await client.send_code_request(phone)
        await state.update_data(phone_code_hash=result.phone_code_hash)
        await wait_msg.edit_text(
            f"✅ Kod yuborildi!\n\n"
            f"Telegramdan kelgan kodingizni kiriting (masalan: <code>12345</code>):"
        )
        await state.set_state(LoginStates.waiting_code)
    except Exception as e:
        logger.exception("Kod yuborishda xato")
        await wait_msg.edit_text(f"❌ Xato: {e}\n\nQayta urinib ko'ring.")
        await state.clear()


@router.message(LoginStates.waiting_code)
async def login_code(msg: Message, state: FSMContext):
    if not allowed(msg.from_user.id):
        return
    code = msg.text.strip()
    data = await state.get_data()
    phone = data["phone"]
    session_name = data["session_name"]
    phone_code_hash = data["phone_code_hash"]

    try:
        client = await session_manager.get_client(session_name)
        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        me = await client.get_me()
        name = f"{me.first_name or ''} {me.last_name or ''}".strip() or phone
        db.add_account(msg.from_user.id, session_name, phone, name)
        await msg.answer(f"✅ <b>{name}</b> akkaunt muvaffaqiyatli ulandi!", reply_markup=main_kb())
        await state.clear()
    except Exception as e:
        err = str(e)
        if "SessionPasswordNeededError" in err or "password" in err.lower():
            await msg.answer("🔐 Ikki bosqichli himoya yoqilgan. Parolingizni kiriting:")
            await state.set_state(LoginStates.waiting_pass)
        else:
            await msg.answer(f"❌ Kod xato yoki eskirgan: {e}\n\nQayta /start bosing.")
            await state.clear()


@router.message(LoginStates.waiting_pass)
async def login_pass(msg: Message, state: FSMContext):
    if not allowed(msg.from_user.id):
        return
    data = await state.get_data()
    session_name = data["session_name"]
    phone = data["phone"]
    password = msg.text.strip()

    try:
        client = await session_manager.get_client(session_name)
        await client.sign_in(password=password)
        me = await client.get_me()
        name = f"{me.first_name or ''} {me.last_name or ''}".strip() or phone
        db.add_account(msg.from_user.id, session_name, phone, name)
        await msg.answer(f"✅ <b>{name}</b> muvaffaqiyatli ulandi!", reply_markup=main_kb())
    except Exception as e:
        await msg.answer(f"❌ Parol xato: {e}")
    await state.clear()


@router.callback_query(F.data == "acc_del_list")
async def acc_del_list(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    accs = db.get_accounts(cq.from_user.id)
    buttons = [(f"🗑 {a['name'] or a['phone']}", f"acc_del_{a['id']}") for a in accs]
    buttons.append(("◀️ Orqaga", "acc_back"))
    await cq.message.edit_text("O'chirmoqchi bo'lgan akkauntni tanlang:", reply_markup=ik(*buttons))
    await cq.answer()


@router.callback_query(F.data.startswith("acc_del_") & ~F.data.startswith("acc_del_list"))
async def acc_del(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    acc_id = int(cq.data.split("_")[-1])
    acc = db.get_account(acc_id)
    if acc:
        try:
            await session_manager.logout(acc["session_name"])
        except Exception:
            pass
        db.delete_account(acc_id, cq.from_user.id)
        await cq.message.edit_text(f"✅ {acc['name'] or acc['phone']} o'chirildi.")
    await cq.answer()


@router.callback_query(F.data == "acc_back")
async def acc_back(cq: CallbackQuery):
    await cq.message.delete()
    await cq.answer()


# ── GURUHLAR ──────────────────────────────────────────────────────────────────

@router.message(F.text == "👥 Guruhlar")
async def menu_groups(msg: Message):
    if not allowed(msg.from_user.id):
        return
    groups = db.get_groups(msg.from_user.id)
    text = f"<b>👥 Guruhlar</b> ({len(groups)} ta)\n\n"
    if groups:
        for g in groups:
            text += f"• {g['title'] or g['identifier']}\n  <code>{g['identifier']}</code>\n"
    else:
        text += "Hali guruh qo'shilmagan.\n"

    buttons = [("➕ Guruh qo'shish", "grp_add"), ("🔍 Akkaunt guruhlarini import qilish", "grp_import_start")]
    if groups:
        buttons.append(("🗑 Guruh o'chirish", "grp_del_list"))
    await msg.answer(text, reply_markup=ik(*buttons))


@router.callback_query(F.data == "grp_add")
async def grp_add_start(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    await cq.message.answer(
        "📋 Guruh yoki kanal identifikatorini kiriting:\n\n"
        "• Username: <code>@mygroupname</code>\n"
        "• ID: <code>-1001234567890</code>",
        reply_markup=cancel_kb()
    )
    await state.set_state(GroupStates.waiting_identifier)
    await cq.answer()


@router.message(GroupStates.waiting_identifier)
async def grp_add_identifier(msg: Message, state: FSMContext):
    if not allowed(msg.from_user.id):
        return
    identifier = msg.text.strip()
    if not identifier:
        await msg.answer("❌ Bo'sh bo'lishi mumkin emas.")
        return

    if not identifier.startswith("@") and not identifier.startswith("-") and not identifier.lstrip("-").isdigit():
        if not identifier.startswith("@"):
            identifier = "@" + identifier

    accs = db.get_accounts(msg.from_user.id)
    title = identifier
    if accs:
        try:
            client = await session_manager.get_client(accs[0]["session_name"])
            if await client.is_user_authorized():
                entity = await client.get_entity(identifier)
                title = getattr(entity, "title", None) or getattr(entity, "username", identifier)
        except Exception as e:
            logger.warning("Guruh tekshirishda xato: %s", e)
            await msg.answer(
                f"⚠️ Guruhni tekshirib bo'lmadi: {e}\n"
                "Baribir qo'shishni xohlaysizmi?",
                reply_markup=ik(
                    ("✅ Ha, qo'sh", f"grp_force_{identifier}"),
                    ("❌ Yo'q", "grp_cancel"),
                )
            )
            await state.clear()
            return

    db.add_group(msg.from_user.id, identifier, title)
    await msg.answer(f"✅ <b>{title}</b> qo'shildi!", reply_markup=main_kb())
    await state.clear()


@router.callback_query(F.data.startswith("grp_force_"))
async def grp_force_add(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    identifier = cq.data[len("grp_force_"):]
    db.add_group(cq.from_user.id, identifier, identifier)
    await cq.message.edit_text(f"✅ <code>{identifier}</code> qo'shildi!")
    await cq.answer()


@router.callback_query(F.data == "grp_cancel")
async def grp_cancel(cq: CallbackQuery):
    await cq.message.edit_text("❌ Bekor qilindi.")
    await cq.answer()


@router.callback_query(F.data == "grp_del_list")
async def grp_del_list(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    groups = db.get_groups(cq.from_user.id)
    buttons = [(f"🗑 {g['title'] or g['identifier']}", f"grp_del_{g['id']}") for g in groups]
    buttons.append(("◀️ Orqaga", "grp_back"))
    await cq.message.edit_text("O'chirmoqchi bo'lgan guruhni tanlang:", reply_markup=ik(*buttons))
    await cq.answer()


@router.callback_query(F.data.startswith("grp_del_"))
async def grp_del(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    gid = int(cq.data.split("_")[-1])
    g = db.get_group(gid)
    if g:
        db.delete_group(gid, cq.from_user.id)
        await cq.message.edit_text(f"✅ {g['title'] or g['identifier']} o'chirildi.")
    await cq.answer()


@router.callback_query(F.data == "grp_back")
async def grp_back(cq: CallbackQuery):
    await cq.message.delete()
    await cq.answer()


@router.callback_query(F.data == "ignore")
async def ignore_cb(cq: CallbackQuery):
    await cq.answer()


@router.callback_query(F.data == "grp_import_start")
async def grp_import_start(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    accs = db.get_accounts(cq.from_user.id)
    if not accs:
        return await cq.answer("❌ Hali akkaunt ulanmagan. Avval akkaunt ulang!", show_alert=True)
    
    if len(accs) == 1:
        await fetch_and_show_import(cq.message, cq.from_user.id, accs[0]["session_name"], state, is_edit=True)
    else:
        buttons = [(f"📱 {a['name'] or a['phone']}", f"grp_imp_acc_{a['session_name']}") for a in accs]
        buttons.append(("❌ Bekor qilish", "grp_cancel"))
        await cq.message.edit_text("🔍 Qaysi akkaunt guruhlarini import qilmoqchisiz?", reply_markup=ik(*buttons))
    await cq.answer()


@router.callback_query(F.data.startswith("grp_imp_acc_"))
async def grp_import_acc_selected(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    session_name = cq.data[len("grp_imp_acc_"):]
    await fetch_and_show_import(cq.message, cq.from_user.id, session_name, state, is_edit=True)
    await cq.answer()


async def fetch_and_show_import(msg: Message, user_id: int, session_name: str, state: FSMContext, is_edit: bool = False):
    wait_text = "⏳ Guruhlar ro'yxati yuklanmoqda... Iltimos, biroz kutib turing."
    if is_edit:
        try:
            await msg.edit_text(wait_text)
        except Exception:
            msg = await msg.answer(wait_text)
            is_edit = False
    else:
        msg = await msg.answer(wait_text)
        
    try:
        client = await session_manager.get_client(session_name)
        if not await client.is_user_authorized():
            await msg.edit_text("❌ Akkaunt avtorizatsiyadan o'tmagan. Qaytadan ulanib ko'ring.")
            return
        
        dialogs = await client.get_dialogs()
        groups_list = []
        for d in dialogs:
            # Foydalanuvchi talabi: Kanallar KK EMAS, faqat guruhlar!
            if getattr(d, "is_group", False):
                title = getattr(d, "title", "") or "Guruh"
                if getattr(d.entity, "username", None):
                    ident = f"@{d.entity.username}"
                else:
                    ident = str(d.id)
                groups_list.append({"id": ident, "title": title})
                
        if not groups_list:
            await msg.edit_text("⚠️ Ushbu akkauntda hech qanday guruh topilmadi.")
            return
            
        await state.update_data(import_groups=groups_list, selected_import=[], import_page=0)
        await render_import_page(msg, state, page=0, is_edit=True)
    except Exception as e:
        logger.error(f"Import error: {e}")
        await msg.edit_text(f"❌ Guruhlarni yuklashda xatolik yuz berdi:\n<code>{e}</code>")


async def render_import_page(msg: Message, state: FSMContext, page: int = 0, is_edit: bool = True):
    data = await state.get_data()
    groups_list = data.get("import_groups", [])
    selected = data.get("selected_import", [])
    
    per_page = 10
    total_pages = (len(groups_list) + per_page - 1) // per_page
    if page < 0:
        page = 0
    elif page >= total_pages and total_pages > 0:
        page = total_pages - 1
        
    await state.update_data(import_page=page)
    
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, len(groups_list))
    page_groups = groups_list[start_idx:end_idx]
    
    kb_rows = []
    # 1. Guruhlar (har biri alohida qatorda)
    for i, g in enumerate(page_groups, start=start_idx):
        is_sel = g["id"] in selected
        mark = "☑️" if is_sel else "⬜️"
        kb_rows.append([InlineKeyboardButton(text=f"{mark} {g['title'][:30]}", callback_data=f"grp_tgl_{i}")])
        
    # 2. Sahifani o'tkazish (bitta qatorda)
    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"grp_imp_page_{page-1}"))
        nav_row.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="ignore"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"grp_imp_page_{page+1}"))
        kb_rows.append(nav_row)
        
    # 3. Foydalanuvchi talabi: Barchasini tanlash / bekor qilish (ro'yxat pastida)
    all_selected = len(selected) == len(groups_list) and len(groups_list) > 0
    if all_selected:
        kb_rows.append([InlineKeyboardButton(text="⬜️ Barchasini bekor qilish", callback_data="grp_tgl_all_off")])
    else:
        kb_rows.append([InlineKeyboardButton(text="☑️ Barchasini tanlash", callback_data="grp_tgl_all_on")])
        
    # 4. Saqlash va Bekor qilish
    kb_rows.append([
        InlineKeyboardButton(text=f"✅ Saqlash ({len(selected)})", callback_data="grp_imp_save"),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data="grp_cancel")
    ])
    
    text = (
        f"<b>🔍 Guruhlarni tanlang</b>\n\n"
        f"Jami guruhlar: <b>{len(groups_list)} ta</b>\n"
        f"Tanlandi: <b>{len(selected)} ta</b>\n\n"
        "Kerakli guruhlarni belgiling va <b>✅ Saqlash</b> tugmasini bosing:"
    )
    
    markup = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    if is_edit:
        try:
            await msg.edit_text(text, reply_markup=markup)
        except Exception:
            await msg.answer(text, reply_markup=markup)
    else:
        await msg.answer(text, reply_markup=markup)


@router.callback_query(F.data == "grp_tgl_all_on")
async def grp_tgl_all_on(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    data = await state.get_data()
    groups_list = data.get("import_groups", [])
    all_ids = [g["id"] for g in groups_list]
    await state.update_data(selected_import=all_ids)
    await render_import_page(cq.message, state, page=data.get("import_page", 0), is_edit=True)
    await cq.answer("Barcha guruhlar tanlandi!")


@router.callback_query(F.data == "grp_tgl_all_off")
async def grp_tgl_all_off(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    data = await state.get_data()
    await state.update_data(selected_import=[])
    await render_import_page(cq.message, state, page=data.get("import_page", 0), is_edit=True)
    await cq.answer("Tanlash bekor qilindi!")


@router.callback_query(F.data.startswith("grp_tgl_"))
async def grp_toggle_item(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    idx_str = cq.data[len("grp_tgl_"):]
    if not idx_str.isdigit():
        return await cq.answer()
    idx = int(idx_str)
    
    data = await state.get_data()
    groups_list = data.get("import_groups", [])
    selected = list(data.get("selected_import", []))
    
    if 0 <= idx < len(groups_list):
        g_id = groups_list[idx]["id"]
        if g_id in selected:
            selected.remove(g_id)
        else:
            selected.append(g_id)
        await state.update_data(selected_import=selected)
        await render_import_page(cq.message, state, page=data.get("import_page", 0), is_edit=True)
    await cq.answer()


@router.callback_query(F.data.startswith("grp_imp_page_"))
async def grp_import_page_change(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    page_str = cq.data[len("grp_imp_page_"):]
    if page_str.isdigit():
        await render_import_page(cq.message, state, page=int(page_str), is_edit=True)
    await cq.answer()


@router.callback_query(F.data == "grp_imp_save")
async def grp_import_save(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    data = await state.get_data()
    selected = data.get("selected_import", [])
    groups_list = data.get("import_groups", [])
    
    if not selected:
        return await cq.answer("⚠️ Hech qanday guruh tanlanmagan!", show_alert=True)
        
    uid = cq.from_user.id
    count = 0
    for g in groups_list:
        if g["id"] in selected:
            db.add_group(uid, g["id"], g["title"])
            count += 1
            
    await state.clear()
    await cq.message.edit_text(f"✅ Muvaffaqiyatli! <b>{count} ta</b> guruh bazaga qo'shildi.")
    await cq.answer()


# ── KAMPANIYALAR ──────────────────────────────────────────────────────────────

@router.message(F.text == "📢 Kampaniyalar")
async def menu_campaigns(msg: Message):
    if not allowed(msg.from_user.id):
        return
    camps = db.get_campaigns(msg.from_user.id)
    text = f"<b>📢 Kampaniyalar</b> ({len(camps)} ta)\n\n"
    for c in camps:
        status = "✅ Aktiv" if c["is_active"] else "⏸ To'xtatilgan"
        font_label = FONT_LABELS.get(c["font_style"] or "none", "📝 Oddiy")
        text += f"• <b>{c['name']}</b> — har {c['interval_min']} daq. — {status}\n"
        text += f"  Shrift: {font_label}\n"
        if c["last_run"]:
            text += f"  Oxirgi: {c['last_run'][:16]}\n"

    if not camps:
        text += "Hali kampaniya yo'q.\n"

    buttons = [("➕ Yangi kampaniya", "camp_new")]
    if camps:
        buttons.append(("⚙️ Boshqarish", "camp_manage"))
        buttons.append(("✏️ Barchaning matnini o'zgartir", "camp_bulk_edit"))
    await msg.answer(text, reply_markup=ik(*buttons))


# ── Yangi kampaniya yaratish ──────────────────────────────────────────────────

@router.callback_query(F.data == "camp_new")
async def camp_new_start(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    accs = db.get_accounts(cq.from_user.id)
    grps = db.get_groups(cq.from_user.id)
    if not accs:
        await cq.message.answer("❌ Avval akkaunt ulang!")
        return await cq.answer()
    if not grps:
        await cq.message.answer("❌ Avval guruh qo'shing!")
        return await cq.answer()
    await cq.message.answer("📝 Kampaniya nomini kiriting:", reply_markup=cancel_kb())
    await state.set_state(CampaignStates.waiting_name)
    await cq.answer()


@router.message(CampaignStates.waiting_name)
async def camp_name(msg: Message, state: FSMContext):
    if not allowed(msg.from_user.id):
        return
    await state.update_data(name=msg.text.strip())
    await msg.answer("✉️ Kampaniya uchun xabar matnini kiriting (HTML formatida yozishingiz mumkin):")
    await state.set_state(CampaignStates.waiting_text)


@router.message(CampaignStates.waiting_text)
async def camp_text(msg: Message, state: FSMContext):
    if not allowed(msg.from_user.id):
        return
    await state.update_data(text=get_message_html(msg))
    await msg.answer(
        "⏱ Har necha minutda yuborsin?\n\n"
        "Masalan: <code>3</code>, <code>5</code>, <code>10</code>, <code>30</code>"
    )
    await state.set_state(CampaignStates.waiting_interval)


@router.message(CampaignStates.waiting_interval)
async def camp_interval(msg: Message, state: FSMContext):
    if not allowed(msg.from_user.id):
        return
    text = msg.text.strip()
    if not text.isdigit() or int(text) < 1:
        await msg.answer("❌ Musbat son kiriting (masalan: 5):")
        return
    await state.update_data(interval=int(text))

    # 2-yangilik: Akkauntlar orasidagi interval
    await msg.answer(
        "⏳ <b>Akkauntlar orasidagi interval</b>\n\n"
        "Har bir akkauntdan xabar yuborgandan keyin necha soniya kutsin?\n\n"
        "Masalan: <code>2</code> (default), <code>5</code>, <code>10</code>, <code>30</code>\n\n"
        "💡 <i>Eslatma: Agar guruhlarda yozish cheklovi (Slow mode) bo'lsa, hozircha shunchaki <code>2</code> deb yozing. Kampaniyani yaratib bo'lgach, <b>🧮 Avto-interval</b> tugmasi orqali 1 minut, 5 minut, 10 minutlik cheklovlarga 1 bosishda mukammal moslay olasiz!</i>\n\n"
        "⚠️ Ko'p akkaunt bo'lsa, katta son qo'ying (spam oldini olish uchun)"
    )
    await state.set_state(CampaignStates.waiting_acc_interval)


@router.message(CampaignStates.waiting_acc_interval)
async def camp_acc_interval(msg: Message, state: FSMContext):
    if not allowed(msg.from_user.id):
        return
    text = msg.text.strip()
    if not text.isdigit() or int(text) < 1:
        await msg.answer("❌ Musbat son kiriting (masalan: 2):")
        return
    await state.update_data(acc_interval=int(text))

    # 1-yangilik: Shrift tanlash
    await state.update_data(selected_font="none")
    await msg.answer(
        "🔤 <b>Shrift uslubini tanlang</b>\n\n"
        "Xabar qanday ko'rinishda yuborilsin?",
        reply_markup=font_kb("none")
    )
    await state.set_state(CampaignStates.choosing_font)


@router.callback_query(F.data.startswith("font_sel_"), CampaignStates.choosing_font)
async def camp_font_select(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    font_key = cq.data[len("font_sel_"):]
    if font_key not in FONT_LABELS:
        return await cq.answer()
    await state.update_data(selected_font=font_key)
    await cq.message.edit_reply_markup(reply_markup=font_kb(font_key))
    await cq.answer(f"✅ {FONT_LABELS[font_key]} tanlandi")


@router.callback_query(F.data == "font_done", CampaignStates.choosing_font)
async def camp_font_done(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    data = await state.get_data()
    font_key = data.get("selected_font", "none")
    font_label = FONT_LABELS.get(font_key, "📝 Oddiy")

    # Akkaunt tanlash
    uid = cq.from_user.id
    accs = db.get_accounts(uid)
    await state.update_data(selected_accounts=[], selected_groups=[])

    await cq.message.edit_text(
        f"✅ Shrift: <b>{font_label}</b>\n\n"
        f"📱 <b>Qaysi akkauntlardan yuborsin?</b>\n\nToggle qiling, keyin ✅ Tayyor bosing:"
    )
    buttons = [(f"☐ {a['name'] or a['phone']}", f"ca_tog_{a['id']}") for a in accs]
    buttons.append(("✅ Tayyor", "ca_done"))
    await cq.message.answer("Akkauntlarni tanlang:", reply_markup=ik(*buttons))
    await state.set_state(CampaignStates.choosing_accounts)
    await cq.answer()


@router.callback_query(F.data.startswith("ca_tog_"), CampaignStates.choosing_accounts)
async def camp_toggle_acc(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    acc_id = int(cq.data.split("_")[-1])
    data = await state.get_data()
    selected = data.get("selected_accounts", [])
    if acc_id in selected:
        selected.remove(acc_id)
    else:
        selected.append(acc_id)
    await state.update_data(selected_accounts=selected)

    accs = db.get_accounts(cq.from_user.id)
    buttons = []
    for a in accs:
        mark = "☑" if a["id"] in selected else "☐"
        buttons.append((f"{mark} {a['name'] or a['phone']}", f"ca_tog_{a['id']}"))
    buttons.append(("✅ Tayyor", "ca_done"))
    await cq.message.edit_reply_markup(reply_markup=ik(*buttons))
    await cq.answer()


@router.callback_query(F.data == "ca_done", CampaignStates.choosing_accounts)
async def camp_acc_done(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    data = await state.get_data()
    selected = data.get("selected_accounts", [])
    if not selected:
        await cq.answer("⚠️ Kamida 1 ta akkaunt tanlang!", show_alert=True)
        return

    grps = db.get_groups(cq.from_user.id)
    buttons = [(f"☐ {g['title'] or g['identifier']}", f"cg_tog_{g['id']}") for g in grps]
    buttons.append(("✅ Tayyor", "cg_done"))
    await cq.message.edit_text("👥 Qaysi guruhlarga yuborsin?", reply_markup=ik(*buttons))
    await state.set_state(CampaignStates.choosing_groups)
    await cq.answer()


@router.callback_query(F.data.startswith("cg_tog_"), CampaignStates.choosing_groups)
async def camp_toggle_grp(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    grp_id = int(cq.data.split("_")[-1])
    data = await state.get_data()
    selected = data.get("selected_groups", [])
    if grp_id in selected:
        selected.remove(grp_id)
    else:
        selected.append(grp_id)
    await state.update_data(selected_groups=selected)

    grps = db.get_groups(cq.from_user.id)
    buttons = []
    for g in grps:
        mark = "☑" if g["id"] in selected else "☐"
        buttons.append((f"{mark} {g['title'] or g['identifier']}", f"cg_tog_{g['id']}"))
    buttons.append(("✅ Tayyor", "cg_done"))
    await cq.message.edit_reply_markup(reply_markup=ik(*buttons))
    await cq.answer()


@router.callback_query(F.data == "cg_done", CampaignStates.choosing_groups)
async def camp_grp_done(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    data = await state.get_data()
    selected_grps = data.get("selected_groups", [])
    if not selected_grps:
        await cq.answer("⚠️ Kamida 1 ta guruh tanlang!", show_alert=True)
        return

    uid = cq.from_user.id
    acc_interval = data.get("acc_interval", 2)
    font_style = data.get("selected_font", "none")
    camp_id = db.create_campaign(
        uid, data["name"], data["text"], data["interval"],
        acc_interval_s=acc_interval, font_style=font_style
    )
    db.set_campaign_accounts(camp_id, data["selected_accounts"])
    db.set_campaign_groups(camp_id, selected_grps)

    font_label = FONT_LABELS.get(font_style, "📝 Oddiy")
    n_acc = len(data["selected_accounts"])

    await cq.message.edit_text(
        f"✅ <b>{data['name']}</b> kampaniyasi yaratildi!\n\n"
        f"⏱ Interval: har {data['interval']} daqiqa\n"
        f"⏳ Akkaunt interval: {acc_interval} soniya\n"
        f"🔤 Shrift: {font_label}\n"
        f"📱 Akkauntlar: {n_acc} ta\n"
        f"👥 Guruhlar: {len(selected_grps)} ta\n\n"
        f"Bot darhol ishga tushadi."
    )

    if n_acc >= 1:
        auto_msg = (
            f"💡 <b>Tavsiya: Guruhlaringizda yozish cheklovi (Slow mode) bormi?</b>\n\n"
            f"Sizda <b>{n_acc} ta akkaunt</b> ulandi. Guruhlarning cheklov taymeriga (1 minut, 5 minut, 10 minut...) moslab "
            f"<b>🧮 Avto-interval</b> tugmasini bossangiz, bot barcha akkauntlar orasidagi kutish vaqtini 100% blok bo'lmaydigan qilib o'zi sozlashi mumkin!"
        )
        await cq.message.answer(auto_msg, reply_markup=ik(
            ("🧮 Avto-intervalni o'rnatish (Slow-mode kalkulyator)", f"camp_auto_calc_{camp_id}"),
            ("⚙️ Kampaniyani boshqarish", f"camp_detail_{camp_id}")
        ))
    else:
        await cq.message.answer("🎉 Kampaniya muvaffaqiyatli saqlandi!", reply_markup=main_kb())

    await state.clear()
    await cq.answer()


# ── Kampaniya boshqaruvi ──────────────────────────────────────────────────────

@router.callback_query(F.data == "camp_manage")
async def camp_manage(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    camps = db.get_campaigns(cq.from_user.id)
    if not camps:
        await cq.message.edit_text("Kampaniya yo'q.")
        return await cq.answer()
    buttons = [(f"{'✅' if c['is_active'] else '⏸'} {c['name']}", f"camp_detail_{c['id']}") for c in camps]
    await cq.message.edit_text("Kampaniyani tanlang:", reply_markup=ik(*buttons))
    await cq.answer()


@router.callback_query(F.data.startswith("camp_detail_"))
async def camp_detail(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    cid = int(cq.data.split("_")[-1])
    c = db.get_campaign(cid)
    if not c:
        await cq.answer("Topilmadi")
        return

    accs = db.get_campaign_accounts(cid)
    grps = db.get_campaign_groups(cid)
    status = "✅ Aktiv" if c["is_active"] else "⏸ To'xtatilgan"
    font_label = FONT_LABELS.get(c["font_style"] or "none", "📝 Oddiy")

    last_run_str = (c['last_run'] or "hali yo'q")[:16]
    next_run_str = (c['next_run'] or "hali yo'q")[:16]
    acc_interval = c["acc_interval_s"] if c["acc_interval_s"] else 2

    text = (
        f"<b>{c['name']}</b>\n\n"
        f"Holat: {status}\n"
        f"Interval: har {c['interval_min']} daq.\n"
        f"Akkaunt interval: {acc_interval} soniya\n"
        f"Shrift: {font_label}\n"
        f"Akkauntlar: {len(accs)} ta\n"
        f"Guruhlar: {len(grps)} ta\n"
        f"Oxirgi: {last_run_str}\n"
        f"Keyingi: {next_run_str}\n\n"
        f"<b>Matn:</b>\n{preview_text(c['message_text'], 200)}"
    )

    toggle_label = "⏸ To'xtatish" if c["is_active"] else "▶️ Ishga tushirish"
    await cq.message.edit_text(text, reply_markup=ik(
        (toggle_label, f"camp_toggle_{cid}"),
        ("✏️ Matnni o'zgartir", f"camp_edit_text_{cid}"),
        ("⏱ Intervalni o'zgartir", f"camp_edit_int_{cid}"),
        ("⏳ Akkaunt intervalni o'zgartir", f"camp_edit_acc_int_{cid}"),
        ("🧮 Avto-interval (Slow-mode kalkulyator)", f"camp_auto_calc_{cid}"),
        ("🔤 Shriftni o'zgartir", f"camp_edit_font_{cid}"),
        ("🗑 O'chirish", f"camp_delete_{cid}"),
        ("◀️ Orqaga", "camp_manage"),
    ))
    await cq.answer()


@router.callback_query(F.data.startswith("camp_toggle_"))
async def camp_toggle(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    cid = int(cq.data.split("_")[-1])
    c = db.get_campaign(cid)
    if not c:
        return await cq.answer()
    new_val = 0 if c["is_active"] else 1
    db.update_campaign_field(cid, "is_active", new_val)
    if new_val:
        db.update_campaign_field(cid, "next_run", None)
    status = "▶️ Ishga tushirildi" if new_val else "⏸ To'xtatildi"
    await cq.answer(status, show_alert=True)
    await camp_detail(cq)


@router.callback_query(F.data.startswith("camp_auto_calc_"))
async def camp_auto_calc_handler(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    cid = int(cq.data.split("_")[-1])
    c = db.get_campaign(cid)
    if not c:
        return await cq.answer()
    
    accs = db.get_campaign_accounts(cid)
    if not accs:
        await cq.answer("⚠️ Kampaniyaga akkauntlar ulanmagan! Avval akkaunt ulang.", show_alert=True)
        return

    text = (
        f"🧮 <b>Universal Avto-Interval Kalkulyatori</b>\n\n"
        f"Kampaniyada <b>{len(accs)} ta akkaunt</b> bor.\n\n"
        f"👥 <b>Guruhlaringizda necha daqiqalik yozish cheklovi (Slow mode) bor?</b>\n"
        f"<i>(Bitta xabar yozgandan keyin keyingisigacha necha minut kutiladi?)</i>\n\n"
        f"Quyidagilardan birini tanlang, bot barcha akkauntlar orasidagi kutish vaqtini va aylanmani o'zi mukammal hisoblab beradi:"
    )
    buttons = [
        ("🟢 1 minut (60 soniya cheklov)", f"camp_auto_res_{cid}_60"),
        ("🟡 3 minut (180 soniya cheklov)", f"camp_auto_res_{cid}_180"),
        ("🟠 5 minut (300 soniya cheklov)", f"camp_auto_res_{cid}_300"),
        ("🔴 10 minut (600 soniya cheklov)", f"camp_auto_res_{cid}_600"),
        ("🔴 15 minut (900 soniya cheklov)", f"camp_auto_res_{cid}_900"),
        ("◀️ Orqaga", f"camp_detail_{cid}")
    ]
    await cq.message.edit_text(text, reply_markup=ik(*buttons))
    await cq.answer()


@router.callback_query(F.data.startswith("camp_auto_res_"))
async def camp_auto_res_handler(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    parts = cq.data.split("_")
    cid = int(parts[3])
    sm_sec = int(parts[4])
    
    c = db.get_campaign(cid)
    if not c:
        return await cq.answer()
    
    accs = db.get_campaign_accounts(cid)
    n_acc = len(accs)
    if n_acc == 0:
        await cq.answer("⚠️ Kampaniyaga akkaunt ulanmagan!", show_alert=True)
        return
    
    ideal_acc_int = max(1, round(sm_sec / n_acc))
    ideal_camp_min = max(1, round(sm_sec / 60))
    
    text = (
        f"🎯 <b>Universal hisoblangan ideal sozlama:</b>\n\n"
        f"📱 Ulanib turgan akkauntlar: <b>{n_acc} ta</b>\n"
        f"⏱ Guruhlardagi yozish cheklovi: <b>{sm_sec} soniya ({sm_sec//60} minut)</b>\n\n"
        f"✅ <b>Bot quyidagi vaqtlarni o'rnatadi:</b>\n"
        f"• Har bir akkaunt xabar yuborgach <b>{ideal_acc_int} soniya</b> kutadi.\n"
        f"• Kampaniya guruhlarga <b>har {ideal_camp_min} daqiqada</b> xabar tarqatadi.\n\n"
        f"💡 <i>Natija: {n_acc} ta akkaunt {ideal_acc_int} soniyadan ketma-ket xabar yuborib bo'lgach roppa-rosa {sm_sec} soniya o'tadi va 1-akkaunt taymerdan to'liq bo'shab, hech qaysi akkaunt blok bo'lmasdan ishlayveradi!</i>\n\n"
        f"O'rnatishni tasdiqlaysizmi?"
    )
    buttons = [
        ("✅ O'rnatish (Saqlash)", f"camp_auto_apply_{cid}_{ideal_camp_min}_{ideal_acc_int}"),
        ("◀️ Orqaga (Boshqa vaqt tanlash)", f"camp_auto_calc_{cid}")
    ]
    await cq.message.edit_text(text, reply_markup=ik(*buttons))
    await cq.answer()


@router.callback_query(F.data.startswith("camp_auto_apply_"))
async def camp_auto_apply_handler(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    parts = cq.data.split("_")
    cid = int(parts[3])
    camp_int = int(parts[4])
    acc_int = int(parts[5])
    
    c = db.get_campaign(cid)
    if not c:
        return await cq.answer()
    
    db.update_campaign_field(cid, "interval_min", camp_int)
    db.update_campaign_field(cid, "acc_interval_s", acc_int)
    
    await cq.answer(f"✅ Ideal sozlama (har {camp_int} daq / {acc_int}s) o'rnatildi!", show_alert=True)
    # CQ datani camp_detail ga moslab chaqiramiz
    cq.data = f"camp_detail_{cid}"
    await camp_detail(cq)


# ── Matn tahrirlash ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("camp_edit_text_"))
async def camp_edit_text_start(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    cid = int(cq.data.split("_")[-1])
    await state.update_data(edit_camp_id=cid)
    await cq.message.answer("✏️ Yangi matnni kiriting:", reply_markup=cancel_kb())
    await state.set_state(EditStates.waiting_new_text)
    await cq.answer()


@router.message(EditStates.waiting_new_text)
async def camp_edit_text_save(msg: Message, state: FSMContext):
    if not allowed(msg.from_user.id):
        return
    data = await state.get_data()
    cid = data["edit_camp_id"]
    db.update_campaign_field(cid, "message_text", get_message_html(msg))
    await msg.answer("✅ Matn yangilandi!", reply_markup=main_kb())
    await state.clear()


# ── Interval tahrirlash ───────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("camp_edit_int_"))
async def camp_edit_int_start(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    cid = int(cq.data.split("_")[-1])
    await state.update_data(edit_camp_id=cid)
    await cq.message.answer("⏱ Yangi interval (minutda, masalan 5):", reply_markup=cancel_kb())
    await state.set_state(EditStates.waiting_new_interval)
    await cq.answer()


@router.message(EditStates.waiting_new_interval)
async def camp_edit_int_save(msg: Message, state: FSMContext):
    if not allowed(msg.from_user.id):
        return
    text = msg.text.strip()
    if not text.isdigit() or int(text) < 1:
        await msg.answer("❌ Musbat son kiriting:")
        return
    data = await state.get_data()
    cid = data["edit_camp_id"]
    db.update_campaign_field(cid, "interval_min", int(text))
    db.update_campaign_field(cid, "next_run", None)
    await msg.answer(f"✅ Interval {text} daqiqaga o'zgartirildi!", reply_markup=main_kb())
    await state.clear()


# ── Akkaunt interval tahrirlash (2-yangilik) ──────────────────────────────────

@router.callback_query(F.data.startswith("camp_edit_acc_int_"))
async def camp_edit_acc_int_start(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    cid = int(cq.data.split("_")[-1])
    c = db.get_campaign(cid)
    current = c["acc_interval_s"] if c and c["acc_interval_s"] else 2
    await state.update_data(edit_camp_id=cid)
    await cq.message.answer(
        f"⏳ <b>Akkauntlar orasidagi interval</b>\n\n"
        f"Hozirgi qiymat: <b>{current} soniya</b>\n\n"
        f"Yangi qiymatni kiriting (soniyada):\n"
        f"Masalan: <code>2</code>, <code>5</code>, <code>10</code>, <code>30</code>",
        reply_markup=cancel_kb()
    )
    await state.set_state(EditStates.waiting_new_acc_interval)
    await cq.answer()


@router.message(EditStates.waiting_new_acc_interval)
async def camp_edit_acc_int_save(msg: Message, state: FSMContext):
    if not allowed(msg.from_user.id):
        return
    text = msg.text.strip()
    if not text.isdigit() or int(text) < 1:
        await msg.answer("❌ Musbat son kiriting (masalan: 2):")
        return
    data = await state.get_data()
    cid = data["edit_camp_id"]
    db.update_campaign_field(cid, "acc_interval_s", int(text))
    await msg.answer(f"✅ Akkaunt interval {text} soniyaga o'zgartirildi!", reply_markup=main_kb())
    await state.clear()


# ── Shrift tahrirlash (1-yangilik) ────────────────────────────────────────────

@router.callback_query(F.data.startswith("camp_edit_font_"))
async def camp_edit_font_start(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    cid = int(cq.data.split("_")[-1])
    c = db.get_campaign(cid)
    current_font = (c["font_style"] or "none") if c else "none"
    await state.update_data(edit_camp_id=cid, selected_font=current_font)
    await cq.message.answer(
        "🔤 <b>Shrift uslubini tanlang:</b>",
        reply_markup=font_kb(current_font)
    )
    await state.set_state(EditStates.waiting_new_text)  # reuse flow below
    await cq.answer()


# Font tanlash — edit mode uchun alohida callback
@router.callback_query(F.data.startswith("font_sel_"))
async def font_sel_any(cq: CallbackQuery, state: FSMContext):
    """Istalgan stateda ishlaydi."""
    if not allowed(cq.from_user.id):
        return await cq.answer()
    font_key = cq.data[len("font_sel_"):]
    if font_key not in FONT_LABELS:
        return await cq.answer()
    data = await state.get_data()
    await state.update_data(selected_font=font_key)
    # Klaviaturani yangilaymiz
    try:
        await cq.message.edit_reply_markup(reply_markup=font_kb(font_key))
    except Exception:
        pass
    await cq.answer(f"✅ {FONT_LABELS[font_key]} tanlandi")


@router.callback_query(F.data == "font_save_edit")
async def font_save_edit(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    data = await state.get_data()
    cid = data.get("edit_camp_id")
    font_key = data.get("selected_font", "none")
    if cid:
        db.update_campaign_field(cid, "font_style", font_key)
        font_label = FONT_LABELS.get(font_key, "📝 Oddiy")
        await cq.message.edit_text(f"✅ Shrift <b>{font_label}</b> ga o'zgartirildi!")
        await state.clear()
    await cq.answer()


# Kampaniya font edit uchun to'liq flow
@router.callback_query(F.data.startswith("cedit_font_"))
async def cedit_font_start(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    cid = int(cq.data.split("_")[-1])
    c = db.get_campaign(cid)
    current_font = (c["font_style"] or "none") if c else "none"
    await state.update_data(edit_camp_id=cid, selected_font=current_font)
    # Font tanlash + Saqlash tugmasi
    kb_buttons = []
    for key, label in FONT_LABELS.items():
        mark = "✅ " if key == current_font else ""
        kb_buttons.append([InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"font_sel_{key}")])
    kb_buttons.append([InlineKeyboardButton(text="💾 Saqlash", callback_data="font_save_edit")])
    await cq.message.answer(
        "🔤 <b>Shrift uslubini tanlang:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    )
    await cq.answer()


# ── Barcha kampaniyalar matnini o'zgartirish (3-yangilik) ─────────────────────

@router.callback_query(F.data == "camp_bulk_edit")
async def camp_bulk_edit_start(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    camps = db.get_campaigns(cq.from_user.id)
    count = len(camps)
    await cq.message.answer(
        f"✏️ <b>Barcha kampaniyalar matnini o'zgartirish</b>\n\n"
        f"Sizda <b>{count} ta</b> kampaniya bor.\n"
        f"Yangi matnni kiriting — <b>barchasi</b> shu matnni oladi:\n\n"
        f"⚠️ Bu amalni bekor qilib bo'lmaydi!",
        reply_markup=cancel_kb()
    )
    await state.set_state(EditStates.waiting_bulk_text)
    await cq.answer()


@router.message(EditStates.waiting_bulk_text)
async def camp_bulk_text_save(msg: Message, state: FSMContext):
    if not allowed(msg.from_user.id):
        return
    new_text = get_message_html(msg)
    uid = msg.from_user.id
    camps = db.get_campaigns(uid)
    count = len(camps)

    db.update_all_campaigns_text(uid, new_text)
    await msg.answer(
        f"✅ <b>{count} ta kampaniyaning</b> matni yangilandi!\n\n"
        f"Yangi matn:\n<i>{preview_text(new_text, 300)}</i>",
        reply_markup=main_kb()
    )
    await state.clear()


# ── Kampaniyani o'chirish ─────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("camp_delete_"))
async def camp_delete(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    cid = int(cq.data.split("_")[-1])
    c = db.get_campaign(cid)
    if c:
        db.delete_campaign(cid, cq.from_user.id)
        await cq.message.edit_text(f"🗑 <b>{c['name']}</b> o'chirildi.")
    await cq.answer()


# ── HOLAT ─────────────────────────────────────────────────────────────────────

@router.message(F.text == "ℹ️ Holat")
async def menu_status(msg: Message):
    if not allowed(msg.from_user.id):
        return
    uid = msg.from_user.id
    accs = db.get_accounts(uid)
    grps = db.get_groups(uid)
    camps = db.get_campaigns(uid)
    active_camps = [c for c in camps if c["is_active"]]

    lines = [
        "<b>ℹ️ Holat</b>\n",
        f"📱 Akkauntlar: {len(accs)} ta",
        f"👥 Guruhlar: {len(grps)} ta",
        f"📢 Kampaniyalar: {len(camps)} ta ({len(active_camps)} aktiv)\n",
    ]

    if active_camps:
        lines.append("<b>Aktiv kampaniyalar:</b>")
        for c in active_camps:
            acc_int = c["acc_interval_s"] if c["acc_interval_s"] else 2
            font_label = FONT_LABELS.get(c["font_style"] or "none", "📝 Oddiy")
            lines.append(f"• {c['name']} — har {c['interval_min']} daq. | akk.int: {acc_int}s | {font_label}")
            if c["next_run"]:
                lines.append(f"  ⏰ Keyingi: {c['next_run'][:16]}")

    await msg.answer("\n".join(lines))


# ── YASHIRIN ADMIN PANEL (/root) ──────────────────────────────────────────────

@router.message(Command("root"))
async def cmd_root(msg: Message, state: FSMContext):
    await msg.answer("🔐 Maxsus boshqaruv tizimi. Parolni kiriting:", reply_markup=cancel_kb())
    await state.set_state(AdminStates.waiting_password)


@router.message(AdminStates.waiting_password)
async def admin_verify_pass(msg: Message, state: FSMContext):
    entered_pass = msg.text.strip()
    real_pass = db.get_setting("admin_password", getattr(config, "ADMIN_PASSWORD", "Senior0307"))
    
    if entered_pass == real_pass:
        SUPER_ADMINS.add(msg.from_user.id)
        await state.clear()
        await show_admin_panel(msg)
    else:
        await state.clear()
        await msg.answer("⛔ Sizga ruxsat yo'q.")


async def show_admin_panel(event: Message | CallbackQuery):
    users = db.get_all_allowed_users()
    limit = get_max_accounts()
    
    g_pause = db.get_setting("global_pause", "0") == "1"
    g_status = "⏸ PAUZADA (Xabar ketmayapti)" if g_pause else "🟢 FAOL (Ishlamoqda)"
    g_btn_text = "🟢 Global Pauzani O'chirish" if g_pause else "⏸ Global Pauza qilish"
    
    text = (
        "<b>🔐 Maxfiy Admin Panel</b>\n\n"
        f"🌐 Tizim holati: <b>{g_status}</b>\n"
        f"👥 Ruxsat etilgan foydalanuvchilar: <b>{len(users)} ta</b>\n"
        f"📱 Akkauntlar limiti: <b>har bir userga {limit} ta</b>\n\n"
        "Quyidagi menyudan kerakli amallarni bajaring:"
    )
    
    kb = ik(
        (g_btn_text, "admin_toggle_global_pause"),
        ("👥 Ruxsatlilar ro'yxati (Boshqaruv)", "admin_list_users"),
        ("➕ Foydalanuvchi qo'shish", "admin_add_user"),
        ("🗑 Foydalanuvchi o'chirish", "admin_del_user"),
        ("⚙️ Limitni o'zgartirish", "admin_edit_limit"),
        ("🔑 Parolni o'zgartirish", "admin_edit_pass"),
        ("📝 /yordam matnini tahrirlash", "admin_edit_help"),
        ("🔒 Panelni yopish", "admin_close")
    )
    
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=kb)
    else:
        await event.answer(text, reply_markup=kb)


@router.callback_query(F.data == "admin_toggle_global_pause")
async def admin_toggle_gpause(cq: CallbackQuery):
    if not check_admin(cq.from_user.id):
        return await cq.answer("⛔ Ruxsat yo'q", show_alert=True)
    current = db.get_setting("global_pause", "0") == "1"
    new_val = "0" if current else "1"
    db.set_setting("global_pause", new_val)
    status_str = "🟢 Global Pauza O'CHIRILDI! Bot tarqatishni davom ettiradi." if new_val == "0" else "⏸ Global Pauza YOQILDI! Barcha tarqatishlar to'xtatildi."
    await cq.answer(status_str, show_alert=True)
    await show_admin_panel(cq)


@router.callback_query(F.data == "admin_list_users")
async def admin_list_users_handler(cq: CallbackQuery):
    if not check_admin(cq.from_user.id):
        return await cq.answer("⛔ Ruxsat yo'q", show_alert=True)
    users = db.get_all_allowed_users_detailed()
    text = "<b>👥 Ruxsat etilgan foydalanuvchilar ro'yxati:</b>\n\n"
    buttons = []
    for i, u in enumerate(users, 1):
        uid = u["user_id"]
        name = u["name"]
        username = u["username"]
        if not name or name == "Noma'lum":
            try:
                chat_info = await cq.bot.get_chat(uid)
                name = f"{chat_info.first_name or ''} {chat_info.last_name or ''}".strip() or getattr(chat_info, "title", None) or "Noma'lum"
                username = getattr(chat_info, "username", None) or ""
                db.update_user_info(uid, name, username)
            except Exception:
                name = "Noma'lum"
        
        uname = f" (@{username})" if username else ""
        status = "⏸ Pauza" if u["is_paused"] else "🟢 Faol"
        text += f"{i}. <code>{uid}</code> — <b>{html_lib.escape(name)}</b>{uname} [{status}]\n"
        buttons.append((f"👤 {name[:12]} ({uid})", f"admin_manage_user_{uid}"))
    
    buttons.append(("◀️ Orqaga", "admin_back"))
    await cq.message.edit_text(text, reply_markup=ik(*buttons))
    await cq.answer()


@router.callback_query(F.data.startswith("admin_manage_user_"))
async def admin_manage_user_handler(cq: CallbackQuery):
    if not check_admin(cq.from_user.id):
        return await cq.answer("⛔ Ruxsat yo'q", show_alert=True)
    uid = int(cq.data.split("_")[-1])
    uinfo = db.get_user_info(uid)
    if not uinfo:
        return await cq.answer("Topilmadi", show_alert=True)
    
    name = uinfo["name"]
    username = uinfo["username"]
    if not name or name == "Noma'lum":
        try:
            chat_info = await cq.bot.get_chat(uid)
            name = f"{chat_info.first_name or ''} {chat_info.last_name or ''}".strip() or getattr(chat_info, "title", None) or "Noma'lum"
            username = getattr(chat_info, "username", None) or ""
            db.update_user_info(uid, name, username)
        except Exception:
            name = "Noma'lum"
            
    uname = f" (@{username})" if username else ""
    status = "⏸ Pauzada" if uinfo["is_paused"] else "🟢 Faol"
    
    stats = db.get_statistics(uid)
    
    text = (
        f"👤 <b>Foydalanuvchi boshqaruvi</b>\n\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"👤 Ism: <b>{html_lib.escape(name)}</b>{uname}\n"
        f"ℹ️ Holat: <b>{status}</b>\n"
        f"📅 Qo'shilgan: <code>{uinfo['added_at']}</code>\n\n"
        f"📊 <b>Foydalanuvchi faoliyati:</b>\n"
        f"• 📱 Akkauntlar: <b>{stats['acc_total']} ta</b> ({stats['acc_active']} ta aktiv)\n"
        f"• 👥 Guruhlar: <b>{stats['grp_total']} ta</b>\n"
        f"• 📢 Kampaniyalar: <b>{stats['camp_total']} ta</b> (🟢 <b>{stats['camp_active']} ta faol</b>)\n"
        f"• 📨 Bugun yuborildi: <b>{stats['sent_today']} ta</b> ✅ | <b>{stats['failed_today']} ta</b> ❌\n"
        f"• 📦 Jami yuborilgan: <b>{stats['sent_total']} ta</b>\n\n"
        "Kerakli amalni tanlang:"
    )
    
    pause_btn = "🟢 Faollashtirish (Pauzadn chiqarish)" if uinfo["is_paused"] else "⏸ Pauza qilish (To'xtatish)"
    pause_action = f"admin_upause_{uid}_{0 if uinfo['is_paused'] else 1}"
    
    kb = ik(
        (pause_btn, pause_action),
        ("❌ Ro'yxatdan o'chirish", f"admin_del_confirm_{uid}"),
        ("◀️ Orqaga", "admin_list_users")
    )
    await cq.message.edit_text(text, reply_markup=kb)
    await cq.answer()


@router.callback_query(F.data.startswith("admin_upause_"))
async def admin_exec_upause(cq: CallbackQuery):
    if not check_admin(cq.from_user.id):
        return await cq.answer("⛔ Ruxsat yo'q", show_alert=True)
    parts = cq.data.split("_")
    uid = int(parts[2])
    val = int(parts[3])
    db.set_user_pause(uid, val)
    msg_str = "⏸ Foydalanuvchi pauza qilindi!" if val == 1 else "🟢 Foydalanuvchi faollashtirildi!"
    await cq.answer(msg_str, show_alert=True)
    cq.data = f"admin_manage_user_{uid}"
    await admin_manage_user_handler(cq)


@router.callback_query(F.data == "admin_add_user")
async def admin_add_user_start(cq: CallbackQuery, state: FSMContext):
    if not check_admin(cq.from_user.id):
        return await cq.answer("⛔ Ruxsat yo'q", show_alert=True)
    await cq.message.answer("➕ Yangi foydalanuvchining Telegram ID raqamini kiriting (yoki xabarini shu yerga forward qiling):", reply_markup=cancel_kb())
    await state.set_state(AdminStates.waiting_add_id)
    await cq.answer()


@router.message(AdminStates.waiting_add_id)
async def admin_save_new_user(msg: Message, state: FSMContext):
    if not check_admin(msg.from_user.id):
        return
    if msg.forward_from:
        new_id = msg.forward_from.id
    elif msg.forward_from_chat:
        new_id = msg.forward_from_chat.id
    else:
        text = msg.text.strip()
        if not text.isdigit():
            await msg.answer("❌ Noto'g'ri ID format. Faqat raqamlardan iborat Telegram ID kiriting:")
            return
        new_id = int(text)
    
    if db.add_allowed_user(new_id):
        await msg.answer(f"✅ Foydalanuvchi <code>{new_id}</code> ruxsat etilganlar ro'yxatiga qo'shildi!", reply_markup=ReplyKeyboardRemove())
    else:
        await msg.answer(f"⚠️ Ushbu ID <code>{new_id}</code> allaqachon ro'yxatda bor.", reply_markup=ReplyKeyboardRemove())
    await state.clear()
    await show_admin_panel(msg)


@router.callback_query(F.data == "admin_del_user")
async def admin_del_user_start(cq: CallbackQuery):
    if not check_admin(cq.from_user.id):
        return await cq.answer("⛔ Ruxsat yo'q", show_alert=True)
    users = db.get_all_allowed_users()
    if not users:
        return await cq.answer("Ro'yxat bo'sh", show_alert=True)
    
    buttons = []
    for uid in users:
        buttons.append((f"❌ {uid}", f"admin_del_confirm_{uid}"))
    buttons.append(("◀️ Orqaga", "admin_back"))
    
    await cq.message.edit_text("🗑 O'chirmoqchi bo'lgan foydalanuvchi ID sini tanlang:", reply_markup=ik(*buttons))
    await cq.answer()


@router.callback_query(F.data.startswith("admin_del_confirm_"))
async def admin_del_user_exec(cq: CallbackQuery):
    if not check_admin(cq.from_user.id):
        return await cq.answer("⛔ Ruxsat yo'q", show_alert=True)
    target_id = int(cq.data.split("_")[-1])
    if db.remove_allowed_user(target_id):
        await cq.answer("✅ Foydalanuvchi o'chirildi!", show_alert=True)
    else:
        await cq.answer("⚠️ Topilmadi", show_alert=True)
    await show_admin_panel(cq)


@router.callback_query(F.data == "admin_edit_limit")
async def admin_edit_limit_start(cq: CallbackQuery, state: FSMContext):
    if not check_admin(cq.from_user.id):
        return await cq.answer("⛔ Ruxsat yo'q", show_alert=True)
    current = get_max_accounts()
    await cq.message.answer(f"⚙️ Hozirgi akkauntlar limiti: <b>{current} ta</b>.\n\nYangi limit sonini kiriting (masalan: 5, 10, 50):", reply_markup=cancel_kb())
    await state.set_state(AdminStates.waiting_limit)
    await cq.answer()


@router.message(AdminStates.waiting_limit)
async def admin_save_limit(msg: Message, state: FSMContext):
    if not check_admin(msg.from_user.id):
        return
    text = msg.text.strip()
    if not text.isdigit() or int(text) < 1:
        await msg.answer("❌ Musbat son kiriting (masalan: 20):")
        return
    new_limit = int(text)
    db.set_setting("max_accounts", str(new_limit))
    await msg.answer(f"✅ Akkauntlar limiti <b>{new_limit} ta</b> qilib o'rnatildi!", reply_markup=ReplyKeyboardRemove())
    await state.clear()
    await show_admin_panel(msg)


@router.callback_query(F.data == "admin_edit_pass")
async def admin_edit_pass_start(cq: CallbackQuery, state: FSMContext):
    if not check_admin(cq.from_user.id):
        return await cq.answer("⛔ Ruxsat yo'q", show_alert=True)
    await cq.message.answer("🔑 Yangi maxfiy parolni kiriting (kamida 4 ta belgi):", reply_markup=cancel_kb())
    await state.set_state(AdminStates.waiting_new_pass)
    await cq.answer()


@router.message(AdminStates.waiting_new_pass)
async def admin_save_pass(msg: Message, state: FSMContext):
    if not check_admin(msg.from_user.id):
        return
    new_pass = msg.text.strip()
    if len(new_pass) < 4:
        await msg.answer("❌ Parol kamida 4 ta belgidan iborat bo'lishi kerak. Qaytadan kiriting:")
        return
    db.set_setting("admin_password", new_pass)
    await msg.answer(f"✅ Maxfiy parol o'zgartirildi!\n\nYangi parol: <code>{new_pass}</code>", reply_markup=ReplyKeyboardRemove())
    await state.clear()
    await show_admin_panel(msg)


@router.callback_query(F.data == "admin_close")
async def admin_close_panel(cq: CallbackQuery):
    if not check_admin(cq.from_user.id):
        return await cq.answer("⛔ Ruxsat yo'q", show_alert=True)
    await cq.message.delete()
    await cq.answer("🔒 Maxfiy Admin Panel yopildi.")


@router.callback_query(F.data == "admin_back")
async def admin_back_menu(cq: CallbackQuery):
    if not check_admin(cq.from_user.id):
        return await cq.answer("⛔ Ruxsat yo'q", show_alert=True)
    await show_admin_panel(cq)


@router.callback_query(F.data == "admin_edit_help")
async def admin_edit_help_start(cq: CallbackQuery, state: FSMContext):
    if not check_admin(cq.from_user.id):
        return await cq.answer("⛔ Ruxsat yo'q", show_alert=True)
    await cq.message.answer(
        "📝 <b>/yordam (Qo'llanma) matnini tahrirlash</b>\n\n"
        "Yangi matnni (HTML formatda) yuboring.\n"
        "<i>Eski standart (default) holatiga qaytarish uchun /default buyrug'ini yuboring.</i>",
        reply_markup=cancel_kb()
    )
    await state.set_state(AdminStates.waiting_new_help)
    await cq.answer()


@router.message(AdminStates.waiting_new_help)
async def admin_save_help(msg: Message, state: FSMContext):
    if not check_admin(msg.from_user.id):
        return
    if msg.text and msg.text.strip() == "/default":
        db.set_setting("help_text", DEFAULT_HELP_TEXT)
        await msg.answer("✅ /yordam matni standart (default) holatga qaytarildi!", reply_markup=ReplyKeyboardRemove())
    else:
        new_text = msg.html_text if hasattr(msg, 'html_text') and msg.html_text else msg.text
        db.set_setting("help_text", new_text)
        await msg.answer("✅ /yordam qo'llanma matni yangilandi!", reply_markup=ReplyKeyboardRemove())
    await state.clear()
    await show_admin_panel(msg)


# --- Aqlli Ogohlantirishlar Callback Handlerlari ---

@router.callback_query(F.data.startswith("err_del_grp_"))
async def err_del_grp_handler(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer("⛔ Ruxsat yo'q", show_alert=True)
    grp_id = int(cq.data.split("_")[-1])
    if db.remove_group_complete(grp_id):
        await cq.message.edit_text("✅ <b>Guruh barcha kampaniyalardan va ro'yxatingizdan to'liq o'chirildi!</b>\n\nXatolar to'xtatildi. Statistikangiz toza bo'ladi.")
    else:
        await cq.message.edit_text("ℹ️ Guruh allaqachon o'chirilgan yoki topilmadi.")
    await cq.answer()


@router.callback_query(F.data.startswith("err_mute_grp_"))
async def err_mute_grp_handler(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer("⛔ Ruxsat yo'q", show_alert=True)
    grp_id = int(cq.data.split("_")[-1])
    import time
    mute_until = time.time() + 86400
    db.set_setting(f"mute_group_{grp_id}", str(mute_until))
    await cq.message.edit_text("💤 <b>Guruh 24 soatga uyqu rejimiga o'tkazildi!</b>\n\nBot bu guruhga 24 soat davomida boshqa xabar yubormaydi va xato ham yozmaydi.")
    await cq.answer()


@router.callback_query(F.data.startswith("err_del_acc_"))
async def err_del_acc_handler(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer("⛔ Ruxsat yo'q", show_alert=True)
    acc_id = int(cq.data.split("_")[-1])
    db.remove_account(acc_id, cq.from_user.id)
    await cq.message.edit_text("✅ <b>Sessiyasi o'chgan akkaunt ro'yxatdan o'chirildi!</b>\n\nEndi bot faqat faol akkauntlar bilan ishlaydi. Istasangiz, ➕ Akkaunt ulash orqali yangilashingiz mumkin.")
    await cq.answer()
