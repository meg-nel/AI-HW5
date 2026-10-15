"""Campus Customs MCP server (FastMCP).

The one shared toolbox for the Campus Customs agent team. Tools read and update the
working database, data/campus_customs_new.db.

Shop rules enforced here, so no agent can get around them:
- "Today" is desk.date_today. Overdue and due-soon are measured from that date.
- Vendor lead times come from vendors.lead_days. A vendor with an open (unpaid) invoice
  will not ship, so purchase orders to that vendor are refused.
- Every payment needs a human approval first. Agents can only *request* a payment;
  only a human can approve it (admin_* tools are hidden from agents). pay_bill then
  writes the payments row, lowers the cash balance, and closes the invoice or moves the
  lease's next_due forward.
- pay_bill refuses if there isn't enough cash. A database trigger also blocks any
  negative balance.
- Cash only goes out. No tool records revenue or adds money.
- Tools only return what is in the database (plus simple arithmetic on it). Unknown
  SKUs, sizes, tickets, vendors, invoices, or leases raise an error instead of guessing.

Helper tables this server adds to the working copy (re-created after a reset):
approvals (payment and purchase-order requests) and drafts (customer messages, never sent).

Run (stdio):  python mcp_server/server.py
"""

import calendar
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

DB_PATH = Path(os.environ.get(
    "CAMPUS_CUSTOMS_DB",
    Path(__file__).resolve().parent.parent / "data" / "campus_customs_new.db",
))

mcp = FastMCP("campus-customs")

EXTRA_SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,              -- invoice_payment | rent_payment | purchase_order
    ref_id INTEGER,                  -- invoices.id or leases.id (NULL for purchase orders)
    amount REAL NOT NULL,            -- always taken from the database, never from the agent
    details TEXT,                    -- JSON with the rows the request was built from
    requested_by TEXT NOT NULL,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected | paid
    decided_by TEXT,
    decision_note TEXT,
    created_on TEXT NOT NULL,        -- shop date
    decided_on TEXT
);
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id),
    recipient TEXT NOT NULL,         -- always the ticket's requester
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    author TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',    -- draft | discarded; drafts are never sent
    created_on TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS cash_never_negative
BEFORE UPDATE OF balance ON cash_accounts
WHEN NEW.balance < 0
BEGIN
    SELECT RAISE(ABORT, 'cash balance cannot go negative');
END;
"""

TICKET_STATUSES = ("open", "in_progress", "waiting_on_human", "waiting_on_vendor", "resolved")


@contextmanager
def _db():
    """Open the working database, make sure helper tables exist, commit on success."""
    if not DB_PATH.exists():
        raise ToolError(f"Database not found: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.executescript(EXTRA_SCHEMA)
        yield conn
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.rollback()
        raise ToolError(f"Refused by the database: {e}") from e
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _one(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> dict | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def _all(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params)]


def _today(conn: sqlite3.Connection) -> date:
    """The shop's 'today' comes from desk.date_today, never the computer clock."""
    row = _one(conn, "SELECT date_today FROM desk")
    if row is None:
        raise ToolError("desk table has no date_today")
    return date.fromisoformat(row["date_today"])


def _days_until(due: str, today: date) -> int:
    return (date.fromisoformat(due) - today).days


def _add_month(d: date) -> date:
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _open_invoices_for_vendor(conn: sqlite3.Connection, vendor_id: int) -> list[dict]:
    return _all(conn, "SELECT id, amount, due_date, description FROM invoices "
                      "WHERE vendor_id = ? AND status = 'open' ORDER BY due_date", (vendor_id,))


def _approval(conn: sqlite3.Connection, approval_id: int) -> dict:
    row = _one(conn, "SELECT * FROM approvals WHERE id = ?", (approval_id,))
    if row is None:
        raise ToolError(f"No approval request {approval_id}")
    row["details"] = json.loads(row["details"] or "{}")
    return row


# =====================================================================================
# Shop date and tickets
# =====================================================================================

