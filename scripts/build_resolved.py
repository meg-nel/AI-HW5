"""Build output/resolved_tickets.json and output/resolved_board.html from the Problem 9 runs.

Reads the per-ticket run logs written by scripts/drive_ticket.py (output/runs/ticket_<id>.json),
the final database, and the board screenshots in output/resolved_board/.

Run from the project root:  .venv\\Scripts\\python scripts\\build_resolved.py
"""

import html
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
DB = ROOT / "data" / "campus_customs_new.db"
TICKETS = (101, 102, 103)
LABEL = {"boss": "Boss", "inventory": "Inventory", "accounting": "Accounting", "facilities": "Facilities",
         "customer_service": "Customer Service"}


def db_rows(sql: str, params: tuple = ()) -> list[dict]:
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def build() -> dict:
    tickets = []
    for t in TICKETS:
        run = json.loads((OUT / "runs" / f"ticket_{t}.json").read_text(encoding="utf-8"))
        row = db_rows("SELECT * FROM tickets WHERE id = ?", (t,))[0]
        boss_decision = next(d for d in run["boss_report"]["tickets"] if d["ticket_id"] == t)
        draft = db_rows("SELECT id, recipient, subject, status, body FROM drafts WHERE ticket_id = ? AND status = 'draft'", (t,))
        tickets.append({
            "id": t,
            "subject": row["subject"],
            "requester": row["requester"],
            "type": row["type"],
            "final_status": row["status"],
            "outcome": boss_decision["decision"],
            "run_id": run["run_id"],
            "model": "gpt-6-luna",
            "usage": run["usage"],
            "cash": {"before": run["cash_before"], "after": run["cash_after"],
                     "change": round(run["cash_after"] - run["cash_before"], 2)},
            "agents": [
                {"agent": a["agent"], "contribution": a["summary"], "actions": a["actions"],
                 "delegated_to": a["delegated_to"], "tools_used": a["tools"]}
                for a in run["summary"]["agents"]
            ],
            "human_approvals": [
                {"approval_id": a["approval_id"], "kind": a["kind"], "amount": a["amount"],
                 "requested_by": a["requested_by"], "decision": a["decision"], "decided_by": a["decided_by"],
                 "paid": a["kind"] != "purchase_order" and a["cash_after"] < a["cash_before"],
                 "cash_before": a["cash_before"], "cash_after": a["cash_after"],
                 "details": {k: v for k, v in a["details"].items() if k in
                             ("payee", "due_date", "vendor_name", "sku", "size", "qty", "expected_arrival", "cash_shortfall")}}
                for a in run["approvals"]
            ],
            "draft_to_requester": ({"draft_id": draft[0]["id"], "recipient": draft[0]["recipient"],
                                    "subject": draft[0]["subject"], "sent": False} if draft else None),
            "ticket_note": row["notes"],
        })
    checking = db_rows("SELECT balance FROM cash_accounts WHERE name = 'checking'")[0]["balance"]
    return {
        "problem": "Problem 9: Resolve the Tickets",
        "shop_date": db_rows("SELECT date_today FROM desk")[0]["date_today"],
        "database": "data/campus_customs_new.db (reset to original values before the runs)",
        "approver": "Meg",
        "checking_start": tickets[0]["cash"]["before"],
        "checking_end": checking,
        "checking_end_matches_cash_accounts": checking == tickets[-1]["cash"]["after"],
        "payments": db_rows("SELECT * FROM payments ORDER BY id"),
        "tickets": tickets,
    }


