"""Run one ticket on the board API and act as the human approver.

Starts POST /tickets/{id}/run, polls GET /runs/current, and whenever the run pauses on an
approval request, approves it through POST /approvals/{id}/approve as the given person (the
approve route is what pays). Writes a JSON log of the run: approvals, cash before and after,
final ticket status, and the run summary.

Usage (from the project root, with the API running on :8000):
    .venv\\Scripts\\python scripts\\drive_ticket.py 101 --approver Meg --out output/runs/ticket_101.json
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

API = "http://127.0.0.1:8000"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ticket", type=int)
    ap.add_argument("--approver", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=int, default=1500, help="seconds to wait for the run")
    a = ap.parse_args()

    c = httpx.Client(base_url=API, timeout=60)
    log: dict = {"ticket_id": a.ticket, "approver": a.approver, "started_at": now(),
                 "cash_before": c.get("/cash").json()["balance"], "approvals": []}
    run = c.post(f"/tickets/{a.ticket}/run")
    run.raise_for_status()
    log["run_id"] = run.json()["run_id"]
    print(f"[{now()}] ticket {a.ticket} run {log['run_id']} started; cash ${log['cash_before']:,.2f}", flush=True)

    handled: set[int] = set()
    deadline = time.time() + a.timeout
    while time.time() < deadline:
        state = c.get("/runs/current").json()
        req = state.get("waiting_for_approval")
        if req and req["approval_id"] not in handled:
            handled.add(req["approval_id"])
            before = c.get("/cash").json()["balance"]
            resp = c.post(f"/approvals/{req['approval_id']}/approve",
                          json={"approved_by": a.approver, "note": "Approved on the board for Problem 9"})
            after = c.get("/cash").json()["balance"]
            entry = {"approval_id": req["approval_id"], "kind": req["kind"], "amount": req["amount"],
                     "requested_by": req["requested_by"], "reason": req["reason"], "details": req["details"],
                     "decision": "approved", "decided_by": a.approver, "decided_at": now(),
                     "http_status": resp.status_code, "response": resp.json(),
                     "cash_before": before, "cash_after": after}
            log["approvals"].append(entry)
            print(f"[{now()}] approved #{req['approval_id']} {req['kind']} ${req['amount']:,.2f} "
                  f"-> HTTP {resp.status_code}; cash ${before:,.2f} -> ${after:,.2f}", flush=True)
        if state["status"] != "running":
            break
        time.sleep(1.5)
    else:
        print("timed out waiting for the run", flush=True)

    state = c.get("/runs/current").json()
    log.update({
        "finished_at": now(), "status": state["status"], "error": state["error"], "usage": state["usage"],
        "boss_report": state["report"], "cash_after": c.get("/cash").json()["balance"],
        "ticket": next(t for t in c.get("/tickets").json()["tickets"] if t["id"] == a.ticket),
        "summary": c.get(f"/runs/{log['run_id']}/summary").json(),
        "events": c.get("/events", params={"run_id": log["run_id"], "limit": 1000}).json()["events"],
    })
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(log, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"[{now()}] run {state['status']}; ticket {a.ticket} is {log['ticket']['status']}; "
          f"cash ${log['cash_after']:,.2f}; wrote {out}", flush=True)
    return 0 if state["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
