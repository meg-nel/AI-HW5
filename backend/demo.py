"""Demo mode: scripted stand-in agents so the board can be tried without calling gpt-6-luna.

Start the API with CAMPUS_CUSTOMS_DEMO=1 to use it. Everything else is real: the same five
PydanticAI agents, prompts, delegation tool, MCP server, database writes, human approval pauses,
audit trail, and routes. Only the model is replaced: each agent follows a short script for the
ticket and quotes the numbers it gets back from the MCP tools.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from backend.agents import CampusCustomsTeam

TICKET_ITEMS = {101: ("CC-TEE-WHITE", "S", 1), 103: ("CC-HOOD-NAVY", "M", 20)}


# ---------------------------------------------------------------- helpers

def _prompt(messages: list) -> str:
    for m in messages:
        if isinstance(m, ModelRequest):
            for p in m.parts:
                if isinstance(p, UserPromptPart):
                    return p.content if isinstance(p.content, str) else str(p.content)
    return ""


def _ticket(text: str) -> int:
    m = re.search(r"[Tt]icket (\d+)", text)
    return int(m.group(1)) if m else 101


def _turn(messages: list) -> int:
    return sum(1 for m in messages if isinstance(m, ModelResponse))


def _returns(messages: list) -> list[Any]:
    """Every tool result so far (newest last), decoded."""
    out = []
    for m in messages:
        if isinstance(m, ModelRequest):
            for p in m.parts:
                if isinstance(p, (ToolReturnPart, RetryPromptPart)):
                    c = p.content
                    if isinstance(c, str):
                        try:
                            c = json.loads(c)
                        except json.JSONDecodeError:
                            pass
                    out.append(c)
    return out


def _say(text: str, *calls: tuple[str, dict]) -> ModelResponse:
    return ModelResponse(parts=[TextPart(text), *[ToolCallPart(name, args) for name, args in calls]])


def _finish(info: AgentInfo, output: dict) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, output)])


def _report(agent: str, ticket: int, summary: str, facts: list[str], actions: list[str] | None = None,
            blocked: list[str] | None = None, recs: list[str] | None = None) -> dict:
    return {"agent": agent, "ticket_ids": [ticket], "summary": summary, "facts": facts,
            "actions_taken": actions or [], "blocked_by": blocked or [], "recommendations": recs or []}


# ---------------------------------------------------------------- the five scripts

def boss(messages: list, info: AgentInfo) -> ModelResponse:
    t, turn, r = _ticket(_prompt(messages)), _turn(messages), _returns(messages)
    first = {101: "inventory", 102: "facilities", 103: "accounting"}[t] if t in (101, 102, 103) else "inventory"
    if turn == 0:
        return _say(f"Reading ticket {t} and the cash position before I route anything.",
                    ("get_ticket", {"ticket_id": t}), ("get_bills_and_cash", {}))
    if turn == 1:
        briefs = {
            "inventory": f"Ticket {t}: check stock and restock facts only, no ordering.",
            "facilities": f"Ticket {t}: confirm lease 1 against the rent notice and whether rent is already paid. "
                          "Do not pay or contact the landlord.",
            "accounting": f"Ticket {t}: numbers only, no payments or orders. Quote margins for 20 CC-HOOD-NAVY "
                          "at 0%, 10% and 15% off.",
        }
        return _say(f"{first.title()} goes first on ticket {t}.", ("delegate_task", {"to_agent": first, "task": briefs[first]}))
    if turn == 2:
        plan = {101: "Money plan: pay invoice 501 ($840, overdue) so Bulldog Print Co ships the S tee.",
                102: "Money plan: pay rent on lease 1 ($2,400, due 2026-09-02).",
                103: "Inventory check for the plan: stock and restock facts for 20 CC-HOOD-NAVY size M."}[t]
        target = "inventory" if t == 103 else "accounting"
        return _say("Setting the money plan for this ticket." if t != 103 else "Checking stock before deciding the discount.",
                    ("delegate_task", {"to_agent": target, "task": f"Ticket {t}: {plan}"}))
    if turn == 3:
        msg = {101: "Draft a reply to Tauhid Zaman: the size S tee is being restocked, expected around 2026-09-05.",
               102: "Draft a short note to Elm City Properties: the shop has paid the $2,400 rent.",
               103: "Draft a reply to Yale AI Club: approved 10% off, $52.20 each, $1,044 for 20; 8 in stock now."}[t]
        return _say("Asking Customer Service to draft the reply.",
                    ("delegate_task", {"to_agent": "customer_service", "task": f"Ticket {t}: {msg}"}))
    if turn == 4:
        return _say("Recording the final call on the ticket.",
                    ("update_ticket", {"ticket_id": t, "status": "resolved", "updated_by": "boss",
                                       "note": "Demo run: decision made, approvals decided, reply drafted."}),
                    ("get_bills_and_cash", {}))
    start = next((x["cash_total"] for x in r if isinstance(x, dict) and "cash_total" in x), 0)
    end = [x["cash_total"] for x in r if isinstance(x, dict) and "cash_total" in x][-1]
    return _finish(info, {
        "shop_date": "2026-08-31", "cash_at_start": start, "cash_at_end": end,
        "payment_priority": f"Ticket {t}: cash ${start:,.2f} -> ${end:,.2f}.",
        "tickets": [{"ticket_id": t, "final_status": "resolved", "owner": "boss",
                     "decision": f"Ticket {t} handled; see the agents' reports.", "actions_taken": ["Updated ticket"]}],
    })


def inventory(messages: list, info: AgentInfo) -> ModelResponse:
    t, turn, r = _ticket(_prompt(messages)), _turn(messages), _returns(messages)
    sku, size, qty = TICKET_ITEMS.get(t, TICKET_ITEMS[101])
    if turn == 0:
        return _say(f"Checking {sku} size {size} on the shelf and who can restock it.",
                    ("check_stock", {"sku": sku, "size": size, "qty_needed": qty}), ("list_vendors", {}))
    stock = next(x for x in r if isinstance(x, dict) and "qty_on_hand" in x)
    v = next(x for x in r if isinstance(x, dict) and "vendors" in x)["vendors"][0]
    blocked = [] if v["will_ship"] else [f"{v['name']} won't ship: open invoice(s) "
                                        f"{', '.join(str(i['id']) for i in v['open_unpaid_invoices'])}"]
    return _finish(info, _report(
        "inventory", t, f"{stock['qty_on_hand']} on hand of {qty} needed (short {stock['shortfall']}). "
                        f"Restock from {v['name']}, {v['lead_days']}-day lead.",
        [f"{sku} {size}: {stock['qty_on_hand']} on hand, shortfall {stock['shortfall']}",
         f"Earliest arrival {v['earliest_arrival_if_ordered_today']}"], blocked=blocked))


def facilities(messages: list, info: AgentInfo) -> ModelResponse:
    t, turn, r = _ticket(_prompt(messages)), _turn(messages), _returns(messages)
    if turn == 0:
        return _say("Pulling lease 1 and any rent already paid.", ("get_lease", {"lease_id": 1}), ("list_payments", {}))
    lease = next(x for x in r if isinstance(x, dict) and "lease" in x)["lease"]
    return _finish(info, _report(
        "facilities", t, f"Notice matches lease 1: ${lease['monthly_rent']:,.0f} to {lease['landlord']}, due "
                         f"{lease['next_due']} ({lease['days_until_due']} days).",
        [f"Lease 1 {lease['space_name']}", f"Due {lease['next_due']}"], recs=["Pay rent before the due date."]))


def accounting(messages: list, info: AgentInfo) -> ModelResponse:
    prompt = _prompt(messages)
    t, turn, r = _ticket(prompt), _turn(messages), _returns(messages)
    if "margins" in prompt:
        if turn == 0:
            return _say("Quoting 20 hoodies at list, 10% and 15% off.",
                        *[("quote_price_margin", {"sku": "CC-HOOD-NAVY", "qty": 20, "discount_pct": d}) for d in (0, 10, 15)])
        q = [x for x in r if isinstance(x, dict) and "margin_pct" in x]
        return _finish(info, _report("accounting", t, "Margins quoted; 10% off keeps a 57.9% margin.",
                                     [f"{x['discount_pct']:.0f}% off: ${x['total_price']:,.2f}, margin {x['margin_pct']}%" for x in q]))
    kind, ref = ("invoice", 501) if "invoice 501" in prompt else ("rent", 1)
    if turn == 0:
        return _say(f"Preparing the {kind} payment for a human to approve.",
                    ("request_payment", {"kind": kind, "ref_id": ref, "requested_by": "accounting",
                                         "reason": f"Ticket {t}: Boss's money plan."}))
    gate = next(x for x in r if isinstance(x, dict) and "next_step" in x)
    return _finish(info, _report("accounting", t, gate["next_step"], [f"Approval #{gate['request']['id']}: "
                                                                       f"${gate['request']['amount']:,.2f}"],
                                 actions=[gate["next_step"]]))


def customer_service(messages: list, info: AgentInfo) -> ModelResponse:
    prompt = _prompt(messages)
    t, turn, r = _ticket(prompt), _turn(messages), _returns(messages)
    if turn == 0:
        body = prompt.split(":", 1)[-1].replace("Draft a reply to", "Hello").replace("Draft a short note to", "Hello")
        return _say("Writing the draft (it stays a draft; nothing is sent).",
                    ("draft_customer_message", {"ticket_id": t, "subject": f"Update on ticket {t}",
                                                "body": body.strip() + "\n\n- Campus Customs", "author": "customer_service"}))
    d = next(x for x in r if isinstance(x, dict) and "recipient" in x)
    return _finish(info, _report("customer_service", t, f"Saved draft {d['id']} to {d['recipient']} (not sent).",
                                 [d["subject"]], actions=[f"Draft {d['id']} saved"]))


SCRIPTS = {"boss": boss, "inventory": inventory, "accounting": accounting, "facilities": facilities,
           "customer_service": customer_service}


def demo_team() -> CampusCustomsTeam:
    team = CampusCustomsTeam()
    for name, fn in SCRIPTS.items():
        team.agents[name].model = FunctionModel(fn, model_name=f"demo-{name}")
    return team
