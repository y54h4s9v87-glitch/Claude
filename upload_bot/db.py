"""SQLite queue: videos and one upload job per (video, account)."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

JOB_STATUSES = ("pending", "scheduled", "failed", "cancelled")

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    added_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY,
    video_id    INTEGER NOT NULL REFERENCES videos(id),
    account_id  TEXT NOT NULL,
    platform    TEXT NOT NULL,
    slot        TEXT NOT NULL,          -- 'YYYY-MM-DD HH:MM' local wall clock, as posted
    base_slot   TEXT,                   -- the schedule slot before jitter
    title       TEXT NOT NULL,
    caption     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    attempts    INTEGER NOT NULL DEFAULT 0,
    result_url  TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL,
    UNIQUE (video_id, account_id)
);
CREATE INDEX IF NOT EXISTS jobs_account_slot ON jobs(account_id, slot);
"""

FMT = "%Y-%m-%d %H:%M"


def stamp(dt: datetime) -> str:
    return dt.strftime(FMT)


def unstamp(s: str) -> datetime:
    return datetime.strptime(s, FMT)


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    if "base_slot" not in cols:  # databases made before jitter existed
        conn.execute("ALTER TABLE jobs ADD COLUMN base_slot TEXT")
        conn.commit()
    return conn


def taken_slots(conn: sqlite3.Connection, account_id: str, exclude_job: int | None = None) -> list[datetime]:
    rows = conn.execute(
        "SELECT id, COALESCE(base_slot, slot) AS slot FROM jobs"
        " WHERE account_id = ? AND status IN ('pending','scheduled')",
        (account_id,),
    ).fetchall()
    return [unstamp(r["slot"]) for r in rows if r["id"] != exclude_job]


def set_status(conn, job_id: int, status: str, *, url: str = "", note: str = "", now: datetime) -> None:
    assert status in JOB_STATUSES
    cur = conn.execute(
        """UPDATE jobs SET status = ?, result_url = CASE WHEN ? != '' THEN ? ELSE result_url END,
           note = ?, updated_at = ?, attempts = attempts + CASE WHEN ? IN ('scheduled','failed') THEN 1 ELSE 0 END
           WHERE id = ?""",
        (status, url, url, note, stamp(now), status, job_id),
    )
    if cur.rowcount == 0:
        raise KeyError(job_id)
    conn.commit()
