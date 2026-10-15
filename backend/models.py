"""Data types shared by the Campus Customs agent team."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import UsageLimits

from backend.audit import AuditTrail

AgentName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]
AGENT_NAMES: tuple[AgentName, ...] = ("boss", "inventory", "accounting", "facilities", "customer_service")

TicketStatus = Literal["open", "in_progress", "waiting_on_human", "waiting_on_vendor", "resolved"]


# ---------- human approval ----------

class ApprovalRequest(BaseModel):
    """A pending payment or purchase order, as recorded by the MCP server's approvals table."""
    approval_id: int
    kind: Literal["invoice_payment", "rent_payment", "purchase_order"]
    amount: float
    requested_by: str
    reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecision(BaseModel):
    """What the human decided. decided_by is the person's name and goes into payments.approved_by."""
    approved: bool
    decided_by: str
    note: str = ""


Approver = Callable[[ApprovalRequest], Awaitable[ApprovalDecision]]
EventSink = Callable[[dict[str, Any]], None]


# ---------- run-time context passed to every agent ----------

@dataclass
class TeamDeps:
    """Passed to every agent run. `agent` is who is running; `chain` is who delegated to them.

    Every event goes to the audit trail (if set) and to on_event (e.g. the terminal printer).
    usage_limits is shared by the whole run, including delegated agents.
    """
    agent: AgentName
    approver: Approver
    usage_limits: UsageLimits
    run_id: str = ""
    chain: list[AgentName] = field(default_factory=list)
    max_delegation_depth: int = 3
    on_event: EventSink | None = None
    audit: AuditTrail | None = None

    def for_delegate(self, to_agent: AgentName) -> TeamDeps:
        return replace(self, agent=to_agent, chain=[*self.chain, self.agent])

    def emit(self, type_: str, **data: Any) -> None:
        event = {"type": type_, "agent": self.agent, "chain": list(self.chain), **data}
        if self.audit:
            self.audit.append({"run_id": self.run_id, **event})
        if self.on_event:
            self.on_event(event)


# ---------- agent outputs ----------

class SpecialistReport(BaseModel):
    """What a specialist (Inventory, Accounting, Facilities, Customer Service) hands back."""
    agent: AgentName
    ticket_ids: list[int] = Field(description="Tickets this work was for")
    summary: str = Field(description="Two or three sentences on what you found and did")
    facts: list[str] = Field(description="Facts from tool results, with the exact numbers, dates, and IDs")
    actions_taken: list[str] = Field(description="Changes actually made (approval requested, bill paid, "
                                                 "draft saved, ticket updated). Empty if none.")
    blocked_by: list[str] = Field(default_factory=list,
                                  description="What is stopping progress (e.g. vendor won't ship, "
                                              "not enough cash, human rejected)")
    recommendations: list[str] = Field(default_factory=list, description="What you suggest the Boss decide")


class TicketResolution(BaseModel):
    ticket_id: int
    final_status: TicketStatus
    owner: AgentName = Field(description="Agent responsible for the remaining work")
    decision: str = Field(description="The Boss's final call, in one or two sentences")
    actions_taken: list[str]
    next_steps: list[str] = Field(default_factory=list)


class BossReport(BaseModel):
    """The Boss's end-of-run report for the whole shop."""
    shop_date: str
    cash_at_start: float
    cash_at_end: float
    payment_priority: str = Field(description="Which bills were paid or held, in what order, and why")
    tickets: list[TicketResolution]
    needs_human: list[str] = Field(default_factory=list,
                                   description="Decisions or reviews still waiting on a person")
