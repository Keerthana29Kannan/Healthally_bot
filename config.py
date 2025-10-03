import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("Please set TELEGRAM_TOKEN in .env")

DB_NAME = os.getenv("DB_NAME", "healthbot.db")
# default timezone (India) — user is not asked for timezone
DEFAULT_TZ = "Asia/Kolkata"

# Daily exercise reminder time (24h)
EXERCISE_REMINDER_HOUR = 17
EXERCISE_REMINDER_MINUTE = 0
