"""The Campus Customs agent team, built with PydanticAI.

Five agents (Boss, Inventory, Accounting, Facilities, Customer Service). They all:
- run on gpt-6-luna (OpenAI Responses API; key read from OPENAI_API_KEY in .env),
- load their instructions from backend/prompts/<agent>.md,
- share one connection to the campus-customs MCP server, each seeing only the tools its
  role needs (admin_* tools are never visible to any agent),
- can delegate to any other agent with `delegate_task` (full mesh, depth-limited).

Human approval: whenever an agent calls request_payment or request_purchase_order, the MCP
toolset's process_tool_call hook stops and asks the human (TeamDeps.approver). The human's
decision is recorded in the database through admin_decide_approval, and the agent gets the
decision back in the same tool result. pay_bill only works on human-approved requests; that
check lives in the MCP server, so it holds even if a prompt is ignored.

Every shop fact comes from the MCP server; the backend has no tools of its own that read or
write the database. The only non-MCP tool is delegate_task.

Audit: every agent-loop step (prompt, model request, model response with tool calls and token
usage, end) plus every tool call/result, delegation, and approval is appended to
output/audit_trail.json as it happens (backend/audit.py).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, ModelRetry, ModelSettings, RunContext, UsageLimits
from pydantic_ai.mcp import MCPToolset, StdioTransport

from backend.audit import AuditTrail, describe_node
from backend.models import (
    AGENT_NAMES,
    AgentName,
    ApprovalRequest,
    Approver,
    BossReport,
    EventSink,
    SpecialistReport,
    TeamDeps,
)

# The only model the team uses.
MODEL = "openai-responses:gpt-6-luna"

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
MCP_SERVER = ROOT / "mcp_server" / "server.py"

# Limits that keep token use in check. One budget covers the whole run, delegated agents included.
# Run #2 (all three tickets) used 31 requests, 51 tool calls, ~146k tokens.
REQUEST_LIMIT = 60
TOOL_CALLS_LIMIT = 120
TOTAL_TOKENS_LIMIT = 400_000
MAX_OUTPUT_TOKENS_PER_RESPONSE = 8_000
MAX_DELEGATION_DEPTH = 3


def default_usage_limits() -> UsageLimits:
    return UsageLimits(request_limit=REQUEST_LIMIT, tool_calls_limit=TOOL_CALLS_LIMIT,
                       total_tokens_limit=TOTAL_TOKENS_LIMIT)

# Which MCP tools each agent can see. admin_* tools are deliberately absent from every list.
AGENT_TOOLS: dict[AgentName, frozenset[str]] = {
    "boss": frozenset({
        "get_shop_date", "list_open_tickets", "get_ticket", "update_ticket", "get_bills_and_cash",
        "check_stock", "list_inventory", "quote_price_margin", "list_vendors", "get_lease", "list_payments",
        "get_approval", "list_approvals", "list_drafts",
    }),
    "inventory": frozenset({"get_shop_date", "get_ticket", "check_stock", "list_inventory", "list_vendors"}),
    "accounting": frozenset({
        "get_shop_date", "get_ticket", "get_bills_and_cash", "quote_price_margin", "list_vendors", "get_lease",
        "list_payments", "request_payment", "get_approval", "list_approvals", "pay_bill", "request_purchase_order",
    }),
    "facilities": frozenset({"get_shop_date", "get_ticket", "get_lease", "get_bills_and_cash", "list_payments"}),
    "customer_service": frozenset({
        "get_shop_date", "get_ticket", "check_stock", "list_inventory", "list_vendors", "list_drafts",
        "draft_customer_message", "discard_draft",
    }),
}

APPROVAL_TOOLS = frozenset({"request_payment", "request_purchase_order"})


def _as_dict(result: Any) -> Any:
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return result
    return result


async def _mcp_call_hook(ctx: RunContext[TeamDeps], call_tool, name: str, args: dict[str, Any]):
    """Runs around every MCP tool call: logs it, and for approval requests asks the human."""
    ctx.deps.emit("tool_call", tool=name, args=args)
    try:
        result = _as_dict(await call_tool(name, args))
    except Exception as e:
        ctx.deps.emit("tool_result", tool=name, error=str(e))
        raise
    ctx.deps.emit("tool_result", tool=name, result=result)
    if name not in APPROVAL_TOOLS or not isinstance(result, dict) or "id" not in result:
        return result

    request = ApprovalRequest(
        approval_id=result["id"], kind=result["kind"], amount=result["amount"],
        requested_by=result["requested_by"], reason=result.get("reason"), details=result.get("details") or {},
    )
    ctx.deps.emit("approval_requested", request=request.model_dump())
    decision = await ctx.deps.approver(request)
    if not decision.decided_by.strip():
        raise RuntimeError("Approver returned a decision without a human name")
    record = _as_dict(await call_tool("admin_decide_approval", {
        "approval_id": request.approval_id, "approved": decision.approved,
        "decided_by": decision.decided_by, "note": decision.note,
    }))
    ctx.deps.emit("approval_decided", approval_id=request.approval_id, approved=decision.approved,
                  decided_by=decision.decided_by, note=decision.note)

    if not decision.approved:
        next_step = "REJECTED by the human. Do not pay or place this order, and do not re-request it this run."
    elif request.kind == "purchase_order":
        next_step = "APPROVED. The purchase order is recorded; no cash moves until the vendor invoices."
    else:
        next_step = f"APPROVED. Call pay_bill(approval_id={request.approval_id}) to make the payment."
    return {"request": result, "human_decision": record, "next_step": next_step}


def build_mcp_toolset() -> MCPToolset:
    """One stdio connection to the campus-customs MCP server, shared by every agent."""
    transport = StdioTransport(command=sys.executable, args=[str(MCP_SERVER)], env=dict(os.environ), cwd=str(ROOT))
    return MCPToolset(transport, id="campus-customs", process_tool_call=_mcp_call_hook)


async def run_agent_step_by_step(agent: Agent[TeamDeps, Any], prompt: str, deps: TeamDeps, usage=None):
    """Run one agent through its loop, auditing every step. Used for top-level and delegated runs."""
    async with agent.iter(prompt, deps=deps, usage=usage, usage_limits=deps.usage_limits) as agent_run:
        step = 0
        async for node in agent_run:
            step += 1
            deps.emit("loop_step", step=step, **describe_node(node))
        return agent_run.result


class CampusCustomsTeam:
    """The five agents, wired so any of them can delegate to any other."""

    def __init__(self, mcp_toolset: MCPToolset | None = None, audit_path: Path | str | None = None):
        self.mcp = mcp_toolset or build_mcp_toolset()
        self.audit_path = audit_path
        self.agents: dict[AgentName, Agent[TeamDeps, Any]] = {name: self._build_agent(name) for name in AGENT_NAMES}

    def _build_agent(self, name: AgentName) -> Agent[TeamDeps, Any]:
        allowed = AGENT_TOOLS[name]
        return Agent(
            MODEL,
            name=name,
            deps_type=TeamDeps,
            output_type=BossReport if name == "boss" else SpecialistReport,
            instructions=(PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8"),
            toolsets=[self.mcp.filtered(lambda ctx, tool, allowed=allowed: tool.name in allowed)],
            tools=[self._make_delegate_tool()],
            model_settings=ModelSettings(max_tokens=MAX_OUTPUT_TOKENS_PER_RESPONSE),
            retries=2,
            defer_model_check=True,  # the API key is only needed when a run starts
        )

    def _make_delegate_tool(self):
        team = self

        async def delegate_task(ctx: RunContext[TeamDeps], to_agent: AgentName, task: str) -> str:
            """Hand a self-contained task to a teammate and wait for their report.

            Args:
                to_agent: The teammate: boss, inventory, accounting, facilities, or customer_service.
                task: A complete brief. The teammate cannot see your conversation, so include ticket IDs,
                    SKUs, sizes, quantities, invoice/lease IDs, decisions already made, and what you need back.
            """
            if to_agent == ctx.deps.agent:
                ctx.deps.emit("delegation_refused", to_agent=to_agent, reason="self")
                raise ModelRetry("You can't delegate to yourself; do the work or pick another teammate.")
            if len(ctx.deps.chain) >= ctx.deps.max_delegation_depth:
                ctx.deps.emit("delegation_refused", to_agent=to_agent, reason="depth")
                return (f"Refused: delegation depth limit ({ctx.deps.max_delegation_depth}) reached "
                        f"(chain: {' -> '.join([*ctx.deps.chain, ctx.deps.agent])}). Finish this yourself.")
            child = ctx.deps.for_delegate(to_agent)
            ctx.deps.emit("delegation", to_agent=to_agent, task=task)
            # usage=ctx.usage: the delegate spends from the same run-wide budget.
            result = await run_agent_step_by_step(team.agents[to_agent], task, child, usage=ctx.usage)
            child.emit("delegation_result", to_agent=ctx.deps.agent, report=result.output.model_dump())
            return result.output.model_dump_json()

        return delegate_task

    async def run(self, prompt: str, approver: Approver, *, agent: AgentName = "boss",
                  on_event: EventSink | None = None, usage_limits: UsageLimits | None = None,
                  run_id: str | None = None):
        """Run one agent (the Boss by default) to completion. Returns the PydanticAI run result.
        Appends run_start, every loop step and event, and run_end to the audit trail."""
        limits = usage_limits or default_usage_limits()
        deps = TeamDeps(
            agent=agent, approver=approver, usage_limits=limits, on_event=on_event,
            run_id=run_id or f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}",
            max_delegation_depth=MAX_DELEGATION_DEPTH, audit=AuditTrail(self.audit_path),
        )
        deps.emit(
            "run_start", prompt=prompt, model=MODEL,
            limits={"request_limit": limits.request_limit, "tool_calls_limit": limits.tool_calls_limit,
                    "total_tokens_limit": limits.total_tokens_limit,
                    "max_output_tokens_per_response": MAX_OUTPUT_TOKENS_PER_RESPONSE,
                    "max_delegation_depth": MAX_DELEGATION_DEPTH},
            database=os.environ.get("CAMPUS_CUSTOMS_DB", str(ROOT / "data" / "campus_customs_new.db")),
            prompt_files={n: hashlib.sha256((PROMPTS_DIR / f"{n}.md").read_bytes()).hexdigest()[:12]
                          for n in AGENT_NAMES},
            tools_by_agent={n: sorted(t) for n, t in AGENT_TOOLS.items()},
        )
        result = None
        try:
            async with self.mcp:
                result = await run_agent_step_by_step(self.agents[agent], prompt, deps)
            return result
        except BaseException as e:
            deps.emit("run_end", status="error", error=f"{type(e).__name__}: {e}")
            raise
        finally:
            if result is not None:
                u = result.usage() if callable(result.usage) else result.usage
                deps.emit("run_end", status="completed", output=result.output.model_dump(),
                          usage={"requests": u.requests, "tool_calls": u.tool_calls,
                                 "input_tokens": u.input_tokens, "output_tokens": u.output_tokens})
