"""Shop-rule tests for the MCP server. Runs against a temporary copy of the original database.

Run from the project root:  .venv\\Scripts\\python tests\\test_shop_rules.py
"""

import asyncio
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP_DB = Path(tempfile.mkdtemp()) / "campus_customs_test.db"
shutil.copyfile(ROOT / "data" / "campus_customs_original.db", TMP_DB)
os.chmod(TMP_DB, 0o666)
os.environ["CAMPUS_CUSTOMS_DB"] = str(TMP_DB)
sys.path.insert(0, str(ROOT))

from fastmcp import Client  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402

from mcp_server.server import mcp  # noqa: E402

passed = 0


def ok(cond: bool, label: str) -> None:
    global passed
    if not cond:
        raise AssertionError(label)
    passed += 1
    print(f"  PASS  {label}")


def sql(q: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(TMP_DB)
    try:
        return conn.execute(q, params).fetchall()
    finally:
        conn.close()


async def call(c: Client, name: str, **args):
    return (await c.call_tool(name, args)).data


async def refused(c: Client, name: str, text: str, **args) -> bool:
    try:
        await c.call_tool(name, args)
    except ToolError as e:
        return text.lower() in str(e).lower()
    return False


async def main() -> None:
    async with Client(mcp) as c:
        tools = {t.name for t in await c.list_tools()}
        print(f"{len(tools)} tools: {', '.join(sorted(tools))}")

        print("Shop date")
        ok((await call(c, "get_shop_date"))["shop_date"] == "2026-08-31", "today comes from desk.date_today")
        t101 = await call(c, "get_ticket", ticket_id=101)
        ok(t101["linked"]["invoice"]["days_until_due"] == -3 and t101["linked"]["invoice"]["overdue"],
           "invoice 501 is 3 days overdue relative to the shop date")

        print("Vendors and lead times")
        vendors = {v["id"]: v for v in (await call(c, "list_vendors"))["vendors"]}
        ok(vendors[1]["lead_days"] == 5 and vendors[1]["earliest_arrival_if_ordered_today"] == "2026-09-05",
           "arrival = shop date + vendors.lead_days")
        ok(vendors[1]["will_ship"] is False and vendors[1]["open_unpaid_invoices"][0]["id"] == 501,
           "Bulldog Print Co won't ship while invoice 501 is open")
        ok(await refused(c, "request_purchase_order", "will not ship", vendor_id=1, sku="CC-HOOD-NAVY", size="M",
                         qty=12, requested_by="accounting", reason="t103 restock"),
           "purchase order to a vendor with an open invoice is refused")

        print("Human approval before payment")
        req = await call(c, "request_payment", kind="invoice", ref_id=501, requested_by="accounting", reason="test")
        ok(req["status"] == "pending" and req["amount"] == 840.0, "request_payment takes the amount from the database")
        ok(await refused(c, "pay_bill", "human must approve", approval_id=req["id"]), "pay_bill refuses a pending request")
        ok(sql("SELECT COUNT(*) FROM payments")[0][0] == 0, "no payment row without approval")

        await call(c, "admin_decide_approval", approval_id=req["id"], approved=False, decided_by="Tester", note="no")
        ok(await refused(c, "pay_bill", "rejected", approval_id=req["id"]), "pay_bill refuses a rejected request")

        req2 = await call(c, "request_payment", kind="invoice", ref_id=501, requested_by="accounting", reason="retry")
        await call(c, "admin_decide_approval", approval_id=req2["id"], approved=True, decided_by="Tester")
        paid = await call(c, "pay_bill", approval_id=req2["id"])
        ok(paid["payment"]["amount"] == 840.0 and paid["payment"]["approved_by"] == "Tester"
           and paid["payment"]["paid_at"] == "2026-08-31", "payments row records amount, shop date, human approver")
        ok(paid["cash_account"]["balance"] == 2560.0, "cash drops from $3,400 to $2,560")
        ok(sql("SELECT status FROM invoices WHERE id = 501")[0][0] == "paid", "invoice 501 marked paid")
        ok(await refused(c, "pay_bill", "paid", approval_id=req2["id"]), "an approval can't be paid twice")
        ok((await call(c, "list_vendors"))["vendors"][0]["will_ship"] is True, "vendor ships once invoice is paid")
        po = await call(c, "request_purchase_order", vendor_id=1, sku="CC-HOOD-NAVY", size="M", qty=12,
                        requested_by="accounting", reason="t103 restock")
        ok(po["amount"] == 264.0 and po["details"]["expected_arrival"] == "2026-09-05",
           "purchase order costed from pricing (12 x $22) with lead-time arrival")
        ok(po["details"]["cash_on_hand"] == 2560.0 and po["details"]["cash_shortfall"] == 0.0,
           "purchase order shows cash on hand and shortfall for the human")
        ok(await refused(c, "pay_bill", "not a payment", approval_id=po["id"]), "purchase orders can't be 'paid'")

        print("Not enough cash")
        sql_conn = sqlite3.connect(TMP_DB)
        sql_conn.execute("UPDATE cash_accounts SET balance = 1000 WHERE name = 'checking'")
        sql_conn.commit()
        sql_conn.close()
        rent = await call(c, "request_payment", kind="rent", ref_id=1, requested_by="accounting", reason="rent")
        await call(c, "admin_decide_approval", approval_id=rent["id"], approved=True, decided_by="Tester")
        ok(await refused(c, "pay_bill", "not enough cash", approval_id=rent["id"]),
           "pay_bill refuses $2,400 rent with $1,000 in checking")
        ok(sql("SELECT balance FROM cash_accounts")[0][0] == 1000.0 and
           sql("SELECT next_due FROM leases WHERE id = 1")[0][0] == "2026-09-02",
           "a refused payment changes nothing")
        try:
            conn = sqlite3.connect(TMP_DB)
            conn.executescript("UPDATE cash_accounts SET balance = -5 WHERE name = 'checking';")
            negative_blocked = False
        except sqlite3.IntegrityError:
            negative_blocked = True
        finally:
            conn.close()
        ok(negative_blocked, "database trigger blocks a negative balance even outside the tools")

        print("Rent payment updates the lease")
        sql_conn = sqlite3.connect(TMP_DB)
        sql_conn.execute("UPDATE cash_accounts SET balance = 2560 WHERE name = 'checking'")
        sql_conn.commit()
        sql_conn.close()
        paid_rent = await call(c, "pay_bill", approval_id=rent["id"])
        ok(paid_rent["updated_bill"]["next_due"] == "2026-10-02" and paid_rent["cash_account"]["balance"] == 160.0,
           "rent paid: lease next_due moves to 2026-10-02, cash $160")

        print("Drafts and tickets")
        draft = await call(c, "draft_customer_message", ticket_id=101, subject="Your tee", body="Hi", author="customer_service")
        ok(draft["recipient"] == "Tauhid Zaman" and draft["status"] == "draft", "draft goes to the ticket's requester, unsent")
        gone = await call(c, "discard_draft", draft_id=draft["id"], reason="superseded", author="customer_service")
        ok(gone["status"] == "discarded" and "superseded" in gone["body"], "outdated draft can be discarded, kept on record")
        ok(await refused(c, "discard_draft", "already", draft_id=draft["id"], reason="again", author="customer_service"),
           "a draft can't be discarded twice")
        upd = await call(c, "update_ticket", ticket_id=101, status="waiting_on_vendor", note="reprint ordered", updated_by="boss")
        ok(upd["status"] == "waiting_on_vendor" and "[2026-08-31 boss] reprint ordered" in upd["notes"],
           "ticket note is stamped with the shop date and agent")
        ok(await refused(c, "check_stock", "no size", sku="CC-MUG-CREST", size="M", qty_needed=1),
           "unknown size is an error, not a guess")

    print(f"\nAll {passed} shop-rule checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
