"""Check the working database after a full run against the original and the shop rules.

Run from the project root:  .venv\\Scripts\\python scripts\\check_run.py
Prints each check and writes output/run_db_check.json.
"""

import json
import sqlite3
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKING = ROOT / "data" / "campus_customs_new.db"
ORIGINAL = ROOT / "data" / "campus_customs_original.db"
OUT = ROOT / "output" / "run_db_check.json"


def rows(db: Path, sql: str) -> list[dict]:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def main() -> None:
    w = {t: rows(WORKING, f"SELECT * FROM {t}") for t in
         ["desk", "cash_accounts", "invoices", "leases", "payments", "tickets", "inventory", "pricing", "vendors",
          "approvals", "drafts"]}
    o = {t: rows(ORIGINAL, f"SELECT * FROM {t}") for t in
         ["desk", "cash_accounts", "invoices", "leases", "payments", "inventory", "pricing", "vendors"]}
    today = w["desk"][0]["date_today"]
    approvals = {a["id"]: a for a in w["approvals"]}
    checks = []

    def check(rule: str, passed: bool, evidence) -> None:
        checks.append({"rule": rule, "pass": bool(passed), "evidence": evidence})
        print(f"[{'PASS' if passed else 'FAIL'}] {rule}")

    # Every payment has a human-approved request behind it, for the same bill and amount.
    linked = []
    for p in w["payments"]:
        kind = "invoice_payment" if p["kind"] == "invoice" else "rent_payment"
        match = [a for a in w["approvals"] if a["kind"] == kind and a["ref_id"] == p["ref_id"]
                 and a["status"] == "paid" and a["decided_by"] == p["approved_by"] and a["amount"] == p["amount"]]
        linked.append({"payment": p, "approval_id": match[0]["id"] if match else None})
    check("Every payment has a matching human-approved request", w["payments"] and all(x["approval_id"] for x in linked), linked)
    check("No approval was decided by an agent name",
          all(a["decided_by"] not in ("boss", "inventory", "accounting", "facilities", "customer_service")
              for a in w["approvals"] if a["decided_by"]),
          [{k: a[k] for k in ("id", "kind", "status", "decided_by")} for a in w["approvals"]])

    paid_total = sum(p["amount"] for p in w["payments"])
    start = sum(a["balance"] for a in o["cash_accounts"])
    end = sum(a["balance"] for a in w["cash_accounts"])
    check("Cash only went out, by exactly the payments", round(start - paid_total, 2) == round(end, 2),
          {"start": start, "payments": paid_total, "end": end})
    check("No negative balance", all(a["balance"] >= 0 for a in w["cash_accounts"]), w["cash_accounts"])

    for p in w["payments"]:
        if p["kind"] == "invoice":
            inv = next(i for i in w["invoices"] if i["id"] == p["ref_id"])
            check(f"Paid invoice {p['ref_id']} is marked paid", inv["status"] == "paid", inv)
        else:
            before = next(l for l in o["leases"] if l["id"] == p["ref_id"])
            after = next(l for l in w["leases"] if l["id"] == p["ref_id"])
            check(f"Paid lease {p['ref_id']} rent moved next_due forward a month",
                  before["next_due"] != after["next_due"], {"before": before["next_due"], "after": after["next_due"]})
        check(f"Payment {p['id']} dated with the shop date", p["paid_at"] == today, {"paid_at": p["paid_at"], "shop_date": today})

    for a in w["approvals"]:
        if a["kind"] == "purchase_order":
            d = json.loads(a["details"])
            vendor = next(v for v in w["vendors"] if v["id"] == d["vendor_id"])
            expected = date.fromordinal(date.fromisoformat(today).toordinal() + vendor["lead_days"]).isoformat()
            open_at_request = [i for i in o["invoices"] if i["vendor_id"] == d["vendor_id"] and i["status"] == "open"]
            paid_first = all(any(p["kind"] == "invoice" and p["ref_id"] == i["id"] for p in w["payments"])
                             for i in open_at_request)
            check(f"Purchase order #{a['id']} uses vendors.lead_days ({vendor['lead_days']}) for arrival",
                  d["expected_arrival"] == expected, {"expected_arrival": d["expected_arrival"], "shop_date": today})
            check(f"Purchase order #{a['id']} placed only after the vendor's open invoices were paid", paid_first,
                  {"vendor": vendor["name"], "originally_open": [i["id"] for i in open_at_request]})

    check("Inventory, pricing, vendors, and desk unchanged",
          all(w[t] == o[t] for t in ("inventory", "pricing", "vendors", "desk")), "compared row by row")
    check("Every draft goes to its ticket's requester",
          all(d["recipient"] == next(t["requester"] for t in w["tickets"] if t["id"] == d["ticket_id"]) for d in w["drafts"]),
          [{k: d[k] for k in ("id", "ticket_id", "recipient", "subject", "status")} for d in w["drafts"]])
    check("No draft was sent (status is draft or discarded)",
          all(d["status"] in ("draft", "discarded") for d in w["drafts"]), len(w["drafts"]))
    live = [d["ticket_id"] for d in w["drafts"] if d["status"] == "draft"]
    check("At most one live draft per ticket", len(live) == len(set(live)),
          {t["id"]: [d["id"] for d in w["drafts"] if d["ticket_id"] == t["id"] and d["status"] == "draft"]
           for t in w["tickets"]})

    OUT.write_text(json.dumps({"shop_date": today, "all_passed": all(c["pass"] for c in checks), "checks": checks,
                               "tables_after_run": w}, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\n{sum(c['pass'] for c in checks)}/{len(checks)} checks passed. Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
