"""Append-only audit trail for agent runs: output/audit_trail.json.

The file is one JSON array. Every entry is added as soon as it happens (so a crash or Ctrl-C
keeps everything up to that point), earlier runs are never removed, and the file is rewritten
atomically so a half-written file can't replace a good one.

Each entry has:
  run_id     - one id per full run (all delegated agents share it)
  seq        - order within the run
  ts         - wall-clock time (UTC) the entry was written
  type       - run_start | loop_step | tool_call | tool_result | delegation | delegation_result |
               delegation_refused | approval_requested | approval_decided | run_end
  agent      - which agent was running
  chain      - who delegated to that agent (e.g. ["boss"] for boss -> accounting)
  ...        - type-specific fields (see describe_node and TeamDeps.emit callers)
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic_ai import CallToolsNode, ModelRequestNode, UserPromptNode
from pydantic_graph import End

DEFAULT_AUDIT_PATH = Path(__file__).resolve().parent.parent / "output" / "audit_trail.json"
MAX_TEXT = 20_000  # long tool results / messages are clipped in the audit, with the original length noted


def clip(value: Any) -> Any:
    """Keep audit entries a reasonable size without dropping structure."""
    if isinstance(value, str) and len(value) > MAX_TEXT:
        return value[:MAX_TEXT] + f"... [clipped, {len(value)} chars total]"
    if isinstance(value, dict):
        return {k: clip(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clip(v) for v in value]
    return value


class AuditTrail:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or os.environ.get("CAMPUS_CUSTOMS_AUDIT") or DEFAULT_AUDIT_PATH)
        self._lock = threading.Lock()
        self._entries = self._load()
        self._seq: dict[str, int] = {}

    def _load(self) -> list[dict]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
        # Never silently overwrite an unreadable audit file: keep it beside the new one.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.path.replace(self.path.with_name(f"{self.path.stem}.unreadable-{stamp}{self.path.suffix}"))
        return []

    def append(self, entry: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            run_id = entry.get("run_id", "")
            self._seq[run_id] = self._seq.get(run_id, 0) + 1
            record = {"run_id": run_id, "seq": self._seq[run_id],
                      "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                      **clip({k: v for k, v in entry.items() if k != "run_id"})}
            self._entries.append(record)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._entries, indent=1, default=str) + "\n", encoding="utf-8")
            os.replace(tmp, self.path)
            return record


def _part(part: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"kind": getattr(part, "part_kind", type(part).__name__)}
    if getattr(part, "tool_name", None):
        out["tool"] = part.tool_name
    if getattr(part, "tool_call_id", None):
        out["tool_call_id"] = part.tool_call_id
    if out["kind"] == "tool-call":
        try:
            out["args"] = part.args_as_dict()
        except Exception:
            out["args"] = str(part.args)
    elif hasattr(part, "content"):
        content = part.content
        out["content"] = content if isinstance(content, (str, int, float, bool, dict, list, type(None))) else str(content)
    return out


def describe_node(node: Any) -> dict[str, Any]:
    """Summarise one PydanticAI agent-loop node for the audit trail."""
    if isinstance(node, UserPromptNode):
        prompt = node.user_prompt
        return {"node": "user_prompt", "prompt": prompt if isinstance(prompt, str) else str(prompt)}
    if isinstance(node, ModelRequestNode):
        return {"node": "model_request", "parts": [_part(p) for p in node.request.parts]}
    if isinstance(node, CallToolsNode):
        r = node.model_response
        u = r.usage
        return {
            "node": "model_response",
            "model": r.model_name,
            "finish_reason": getattr(r, "finish_reason", None),
            "usage": {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens},
            "parts": [_part(p) for p in r.parts],
        }
    if isinstance(node, End):
        data = node.data
        output = getattr(data, "output", data)
        return {"node": "end", "output": output.model_dump() if hasattr(output, "model_dump") else str(output)}
    return {"node": type(node).__name__}
