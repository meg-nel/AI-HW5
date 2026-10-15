"""MCP smoke test: call each campus-customs tool over MCP and check its output against the database.

Starts the server exactly as .mcp.json describes, calls each tool once for the ticket it
unlocks, then re-reads the same values from data/campus_customs_new.db with plain SQL
(independent of the server code) and records whether they match.

Run from the project root:  .venv\\Scripts\\python scripts\\mcp_smoke.py
Writes:                      output/mcp_smoke.json
"""

import asyncio
import json
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "campus_customs_new.db"
OUT = ROOT / "output" / "mcp_smoke.json"

TESTS = [
    {
        "ticket": 101,
        "prompt": "Ticket 101: Tauhid Zaman wants 1 Classic Bulldog Tee (CC-TEE-WHITE) in size S. "
                  "Can we fill it from the shelf, and if not, how many are we short?",
        "tool": "check_stock",
        "arguments": {"sku": "CC-TEE-WHITE", "size": "S", "qty_needed": 1},
    },
    {
        "ticket": 102,
        "prompt": "Ticket 102: Elm City Properties says rent on the Chapel Street shop is due. "
                  "What bills do we owe, when is each due, and how much cash is left after paying them?",
        "tool": "get_bills_and_cash",
        "arguments": {},
    },
    {
        "ticket": 103,
        "prompt": "Ticket 103: Yale AI Club wants 20 Basic Hoodie Big Yale (CC-HOOD-NAVY) at a bulk discount. "
                  "What are the price and margin for 20 hoodies at 10% off list?",
        "tool": "quote_price_margin",
        "arguments": {"sku": "CC-HOOD-NAVY", "qty": 20, "discount_pct": 10},
    },
]


def db_rows(sql: str, params: tuple = ()) -> list[dict]:
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def check(field: str, tool_value, db_value) -> dict:
    return {"field": field, "tool_value": tool_value, "db_value": db_value, "match": tool_value == db_value}


def verify(test: dict, out: dict) -> tuple[list[dict], list[dict]]:
    """Return (SQL queries used, field-by-field comparisons) for one tool result."""
    a = test["arguments"]
    if test["tool"] == "check_stock":
        sql = "SELECT sku, name, size, qty, location FROM inventory WHERE sku = ? AND size = ?"
        row = db_rows(sql, (a["sku"], a["size"]))[0]
        return [{"sql": sql, "params": [a["sku"], a["size"]], "rows": [row]}], [
            check("name", out["name"], row["name"]),
            check("location", out["location"], row["location"]),
            check("qty_on_hand", out["qty_on_hand"], row["qty"]),
            check("shortfall", out["shortfall"], max(0, a["qty_needed"] - row["qty"])),
        ]

    if test["tool"] == "quote_price_margin":
        sql = "SELECT sku, unit_cost, list_price FROM pricing WHERE sku = ?"
        row = db_rows(sql, (a["sku"],))[0]
        price = round(row["list_price"] * (1 - a["discount_pct"] / 100), 2)
        return [{"sql": sql, "params": [a["sku"]], "rows": [row]}], [
            check("unit_cost", out["unit_cost"], row["unit_cost"]),
            check("list_price", out["list_price"], row["list_price"]),
            check("unit_price (list less discount)", out["unit_price"], price),
            check("total_price", out["total_price"], round(price * a["qty"], 2)),
            check("total_margin", out["total_margin"], round((price - row["unit_cost"]) * a["qty"], 2)),
        ]

    if test["tool"] == "get_bills_and_cash":
        queries = {
            "desk": "SELECT date_today FROM desk",
            "cash": "SELECT name, balance FROM cash_accounts",
            "invoices": "SELECT i.id, v.name AS vendor, i.amount, i.due_date FROM invoices i "
                        "JOIN vendors v ON v.id = i.vendor_id WHERE i.status = 'open'",
            "leases": "SELECT id, landlord, monthly_rent, next_due FROM leases",
        }
        rows = {k: db_rows(q) for k, q in queries.items()}
        today = date.fromisoformat(rows["desk"][0]["date_today"])
        inv = rows["invoices"][0]
        lease = rows["leases"][0]
        bills = {b.get("invoice_id") or f"lease-{b.get('lease_id')}": b for b in out["bills"]}
        cash = sum(r["balance"] for r in rows["cash"])
        owed = sum(r["amount"] for r in rows["invoices"]) + sum(r["monthly_rent"] for r in rows["leases"])
        return [{"sql": q, "params": [], "rows": rows[k]} for k, q in queries.items()], [
            check("shop_date", out["shop_date"], today.isoformat()),
            check("cash_total", out["cash_total"], cash),
            check(f"invoice {inv['id']} payee", bills[inv["id"]]["payee"], inv["vendor"]),
            check(f"invoice {inv['id']} amount", bills[inv["id"]]["amount"], inv["amount"]),
            check(f"invoice {inv['id']} days_until_due", bills[inv["id"]]["days_until_due"],
                  (date.fromisoformat(inv["due_date"]) - today).days),
            check(f"lease {lease['id']} payee", bills[f"lease-{lease['id']}"]["payee"], lease["landlord"]),
            check(f"lease {lease['id']} rent", bills[f"lease-{lease['id']}"]["amount"], lease["monthly_rent"]),
            check(f"lease {lease['id']} days_until_due", bills[f"lease-{lease['id']}"]["days_until_due"],
                  (date.fromisoformat(lease["next_due"]) - today).days),
            check("cash_after_all_bills", out["cash_after_all_bills"], round(cash - owed, 2)),
        ]

    raise ValueError(f"No verifier for {test['tool']}")


async def main() -> None:
    cfg = json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]["campus-customs"]
    params = StdioServerParameters(command=cfg["command"], args=cfg["args"], env={**os.environ, **cfg.get("env", {})})
    results = []
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        listed = [t.name for t in (await session.list_tools()).tools]
        for test in TESTS:
            res = await session.call_tool(test["tool"], test["arguments"])
            text = "\n".join(c.text for c in res.content if c.type == "text")
            output = json.loads(text) if not res.isError else text
            queries, checks = verify(test, output) if not res.isError else ([], [])
            results.append({
                **test,
                "is_error": res.isError,
                "tool_output": output,
                "db_queries": queries,
                "db_checks": checks,
                "pass": not res.isError and all(c["match"] for c in checks),
            })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "server": "campus-customs (stdio, launched from .mcp.json)",
        "database": "data/campus_customs_new.db",
        "tools_listed_by_server": listed,
        "all_passed": all(r["pass"] for r in results),
        "results": results,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    for r in results:
        print(f"[{'PASS' if r['pass'] else 'FAIL'}] ticket {r['ticket']} {r['tool']}: "
              f"{sum(c['match'] for c in r['db_checks'])}/{len(r['db_checks'])} fields match the database")
    print(f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
