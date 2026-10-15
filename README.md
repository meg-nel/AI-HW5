# AI Foundations HW5 — Campus Customs Multi-Agent Operations

Three pieces that work together:

```
React dashboard (:5173)  ──REST + WebSocket──▶  FastAPI backend (:8000)  ──MCP over stdio──▶  MCP server
  watch agents, approve,                          agent team (Claude),                         shop data (SQLite),
  review drafts                                   delegation, approvals, event bus             drafts board, approvals
```

| Folder | What it is |
|---|---|
| `mcp_server/` | `campus-customs` MCP server (FastMCP) with three read-only tools over `data/campus_customs_new.db`. See [mcp_server/README.md](mcp_server/README.md). |
| `backend/` | FastAPI app. Starts the MCP server as a subprocess, runs the agent team, streams every step to `/ws`. |
| `backend/agents.py` | **The agent roster** (starter placeholders, to be designed in detail). |
| `dashboard/` | Vite + React dashboard: agent mesh, live activity feed, approvals queue, drafts board, shop tables. |

## Safety rules (enforced in code, not just prompts)
- **No outbound actions exist.** The MCP server has no send-email or contact-vendor tools. Agents can only write drafts (`draft_customer_email`, `draft_vendor_request`), which stay on the board. Draft status can be `draft`, `reviewed`, or `discarded`; there is no `sent`.
- **Human approvals block the agent.** When an agent calls `request_approval`, its run pauses until you approve or reject on the dashboard, and your note goes back to the agent.
- `admin_*` MCP tools (deciding approvals, changing draft status) are filtered out of every agent's toolset.

## Agent team
- Full mesh: every agent gets a `delegate_task` tool that can target any teammate. The delegated agent runs with a fresh context and its final answer goes back as the tool result.
- Delegation depth is capped (`CAMPUS_CUSTOMS_MAX_DEPTH`, default 3) so A→B→A loops can't run forever.
- Model: `claude-opus-5-5` (override with `CAMPUS_CUSTOMS_MODEL`), adaptive thinking with summarized reasoning shown in the feed, per-agent `effort`, and server-side refusal fallback enabled.

## Running it
Needs Python 3.10+, Node 18+, and an Anthropic API key.

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env   # then put your key in .env (it's gitignored)
.venv\Scripts\uvicorn backend.main:app --reload --port 8000
```

In a second terminal:

```bash
cd dashboard
npm install
npm run dev
```

Open http://localhost:5173. To reset the demo shop, delete `data/shop.db`.

To use the MCP server from another MCP client (e.g. Claude Desktop), run `python -m mcp_server.server` from the project root.
