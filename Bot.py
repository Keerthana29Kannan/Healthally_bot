# Bot.py
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    ConversationHandler, CallbackQueryHandler
)
from telegram import ReplyKeyboardRemove
import logging
import re
from datetime import datetime
import json

import db
import scheduler
from config import TELEGRAM_TOKEN, DEFAULT_TZ

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Conversation states
MED_NAME, MED_DOSE, MED_TIMES = range(3)
EX_NAME, EX_QTY = range(3, 5)
DEL_MED, DEL_EX = range(5, 7)

# Helpers
def parse_times_input(text):
    """
    Accepts inputs like:
      "9am,9pm", "09:00,21:00", "10pm", "9:30pm 21:00"
    Returns list of "HH:MM" strings (24-hour).
    """
    parts = [p.strip() for p in re.split(r'[,\s]+', text) if p.strip()]
    out = []
    for p in parts:
        try:
            low = p.lower()
            # am/pm forms: 9am, 9pm, 9:30pm
            m = re.match(r'^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$', low)
            if m:
                hour = int(m.group(1))
                minute = int(m.group(2) or 0)
                ampm = m.group(3)
                if ampm == 'pm' and hour != 12:
                    hour += 12
                if ampm == 'am' and hour == 12:
                    hour = 0
                out.append(f"{hour:02d}:{minute:02d}")
                continue
            # HH:MM format
            m2 = re.match(r'^(\d{1,2}):(\d{2})$', p)
            if m2:
                h = int(m2.group(1)); mi = int(m2.group(2))
                if 0 <= h < 24 and 0 <= mi < 60:
                    out.append(f"{h:02d}:{mi:02d}")
                    continue
            # single hour number e.g., "9" -> 09:00
            m3 = re.match(r'^(\d{1,2})$', p)
            if m3:
                h = int(m3.group(1))
                if 0 <= h < 24:
                    out.append(f"{h:02d}:00")
                    continue
            raise ValueError("unrecognized")
        except Exception:
            raise ValueError(f"Couldn't parse time token: {p}")
    return out

def parse_quantity_input(text):
    """
      Accept strings like:
      "45" -> (45, 'mins')
      "30 mins" -> (30, 'mins')
    Returns (number, unit)
    """
    s = text.strip().lower()
    m = re.match(r'^(\d+(?:\.\d+)?)(?:\s*(mins?|minutes?|m))?$', s)
    if m:
        return float(m.group(1)), 'mins'
    m2 = re.search(r'(\d+(?:\.\d+)?)', s)
    if m2:
        return float(m2.group(1)), 'mins'
    raise ValueError("Couldn't parse quantity")

# ---------------- Handlers ----------------
def start(update, context):
    user = update.effective_user
    db.add_user(user.id, user.username)
    update.message.reply_text(
        "Hello 👋 — Healthally here!\n\n"
        "Commands:\n"
        "/add_medicine - log your medicine in the format(name → dose → times) to get scheduled reminders\n"
        "/log_exercise - log exercise routine in the format (name → minutes) and track your self progress\n"
        "/delete_medicine - cancel future reminders for a medicine\n"
        "/delete_exercise - delete a logged exercise entry\n"
        "/progress - simple weekly summary of medicine intake and exercise routine.\n"
    )

# ---- Medicine flow ----
def add_med_start(update, context):
    update.message.reply_text("Medicine name? (e.g., Paracetamol)")
    return MED_NAME

def add_med_dose(update, context):
    context.user_data['med_name'] = update.message.text.strip()
    update.message.reply_text("Dose? (e.g., 500 mg or 1 tablet)")
    return MED_DOSE

def med_ask_times(update, context):
    context.user_data['med_dose'] = update.message.text.strip()
    update.message.reply_text("Suggest time for the reminder as comma-separated. e.g., 09:00, 21:00 or 9am, 9pm")
    return MED_TIMES


def add_med_times(update, context):
    user_input = update.message.text.strip()
    try:
        times = parse_times_input(user_input)
    except ValueError as e:
        update.message.reply_text("⚠️ Couldn't understand time(s). Try like: 09:00, 21:00 or 9am, 9pm or 10pm")
        return MED_TIMES

    user_id = update.effective_user.id
    med_name = context.user_data.get('med_name')
    med_dose = context.user_data.get('med_dose', '').strip()

    med_id = db.add_medicine(user_id, med_name, med_dose, times)

    med_row = db.get_medicine(med_id)
    if med_row:
        scheduler.schedule_med_jobs_for_med(med_row)

    update.message.reply_text(f"Saved medicine #{med_id}: {med_name} ({med_dose}) at {', '.join(times)} daily ✅ .")
    return ConversationHandler.END

def ex_start(update, context):
    update.message.reply_text("What exercise did you do? (e.g., cycling, pushups)")
    return EX_NAME

def ex_qty(update, context):
    context.user_data['ex_name'] = update.message.text.strip().lower()
    update.message.reply_text("Duration of the exercise today? (e.g., 45 or 45 mins)")
    return EX_QTY

def ex_save(update, context):
    user_input = update.message.text.strip()
    try:
        qty, unit = parse_quantity_input(user_input)
    except ValueError:
        update.message.reply_text("Couldn't parse duration. Enter a number (e.g., 45).")
        return EX_QTY

    user_id = update.effective_user.id
    name = context.user_data.get('ex_name', 'exercise')


    stored_name = name
    minutes = float(qty)

    db.add_exercise(user_id, stored_name, minutes)
    update.message.reply_text(f"✅ Logged {int(qty)} {unit} for {name} today. (You can log as many times for the same exercise or different exercise as you wish)")
    return ConversationHandler.END

