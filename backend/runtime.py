"""Agent runtime: a manual Claude tool-use loop per agent, with full-mesh delegation and
human-in-the-loop approvals. Every step is published to the event bus for the dashboard."""

import asyncio
import json
import os
import uuid
from collections import Counter

import anthropic

from backend.agents import AGENTS, AGENTS_BY_ID, AgentSpec, system_prompt
from backend.events import bus
from backend.mcp_bridge import bridge

MODEL = os.environ.get("CAMPUS_CUSTOMS_MODEL", "claude-opus-5-5")
MAX_DELEGATION_DEPTH = int(os.environ.get("CAMPUS_CUSTOMS_MAX_DEPTH", "3"))
MAX_TURNS = 25

client = anthropic.AsyncAnthropic()

# agent id -> number of runs currently in flight (an agent can work on several tasks at once)
active_runs: Counter = Counter()
# approval id -> future resolved by the dashboard
pending_approvals: dict[int, asyncio.Future] = {}
tasks: dict[str, dict] = {}


def delegate_tool_def(agent: AgentSpec) -> dict:
    others = [a.id for a in AGENTS if a.id != agent.id]
    return {
        "name": "delegate_task",
        "description": "Hand a self-contained task to a teammate and wait for their result. "
                       "The teammate cannot see your conversation, so include every detail they need.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "enum": others},
                "task": {"type": "string", "description": "Complete brief for the teammate."},
            },
            "required": ["agent_id", "task"],
            "additionalProperties": False,
        },
    }


def _set_status(agent_id: str, delta: int, task_id: str) -> None:
    active_runs[agent_id] += delta
    bus.publish("agent_status", agent=agent_id, task_id=task_id,
                status="working" if active_runs[agent_id] > 0 else "idle")


async def _await_approval(approval_id: int, agent_id: str, task_id: str, summary: str) -> dict:
    fut = asyncio.get_running_loop().create_future()
    pending_approvals[approval_id] = fut
    bus.publish("approval_requested", agent=agent_id, task_id=task_id, approval_id=approval_id, summary=summary)
    bus.publish("agent_status", agent=agent_id, task_id=task_id, status="waiting_approval")
    try:
        return await fut
    finally:
        pending_approvals.pop(approval_id, None)
        bus.publish("agent_status", agent=agent_id, task_id=task_id, status="working")


async def resolve_approval(approval_id: int, approved: bool, note: str) -> dict:
    record = await bridge.call("admin_decide_approval", {"approval_id": approval_id, "approved": approved, "note": note})
    bus.publish("approval_decided", approval_id=approval_id, approved=approved, note=note)
    fut = pending_approvals.get(approval_id)
    if fut and not fut.done():
        fut.set_result(record)
    return record


async def _run_tool(agent: AgentSpec, name: str, args: dict, task_id: str, chain: list[str]) -> str:
    if name == "delegate_task":
        target = args["agent_id"]
        if target not in AGENTS_BY_ID:
            raise RuntimeError(f"Unknown teammate {target}")
        if len(chain) >= MAX_DELEGATION_DEPTH:
            raise RuntimeError(f"Delegation depth limit ({MAX_DELEGATION_DEPTH}) reached; finish this yourself.")
        bus.publish("delegation", task_id=task_id, from_agent=agent.id, to_agent=target, brief=args["task"])
        result = await run_agent(target, args["task"], task_id, chain + [agent.id])
        bus.publish("delegation_result", task_id=task_id, from_agent=target, to_agent=agent.id, result=result)
        return result

    result = await bridge.call(name, args)
    if name in ("draft_customer_email", "draft_vendor_request"):
        bus.publish("draft_created", task_id=task_id, agent=agent.id, draft_id=result["draft_id"])
    if name == "request_approval":
        decision = await _await_approval(result["approval_id"], agent.id, task_id, args.get("summary", ""))
        return json.dumps({"approval_id": decision["id"], "status": decision["status"], "note": decision["decision_note"]})
    return result if isinstance(result, str) else json.dumps(result, default=str)


async def run_agent(agent_id: str, prompt: str, task_id: str, chain: list[str] | None = None) -> str:
    """Run one agent to completion on `prompt`. Returns its final text."""
    chain = chain or []
    agent = AGENTS_BY_ID[agent_id]
    tools = bridge.agent_tool_defs(agent.tools) + [delegate_tool_def(agent)]
    messages: list = [{"role": "user", "content": prompt}]
    _set_status(agent.id, +1, task_id)
    bus.publish("agent_started", task_id=task_id, agent=agent.id, prompt=prompt, delegated_by=chain[-1] if chain else None)
    try:
        for _ in range(MAX_TURNS):
            response = await client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                system=system_prompt(agent),
                tools=tools,
                messages=messages,
                thinking={"type": "adaptive", "display": "summarized"},
                output_config={"effort": agent.effort},
                betas=["server-side-fallback-2026-07-01"],
                extra_body={"fallbacks": "default"},
            )
            if response.stop_reason == "refusal":
                raise RuntimeError("Model declined this request.")

            for block in response.content:
                if block.type == "thinking" and block.thinking:
                    bus.publish("thinking", task_id=task_id, agent=agent.id, text=block.thinking)
                elif block.type == "text" and block.text.strip():
                    bus.publish("message", task_id=task_id, agent=agent.id, text=block.text)

            messages.append({"role": "assistant", "content": response.content})
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_uses:
                final = "\n".join(b.text for b in response.content if b.type == "text").strip()
                bus.publish("agent_finished", task_id=task_id, agent=agent.id, result=final)
                return final

            async def one(block):
                bus.publish("tool_call", task_id=task_id, agent=agent.id, tool=block.name, input=block.input)
                try:
                    out = await _run_tool(agent, block.name, block.input, task_id, chain)
                    bus.publish("tool_result", task_id=task_id, agent=agent.id, tool=block.name, output=out[:2000])
                    return {"type": "tool_result", "tool_use_id": block.id, "content": out}
                except Exception as e:  # report tool failures back to the model
                    bus.publish("tool_result", task_id=task_id, agent=agent.id, tool=block.name, output=str(e), error=True)
                    return {"type": "tool_result", "tool_use_id": block.id, "content": f"Error: {e}", "is_error": True}

            # Parallel tool calls run concurrently; all results go back in one user message.
            messages.append({"role": "user", "content": list(await asyncio.gather(*(one(b) for b in tool_uses)))})

        raise RuntimeError(f"Stopped after {MAX_TURNS} turns without finishing.")
    except Exception as e:
        bus.publish("agent_error", task_id=task_id, agent=agent.id, error=str(e))
        if chain:  # a delegated run's failure becomes the delegator's tool error
            raise
        return f"Error: {e}"
    finally:
        _set_status(agent.id, -1, task_id)


def start_task(agent_id: str, prompt: str) -> dict:
    task_id = uuid.uuid4().hex[:8]
    task = {"id": task_id, "agent": agent_id, "prompt": prompt, "status": "running", "result": None}
    tasks[task_id] = task
    bus.publish("task_started", task_id=task_id, agent=agent_id, prompt=prompt)

    async def runner():
        task["result"] = await run_agent(agent_id, prompt, task_id)
        task["status"] = "error" if task["result"].startswith("Error:") else "done"
        bus.publish("task_finished", task_id=task_id, status=task["status"], result=task["result"])

    t = asyncio.create_task(runner())
    _background.add(t)
    t.add_done_callback(_background.discard)
    return task


_background: set[asyncio.Task] = set()
