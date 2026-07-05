import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN   = os.getenv("BOT_TOKEN", "")
API_ID      = int(os.getenv("API_ID", "0"))
API_HASH    = os.getenv("API_HASH", "")

# Ruxsat etilgan 5 ta foydalanuvchi Telegram ID lari
ALLOWED_USERS: list[int] = [
    int(x.strip()) for x in os.getenv("ALLOWED_USERS", "").split(",")
    if x.strip().isdigit()
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_DIR = os.getenv("SESSION_DIR", os.path.join(BASE_DIR, "sessions"))
MAX_ACCOUNTS_PER_USER = 20
