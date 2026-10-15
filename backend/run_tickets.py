"""Full run: reset the database, then have the Boss work every open ticket.

Payments and purchase orders stop and ask you (in this terminal) to approve or reject.

Run from the project root:
    .venv\\Scripts\\python -m backend.run_tickets
Options:
    --no-reset   keep the current database instead of restoring the original values

Writes output/run_report.json: the Boss's report, every event (delegations, tool calls,
approvals), and the database tables the run changed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.agents import MODEL, CampusCustomsTeam
from backend.models import ApprovalDecision, ApprovalRequest

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "output" / "run_report.json"
DB = ROOT / "data" / "campus_customs_new.db"

DEFAULT_PROMPT = (
    "Work every open ticket in the shop. Read them all, check the cash position, route work to the "
    "right teammates, decide the payment order for the whole shop, make the final call on each ticket, "
    "make sure each requester has a drafted reply, update every ticket, and return your report."
)


# While the human is answering an approval, other agents' output is held here so it
# doesn't land on top of the "Approve? [y/N]" prompt. Approvals are asked one at a time.
_held_output: list[str] | None = None
_approval_lock = asyncio.Lock()


def make_terminal_approver(human_name: str):
    async def approve(request: ApprovalRequest) -> ApprovalDecision:
        global _held_output
        async with _approval_lock:
            _held_output = []
            try:
                d = request.details
                print("\n" + "=" * 70)
                print(f"APPROVAL NEEDED  #{request.approval_id}  {request.kind}  ${request.amount:,.2f}")
                print(f"Requested by: {request.requested_by}")
                if request.kind == "purchase_order":
                    print(f"Order: {d.get('qty')} x {d.get('sku')} ({d.get('size')}) from {d.get('vendor_name')}, "
                          f"arrives {d.get('expected_arrival')}")
                    print(f"No cash moves now; the vendor invoices later. Cash on hand ${d.get('cash_on_hand', 0):,.2f}"
                          + (f", short ${d['cash_shortfall']:,.2f} for this order" if d.get("cash_shortfall") else ""))
                else:
                    print(f"Pay: {d.get('payee')}  due {d.get('due_date')} ({d.get('days_until_due')} days)")
                print(f"Reason: {request.reason}")
                answer = (await asyncio.to_thread(input, "Approve? [y/N] ")).replace("﻿", "").strip().lower()
                note = (await asyncio.to_thread(input, "Note for the agent (optional): ")).strip()
                print("=" * 70)
            finally:
                held, _held_output = _held_output, None
                for line in held:
                    print(line)
        return ApprovalDecision(approved=answer in ("y", "yes"), decided_by=human_name, note=note)

    return approve


def print_event(event: dict) -> None:
    line = format_event(event)
    if line is None:
        return
    if _held_output is not None:
        _held_output.append(line)
    else:
        print(line)


def format_event(event: dict) -> str | None:
    who = " -> ".join([*event["chain"], event["agent"]])
    t = event["type"]
    if t == "delegation":
        return f"[{who}] delegates to {event['to_agent']}: {event['task'][:160]}"
    if t == "delegation_result":
        return f"[{who}] reports back to {event['to_agent']}: {event['report'].get('summary', '')[:200]}"
    if t == "tool_call":
        return f"[{who}] calls {event['tool']}({json.dumps(event['args'])[:160]})"
    if t == "approval_decided":
        return (f"[{who}] approval #{event['approval_id']} {'APPROVED' if event['approved'] else 'REJECTED'} "
                f"by {event['decided_by']}")
    return None


def snapshot_tables() -> dict:
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = ["tickets", "cash_accounts", "invoices", "leases", "payments", "approvals", "drafts"]
        return {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t}")] for t in tables}
    finally:
        conn.close()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-reset", action="store_true", help="don't reset the database first")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="task for the Boss")
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set. Copy .env.example to .env and paste your key after OPENAI_API_KEY=.")
        return 1

    if not args.no_reset:
        sys.path.insert(0, str(ROOT / "scripts"))
        from reset_db import reset_database
        reset_database()
        print("Database reset to original values.")

    human = (await asyncio.to_thread(input, "Your name (recorded as the approver on payments): ")
             ).replace("﻿", "").strip() or "human"
    events: list[dict] = []

    def on_event(e: dict) -> None:
        events.append(e)
        print_event(e)

    team = CampusCustomsTeam()
    started = datetime.now(timezone.utc)
    result, error = None, None
    try:
        result = await team.run(args.prompt, make_terminal_approver(human), on_event=on_event)
    except BaseException as e:  # still save what happened, including Ctrl-C
        error = f"{type(e).__name__}: {e}"
        raise
    finally:
        save_report(build_report(started, not args.no_reset, events, result, error))
    print("\n" + json.dumps(result.output.model_dump(), indent=2))
    return 0


def build_report(started: datetime, reset: bool, events: list[dict], result, error: str | None) -> dict:
    report = {
        "model": MODEL,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "database_reset": reset,
        "completed": result is not None,
        "error": error,
        "usage": None,
        "boss_report": None,
        "events": events,
        "database_after": snapshot_tables(),
    }
    if result is not None:
        usage = result.usage() if callable(result.usage) else result.usage
        report["usage"] = {"requests": usage.requests, "input_tokens": usage.input_tokens,
                           "output_tokens": usage.output_tokens}
        report["boss_report"] = result.output.model_dump()
    return report


def save_report(report: dict) -> None:
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nSaved {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
