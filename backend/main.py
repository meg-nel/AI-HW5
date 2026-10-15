"""Campus Customs board API (FastAPI).

Start it from the backend/ folder:
    uvicorn main:app --reload --port 8000
(with the project's virtual environment: ..\\.venv\\Scripts\\uvicorn main:app --reload --port 8000)

Routes (interactive docs at http://localhost:8000/docs):
    GET  /tickets                      the three tickets and whether each is open or resolved
    POST /tickets/{ticket_id}/run      run the agent team on one ticket (in the background)
    GET  /runs/current                 status of the latest run (and the approval it is paused on, if any)
    GET  /runs/{run_id}/summary        short summary of what each agent did in a run
    GET  /events                       recent agent events: what each agent said and which tools it used
    GET  /approvals                    payment and purchase-order requests waiting for a human
    POST /approvals/{id}/approve       a human approves; for a payment this is what actually pays and moves cash
    POST /approvals/{id}/reject        a human rejects; nothing is paid or ordered
    GET  /cash                         current checking balance from cash_accounts
    POST /reset                        reset the database to the original values for a fresh run

Every shop fact goes through the campus-customs MCP server (the same 21 tools the agents use),
here called in-process with a FastMCP client. Agents only *prepare* payments. A board run pauses
on each payment or purchase-order request until a human calls the approve or reject route; the
approve route is what records the decision and pays, then the run continues with the outcome.

CAMPUS_CUSTOMS_DEMO=1 runs scripted stand-in agents instead of gpt-6-luna (free, for trying the board).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "scripts"):  # so `uvicorn main:app` works when started from backend/
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastmcp import Client  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from backend.agents import MODEL, CampusCustomsTeam  # noqa: E402  (importing backend loads .env)
from backend.audit import AuditTrail, read_entries  # noqa: E402
from backend.models import ApprovalDecision, ApprovalRequest  # noqa: E402
from mcp_server.server import mcp as shop_mcp  # noqa: E402
from reset_db import reset_database  # noqa: E402

TICKET_PROMPT = (
    "Work ticket {ticket_id} only. Read it and the shop's cash position, route the work to the right "
    "teammates, set the money plan this ticket needs, make the final call, have the requester's reply drafted, "
    "update the ticket, and return your report. A human is watching the board: each payment or purchase order "
    "Accounting requests pauses until they approve or reject it, and their approval is what pays. "
    "For this board run, when the desk's work is done (decision made, approvals decided, reply drafted), mark the "
    "ticket resolved and put any follow-up, such as an expected delivery date, in the note. Use waiting_on_human "
    "only if a request was left undecided or a rejection needs a new human decision."
)
EVENT_TEXT_LIMIT = 600
APPROVAL_WAIT_SECONDS = 30 * 60  # how long a board run waits for a human before leaving a request pending

app = FastAPI(title="Campus Customs Board API", version="1.0",
              description="Tickets, agent runs, events, human approvals, cash, and reset.")
# The Vite dashboard (npm run dev) is served from port 5173; allow the browser to call these routes from it.
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

# CAMPUS_CUSTOMS_DEMO=1 swaps gpt-6-luna for scripted stand-in agents (free, for trying the board).
# Tests also swap this.
if os.environ.get("CAMPUS_CUSTOMS_DEMO") == "1":
    from backend.demo import demo_team as _factory  # noqa: E402
else:
    _factory = CampusCustomsTeam
app.state.team_factory = _factory
DEMO_MODE = _factory is not CampusCustomsTeam


# ---------------------------------------------------------------- MCP access

class ShopError(Exception):
    pass


async def shop(tool: str, **args: Any) -> Any:
    """Call one campus-customs MCP tool and return its decoded result."""
    async with Client(shop_mcp) as client:
        res = await client.call_tool(tool, args, raise_on_error=False)
    text = "\n".join(c.text for c in res.content if getattr(c, "type", "") == "text")
    if res.is_error:
        raise ShopError(text or f"{tool} failed")
    sc = res.structured_content
    if isinstance(sc, dict):
        return sc["result"] if set(sc) == {"result"} else sc
    return json.loads(text) if text else None


def audit_human(type_: str, **data: Any) -> None:
    """Human actions on the board go into the same append-only audit trail as agent steps."""
    AuditTrail().append({"run_id": "board", "type": type_, "agent": "human", "chain": [], **data})


# ---------------------------------------------------------------- run state

class RunState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.clear()

    def clear(self) -> None:
        self.run_id: str | None = None
        self.ticket_id: int | None = None
        self.status = "idle"  # idle | running | completed | error
        self.error: str | None = None
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.report: dict | None = None
        self.usage: dict | None = None
        self.waiting_for_approval: dict | None = None  # the request the run is paused on, if any

    @property
    def running(self) -> bool:
        return self.status == "running"

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("run_id", "ticket_id", "status", "error", "started_at",
                                               "finished_at", "report", "usage", "waiting_for_approval")}


RUN = RunState()


class BoardApprovals:
    """Lets a board run pause on an approval request until a human clicks approve or reject.

    The run lives on its own event loop in a background thread; the routes run on uvicorn's loop.
    The route does the real work (records the decision, pays), then hands the outcome to the
    waiting run with call_soon_threadsafe."""

    def __init__(self) -> None:
        self._waiting: dict[int, tuple[asyncio.AbstractEventLoop, asyncio.Future]] = {}
        self._lock = threading.Lock()

    async def approver(self, request: ApprovalRequest) -> ApprovalDecision | None:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        with self._lock:
            self._waiting[request.approval_id] = (loop, fut)
        RUN.waiting_for_approval = request.model_dump()
        try:
            return await asyncio.wait_for(fut, timeout=APPROVAL_WAIT_SECONDS)
        except asyncio.TimeoutError:
            return None  # left pending; it can still be approved on the board later
        finally:
            with self._lock:
                self._waiting.pop(request.approval_id, None)
            RUN.waiting_for_approval = None

    def deliver(self, approval_id: int, decision: ApprovalDecision) -> bool:
        with self._lock:
            entry = self._waiting.get(approval_id)
        if entry is None:
            return False
        loop, fut = entry
        loop.call_soon_threadsafe(lambda: fut.done() or fut.set_result(decision))
        return True


BOARD = BoardApprovals()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run_team_in_thread(ticket_id: int, run_id: str) -> None:
    """Agent runs start the MCP server as a subprocess. Windows needs a Proactor event loop for
    that, and uvicorn --reload may run a selector loop, so each run gets its own loop in a thread."""
    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        team = app.state.team_factory()
        result = loop.run_until_complete(
            team.run(TICKET_PROMPT.format(ticket_id=ticket_id), BOARD.approver, run_id=run_id))
        usage = result.usage() if callable(result.usage) else result.usage
        RUN.report = result.output.model_dump()
        RUN.usage = {"requests": usage.requests, "tool_calls": usage.tool_calls,
                     "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}
        RUN.status = "completed"
    except BaseException as e:  # noqa: BLE001 - report every failure on the board
        RUN.status, RUN.error = "error", f"{type(e).__name__}: {e}"
    finally:
        RUN.finished_at = _now()
        loop.close()


# ---------------------------------------------------------------- routes: tickets and runs

@app.get("/tickets", summary="The three tickets and whether each is open or resolved")
async def get_tickets():
    data = await shop("list_tickets")
    return {
        "shop_date": data["shop_date"],
        "tickets": [{"id": t["id"], "type": t["type"], "requester": t["requester"], "subject": t["subject"],
                     "status": t["status"], "state": t["state"]} for t in data["tickets"]],
    }


@app.post("/tickets/{ticket_id}/run", status_code=202, summary="Run the agent team on one ticket")
async def run_ticket(ticket_id: int):
    try:
        await shop("get_ticket", ticket_id=ticket_id)
    except ShopError as e:
        raise HTTPException(404, str(e)) from e
    if not DEMO_MODE and not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(503, "OPENAI_API_KEY is not set in .env")
    with RUN.lock:
        if RUN.running:
            raise HTTPException(409, f"Run {RUN.run_id} on ticket {RUN.ticket_id} is still running")
        run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-t{ticket_id}-{uuid.uuid4().hex[:4]}"
        RUN.clear()
        RUN.run_id, RUN.ticket_id, RUN.status, RUN.started_at = run_id, ticket_id, "running", _now()
    threading.Thread(target=_run_team_in_thread, args=(ticket_id, run_id), daemon=True, name=run_id).start()
    return {"run_id": run_id, "ticket_id": ticket_id, "status": "running",
            "model": "demo (scripted stand-in agents)" if DEMO_MODE else MODEL, "watch": f"/events?run_id={run_id}"}


@app.get("/runs/current", summary="Status of the latest run")
async def current_run():
    return {**RUN.as_dict(), "demo_mode": DEMO_MODE}


def _read_audit() -> list[dict]:
    return read_entries()  # same lock as the writers, with retries for Windows file sharing


@app.get("/runs/{run_id}/summary", summary="Short summary of what each agent did in a run")
async def run_summary(run_id: str):
    entries = [e for e in _read_audit() if e.get("run_id") == run_id]
    if not entries:
        raise HTTPException(404, f"No run {run_id} in the audit trail")
    agents: dict[str, dict] = {}
    for e in entries:
        name = e.get("agent")
        if not name or name == "human":
            continue
        a = agents.setdefault(name, {"agent": name, "summary": None, "decisions": [], "actions": [],
                                     "tools": {}, "delegated_to": [], "steps": 0})
        t = e.get("type")
        if t == "tool_call":
            a["tools"][e["tool"]] = a["tools"].get(e["tool"], 0) + 1
        elif t == "delegation":
            a["delegated_to"].append(e.get("to_agent"))
        elif t == "loop_step":
            a["steps"] += 1
            if e.get("node") == "end":
                out = e.get("output") or {}
                if "tickets" in out:  # the Boss's report
                    a["summary"] = out.get("payment_priority")
                    a["decisions"] = [{"ticket_id": t["ticket_id"], "final_status": t["final_status"],
                                       "decision": t["decision"]} for t in out["tickets"]]
                    a["actions"] = [x for t in out["tickets"] for x in t.get("actions_taken", [])]
                else:
                    a["summary"] = out.get("summary")
                    a["actions"] += out.get("actions_taken", [])
    end = next((e for e in reversed(entries) if e.get("type") == "run_end"), None)
    order = ["boss", "inventory", "accounting", "facilities", "customer_service"]
    return {"run_id": run_id, "status": end.get("status") if end else "running",
            "usage": end.get("usage") if end else None,
            "agents": sorted(agents.values(), key=lambda a: order.index(a["agent"]) if a["agent"] in order else 99)}


# ---------------------------------------------------------------- routes: events

def _clip(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= EVENT_TEXT_LIMIT else text[:EVENT_TEXT_LIMIT] + "..."


def board_event(index: int, e: dict) -> dict | None:
    """Turn one audit-trail entry into a board line: who, what they said, which tools they used."""
    base = {"index": index, "ts": e.get("ts"), "run_id": e.get("run_id"), "agent": e.get("agent"),
            "chain": e.get("chain", []), "kind": e.get("type"), "said": None, "tools": []}
    t = e.get("type")
    if t == "loop_step":
        node = e.get("node")
        if node == "model_response":
            parts = e.get("parts", [])
            text = " ".join(p.get("content", "") for p in parts if p.get("kind") == "text" and p.get("content"))
            calls = [{"tool": p["tool"], "args": p.get("args")} for p in parts
                     if p.get("kind") == "tool-call" and p.get("tool") != "final_result"]
            if not text and not calls:
                return None
            return {**base, "kind": "said", "said": _clip(text) if text else None, "tools": calls}
        if node == "end":
            out = e.get("output") or {}
            summary = out.get("summary") or out.get("payment_priority") or out
            return {**base, "kind": "report", "said": _clip(summary)}
        if node == "user_prompt":
            return {**base, "kind": "task", "said": _clip(e.get("prompt", ""))}
        return None  # model_request: the tool results are already covered by tool_result events
    if t == "tool_result":
        res = e.get("error") or e.get("result")
        return {**base, "said": _clip(res), "tools": [{"tool": e.get("tool")}], "error": "error" in e}
    if t == "tool_call":
        return {**base, "tools": [{"tool": e.get("tool"), "args": e.get("args")}]}
    if t == "delegation":
        return {**base, "said": _clip(e.get("task", "")), "to_agent": e.get("to_agent")}
    if t == "delegation_result":
        return {**base, "said": _clip((e.get("report") or {}).get("summary", "")), "to_agent": e.get("to_agent")}
    if t == "approval_requested":
        r = e.get("request", {})
        return {**base, "said": f"Requests approval #{r.get('approval_id')}: {r.get('kind')} ${r.get('amount', 0):,.2f}"
                                f" - {r.get('reason') or ''}"[:EVENT_TEXT_LIMIT], "approval_id": r.get("approval_id")}
    if t == "waiting_for_human":
        return {**base, "said": f"Waiting for a human to approve or reject #{e.get('approval_id')} on the board",
                "approval_id": e.get("approval_id")}
    if t in ("approval_decided", "human_approved", "human_rejected"):
        approved = e.get("approved", t == "human_approved")
        return {**base, "said": f"#{e.get('approval_id')} {'approved' if approved else 'rejected'} by "
                                f"{e.get('decided_by')}" + (f": {e['note']}" if e.get("note") else ""),
                "approval_id": e.get("approval_id")}
    if t == "payment_made":
        p = e.get("payment") or {}
        pay, bal = p.get("payment", p), e.get("balance", (p.get("cash_account") or {}).get("balance"))
        return {**base, "said": f"Paid ${pay.get('amount', 0):,.2f} ({pay.get('kind')} {pay.get('ref_id')}), "
                                f"approved by {pay.get('approved_by')}. Checking now ${bal:,.2f}" if bal is not None
                else f"Paid ${pay.get('amount', 0):,.2f}", "approval_id": e.get("approval_id")}
    if t == "payment_refused":
        return {**base, "said": f"#{e.get('approval_id')} not paid: {e.get('error')}", "error": True}
    if t == "database_reset":
        return {**base, "said": "Database reset to the original values"}
    if t in ("run_start", "run_end"):
        said = e.get("prompt") if t == "run_start" else (e.get("status") + (f": {e['error']}" if e.get("error") else ""))
        return {**base, "said": _clip(said or "")}
    return {**base, "said": _clip({k: v for k, v in e.items() if k not in base and k not in ("type", "seq")})}


@app.get("/events", summary="Recent agent events: what each agent said and which tools it used")
async def get_events(limit: int = Query(100, ge=1, le=1000),
                     after: int | None = Query(None, description="Only events after this index (for polling)"),
                     run_id: str | None = None):
    entries = _read_audit()
    events = []
    for i, e in enumerate(entries):
        if (after is not None and i <= after) or (run_id and e.get("run_id") != run_id):
            continue
        ev = board_event(i, e)
        if ev:
            events.append(ev)
    events = events[-limit:]
    return {"events": events, "last_index": len(entries) - 1, "run": RUN.as_dict()}


# ---------------------------------------------------------------- routes: approvals and cash

class Decision(BaseModel):
    approved_by: str = Field(..., min_length=1, description="Name of the human approving")
    note: str = ""


@app.get("/approvals", summary="Payment and purchase-order requests (pending by default)")
async def get_approvals(status: str | None = "pending"):
    return await shop("list_approvals", **({"status": status} if status else {}))


@app.post("/approvals/{approval_id}/approve",
          summary="Human approves. For a payment this is what actually pays and changes cash")
async def approve(approval_id: int, body: Decision):
    try:
        appr = await shop("get_approval", approval_id=approval_id)
    except ShopError as e:
        raise HTTPException(404, str(e)) from e
    if appr["status"] in ("rejected", "paid"):
        raise HTTPException(409, f"Approval {approval_id} is already {appr['status']}")
    if appr["status"] == "pending":
        appr = await shop("admin_decide_approval", approval_id=approval_id, approved=True,
                          decided_by=body.approved_by.strip(), note=body.note)
        audit_human("human_approved", approval_id=approval_id, kind=appr["kind"], amount=appr["amount"],
                    decided_by=body.approved_by.strip(), note=body.note)
    who = body.approved_by.strip()
    if appr["kind"] == "purchase_order":
        BOARD.deliver(approval_id, ApprovalDecision(approved=True, decided_by=who, note=body.note, applied=True))
        return {"approval": appr, "payment": None, "note": "Purchase order approved. No cash moves until the vendor invoices."}

    # A payment: this route is what pays. pay_bill re-checks the approval and refuses if cash is short.
    try:
        paid = await shop("pay_bill", approval_id=approval_id)
    except ShopError as e:
        audit_human("payment_refused", approval_id=approval_id, error=str(e))
        BOARD.deliver(approval_id, ApprovalDecision(approved=True, decided_by=who, note=body.note, applied=True,
                                                    payment_error=str(e)))
        raise HTTPException(409, f"Approved but not paid: {e}") from e
    audit_human("payment_made", approval_id=approval_id, payment=paid["payment"],
                balance=paid["cash_account"]["balance"])
    BOARD.deliver(approval_id, ApprovalDecision(approved=True, decided_by=who, note=body.note, applied=True,
                                                payment=paid))
    return {"approval": await shop("get_approval", approval_id=approval_id), "payment": paid["payment"],
            "updated_bill": paid["updated_bill"], "checking_balance": paid["cash_account"]["balance"]}


@app.post("/approvals/{approval_id}/reject", summary="Human rejects. Nothing is paid or ordered")
async def reject(approval_id: int, body: Decision):
    try:
        appr = await shop("admin_decide_approval", approval_id=approval_id, approved=False,
                          decided_by=body.approved_by.strip(), note=body.note)
    except ShopError as e:
        raise HTTPException(409, str(e)) from e
    audit_human("human_rejected", approval_id=approval_id, decided_by=body.approved_by.strip(), note=body.note)
    BOARD.deliver(approval_id, ApprovalDecision(approved=False, decided_by=body.approved_by.strip(),
                                                note=body.note, applied=True))
    return {"approval": appr}


@app.get("/cash", summary="Current checking balance from cash_accounts")
async def get_cash():
    data = await shop("get_bills_and_cash")
    checking = next((a for a in data["cash_accounts"] if a["name"] == "checking"), None)
    if checking is None:
        raise HTTPException(404, "No checking account in cash_accounts")
    return {"account": "checking", "balance": checking["balance"], "as_of": checking["date"],
            "shop_date": data["shop_date"], "open_bills_total": data["bills_total"]}


# ---------------------------------------------------------------- routes: reset

@app.post("/reset", summary="Reset the database to the original values for a fresh run")
async def reset():
    with RUN.lock:
        if RUN.running:
            raise HTTPException(409, f"Run {RUN.run_id} is still running; reset after it finishes")
        digest = reset_database()
        RUN.clear()
    audit_human("database_reset", sha256=digest)
    return {"reset": True, "sha256": digest, **(await get_tickets()), "cash": await get_cash()}


@app.get("/", include_in_schema=False)
async def index():
    return {"name": "Campus Customs Board API", "docs": "/docs",
            "routes": ["GET /tickets", "POST /tickets/{ticket_id}/run", "GET /runs/current",
                       "GET /runs/{run_id}/summary", "GET /events",
                       "GET /approvals", "POST /approvals/{id}/approve", "POST /approvals/{id}/reject",
                       "GET /cash", "POST /reset"]}