def page(data: dict) -> str:
    e = html.escape
    money = lambda n: f"${n:,.2f}"  # noqa: E731
    cards = []
    for t in data["tickets"]:
        approvals = "".join(
            f"<li><b>#{a['approval_id']} {e(a['kind'].replace('_', ' '))} {money(a['amount'])}</b> — {e(a['decision'])} by "
            f"{e(a['decided_by'])}{' · paid' if a['paid'] else ' · no cash moved'} "
            f"(checking {money(a['cash_before'])} → {money(a['cash_after'])})</li>" for a in t["human_approvals"]
        ) or "<li>None</li>"
        agents = "".join(
            f"<li><b>{LABEL.get(a['agent'], a['agent'])}:</b> {e(a['contribution'] or '')}</li>" for a in t["agents"]
        )
        delta = t["cash"]["change"]
        cards.append(f"""
<section class="ticket" id="t{t['id']}">
  <header>
    <div><span class="tid">#{t['id']}</span><h2>{e(t['subject'])}</h2>
      <p>{e(t['requester'])} · {e(t['type'].replace('_', ' '))} · run <code>{e(t['run_id'])}</code></p></div>
    <span class="stamp">{e(t['final_status'].replace('_', ' ')).upper()}</span>
  </header>
  <p class="outcome">{e(t['outcome'])}</p>
  <div class="grid">
    <div><h3>Cash</h3><p class="cash">{money(t['cash']['before'])} → <b>{money(t['cash']['after'])}</b>
      <span class="{'neg' if delta < 0 else 'zero'}">{'−' + money(-delta) if delta < 0 else 'no change'}</span></p>
      <h3>Human approvals</h3><ul>{approvals}</ul></div>
    <div><h3>What each agent did</h3><ul>{agents}</ul></div>
  </div>
  <figure>
    <a href="resolved_board/ticket_{t['id']}.png" target="_blank"><img src="resolved_board/ticket_{t['id']}.png"
      alt="React board after ticket {t['id']} was resolved" loading="lazy"></a>
    <figcaption>The React board (http://localhost:5173) right after ticket {t['id']} resolved. Click to open full size.</figcaption>
  </figure>
</section>""")
    nav = "".join(f'<a href="#t{t["id"]}">#{t["id"]} {e(t["subject"])}</a>' for t in data["tickets"])
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Campus Customs — Resolved Tickets on the Board</title>
<style>
  :root {{ --ink:#3e2a20; --muted:#8a6d5c; --card:#fffaf4; --line:#efdcca; --accent:#b4532e; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font:16px/1.6 "Segoe UI",system-ui,sans-serif; color:var(--ink); background:#f6ece9; }}
  .hero {{ background:linear-gradient(180deg,#8f5a7a,#e9a98e); color:#fff8f2; padding:34px 40px 30px; }}
  .hero h1 {{ margin:0; font-size:28px; }} .hero p {{ margin:6px 0 0; color:#fbe6dc; }}
  .totals {{ display:flex; gap:14px; flex-wrap:wrap; margin-top:18px; }}
  .totals div {{ background:rgba(255,250,244,.9); color:var(--ink); border-radius:14px; padding:10px 18px; }}
  .totals b {{ display:block; font-size:22px; }}
  nav {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:16px; }}
  nav a {{ color:#fff; background:rgba(255,255,255,.18); padding:6px 14px; border-radius:999px; text-decoration:none; font-weight:600; }}
  main {{ max-width:1180px; margin:0 auto; padding:28px 40px 60px; display:grid; gap:28px; }}
  .ticket {{ background:var(--card); border:1px solid var(--line); border-radius:18px; padding:24px 28px; box-shadow:0 6px 22px rgba(120,60,30,.08); }}
  .ticket header {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; }}
  .tid {{ color:var(--accent); font-weight:700; }} h2 {{ margin:2px 0; font-size:24px; }} h3 {{ font-size:14px; text-transform:uppercase; letter-spacing:.08em; color:var(--accent); margin:14px 0 6px; }}
  header p {{ margin:0; color:var(--muted); font-size:14px; text-transform:capitalize; }}
  .stamp {{ font-weight:800; letter-spacing:.14em; color:#a2462c; border:3px solid #d98a6c; border-radius:10px; padding:6px 14px; transform:rotate(-4deg); background:#fff1e8; }}
  .outcome {{ background:#fbe4d8; border-left:5px solid var(--accent); border-radius:0 12px 12px 0; padding:12px 16px; margin:14px 0 4px; }}
  .grid {{ display:grid; grid-template-columns:1fr 1.4fr; gap:24px; }}
  ul {{ margin:0; padding-left:20px; }} li {{ margin:4px 0; font-size:14.5px; }}
  .cash {{ font-size:18px; margin:0; }} .neg {{ color:#a5483a; font-weight:700; margin-left:8px; }} .zero {{ color:var(--muted); margin-left:8px; }}
  code {{ font-family:Consolas,monospace; font-size:.85em; background:#f5e6d6; padding:1px 6px; border-radius:5px; text-transform:none; }}
  figure {{ margin:20px 0 0; }} figure img {{ width:100%; border-radius:12px; border:1px solid var(--line); }}
  figcaption {{ color:var(--muted); font-size:13.5px; margin-top:6px; }}
  @media (max-width:820px) {{ .grid {{ grid-template-columns:1fr; }} main, .hero {{ padding-left:18px; padding-right:18px; }} }}
</style></head>
<body>
<div class="hero">
  <h1>Campus Customs — Resolved Tickets on the Board</h1>
  <p>Problem 9 · shop date {e(data['shop_date'])} · five agents on gpt-6-luna · human approver: {e(data['approver'])}</p>
  <div class="totals">
    <div>Checking after reset<b>{money(data['checking_start'])}</b></div>
    <div>Paid out<b>{money(sum(p['amount'] for p in data['payments']))}</b></div>
    <div>Checking now (cash_accounts)<b>{money(data['checking_end'])}</b></div>
    <div>Tickets resolved<b>{sum(t['final_status'] == 'resolved' for t in data['tickets'])} of {len(data['tickets'])}</b></div>
  </div>
  <nav>{nav}</nav>
</div>
<main>{''.join(cards)}</main>
</body></html>
"""


if __name__ == "__main__":
    data = build()
    (OUT / "resolved_tickets.json").write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
    (OUT / "resolved_board.html").write_text(page(data), encoding="utf-8")
    print(f"Wrote output/resolved_tickets.json and output/resolved_board.html "
          f"(checking {data['checking_start']} -> {data['checking_end']}, matches: {data['checking_end_matches_cash_accounts']})")
