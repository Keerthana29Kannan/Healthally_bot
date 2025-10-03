import json
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from config import TELEGRAM_TOKEN, DEFAULT_TZ, EXERCISE_REMINDER_HOUR, EXERCISE_REMINDER_MINUTE
import db

bot = Bot(token=TELEGRAM_TOKEN)
scheduler = BackgroundScheduler()
scheduler.start()

# helper to create short timestamp for callback (YYYYMMDDHHMM)in
def short_now_tz(tzname=DEFAULT_TZ):
    tz = pytz.timezone(tzname)
    return datetime.now(tz).strftime("%Y%m%d%H%M")

def send_med_reminder(med_id: int, user_id: int, med_name: str, dose: str):
    sched_short = short_now_tz()
    text = f"💊 Time to take *{med_name}* ({dose}) 💊."
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Taken ✅", callback_data=f"MED|{med_id}|{sched_short}|taken"),
        InlineKeyboardButton("Missed ❌", callback_data=f"MED|{med_id}|{sched_short}|missed"),
    ]])
    bot.send_message(chat_id=user_id, text=text, reply_markup=kb, parse_mode="Markdown")

def schedule_med_jobs_for_med(med_row):
    """med_row is sqlite Row with med_id, user_id, name, dose, times"""
    times = json.loads(med_row["times"] or "[]")
    tzname = DEFAULT_TZ
    for t in times:
        hour, minute = map(int, t.split(":"))
        job_id = f"med_{med_row['med_id']}_{t}"
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass
        trigger = CronTrigger(hour=hour, minute=minute, timezone=pytz.timezone(tzname))
        scheduler.add_job(send_med_reminder, trigger, id=job_id, replace_existing=True,
                          args=[med_row["med_id"], med_row["user_id"], med_row["name"], med_row["dose"]])

def remove_med_jobs(med_id: int):
    jobs = scheduler.get_jobs()
    prefix = f"med_{med_id}_"
    for j in jobs:
        if j.id.startswith(prefix):
            try:
                scheduler.remove_job(j.id)
            except Exception:
                pass

def schedule_all_meds_for_all_users():
    meds = []
    users = db.list_users()
    for u in users:
        meds += db.list_medicines(u["user_id"])
    for med_row in meds:
        schedule_med_jobs_for_med(med_row)

# DAILY exercise reminder -> sends to every user at configured time
def send_daily_exercise_reminder():
    now_short = short_now_tz()
    users = db.list_users()
    for u in users:
        text = "🏃‍♀️ Did you complete your exercise today? Reply with the buttons.\n\nIf you already exercised, press ✅ Done. If not, press ❌ Skip. It's time to stretch some muscles!"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("Done ✅", callback_data=f"EX|{u['user_id']}|{now_short}|done"),
            InlineKeyboardButton("Skip ❌", callback_data=f"EX|{u['user_id']}|{now_short}|skip"),
        ]])
        try:
            bot.send_message(chat_id=u["user_id"], text=text, reply_markup=kb)
        except Exception:
            # user may not have started bot or blocked it
            pass

def schedule_daily_exercise():
    job_id = "daily_exercise_reminder"
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass
    tz = pytz.timezone(DEFAULT_TZ)
    trigger = CronTrigger(hour=EXERCISE_REMINDER_HOUR, minute=EXERCISE_REMINDER_MINUTE, timezone=tz)
    scheduler.add_job(send_daily_exercise_reminder, trigger, id=job_id, replace_existing=True)