@mcp.tool
def get_shop_date() -> dict:
    """Return the shop's 'today' (desk.date_today). Use it for every overdue / due-soon judgment."""
    with _db() as conn:
        return {"shop_date": _today(conn).isoformat()}


@mcp.tool
def list_tickets() -> dict:
    """List every ticket, resolved or not, with its status and whether it is open or resolved.
    Reads tickets and desk."""
    with _db() as conn:
        tickets = _all(conn, "SELECT id, type, requester, subject, sku, size, qty, lease_id, invoice_id, status, "
                             "created_at FROM tickets ORDER BY id")
        for t in tickets:
            t["state"] = "resolved" if t["status"] == "resolved" else "open"
        return {"shop_date": _today(conn).isoformat(), "tickets": tickets}


@mcp.tool
def list_open_tickets() -> dict:
    """List every ticket that is not resolved, oldest first, with the shop date. Reads tickets and desk."""
    with _db() as conn:
        tickets = _all(conn, "SELECT * FROM tickets WHERE status != 'resolved' ORDER BY created_at")
        return {"shop_date": _today(conn).isoformat(), "tickets": tickets}


@mcp.tool
def get_ticket(ticket_id: int) -> dict:
    """Return one ticket with everything it links to: the inventory row and pricing for its SKU/size,
    its invoice (with vendor and days overdue), and its lease (with days until rent is due).
    Reads tickets, inventory, pricing, invoices, vendors, leases, desk."""
    with _db() as conn:
        ticket = _one(conn, "SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        if ticket is None:
            raise ToolError(f"No ticket {ticket_id}")
        today = _today(conn)
        linked: dict = {}
        if ticket["sku"]:
            linked["inventory"] = _one(conn, "SELECT * FROM inventory WHERE sku = ? AND size = ?",
                                       (ticket["sku"], ticket["size"]))
            linked["pricing"] = _one(conn, "SELECT * FROM pricing WHERE sku = ?", (ticket["sku"],))
        if ticket["invoice_id"] is not None:
            inv = _one(conn, "SELECT i.*, v.name AS vendor_name, v.lead_days FROM invoices i "
                             "JOIN vendors v ON v.id = i.vendor_id WHERE i.id = ?", (ticket["invoice_id"],))
            if inv:
                inv["days_until_due"] = _days_until(inv["due_date"], today)
                inv["overdue"] = inv["status"] == "open" and inv["days_until_due"] < 0
            linked["invoice"] = inv
        if ticket["lease_id"] is not None:
            lease = _one(conn, "SELECT * FROM leases WHERE id = ?", (ticket["lease_id"],))
            if lease:
                lease["days_until_due"] = _days_until(lease["next_due"], today)
                lease["overdue"] = lease["days_until_due"] < 0
            linked["lease"] = lease
        return {"shop_date": today.isoformat(), "ticket": ticket, "linked": linked}


@mcp.tool
def update_ticket(ticket_id: int, status: Literal[TICKET_STATUSES], note: str, updated_by: str) -> dict:
    """Set a ticket's status and append a dated note (shop date) saying who did what. Writes tickets.
    Statuses: open, in_progress, waiting_on_human, waiting_on_vendor, resolved."""
    if not note.strip() or not updated_by.strip():
        raise ToolError("note and updated_by are required")
    with _db() as conn:
        if _one(conn, "SELECT id FROM tickets WHERE id = ?", (ticket_id,)) is None:
            raise ToolError(f"No ticket {ticket_id}")
        line = f"[{_today(conn).isoformat()} {updated_by}] {note.strip()}"
        conn.execute(
            "UPDATE tickets SET status = ?, notes = CASE WHEN notes IS NULL OR notes = '' THEN ? "
            "ELSE notes || char(10) || ? END WHERE id = ?",
            (status, line, line, ticket_id),
        )
        return _one(conn, "SELECT * FROM tickets WHERE id = ?", (ticket_id,))


# =====================================================================================
# Inventory, pricing, vendors
# =====================================================================================

@mcp.tool
def check_stock(sku: str, size: str, qty_needed: int) -> dict:
    """Check how many units of a SKU in a given size are on the shelf, and the shortfall
    against qty_needed. Reads the inventory table. Sizes are S, M, L, XL, or OS (one size)."""
    if qty_needed < 1:
        raise ToolError("qty_needed must be at least 1")
    with _db() as conn:
        row = _one(conn, "SELECT sku, name, size, qty, location FROM inventory WHERE sku = ? AND size = ?",
                   (sku, size))
        if row is None:
            sizes = [r["size"] for r in _all(conn, "SELECT size FROM inventory WHERE sku = ?", (sku,))]
            if not sizes:
                raise ToolError(f"SKU {sku} is not in inventory")
            raise ToolError(f"SKU {sku} has no size {size}; sizes in inventory: {', '.join(sizes)}")
    return {
        "sku": row["sku"], "name": row["name"], "size": row["size"], "location": row["location"],
        "qty_on_hand": row["qty"], "qty_needed": qty_needed,
        "can_fill": row["qty"] >= qty_needed, "shortfall": max(0, qty_needed - row["qty"]),
    }


@mcp.tool
def list_inventory(sku: str | None = None) -> dict:
    """List every size of one SKU (or the whole shelf if sku is omitted) with quantity, location,
    and whether it is out of stock. Use it to see all sizes before suggesting an alternative. Reads inventory."""
    with _db() as conn:
        if sku is None:
            items = _all(conn, "SELECT * FROM inventory ORDER BY sku, size")
        else:
            items = _all(conn, "SELECT * FROM inventory WHERE sku = ? ORDER BY size", (sku,))
            if not items:
                raise ToolError(f"SKU {sku} is not in inventory")
    for item in items:
        item["out_of_stock"] = item["qty"] == 0
    return {"sku": sku, "items": items, "total_units": sum(i["qty"] for i in items)}


@mcp.tool
def quote_price_margin(sku: str, qty: int, discount_pct: float = 0.0) -> dict:
    """Price a quantity of a SKU at list price minus an optional discount, and show the
    resulting margin. Reads the pricing table. discount_pct is 0-100 (e.g. 15 = 15% off)."""
    if qty < 1:
        raise ToolError("qty must be at least 1")
    if not 0 <= discount_pct <= 100:
        raise ToolError("discount_pct must be between 0 and 100")
    with _db() as conn:
        row = _one(conn, "SELECT sku, unit_cost, list_price FROM pricing WHERE sku = ?", (sku,))
    if row is None:
        raise ToolError(f"SKU {sku} has no pricing row")
    unit_price = round(row["list_price"] * (1 - discount_pct / 100), 2)
    unit_margin = round(unit_price - row["unit_cost"], 2)
    return {
        "sku": row["sku"], "qty": qty, "unit_cost": row["unit_cost"], "list_price": row["list_price"],
        "discount_pct": discount_pct, "unit_price": unit_price, "unit_margin": unit_margin,
        "margin_pct": round(100 * unit_margin / unit_price, 1) if unit_price else None,
        "total_price": round(unit_price * qty, 2), "total_cost": round(row["unit_cost"] * qty, 2),
        "total_margin": round(unit_margin * qty, 2),
    }


@mcp.tool
def list_vendors() -> dict:
    """List every vendor with its specialty, lead time (days), open unpaid invoices, whether it
    will ship (a vendor with an open unpaid invoice will NOT ship), and the earliest arrival
    date if ordered today (shop date + lead_days). Reads vendors, invoices, desk."""
    with _db() as conn:
        today = _today(conn)
        vendors = []
        for v in _all(conn, "SELECT * FROM vendors ORDER BY id"):
            open_invoices = _open_invoices_for_vendor(conn, v["id"])
            for inv in open_invoices:
                inv["days_until_due"] = _days_until(inv["due_date"], today)
                inv["overdue"] = inv["days_until_due"] < 0
            vendors.append({
                **v,
                "open_unpaid_invoices": open_invoices,
                "amount_owed": round(sum(i["amount"] for i in open_invoices), 2),
                "will_ship": not open_invoices,
                "earliest_arrival_if_ordered_today": (today + timedelta(days=v["lead_days"])).isoformat(),
            })
        return {"shop_date": today.isoformat(), "vendors": vendors}


# =====================================================================================
# Money: bills, approvals, payments
# =====================================================================================

@mcp.tool
def get_bills_and_cash() -> dict:
    """List everything the shop owes (open vendor invoices and upcoming lease rent) with
    days until due relative to the shop's date, next to the cash on hand. Reads the
    invoices, vendors, leases, cash_accounts, and desk tables."""
    with _db() as conn:
        today = _today(conn)
        invoices = _all(conn, "SELECT i.id, i.amount, i.due_date, i.description, v.id AS vendor_id, "
                              "v.name AS vendor_name FROM invoices i JOIN vendors v ON v.id = i.vendor_id "
                              "WHERE i.status = 'open' ORDER BY i.due_date")
        leases = _all(conn, "SELECT id, space_name, landlord, monthly_rent, next_due FROM leases ORDER BY next_due")
        accounts = _all(conn, "SELECT name, balance, date FROM cash_accounts")
    bills = [
        {"kind": "invoice", "invoice_id": r["id"], "payee": r["vendor_name"], "vendor_id": r["vendor_id"],
         "amount": r["amount"], "due_date": r["due_date"], "days_until_due": _days_until(r["due_date"], today),
         "overdue": _days_until(r["due_date"], today) < 0, "description": r["description"]}
        for r in invoices
    ] + [
        {"kind": "rent", "lease_id": r["id"], "payee": r["landlord"], "space_name": r["space_name"],
         "amount": r["monthly_rent"], "due_date": r["next_due"], "days_until_due": _days_until(r["next_due"], today),
         "overdue": _days_until(r["next_due"], today) < 0}
        for r in leases
    ]
    bills.sort(key=lambda b: b["due_date"])
    cash_total = sum(a["balance"] for a in accounts)
    bills_total = sum(b["amount"] for b in bills)
    return {
        "shop_date": today.isoformat(), "cash_accounts": accounts, "cash_total": cash_total,
        "bills": bills, "bills_total": bills_total, "cash_after_all_bills": round(cash_total - bills_total, 2),
    }


@mcp.tool
def get_lease(lease_id: int) -> dict:
    """Return one lease (space, landlord, monthly rent, next due date, days until due) and every rent
    payment recorded against it. Reads leases, payments, desk."""
    with _db() as conn:
        lease = _one(conn, "SELECT * FROM leases WHERE id = ?", (lease_id,))
        if lease is None:
            raise ToolError(f"No lease {lease_id}")
        today = _today(conn)
        lease["days_until_due"] = _days_until(lease["next_due"], today)
        lease["overdue"] = lease["days_until_due"] < 0
        payments = _all(conn, "SELECT * FROM payments WHERE kind = 'rent' AND ref_id = ? ORDER BY id", (lease_id,))
        return {"shop_date": today.isoformat(), "lease": lease, "rent_payments": payments}


@mcp.tool
def list_payments() -> dict:
    """List every payment the shop has made (each one was human-approved), with the total paid out.
    Reads payments."""
    with _db() as conn:
        payments = _all(conn, "SELECT * FROM payments ORDER BY id")
    return {"payments": payments, "total_paid": round(sum(p["amount"] for p in payments), 2)}


@mcp.tool
def list_approvals(status: Literal["pending", "approved", "rejected", "paid"] | None = None) -> list[dict]:
    """List payment and purchase-order approval requests and the human's decisions, optionally by status.
    Read-only: only a human can decide a request. Reads approvals."""
    with _db() as conn:
        ids = [r["id"] for r in _all(conn, "SELECT id FROM approvals" + (" WHERE status = ?" if status else "")
                                     + " ORDER BY id", (status,) if status else ())]
        return [_approval(conn, i) for i in ids]


@mcp.tool
def request_payment(kind: Literal["invoice", "rent"], ref_id: int, requested_by: str, reason: str) -> dict:
    """Ask a human to approve paying one bill. kind='invoice' uses invoices.id; kind='rent' uses leases.id.
    The amount is read from the database. Nothing is paid until a human approves and pay_bill runs.
    Writes the approvals table."""
    with _db() as conn:
        today = _today(conn)
        if kind == "invoice":
            bill = _one(conn, "SELECT i.*, v.name AS vendor_name FROM invoices i JOIN vendors v "
                              "ON v.id = i.vendor_id WHERE i.id = ?", (ref_id,))
            if bill is None:
                raise ToolError(f"No invoice {ref_id}")
            if bill["status"] != "open":
                raise ToolError(f"Invoice {ref_id} is '{bill['status']}', not open; nothing to pay")
            amount, approval_kind = bill["amount"], "invoice_payment"
            details = {"payee": bill["vendor_name"], "due_date": bill["due_date"],
                       "days_until_due": _days_until(bill["due_date"], today), "description": bill["description"]}
        else:
            bill = _one(conn, "SELECT * FROM leases WHERE id = ?", (ref_id,))
            if bill is None:
                raise ToolError(f"No lease {ref_id}")
            amount, approval_kind = bill["monthly_rent"], "rent_payment"
            details = {"payee": bill["landlord"], "space_name": bill["space_name"], "due_date": bill["next_due"],
                       "days_until_due": _days_until(bill["next_due"], today)}
        dup = _one(conn, "SELECT id, status FROM approvals WHERE kind = ? AND ref_id = ? "
                         "AND status IN ('pending', 'approved')", (approval_kind, ref_id))
        if dup:
            raise ToolError(f"Approval request {dup['id']} for this bill is already {dup['status']}")
        cur = conn.execute(
            "INSERT INTO approvals (kind, ref_id, amount, details, requested_by, reason, created_on) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (approval_kind, ref_id, amount, json.dumps(details), requested_by, reason, today.isoformat()),
        )
        return {**_approval(conn, cur.lastrowid), "note": "Waiting for a human decision. Nothing has been paid."}


@mcp.tool
def request_purchase_order(vendor_id: int, sku: str, size: str, qty: int, requested_by: str, reason: str) -> dict:
    """Ask a human to approve a restock purchase order. Refused if the vendor has an open unpaid
    invoice (they will not ship). Cost uses pricing.unit_cost; arrival is shop date + vendors.lead_days.
    Approving a purchase order does not move cash. Writes the approvals table."""
    if qty < 1:
        raise ToolError("qty must be at least 1")
    with _db() as conn:
        today = _today(conn)
        vendor = _one(conn, "SELECT * FROM vendors WHERE id = ?", (vendor_id,))
        if vendor is None:
            raise ToolError(f"No vendor {vendor_id}")
        blocking = _open_invoices_for_vendor(conn, vendor_id)
        if blocking:
            ids = ", ".join(str(i["id"]) for i in blocking)
            raise ToolError(f"{vendor['name']} will not ship: open unpaid invoice(s) {ids} "
                            f"(${sum(i['amount'] for i in blocking):,.2f}). Pay those first.")
        item = _one(conn, "SELECT * FROM inventory WHERE sku = ? AND size = ?", (sku, size))
        if item is None:
            raise ToolError(f"SKU {sku} size {size} is not in inventory")
        price = _one(conn, "SELECT unit_cost FROM pricing WHERE sku = ?", (sku,))
        if price is None:
            raise ToolError(f"SKU {sku} has no pricing row, so the order can't be costed")
        cost = round(price["unit_cost"] * qty, 2)
        cash = round(sum(a["balance"] for a in _all(conn, "SELECT balance FROM cash_accounts")), 2)
        details = {"vendor_id": vendor_id, "vendor_name": vendor["name"], "sku": sku, "item_name": item["name"],
                   "size": size, "qty": qty, "unit_cost": price["unit_cost"], "lead_days": vendor["lead_days"],
                   "expected_arrival": (today + timedelta(days=vendor["lead_days"])).isoformat(),
                   # A PO moves no cash now; the vendor invoices later. Shown so the human can judge.
                   "cash_on_hand": cash, "cash_shortfall": round(max(0.0, cost - cash), 2)}
        cur = conn.execute(
            "INSERT INTO approvals (kind, ref_id, amount, details, requested_by, reason, created_on) "
            "VALUES ('purchase_order', NULL, ?, ?, ?, ?, ?)",
            (cost, json.dumps(details), requested_by, reason, today.isoformat()),
        )
        return {**_approval(conn, cur.lastrowid), "note": "Waiting for a human decision. No order placed."}


@mcp.tool
def get_approval(approval_id: int) -> dict:
    """Check the status of a payment or purchase-order approval request. Reads approvals."""
    with _db() as conn:
        return _approval(conn, approval_id)


@mcp.tool
def pay_bill(approval_id: int, account: str = "checking") -> dict:
    """Pay a bill that a human has approved. Refuses if the request isn't approved, was already
    paid, or there isn't enough cash (balances never go negative). On success, in one transaction:
    adds a payments row, lowers cash_accounts.balance, and marks the invoice 'paid' or moves the
    lease's next_due forward one month. Writes payments, cash_accounts, invoices/leases, approvals."""
    with _db() as conn:
        today = _today(conn)
        appr = _approval(conn, approval_id)
        if appr["kind"] not in ("invoice_payment", "rent_payment"):
            raise ToolError(f"Approval {approval_id} is a {appr['kind']}, not a payment")
        if appr["status"] != "approved":
            raise ToolError(f"Approval {approval_id} is '{appr['status']}'. A human must approve it before paying.")
        if not appr["decided_by"]:
            raise ToolError(f"Approval {approval_id} has no human approver recorded")
        acct = _one(conn, "SELECT * FROM cash_accounts WHERE name = ?", (account,))
        if acct is None:
            raise ToolError(f"No cash account '{account}'")

        # Re-check the bill against the database so the approved amount is still right.
        if appr["kind"] == "invoice_payment":
            inv = _one(conn, "SELECT * FROM invoices WHERE id = ?", (appr["ref_id"],))
            if inv is None or inv["status"] != "open":
                raise ToolError(f"Invoice {appr['ref_id']} is no longer open")
            amount, pay_kind = inv["amount"], "invoice"
        else:
            lease = _one(conn, "SELECT * FROM leases WHERE id = ?", (appr["ref_id"],))
            if lease is None:
                raise ToolError(f"Lease {appr['ref_id']} not found")
            amount, pay_kind = lease["monthly_rent"], "rent"
        if round(amount, 2) != round(appr["amount"], 2):
            raise ToolError(f"Bill amount changed since approval (${appr['amount']:,.2f} -> ${amount:,.2f}); "
                            "request a new approval")
        if acct["balance"] < amount:
            raise ToolError(f"Refused: not enough cash. {account} has ${acct['balance']:,.2f}, "
                            f"bill is ${amount:,.2f}. Negative balances are not allowed.")

        conn.execute("UPDATE cash_accounts SET balance = balance - ?, date = ? WHERE name = ?",
                     (amount, today.isoformat(), account))
        cur = conn.execute(
            "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) VALUES (?, ?, ?, ?, ?, ?)",
            (pay_kind, appr["ref_id"], amount, account, today.isoformat(), appr["decided_by"]),
        )
        if pay_kind == "invoice":
            conn.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (appr["ref_id"],))
            updated = _one(conn, "SELECT * FROM invoices WHERE id = ?", (appr["ref_id"],))
        else:
            new_due = _add_month(date.fromisoformat(lease["next_due"])).isoformat()
            conn.execute("UPDATE leases SET next_due = ? WHERE id = ?", (new_due, appr["ref_id"]))
            updated = _one(conn, "SELECT * FROM leases WHERE id = ?", (appr["ref_id"],))
        conn.execute("UPDATE approvals SET status = 'paid' WHERE id = ?", (approval_id,))
        return {
            "payment": _one(conn, "SELECT * FROM payments WHERE id = ?", (cur.lastrowid,)),
            "cash_account": _one(conn, "SELECT * FROM cash_accounts WHERE name = ?", (account,)),
            "updated_bill": updated,
        }


