"""SQLite storage for the Campus Customs shop. Seeded with demo data on first run."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.environ.get("CAMPUS_CUSTOMS_DB", Path(__file__).resolve().parent.parent / "data" / "shop.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY, name TEXT, org TEXT, email TEXT
);
CREATE TABLE IF NOT EXISTS products (
    sku TEXT PRIMARY KEY, name TEXT, base_price REAL, stock INTEGER, reorder_point INTEGER, vendor TEXT
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY, customer_id TEXT, items TEXT, status TEXT, due_date TEXT,
    total REAL, notes TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS vendors (
    name TEXT PRIMARY KEY, contact TEXT, lead_time_days INTEGER, specialty TEXT
);
-- Drafts are never sent anywhere. They exist only on the dashboard board.
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, recipient TEXT, subject TEXT, body TEXT,
    related_order TEXT, author_agent TEXT, status TEXT DEFAULT 'draft', created_at TEXT
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, summary TEXT, payload TEXT,
    requested_by TEXT, status TEXT DEFAULT 'pending', decision_note TEXT,
    created_at TEXT, decided_at TEXT
);
"""

SEED_CUSTOMERS = [
    ("C001", "Priya Shah", "Yale Robotics Club", "priya.shah@example.edu"),
    ("C002", "Marcus Lee", "Branford College Council", "marcus.lee@example.edu"),
    ("C003", "Dana Ortiz", "Women's Rugby", "dana.ortiz@example.edu"),
    ("C004", "Sam Okafor", "Whiffenpoofs Alumni", "sam.okafor@example.com"),
]
SEED_PRODUCTS = [
    ("TEE-BLK", "Black cotton tee (screen print)", 14.0, 120, 50, "Elm City Print Co."),
    ("TEE-NVY", "Navy cotton tee (screen print)", 14.0, 35, 50, "Elm City Print Co."),
    ("HOOD-GRY", "Heather grey hoodie (embroidered)", 38.0, 18, 25, "Stitchworks Supply"),
    ("CAP-NVY", "Navy dad cap (embroidered)", 22.0, 60, 20, "Stitchworks Supply"),
    ("STK-DIE", "Die-cut vinyl stickers (pack of 50)", 30.0, 8, 10, "Sticky Situation LLC"),
    ("TOTE-NAT", "Natural canvas tote", 12.0, 0, 15, "Elm City Print Co."),
]
SEED_VENDORS = [
    ("Elm City Print Co.", "orders@elmcityprint.example", 7, "screen printing, totes"),
    ("Stitchworks Supply", "sales@stitchworks.example", 12, "embroidery, hoodies, caps"),
    ("Sticky Situation LLC", "hello@stickysituation.example", 5, "vinyl stickers"),
]
SEED_ORDERS = [
    ("ORD-1001", "C001", [{"sku": "TEE-BLK", "qty": 40}], "new", "2026-10-30", 560.0, "Two-color logo on front, sponsor list on back."),
    ("ORD-1002", "C002", [{"sku": "HOOD-GRY", "qty": 30}], "new", "2026-10-24", 1140.0, "College crest embroidered left chest."),
    ("ORD-1003", "C003", [{"sku": "TEE-NVY", "qty": 45}, {"sku": "STK-DIE", "qty": 2}], "in_production", "2026-10-21", 690.0, "Customer asked if they can add 5 more tees."),
    ("ORD-1004", "C004", [{"sku": "TOTE-NAT", "qty": 25}], "on_hold", "2026-11-05", 300.0, "Totes out of stock; waiting on restock."),
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]:
            return
        conn.executemany("INSERT INTO customers VALUES (?,?,?,?)", SEED_CUSTOMERS)
        conn.executemany("INSERT INTO products VALUES (?,?,?,?,?,?)", SEED_PRODUCTS)
        conn.executemany("INSERT INTO vendors VALUES (?,?,?,?)", SEED_VENDORS)
        ts = now()
        conn.executemany(
            "INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?)",
            [(o[0], o[1], json.dumps(o[2]), o[3], o[4], o[5], o[6], ts, ts) for o in SEED_ORDERS],
        )


def rows(sql: str, params: tuple = ()) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def execute(sql: str, params: tuple = ()) -> int:
    with connect() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid
