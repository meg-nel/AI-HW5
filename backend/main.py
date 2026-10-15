"""Campus Customs operations API.

Run:  uvicorn backend.main:app --reload --port 8000   (from the project root)
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend import runtime
from backend.agents import AGENTS, AGENTS_BY_ID
from backend.events import bus
from backend.mcp_bridge import bridge


@asynccontextmanager
async def lifespan(app: FastAPI):
    await bridge.start()
    yield
    await bridge.stop()


app = FastAPI(title="Campus Customs Ops", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


class TaskIn(BaseModel):
    agent_id: str = "ops_lead"
    prompt: str


class DecisionIn(BaseModel):
    approved: bool
    note: str = ""


class DraftStatusIn(BaseModel):
    status: str


@app.get("/api/agents")
def list_agents():
    return [
        {"id": a.id, "name": a.name, "role": a.role, "color": a.color,
         "status": "working" if runtime.active_runs[a.id] > 0 else "idle",
         "can_delegate_to": [b.id for b in AGENTS if b.id != a.id]}
        for a in AGENTS
    ]


@app.get("/api/tools")
def list_tools():
    return [{"name": t.name, "description": t.description} for t in bridge.tools]


@app.post("/api/tasks")
def create_task(body: TaskIn):
    if body.agent_id not in AGENTS_BY_ID:
        raise HTTPException(404, f"Unknown agent {body.agent_id}")
    return runtime.start_task(body.agent_id, body.prompt)


@app.get("/api/tasks")
def list_tasks():
    return list(reversed(runtime.tasks.values()))


@app.get("/api/events")
def list_events(since: int = 0):
    return [e for e in bus.history if e["id"] > since]


@app.get("/api/approvals")
async def list_approvals(status: str | None = None):
    rows = await bridge.call("admin_list_approvals", {"status": status} if status else {})
    for r in rows:  # an approval nobody is waiting on (e.g. after a restart) can still be decided
        r["agent_waiting"] = r["id"] in runtime.pending_approvals
    return rows


@app.post("/api/approvals/{approval_id}")
async def decide_approval(approval_id: int, body: DecisionIn):
    return await runtime.resolve_approval(approval_id, body.approved, body.note)


@app.get("/api/drafts")
async def list_drafts():
    return await bridge.call("list_drafts", {})


@app.post("/api/drafts/{draft_id}")
async def set_draft_status(draft_id: int, body: DraftStatusIn):
    if body.status not in ("draft", "reviewed", "discarded"):
        raise HTTPException(400, "Drafts are never sent; status must be draft, reviewed, or discarded.")
    return await bridge.call("admin_set_draft_status", {"draft_id": draft_id, "status": body.status})


@app.get("/api/orders")
async def list_orders():
    return await bridge.call("list_orders", {})


@app.get("/api/inventory")
async def list_inventory():
    return await bridge.call("list_inventory", {})


@app.websocket("/ws")
async def events_ws(ws: WebSocket):
    await ws.accept()
    q = bus.subscribe()
    try:
        for e in bus.history[-300:]:
            await ws.send_json(e)
        while True:
            await ws.send_json(await q.get())
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(q)
