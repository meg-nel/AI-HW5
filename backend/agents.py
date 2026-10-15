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
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, ModelRetry, RunContext, UsageLimits
from pydantic_ai.mcp import MCPToolset, StdioTransport

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

# Which MCP tools each agent can see. admin_* tools are deliberately absent from every list.
AGENT_TOOLS: dict[AgentName, frozenset[str]] = {
    "boss": frozenset({
        "get_shop_date", "list_open_tickets", "get_ticket", "update_ticket", "get_bills_and_cash",
        "check_stock", "quote_price_margin", "list_vendors", "get_approval", "list_drafts",
    }),
    "inventory": frozenset({"get_shop_date", "get_ticket", "check_stock", "list_vendors"}),
    "accounting": frozenset({
        "get_shop_date", "get_ticket", "get_bills_and_cash", "quote_price_margin", "list_vendors",
        "request_payment", "get_approval", "pay_bill", "request_purchase_order",
    }),
    "facilities": frozenset({"get_shop_date", "get_ticket", "get_bills_and_cash"}),
    "customer_service": frozenset({
        "get_shop_date", "get_ticket", "check_stock", "list_vendors", "list_drafts", "draft_customer_message",
        "discard_draft",
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


class CampusCustomsTeam:
    """The five agents, wired so any of them can delegate to any other."""

    def __init__(self, mcp_toolset: MCPToolset | None = None):
        self.mcp = mcp_toolset or build_mcp_toolset()
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
            result = await team.agents[to_agent].run(
                task, deps=child, usage=ctx.usage,
                usage_limits=UsageLimits(request_limit=ctx.deps.request_limit),
            )
            child.emit("delegation_result", to_agent=ctx.deps.agent, report=result.output.model_dump())
            return result.output.model_dump_json()

        return delegate_task

    async def run(self, prompt: str, approver: Approver, *, agent: AgentName = "boss",
                  on_event: EventSink | None = None, request_limit: int = 150):
        """Run one agent (the Boss by default) to completion. Returns the PydanticAI run result."""
        deps = TeamDeps(agent=agent, approver=approver, on_event=on_event, request_limit=request_limit)
        async with self.mcp:
            return await self.agents[agent].run(
                prompt, deps=deps, usage_limits=UsageLimits(request_limit=request_limit),
            )