def delete_med_start(update, context):
    meds = db.list_medicines(update.effective_user.id)
    if not meds:
        update.message.reply_text("You have no active medicines.")
        return ConversationHandler.END
    lines = []
    for m in meds:
        try:
            times = json.loads(m['times'] or "[]")
        except Exception:
            times = [m['times']]
        lines.append(f"{m['med_id']}) {m['name']} ({m['dose']}) — times: {', '.join(times)}")
    update.message.reply_text("Reply with the medicine ID to cancel future reminders:\n\n" + "\n".join(lines))
    return DEL_MED

def delete_med_confirm(update, context):
    s = update.message.text.strip()
    try:
        med_id = int(s)
    except Exception:
        update.message.reply_text("Please reply with a numeric medicine ID.")
        return DEL_MED
    user_id = update.effective_user.id
    # remove scheduled jobs
    scheduler.remove_med_jobs(med_id)
    db.delete_medicine(med_id, user_id)
    update.message.reply_text(f"Cancelled future reminders for medicine #{med_id} ✅. ")
    return ConversationHandler.END

def delete_ex_start(update, context):
    rows = db.list_recent_exercises(update.effective_user.id)
    if not rows:
        update.message.reply_text("No exercise entries found.")
        return ConversationHandler.END
    lines = []
    for r in rows[:20]:
        lines.append(f"{r['id']}) {r['date']} — {int(r['minutes'])} mins {r['name']}")
    update.message.reply_text("Reply with the entry ID to delete:\n\n" + "\n".join(lines))
    return DEL_EX

def delete_ex_confirm(update, context):
    s = update.message.text.strip()
    try:
        entry_id = int(s)
    except Exception:
        update.message.reply_text("Please reply with a numeric entry ID.")
        return DEL_EX
    user_id = update.effective_user.id
    db.delete_exercise(entry_id, user_id)
    update.message.reply_text("✅ Deleted exercise entry.")
    return ConversationHandler.END


def on_callback(update, context):
    q = update.callback_query
    q.answer()
    data = q.data  
    try:
        parts = data.split("|")
        if parts[0] == "MED":
            med_id = int(parts[1])
            sched_short = parts[2]
            status = parts[3]
            user_id = q.from_user.id
            db.log_med_status(med_id, user_id, sched_short, status)
            q.edit_message_text(f"Logged: {status.upper()} ✅")
        elif parts[0] == "EX":
            action = parts[3]
            if action == "done":
                q.edit_message_text("Great! keep going on the fitness streak 🎯💪")
            else:
                q.edit_message_text("No worries! Try a short session later — even 10 minutes helps. Remember, any amount of physical activity is better than none 💪")
        else:
            q.edit_message_text("Unknown callback")
    except Exception:
        logger.exception("callback error")
        q.edit_message_text("Error processing button. Try again.")

def progress(update, context):
    user_id = update.effective_user.id
    days = db.days_exercised_last_7_days(user_id)
    total_minutes = db.total_minutes_last_7_days(user_id)
    most_common = db.most_common_activity_last_7_days(user_id) or "—"
    taken = db.taken_count_last_7_days(user_id)
    expected = db.expected_doses_last_7_days(user_id)
    pct = int((taken * 100 / expected)) if expected else 0
    update.message.reply_text(
        f"📊 Last 7 days summary:\n"
        f"• Exercise days: {days}\n"
        f"• Total minutes: {total_minutes}\n"
        f"• Most common activity: {most_common}\n"
        f"• Medicine adherence: {taken}/{expected} ({pct}%)"
    )

def cancel(update, context):
    update.message.reply_text("Cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def main():
    db.init_db()
    # schedule existing meds & daily exercise reminder
    try:
        scheduler.schedule_all_meds_for_all_users()
        scheduler.schedule_daily_exercise()
    except Exception:
        logger.exception("Scheduling startup jobs failed (check scheduler).")

    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))



    # add medicine conversation
    dp.add_handler(ConversationHandler(
        entry_points=[CommandHandler("add_medicine", add_med_start)],
        states={
            MED_NAME: [MessageHandler(Filters.text & ~Filters.command, add_med_dose)],
            MED_DOSE: [MessageHandler(Filters.text & ~Filters.command, med_ask_times)],
            MED_TIMES: [MessageHandler(Filters.text & ~Filters.command, add_med_times)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    ))

    # log exercise conversation
    dp.add_handler(ConversationHandler(
        entry_points=[CommandHandler("log_exercise", ex_start)],
        states={
            EX_NAME: [MessageHandler(Filters.text & ~Filters.command, ex_qty)],
            EX_QTY: [MessageHandler(Filters.text & ~Filters.command, ex_save)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    ))

    # delete medicine
    dp.add_handler(ConversationHandler(
        entry_points=[CommandHandler("delete_medicine", delete_med_start)],
        states={DEL_MED: [MessageHandler(Filters.text & ~Filters.command, delete_med_confirm)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    ))

    # delete exercise
    dp.add_handler(ConversationHandler(
        entry_points=[CommandHandler("delete_exercise", delete_ex_start)],
        states={DEL_EX: [MessageHandler(Filters.text & ~Filters.command, delete_ex_confirm)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    ))

    # callback handler
    dp.add_handler(CallbackQueryHandler(on_callback))

    # progress command
    dp.add_handler(CommandHandler("progress", progress))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
