"""Route tests for backend/main.py (FastAPI). Offline: a temporary database copy, a temporary
audit file, and a stand-in model for the run route. No API key or cost.

Run from the project root:  .venv\\Scripts\\python tests\\test_api.py
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp())
DB, AUDIT = TMP / "api_test.db", TMP / "audit_trail.json"
ORIGINAL = ROOT / "data" / "campus_customs_original.db"
shutil.copyfile(ORIGINAL, DB)
os.chmod(DB, 0o666)
os.environ.update(CAMPUS_CUSTOMS_DB=str(DB), CAMPUS_CUSTOMS_AUDIT=str(AUDIT), OPENAI_API_KEY="test-not-used")
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from pydantic_ai.messages import ModelResponse, ToolCallPart  # noqa: E402
from pydantic_ai.models.function import FunctionModel  # noqa: E402

import backend.main as main  # noqa: E402
import reset_db  # noqa: E402  (scripts/ is on sys.path once backend.main is imported)
from backend.agents import CampusCustomsTeam  # noqa: E402

# The reset route must restore the temporary copy, not the real working database.
reset_db.WORKING = DB
main.reset_database = reset_db.reset_database

passed = 0


def ok(cond: bool, label: str) -> None:
    global passed
    if not cond:
        raise AssertionError(label)
    passed += 1
    print(f"  PASS  {label}")


def sql(q: str) -> list[tuple]:
    conn = sqlite3.connect(DB)
    try:
        out = conn.execute(q).fetchall()
        conn.commit()
        return out
    finally:
        conn.close()


def boss_finishes(messages, info):
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
        "shop_date": "2026-08-31", "cash_at_start": 3400, "cash_at_end": 3400, "payment_priority": "test run",
        "tickets": [{"ticket_id": 101, "final_status": "in_progress", "owner": "boss", "decision": "test",
                     "actions_taken": []}]})])


def fake_team():
    team = CampusCustomsTeam()
    team.agents["boss"].model = FunctionModel(boss_finishes)
    return team


main.app.state.team_factory = fake_team


def main_test() -> None:
    c = TestClient(main.app)
    import asyncio
    shop = lambda tool, **a: asyncio.run(main.shop(tool, **a))  # noqa: E731

    print("GET /tickets")
    r = c.get("/tickets").json()
    ok([(t["id"], t["state"]) for t in r["tickets"]] == [(101, "open"), (102, "open"), (103, "open")],
       "three tickets, all open")

    print("GET /cash")
    ok(c.get("/cash").json()["balance"] == 3400.0, "checking balance comes from cash_accounts: $3,400")

    print("Approvals: agents prepare, the route pays")
    inv = shop("request_payment", kind="invoice", ref_id=501, requested_by="accounting", reason="test")
    rent = shop("request_payment", kind="rent", ref_id=1, requested_by="accounting", reason="test")
    ok([a["id"] for a in c.get("/approvals").json()] == [inv["id"], rent["id"]], "GET /approvals lists both pending requests")
    ok(c.get("/cash").json()["balance"] == 3400.0, "a pending request moves no cash")
    ok(c.post(f"/approvals/{inv['id']}/approve", json={"approved_by": ""}).status_code == 422,
       "approve needs the human's name")
    r = c.post(f"/approvals/{inv['id']}/approve", json={"approved_by": "Meg", "note": "pay it"})
    body = r.json()
    ok(r.status_code == 200 and body["payment"]["amount"] == 840.0 and body["payment"]["approved_by"] == "Meg"
       and body["checking_balance"] == 2560.0, "approve route pays invoice 501: $3,400 -> $2,560")
    ok(sql("SELECT status FROM invoices WHERE id = 501") == [("paid",)], "invoice 501 marked paid")
    ok(c.post(f"/approvals/{inv['id']}/approve", json={"approved_by": "Meg"}).status_code == 409,
       "approving an already-paid request is refused")
    r = c.post(f"/approvals/{rent['id']}/reject", json={"approved_by": "Meg", "note": "not yet"})
    ok(r.status_code == 200 and r.json()["approval"]["status"] == "rejected", "reject route records the rejection")
    ok(c.post(f"/approvals/{rent['id']}/approve", json={"approved_by": "Meg"}).status_code == 409,
       "a rejected request can't be approved")
    ok(c.get("/cash").json()["balance"] == 2560.0, "rejection moves no cash")

    po = shop("request_purchase_order", vendor_id=1, sku="CC-HOOD-NAVY", size="M", qty=12,
              requested_by="accounting", reason="test")
    r = c.post(f"/approvals/{po['id']}/approve", json={"approved_by": "Meg"}).json()
    ok(r["approval"]["status"] == "approved" and r["payment"] is None and c.get("/cash").json()["balance"] == 2560.0,
       "approving a purchase order records it without moving cash")

    sql("UPDATE cash_accounts SET balance = 1000 WHERE name = 'checking'")
    rent2 = shop("request_payment", kind="rent", ref_id=1, requested_by="accounting", reason="test")
    r = c.post(f"/approvals/{rent2['id']}/approve", json={"approved_by": "Meg"})
    ok(r.status_code == 409 and "not enough cash" in r.json()["detail"].lower()
       and c.get("/cash").json()["balance"] == 1000.0, "approve refuses $2,400 rent with $1,000 cash; balance unchanged")
    ok(c.get("/approvals").json() == [], "nothing left pending (the refused one is approved-but-unpaid)")

    print("POST /tickets/{id}/run and GET /events")
    ok(c.post("/tickets/999/run").status_code == 404, "unknown ticket is 404")
    r = c.post("/tickets/101/run")
    run_id = r.json()["run_id"]
    ok(r.status_code == 202 and r.json()["status"] == "running", "run starts in the background (202)")
    for _ in range(120):
        if c.get("/runs/current").json()["status"] != "running":
            break
        time.sleep(0.5)
    state = c.get("/runs/current").json()
    ok(state["status"] == "completed" and state["report"]["payment_priority"] == "test run",
       f"run completes and its report is available (status={state['status']}, error={state.get('error')})")
    ev = c.get("/events", params={"run_id": run_id}).json()["events"]
    kinds = [e["kind"] for e in ev]
    ok(kinds[0] == "run_start" and "task" in kinds and "report" in kinds and kinds[-1] == "run_end",
       "events for the run: run_start, task, report, run_end")
    ok(all(e["run_id"] == run_id for e in ev) and ev[1]["agent"] == "boss", "events are filtered to the run")
    allev = c.get("/events", params={"limit": 1000}).json()
    ok(any(e["kind"] == "payment_made" and e["agent"] == "human" for e in allev["events"]),
       "human approvals and payments appear in the events too")
    ok(c.get("/events", params={"after": allev["last_index"]}).json()["events"] == [], "after= returns only new events")

    print("POST /reset")
    r = c.post("/reset").json()
    ok(r["reset"] and r["cash"]["balance"] == 3400.0 and all(t["state"] == "open" for t in r["tickets"]),
       "reset restores cash $3,400 and all tickets open")
    ok(c.get("/approvals", params={"status": ""}).json() == [] and sql("SELECT COUNT(*) FROM payments") == [(0,)],
       "reset clears approvals and payments")

    print("Board run pauses for a human, the approve route pays, the run finishes resolved (demo agents)")
    from backend.demo import demo_team
    main.app.state.team_factory = demo_team

    def wait_until(pred, label):
        for _ in range(240):
            state = c.get("/runs/current").json()
            if pred(state):
                return state
            time.sleep(0.25)
        raise AssertionError(f"timed out: {label} (last state {state})")

    run_id = c.post("/tickets/101/run").json()["run_id"]
    state = wait_until(lambda s: s["waiting_for_approval"] or s["status"] != "running", "approval request")
    ok(state["status"] == "running" and state["waiting_for_approval"]["kind"] == "invoice_payment"
       and state["waiting_for_approval"]["amount"] == 840.0, "run pauses on the $840 invoice 501 request")
    ok(c.get("/cash").json()["balance"] == 3400.0, "nothing paid while waiting")
    appr_id = state["waiting_for_approval"]["approval_id"]
    r = c.post(f"/approvals/{appr_id}/approve", json={"approved_by": "Meg"}).json()
    ok(r["checking_balance"] == 2560.0, "approve route pays: checking drops $3,400 -> $2,560")
    state = wait_until(lambda s: s["status"] != "running", "run end")
    ok(state["status"] == "completed" and state["waiting_for_approval"] is None, "run resumes and completes")
    t101 = next(t for t in c.get("/tickets").json()["tickets"] if t["id"] == 101)
    ok(t101["state"] == "resolved", "ticket 101 shows resolved after the run")
    summary = c.get(f"/runs/{run_id}/summary").json()
    names = [a["agent"] for a in summary["agents"]]
    acct = next(a for a in summary["agents"] if a["agent"] == "accounting")
    ok(names == ["boss", "inventory", "accounting", "customer_service"] and "APPROVED AND PAID" in acct["summary"]
       and acct["tools"] == {"request_payment": 1}, "summary lists each agent with what it did and its tools")
    ev = c.get("/events", params={"run_id": run_id, "limit": 500}).json()["events"]
    ok(any(e["kind"] == "said" and e["agent"] == "inventory" and e["tools"] for e in ev)
       and any(e["kind"] == "waiting_for_human" for e in ev), "events show what agents said, their tools, and the pause")

    run_id = c.post("/tickets/102/run").json()["run_id"]
    state = wait_until(lambda s: s["waiting_for_approval"] or s["status"] != "running", "rent approval")
    c.post(f"/approvals/{state['waiting_for_approval']['approval_id']}/reject", json={"approved_by": "Meg", "note": "hold"})
    state = wait_until(lambda s: s["status"] != "running", "run end")
    acct = next(a for a in c.get(f"/runs/{run_id}/summary").json()["agents"] if a["agent"] == "accounting")
    ok(state["status"] == "completed" and "REJECTED" in acct["summary"] and c.get("/cash").json()["balance"] == 2560.0,
       "a rejection resumes the run without paying (checking stays $2,560)")
    c.post("/reset")

    print(f"\nAll {passed} API checks passed.")


if __name__ == "__main__":
    main_test()
