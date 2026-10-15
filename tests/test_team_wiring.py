"""Team wiring test: delegation, per-agent tool access, and the human approval gate.

Uses scripted PydanticAI FunctionModels instead of gpt-6-luna, so it needs no API key and
costs nothing. The real MCP server runs over stdio against a temporary database copy.

Run from the project root:  .venv\\Scripts\\python tests\\test_team_wiring.py
"""

import asyncio
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP_DB = Path(tempfile.mkdtemp()) / "campus_customs_team_test.db"
os.environ["CAMPUS_CUSTOMS_DB"] = str(TMP_DB)  # passed through to the MCP server process
sys.path.insert(0, str(ROOT))

from pydantic_ai.messages import ModelResponse, RetryPromptPart, ToolCallPart, ToolReturnPart  # noqa: E402
from pydantic_ai.models.function import AgentInfo, FunctionModel  # noqa: E402

from backend.agents import AGENT_TOOLS, CampusCustomsTeam  # noqa: E402
from backend.models import ApprovalDecision  # noqa: E402

passed = 0
seen_tools: dict[str, set[str]] = {}


def ok(cond: bool, label: str) -> None:
    global passed
    if not cond:
        raise AssertionError(label)
    passed += 1
    print(f"  PASS  {label}")


def fresh_db() -> None:
    shutil.copyfile(ROOT / "data" / "campus_customs_original.db", TMP_DB)
    os.chmod(TMP_DB, 0o666)


def sql(q: str) -> list[tuple]:
    conn = sqlite3.connect(TMP_DB)
    try:
        return conn.execute(q).fetchall()
    finally:
        conn.close()


def last_results(messages) -> list:
    """Tool returns / retry prompts from the most recent request."""
    parts = messages[-1].parts
    return [p for p in parts if isinstance(p, (ToolReturnPart, RetryPromptPart))]


def content_of(part) -> dict | str:
    c = part.content
    if isinstance(c, str):
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            return c
    return c


def finish(info: AgentInfo, output: dict) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, output)])


def specialist_output(agent: str, summary: str, actions: list[str]) -> dict:
    return {"agent": agent, "ticket_ids": [101], "summary": summary, "facts": [], "actions_taken": actions}


def boss_model(steps: int = 0):
    def fn(messages, info: AgentInfo) -> ModelResponse:
        seen_tools["boss"] = {t.name for t in info.function_tools}
        turn = sum(1 for m in messages if isinstance(m, ModelResponse))
        if turn == 0:  # try delegating to itself first: must be bounced
            return ModelResponse(parts=[ToolCallPart("delegate_task", {"to_agent": "boss", "task": "x"})])
        if turn == 1:
            return ModelResponse(parts=[ToolCallPart("delegate_task", {
                "to_agent": "accounting",
                "task": "Ticket 101: invoice 501 to Bulldog Print Co is overdue. Request payment, pay if approved."})])
        return finish(info, {"shop_date": "2026-08-31", "cash_at_start": 3400, "cash_at_end": 0,
                             "payment_priority": "test", "tickets": []})
    return FunctionModel(fn)


def accounting_model(pay_even_if_rejected: bool):
    def fn(messages, info: AgentInfo) -> ModelResponse:
        seen_tools["accounting"] = {t.name for t in info.function_tools}
        turn = sum(1 for m in messages if isinstance(m, ModelResponse))
        if turn == 0:
            return ModelResponse(parts=[ToolCallPart("request_payment", {
                "kind": "invoice", "ref_id": 501, "requested_by": "accounting", "reason": "overdue 3 days"})])
        if turn == 1:
            gate = content_of(last_results(messages)[0])
            approval_id = gate["request"]["id"]
            if gate["human_decision"]["status"] == "approved" or pay_even_if_rejected:
                return ModelResponse(parts=[ToolCallPart("pay_bill", {"approval_id": approval_id})])
        result = last_results(messages)[0]
        return finish(info, specialist_output("accounting", f"pay_bill result: {type(result).__name__}",
                                              [str(content_of(result))[:200]]))
    return FunctionModel(fn)


async def run_scenario(approve: bool, pay_even_if_rejected: bool = False) -> list[dict]:
    fresh_db()
    team = CampusCustomsTeam()
    events: list[dict] = []
    asked: list = []

    async def approver(request):
        asked.append(request)
        return ApprovalDecision(approved=approve, decided_by="Test Human", note="ok" if approve else "not now")

    with team.agents["boss"].override(model=boss_model()), \
         team.agents["accounting"].override(model=accounting_model(pay_even_if_rejected)):
        await team.run("Work ticket 101.", approver, on_event=events.append)
    ok(len(asked) == 1 and asked[0].amount == 840.0 and asked[0].kind == "invoice_payment",
       "the human was asked once, for $840 on invoice 501")
    return events


async def main() -> None:
    print("Scenario 1: human approves")
    events = await run_scenario(approve=True)
    types = [e["type"] for e in events]
    ok(any(e["type"] == "delegation_refused" and e["reason"] == "self" for e in events),
       "an agent delegating to itself is bounced")
    ok(any(e["type"] == "delegation" and e["agent"] == "boss" and e["to_agent"] == "accounting" for e in events),
       "boss delegated to accounting")
    ok(any(e["type"] == "tool_call" and e["agent"] == "accounting" and e["chain"] == ["boss"] for e in events),
       "accounting's tool calls are tagged with the delegation chain boss -> accounting")
    ok(types.index("approval_requested") < types.index("approval_decided"), "approval requested, then decided")
    ok(sql("SELECT kind, ref_id, amount, approved_by FROM payments") == [("invoice", 501, 840.0, "Test Human")],
       "payment recorded with the human's name")
    ok(sql("SELECT balance FROM cash_accounts")[0][0] == 2560.0 and
       sql("SELECT status FROM invoices WHERE id = 501")[0][0] == "paid", "cash and invoice updated")

    print("Tool access per agent")
    for agent, tools in seen_tools.items():
        ok(not any(t.startswith("admin_") for t in tools), f"{agent} can't see admin_* tools")
        ok(tools - {"delegate_task"} == set(AGENT_TOOLS[agent]), f"{agent} sees exactly its allowed tools")
    ok("pay_bill" not in seen_tools["boss"], "boss has no pay_bill tool")

    print("Scenario 2: human rejects, agent tries to pay anyway")
    await run_scenario(approve=False, pay_even_if_rejected=True)
    ok(sql("SELECT COUNT(*) FROM payments")[0][0] == 0, "no payment row after a rejection")
    ok(sql("SELECT balance FROM cash_accounts")[0][0] == 3400.0 and
       sql("SELECT status FROM invoices WHERE id = 501")[0][0] == "open", "cash and invoice unchanged")
    ok(sql("SELECT status, decided_by FROM approvals") == [("rejected", "Test Human")], "rejection recorded")

    print(f"\nAll {passed} team wiring checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
