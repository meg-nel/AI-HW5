"""Campus Customs MCP server.

Exposes the shop's data (orders, customers, inventory, vendors) and a drafts board to the
agent team. There are deliberately NO tools that send email or contact vendors: anything
outbound is written as a draft and stays on the dashboard board for a human.

Tools prefixed with `admin_` are for the FastAPI backend / dashboard only and are filtered
out of every agent's toolset.

Run standalone:  python -m mcp_server.server   (stdio transport)
"""

import json
from typing import Literal

from mcp.server.fastmcp import FastMCP

from mcp_server import db

mcp = FastMCP("campus-customs")
db.init_db()

OrderStatus = Literal["new", "awaiting_approval", "in_production", "ready", "shipped", "on_hold", "cancelled"]


def _order(row: dict) -> dict:
    row["items"] = json.loads(row["items"])
    return row


# ---------- Orders & customers ----------

@mcp.tool()
def list_orders(status: OrderStatus | None = None) -> list[dict]:
    """List shop orders, optionally filtered by status."""
    if status:
        return [_order(r) for r in db.rows("SELECT * FROM orders WHERE status=? ORDER BY due_date", (status,))]
    return [_order(r) for r in db.rows("SELECT * FROM orders ORDER BY due_date")]


@mcp.tool()
def get_order(order_id: str) -> dict:
    """Get one order with its customer details."""
    found = db.rows("SELECT * FROM orders WHERE id=?", (order_id,))
    if not found:
        raise ValueError(f"No order {order_id}")
    order = _order(found[0])
    order["customer"] = db.rows("SELECT * FROM customers WHERE id=?", (order["customer_id"],))[0]
    return order


@mcp.tool()
def update_order_status(order_id: str, status: OrderStatus, note: str = "") -> dict:
    """Change an order's status and optionally append a note (internal only, nothing is sent)."""
    if not db.rows("SELECT id FROM orders WHERE id=?", (order_id,)):
        raise ValueError(f"No order {order_id}")
    db.execute(
        "UPDATE orders SET status=?, notes=COALESCE(notes,'') || ?, updated_at=? WHERE id=?",
        (status, f"\n[{db.now()}] {note}" if note else "", db.now(), order_id),
    )
    return get_order(order_id)


@mcp.tool()
def list_customers() -> list[dict]:
    """List customers (campus organizations and their contacts)."""
    return db.rows("SELECT * FROM customers")


# ---------- Inventory & vendors ----------

@mcp.tool()
def list_inventory(low_stock_only: bool = False) -> list[dict]:
    """List products with stock levels. low_stock_only returns items at/below reorder point."""
    sql = "SELECT * FROM products" + (" WHERE stock <= reorder_point" if low_stock_only else "")
    return db.rows(sql)


@mcp.tool()
def check_stock(sku: str, quantity: int) -> dict:
    """Check whether `quantity` units of a SKU are available right now."""
    found = db.rows("SELECT * FROM products WHERE sku=?", (sku,))
    if not found:
        raise ValueError(f"Unknown SKU {sku}")
    p = found[0]
    return {"sku": sku, "requested": quantity, "in_stock": p["stock"],
            "available": p["stock"] >= quantity, "shortfall": max(0, quantity - p["stock"]), "vendor": p["vendor"]}


@mcp.tool()
def list_vendors() -> list[dict]:
    """List suppliers with lead times and specialties."""
    return db.rows("SELECT * FROM vendors")


# ---------- Drafts board (never sent) ----------

@mcp.tool()
def draft_customer_email(to: str, subject: str, body: str, author_agent: str, related_order: str = "") -> dict:
    """Write a customer email DRAFT to the board. It is NOT sent; a human reviews it on the dashboard."""
    draft_id = db.execute(
        "INSERT INTO drafts (kind, recipient, subject, body, related_order, author_agent, created_at) VALUES (?,?,?,?,?,?,?)",
        ("customer_email", to, subject, body, related_order, author_agent, db.now()),
    )
    return {"draft_id": draft_id, "status": "draft", "note": "Saved to the drafts board. Not sent."}


@mcp.tool()
def draft_vendor_request(vendor: str, subject: str, body: str, author_agent: str, related_order: str = "") -> dict:
    """Write a vendor purchase/quote request DRAFT to the board. Vendors are NOT contacted."""
    draft_id = db.execute(
        "INSERT INTO drafts (kind, recipient, subject, body, related_order, author_agent, created_at) VALUES (?,?,?,?,?,?,?)",
        ("vendor_request", vendor, subject, body, related_order, author_agent, db.now()),
    )
    return {"draft_id": draft_id, "status": "draft", "note": "Saved to the drafts board. Vendor not contacted."}


@mcp.tool()
def list_drafts(kind: Literal["customer_email", "vendor_request"] | None = None) -> list[dict]:
    """List drafts on the board."""
    if kind:
        return db.rows("SELECT * FROM drafts WHERE kind=? ORDER BY id DESC", (kind,))
    return db.rows("SELECT * FROM drafts ORDER BY id DESC")


# ---------- Human approvals ----------

@mcp.tool()
def request_approval(kind: str, summary: str, requested_by: str, payload_json: str = "{}") -> dict:
    """Ask the human operator to approve something (discount, refund, rush order, purchase, etc.).
    Returns once the request is recorded; the backend waits for the human's decision."""
    approval_id = db.execute(
        "INSERT INTO approvals (kind, summary, payload, requested_by, created_at) VALUES (?,?,?,?,?)",
        (kind, summary, payload_json, requested_by, db.now()),
    )
    return {"approval_id": approval_id, "status": "pending"}


@mcp.tool()
def get_approval(approval_id: int) -> dict:
    """Check the status of an approval request."""
    found = db.rows("SELECT * FROM approvals WHERE id=?", (approval_id,))
    if not found:
        raise ValueError(f"No approval {approval_id}")
    return found[0]


# ---------- Admin tools (backend/dashboard only) ----------

@mcp.tool()
def admin_list_approvals(status: str | None = None) -> list[dict]:
    """[admin] List approval requests."""
    if status:
        return db.rows("SELECT * FROM approvals WHERE status=? ORDER BY id DESC", (status,))
    return db.rows("SELECT * FROM approvals ORDER BY id DESC")


@mcp.tool()
def admin_decide_approval(approval_id: int, approved: bool, note: str = "") -> dict:
    """[admin] Record the human's decision on an approval request."""
    db.execute(
        "UPDATE approvals SET status=?, decision_note=?, decided_at=? WHERE id=?",
        ("approved" if approved else "rejected", note, db.now(), approval_id),
    )
    return get_approval(approval_id)


@mcp.tool()
def admin_set_draft_status(draft_id: int, status: Literal["draft", "reviewed", "discarded"]) -> dict:
    """[admin] Mark a draft reviewed or discarded. There is no 'sent' status by design."""
    db.execute("UPDATE drafts SET status=? WHERE id=?", (status, draft_id))
    return db.rows("SELECT * FROM drafts WHERE id=?", (draft_id,))[0]


if __name__ == "__main__":
    mcp.run()
