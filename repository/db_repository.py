import sqlite3
import os
from main import ROOT

DB_PATH = os.environ.get("JOBSEEKER_DB", os.path.join(ROOT, "JobSeeker.db"))

"""
KV(prefs, ) -> Your search keywords
KV(last_search_key, )
KV(cv_extra, )

If you generate a CV for a job, will store it.
"""


SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT, 
  title TEXT, 
  company TEXT, 
  location TEXT, 
  url TEXT,
  listed_at TEXT, 
  status TEXT DEFAULT 'new', 
  jd TEXT DEFAULT '',
  applied_at TEXT DEFAULT '', 
  notes TEXT DEFAULT '',
  UNIQUE(company, title)
);
CREATE TABLE IF NOT EXISTS generations (
  job_id INTEGER PRIMARY KEY, 
  cv TEXT, 
  cover_letter TEXT, 
  added TEXT DEFAULT ''
);
"""


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # ponytail: 已有的库不会被 CREATE TABLE IF NOT EXISTS 补列，加一次就够，加过会报错直接吞掉
    for table, col in (("jobs", "applied_at"), ("jobs", "notes"), ("generations", "added")):
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
    return conn


def kv_get(conn, key):
    row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return row["value"] if row else ""


def kv_set(conn, key, value):
    conn.execute(
        "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value))
    conn.commit()


def upsert_job(conn, source, title, company, location, url, listed_at):
    conn.execute(
        """INSERT INTO jobs(source,title,company,location,url,listed_at)
        VALUES(?,?,?,?,?,?) ON CONFLICT(company,title) DO NOTHING""",
        (source, title.strip(), company.strip(), location, url, listed_at))
    conn.commit()
    return conn.execute("SELECT id FROM jobs WHERE company=? AND title=?",
                        (company.strip(), title.strip())).fetchone()["id"]