# =====================================================================================
# Customer messages (drafts only)
# =====================================================================================

@mcp.tool
def draft_customer_message(ticket_id: int, subject: str, body: str, author: str) -> dict:
    """Save a DRAFT message to the ticket's requester. It is never sent; a human reviews it.
    The recipient is always the ticket's requester. Writes the drafts table."""
    if not subject.strip() or not body.strip():
        raise ToolError("subject and body are required")
    with _db() as conn:
        ticket = _one(conn, "SELECT id, requester FROM tickets WHERE id = ?", (ticket_id,))
        if ticket is None:
            raise ToolError(f"No ticket {ticket_id}")
        cur = conn.execute(
            "INSERT INTO drafts (ticket_id, recipient, subject, body, author, created_on) VALUES (?, ?, ?, ?, ?, ?)",
            (ticket_id, ticket["requester"], subject.strip(), body.strip(), author, _today(conn).isoformat()),
        )
        return {**_one(conn, "SELECT * FROM drafts WHERE id = ?", (cur.lastrowid,)),
                "note": "Saved as a draft. Not sent."}


@mcp.tool
def discard_draft(draft_id: int, reason: str, author: str) -> dict:
    """Mark an outdated draft as discarded so only one current draft remains per ticket.
    The draft stays on record (never deleted, never sent). Writes the drafts table."""
    if not reason.strip():
        raise ToolError("reason is required")
    with _db() as conn:
        draft = _one(conn, "SELECT * FROM drafts WHERE id = ?", (draft_id,))
        if draft is None:
            raise ToolError(f"No draft {draft_id}")
        if draft["status"] != "draft":
            raise ToolError(f"Draft {draft_id} is already '{draft['status']}'")
        conn.execute("UPDATE drafts SET status = 'discarded', body = body || char(10) || char(10) || ? WHERE id = ?",
                     (f"[discarded {_today(conn).isoformat()} by {author}: {reason.strip()}]", draft_id))
        return _one(conn, "SELECT * FROM drafts WHERE id = ?", (draft_id,))


