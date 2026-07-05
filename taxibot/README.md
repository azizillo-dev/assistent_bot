# 🚖 TaxiAutoPost Bot

Faqat **3 ta foydalanuvchi** uchun. Har biri o'z Telegram akkauntlaridan (max 20 ta)
o'z guruhlariga avtomatik xabar yuboradi.

---

## O'rnatish

### 1. Python va kutubxonalar

```bash
python -m venv .venv

# Windows:
.venv\Scripts\activate

# Linux/Mac:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. .env fayl yaratish

```bash
cp .env.example .env
```

`.env` ni oching va to'ldiring:

```
BOT_TOKEN=     ← @BotFather dan oling
API_ID=        ← https://my.telegram.org/apps dan
API_HASH=      ← https://my.telegram.org/apps dan
ALLOWED_USERS= ← 3 ta Telegram ID (vergul bilan)
```

> **Telegram ID bilish:** @userinfobot ga /start yuboring

### 3. Ishga tushirish

```bash
python main.py
```

---

## Foydalanish

1. Botga `/start` yuboring
2. **📱 Akkauntlar** — telefon raqam kiriting, kod bilan tasdiqlang
3. **👥 Guruhlar** — `@username` yoki `-1001234567890` formatida guruh qo'shing
4. **📢 Kampaniyalar** — yangi kampaniya yarating:
   - Nom, matn, interval (minutda) kiriting
   - Akkauntlar va guruhlarni tanlang
5. Bot avtomatik ishlaydi!

---

## Xususiyatlar

- ✅ 20 tagacha akkaunt ulash
- ✅ Cheklanmagan guruhlar
- ✅ Timer bor guruhni o'tkazib, keyinroq qayta urinadi
- ✅ Ko'rinmas watermark (spam blokdan himoya)
- ✅ FloodWait va SlowMode avtomatik boshqaruvi
- ✅ Kampaniyani to'xtatish/ishga tushirish
- ✅ SQLite — hech qanday server kerak emas

---

## Fayl tuzilmasi

```
taxibot/
├── main.py          ← Asosiy fayl
├── config.py        ← Sozlamalar
├── db.py            ← SQLite ma'lumotlar bazasi
├── handlers.py      ← Bot handlerlari (UI)
├── scheduler.py     ← Kampaniyalarni vaqtida ishga tushirish
├── sender.py        ← Telethon orqali xabar yuborish
├── sessions_mgr.py  ← Akkaunt sessiyalarini boshqarish
├── requirements.txt
├── .env.example
├── sessions/        ← Telethon session fayllari (auto yaratiladi)
└── data/
    ├── bot.db       ← SQLite bazasi (auto yaratiladi)
    └── bot.log      ← Log fayli
```

---

## Muhim eslatmalar

- `sessions/` va `data/` papkalarini hech kimga bermang — akkaunt ma'lumotlari bor
- `.env` ni hech kimga ko'rsatmang
- Bot serverda doim yoniq turishi kerak (yoki `screen`/`pm2` ishlating)

### Screen bilan ishga tushirish (Linux):
```bash
screen -S taxibot
python main.py
# Ctrl+A, D — foniga o'tkazish
```
