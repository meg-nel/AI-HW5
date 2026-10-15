"""Campus Customs MCP server (FastMCP).

Gives every agent on the team read access to the shop database
(data/campus_customs_new.db) through three tools. Every value a tool returns comes
straight from the database or is simple arithmetic on those values; if a SKU, size,
or record isn't in the database, the tool raises an error instead of guessing.

Run (stdio):  python -m mcp_server.server   (from the project root)
"""

import os
import sqlite3
from datetime import date
from pathlib import Path

from mcp.server.fastmcp import FastMCP

DB_PATH = Path(os.environ.get(
    "CAMPUS_CUSTOMS_DB",
    Path(__file__).resolve().parent.parent / "data" / "campus_customs_new.db",
))

mcp = FastMCP("campus-customs")


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")
    conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)  # read-only
    conn.row_factory = sqlite3.Row
    return conn


def _shop_today(conn: sqlite3.Connection) -> date:
    """The shop's 'today' comes from the desk table, not the real clock."""
    row = conn.execute("SELECT date_today FROM desk").fetchone()
    if row is None:
        raise ValueError("desk table has no date_today")
    return date.fromisoformat(row["date_today"])


@mcp.tool()
def check_stock(sku: str, size: str, qty_needed: int) -> dict:
    """Check how many units of a SKU in a given size are on the shelf, and the shortfall
    against qty_needed. Reads the inventory table. Sizes are S, M, L, XL, or OS (one size)."""
    if qty_needed < 1:
        raise ValueError("qty_needed must be at least 1")
    with _connect() as conn:
        row = conn.execute(
            "SELECT sku, name, size, qty, location FROM inventory WHERE sku = ? AND size = ?",
            (sku, size),
        ).fetchone()
        if row is None:
            sizes = [r["size"] for r in conn.execute("SELECT size FROM inventory WHERE sku = ?", (sku,))]
            if not sizes:
                raise ValueError(f"SKU {sku} is not in inventory")
            raise ValueError(f"SKU {sku} has no size {size}; sizes in inventory: {', '.join(sizes)}")
    return {
        "sku": row["sku"],
        "name": row["name"],
        "size": row["size"],
        "location": row["location"],
        "qty_on_hand": row["qty"],
        "qty_needed": qty_needed,
        "can_fill": row["qty"] >= qty_needed,
        "shortfall": max(0, qty_needed - row["qty"]),
    }


@mcp.tool()
def quote_price_margin(sku: str, qty: int, discount_pct: float = 0.0) -> dict:
    """Price a quantity of a SKU at list price minus an optional discount, and show the
    resulting margin. Reads the pricing table. discount_pct is 0-100 (e.g. 15 = 15% off)."""
    if qty < 1:
        raise ValueError("qty must be at least 1")
    if not 0 <= discount_pct <= 100:
        raise ValueError("discount_pct must be between 0 and 100")
    with _connect() as conn:
        row = conn.execute("SELECT sku, unit_cost, list_price FROM pricing WHERE sku = ?", (sku,)).fetchone()
    if row is None:
        raise ValueError(f"SKU {sku} has no pricing row")
    unit_price = round(row["list_price"] * (1 - discount_pct / 100), 2)
    unit_margin = round(unit_price - row["unit_cost"], 2)
    return {
        "sku": row["sku"],
        "qty": qty,
        "unit_cost": row["unit_cost"],
        "list_price": row["list_price"],
        "discount_pct": discount_pct,
        "unit_price": unit_price,
        "unit_margin": unit_margin,
        "margin_pct": round(100 * unit_margin / unit_price, 1) if unit_price else None,
        "total_price": round(unit_price * qty, 2),
        "total_cost": round(row["unit_cost"] * qty, 2),
        "total_margin": round(unit_margin * qty, 2),
    }


@mcp.tool()
def get_bills_and_cash() -> dict:
    """List everything the shop owes (open vendor invoices and upcoming lease rent) with
    days until due relative to the shop's date, next to the cash on hand. Reads the
    invoices, vendors, leases, cash_accounts, and desk tables."""
    with _connect() as conn:
        today = _shop_today(conn)
        invoices = conn.execute(
            """SELECT i.id, i.amount, i.due_date, i.status, i.description,
                      v.id AS vendor_id, v.name AS vendor_name
               FROM invoices i JOIN vendors v ON v.id = i.vendor_id
               WHERE i.status = 'open' ORDER BY i.due_date"""
        ).fetchall()
        leases = conn.execute(
            "SELECT id, space_name, landlord, monthly_rent, next_due FROM leases ORDER BY next_due"
        ).fetchall()
        accounts = conn.execute("SELECT name, balance, date FROM cash_accounts").fetchall()

    def days_until(d: str) -> int:
        return (date.fromisoformat(d) - today).days

    bills = [
        {"kind": "invoice", "invoice_id": r["id"], "payee": r["vendor_name"], "vendor_id": r["vendor_id"],
         "amount": r["amount"], "due_date": r["due_date"], "days_until_due": days_until(r["due_date"]),
         "overdue": days_until(r["due_date"]) < 0, "description": r["description"]}
        for r in invoices
    ] + [
        {"kind": "rent", "lease_id": r["id"], "payee": r["landlord"], "space_name": r["space_name"],
         "amount": r["monthly_rent"], "due_date": r["next_due"], "days_until_due": days_until(r["next_due"]),
         "overdue": days_until(r["next_due"]) < 0}
        for r in leases
    ]
    bills.sort(key=lambda b: b["due_date"])
    cash_total = sum(a["balance"] for a in accounts)
    bills_total = sum(b["amount"] for b in bills)
    return {
        "shop_date": today.isoformat(),
        "cash_accounts": [dict(a) for a in accounts],
        "cash_total": cash_total,
        "bills": bills,
        "bills_total": bills_total,
        "cash_after_all_bills": round(cash_total - bills_total, 2),
    }


if __name__ == "__main__":
    mcp.run()
