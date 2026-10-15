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
import time
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


# One lock per audit file for the whole process, shared by every AuditTrail object and reader,
# so a run's writer, the board's human-action writer, and GET /events never step on each other.
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve()).lower()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _retry(action, attempts: int = 40, delay: float = 0.05):
    """Windows briefly refuses to replace or read a file someone else has open (another reader,
    OneDrive, antivirus). Retry for up to ~2 seconds before giving up."""
    for i in range(attempts):
        try:
            return action()
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)


def default_audit_path() -> Path:
    return Path(os.environ.get("CAMPUS_CUSTOMS_AUDIT") or DEFAULT_AUDIT_PATH)


def read_entries(path: Path | str | None = None) -> list[dict]:
    """Read the audit file safely (same lock as the writers)."""
    p = Path(path) if path else default_audit_path()
    with _lock_for(p):
        if not p.exists() or p.stat().st_size == 0:
            return []
        data = json.loads(_retry(lambda: p.read_text(encoding="utf-8")))
        return data if isinstance(data, list) else []


class AuditTrail:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_audit_path()
        self._lock = _lock_for(self.path)

    def _load(self) -> list[dict]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return []
        try:
            data = json.loads(_retry(lambda: self.path.read_text(encoding="utf-8")))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
        # Never silently overwrite an unreadable audit file: keep it beside the new one.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.path.replace(self.path.with_name(f"{self.path.stem}.unreadable-{stamp}{self.path.suffix}"))
        return []

    def append(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Read the current file, add one entry, write it back atomically. Never drops earlier entries."""
        with self._lock:
            entries = self._load()
            run_id = entry.get("run_id", "")
            seq = 1 + max((e.get("seq", 0) for e in entries if e.get("run_id") == run_id), default=0)
            record = {"run_id": run_id, "seq": seq,
                      "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                      **clip({k: v for k, v in entry.items() if k != "run_id"})}
            entries.append(record)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            _retry(lambda: tmp.write_text(json.dumps(entries, indent=1, default=str) + "\n", encoding="utf-8"))
            _retry(lambda: os.replace(tmp, self.path))
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