@mcp.tool
def list_drafts(ticket_id: int | None = None) -> list[dict]:
    """List customer message drafts, optionally for one ticket. Reads drafts."""
    with _db() as conn:
        if ticket_id is None:
            return _all(conn, "SELECT * FROM drafts ORDER BY id")
        return _all(conn, "SELECT * FROM drafts WHERE ticket_id = ? ORDER BY id", (ticket_id,))


# =====================================================================================
# Human-only tools. Hidden from every agent; used by the human approval step.
# =====================================================================================

@mcp.tool
def admin_decide_approval(approval_id: int, approved: bool, decided_by: str, note: str = "") -> dict:
    """[human only] Record a human's approve/reject decision on a pending request."""
    if not decided_by.strip():
        raise ToolError("decided_by (the human's name) is required")
    with _db() as conn:
        appr = _approval(conn, approval_id)
        if appr["status"] != "pending":
            raise ToolError(f"Approval {approval_id} is already '{appr['status']}'")
        conn.execute("UPDATE approvals SET status = ?, decided_by = ?, decision_note = ?, decided_on = ? WHERE id = ?",
                     ("approved" if approved else "rejected", decided_by.strip(), note, _today(conn).isoformat(),
                      approval_id))
        return _approval(conn, approval_id)


if __name__ == "__main__":
    mcp.run()
