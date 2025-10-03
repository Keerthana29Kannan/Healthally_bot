import sqlite3
import json
from datetime import datetime, date
from typing import List, Optional
from config import DB_NAME

def get_conn():
    # use separate connections per thread/call
    conn = sqlite3.connect(DB_NAME, detect_types=sqlite3.PARSE_DECLTYPES|sqlite3.PARSE_COLNAMES)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
      CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT
      )
    """)
    c.execute("""
      CREATE TABLE IF NOT EXISTS exercises (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT,
        minutes REAL,
        date TEXT,
        created_at TEXT DEFAULT (datetime('now'))
      )
    """)
    c.execute("""
      CREATE TABLE IF NOT EXISTS medicines (
        med_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT,
        dose TEXT,
        times TEXT,            -- JSON array of "HH:MM" strings
        created_at TEXT DEFAULT (datetime('now'))
      )
    """)
    c.execute("""
      CREATE TABLE IF NOT EXISTS med_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        med_id INTEGER,
        user_id INTEGER,
        scheduled_time TEXT,
        status TEXT,           -- 'taken' or 'missed'
        logged_at TEXT DEFAULT (datetime('now'))
      )
    """)
    conn.commit()
    conn.close()

def add_user(user_id: int, username: Optional[str]):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)", (user_id, username))
    conn.commit()
    conn.close()

def list_users():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id, username FROM users")
    rows = cur.fetchall()
    conn.close()
    return rows

def add_exercise(user_id: int, name: str, minutes: float, for_date: Optional[str] = None):
    d = for_date or date.today().isoformat()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, minutes FROM exercises WHERE user_id=? AND name=? AND date=?", (user_id, name.lower(), d))
    row = cur.fetchone()
    if row:
        new_minutes = (row["minutes"] or 0) + minutes
        cur.execute("UPDATE exercises SET minutes=?, created_at=datetime('now') WHERE id=?", (new_minutes, row["id"]))
    else:
        cur.execute("INSERT INTO exercises (user_id, name, minutes, date) VALUES (?,?,?,?)",
                    (user_id, name.lower(), minutes, d))
    conn.commit()
    conn.close()

def list_recent_exercises(user_id: int, days: int = 14):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
      SELECT id, name, minutes, date
      FROM exercises
      WHERE user_id=?
      ORDER BY date DESC, id DESC
      LIMIT 200
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def delete_exercise(entry_id: int, user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM exercises WHERE id=? AND user_id=?", (entry_id, user_id))
    conn.commit()
    conn.close()

def exercises_summary_last_7_days(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
      SELECT date, SUM(minutes) as total_minutes
      FROM exercises
      WHERE user_id=? AND date >= date('now','-6 days')
      GROUP BY date
      ORDER BY date DESC
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return [(r["date"], int(r["total_minutes"] or 0)) for r in rows]

def total_minutes_last_7_days(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
      SELECT SUM(minutes) as total FROM exercises
      WHERE user_id=? AND date >= date('now','-6 days')
    """, (user_id,))
    row = cur.fetchone()
    conn.close()
    return int(row["total"] or 0)

def days_exercised_last_7_days(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
      SELECT COUNT(DISTINCT date) as days FROM exercises
      WHERE user_id=? AND date >= date('now','-6 days')
    """, (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["days"] or 0

def most_common_activity_last_7_days(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
      SELECT name, SUM(minutes) as total FROM exercises
      WHERE user_id=? AND date >= date('now','-6 days')
      GROUP BY name ORDER BY total DESC LIMIT 1
    """, (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["name"] if row else None

def add_medicine(user_id: int, name: str, dose: str, times_list: List[str]) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO medicines (user_id, name, dose, times) VALUES (?,?,?,?)",
                (user_id, name.strip(), dose.strip(), json.dumps(times_list)))
    med_id = cur.lastrowid
    conn.commit()
    conn.close()
    return med_id

def list_medicines(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT med_id, name, dose, times, created_at FROM medicines WHERE user_id=? ORDER BY med_id", (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def get_medicine(med_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM medicines WHERE med_id=?", (med_id,))
    row = cur.fetchone()
    conn.close()
    return row

def delete_medicine(med_id: int, user_id: int):
    # delete the med row (we keep med_logs history intact)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM medicines WHERE med_id=? AND user_id=?", (med_id, user_id))
    conn.commit()
    conn.close()

# MED LOGS
def log_med_status(med_id: int, user_id: int, scheduled_short: str, status: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO med_logs (med_id, user_id, scheduled_time, status) VALUES (?,?,?,?)",
                (med_id, user_id, scheduled_short, status))
    conn.commit()
    conn.close()

def taken_count_last_7_days(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
      SELECT COUNT(*) as taken FROM med_logs
      WHERE user_id=? AND status='taken' AND logged_at >= datetime('now','-7 days')
    """, (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["taken"] or 0

def expected_doses_last_7_days(user_id: int):
    """Estimate expected doses in last 7 days based on medicine created_at and times count."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT times, created_at FROM medicines WHERE user_id=?", (user_id,))
    rows = cur.fetchall()
    conn.close()
    total_expected = 0
    today = datetime.utcnow().date()
    for r in rows:
        times = json.loads(r["times"] or "[]")
        if not times:
            continue
        # parse created_at to date
        try:
            created_dt = datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S")
        except Exception:
            try:
                created_dt = datetime.fromisoformat(r["created_at"])
            except Exception:
                created_dt = datetime.utcnow()
        created_date = created_dt.date()
        days_active = (today - created_date).days + 1
        if days_active < 0:
            days_active = 0
        days_count = min(7, days_active)
        total_expected += days_count * len(times)
    return total_expected
