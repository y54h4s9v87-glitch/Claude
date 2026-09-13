"""SQLite storage. One file, no server, no dependencies.

Set WHOLESALE_DB to move the database. It defaults to ~/.wholesale/deals.db
so your pipeline survives moving between directories.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1

STATUSES = (
    "lead",          # found it, nothing done yet
    "screening",     # running comps / repair numbers
    "contacted",     # outreach sent
    "negotiating",   # offers going back and forth
    "under_contract",
    "marketing",     # assigning: equitable interest is out to buyers
    "assigned",
    "closed",
    "dead",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    address         TEXT NOT NULL,
    city            TEXT,
    state           TEXT DEFAULT 'NJ',
    county          TEXT,
    property_type   TEXT,
    beds            INTEGER,
    baths           REAL,
    sqft            INTEGER,
    asking          REAL,
    arv             REAL,
    repairs         REAL,
    repair_tier     TEXT,
    assignment_fee  REAL,
    buyer_discount  REAL,
    closing_costs   REAL DEFAULT 0,
    days_on_market  INTEGER,
    price_cuts      INTEGER DEFAULT 0,
    vacant          INTEGER DEFAULT 0,
    fsbo            INTEGER DEFAULT 0,
    agent_name      TEXT,
    agent_phone     TEXT,
    agent_email     TEXT,
    seller_name     TEXT,
    source          TEXT,
    listing_url     TEXT,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'lead',
    contract_price  REAL,
    notes           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE(address, city)
);

CREATE TABLE IF NOT EXISTS comps (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id       INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    address       TEXT NOT NULL,
    sold_price    REAL NOT NULL,
    sqft          INTEGER,
    sold_date     TEXT,
    same_building INTEGER DEFAULT 0,
    same_street   INTEGER DEFAULT 0,
    renovated     INTEGER DEFAULT 0,
    note          TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS buyers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    company        TEXT,
    phone          TEXT,
    email          TEXT,
    markets        TEXT,            -- comma separated towns/counties
    property_types TEXT,            -- comma separated
    min_price      REAL DEFAULT 0,
    max_price      REAL,
    max_repairs    REAL,
    buyer_discount REAL,
    proof_of_funds INTEGER DEFAULT 0,
    deals_closed   INTEGER DEFAULT 0,
    notes          TEXT,
    active         INTEGER DEFAULT 1,
    created_at     TEXT NOT NULL,
    UNIQUE(name, phone)
);

CREATE TABLE IF NOT EXISTS activity (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id    INTEGER REFERENCES deals(id) ON DELETE CASCADE,
    buyer_id   INTEGER REFERENCES buyers(id) ON DELETE SET NULL,
    kind       TEXT NOT NULL,      -- call, text, email, offer, note, status
    detail     TEXT,
    amount     REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checklist (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id    INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    item_key   TEXT NOT NULL,
    done       INTEGER DEFAULT 0,
    done_at    TEXT,
    UNIQUE(deal_id, item_key)
);

CREATE INDEX IF NOT EXISTS idx_deals_status ON deals(status);
CREATE INDEX IF NOT EXISTS idx_comps_deal ON comps(deal_id);
CREATE INDEX IF NOT EXISTS idx_activity_deal ON activity(deal_id);
"""


def default_db_path() -> Path:
    env = os.environ.get("WHOLESALE_DB")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".wholesale" / "deals.db"


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    db_path = Path(path).expanduser() if path else default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def log(
    conn: sqlite3.Connection,
    *,
    deal_id: int | None = None,
    buyer_id: int | None = None,
    kind: str = "note",
    detail: str = "",
    amount: float | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO activity (deal_id, buyer_id, kind, detail, amount, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (deal_id, buyer_id, kind, detail, amount, now()),
    )
    conn.commit()
    return int(cur.lastrowid)
