# AI Foundations HW5 — Campus Customs Multi-Agent Operations

A PydanticAI agent team (Boss, Inventory, Accounting, Facilities, Customer Service) that works the shop's tickets through a shared MCP server over the Campus Customs SQLite database.

```
backend/ agent team (PydanticAI, gpt-6-luna)  ──MCP over stdio──▶  mcp_server/ (FastMCP)  ──▶  data/campus_customs_new.db
   any agent can delegate to any other                 shop rules enforced here
   human approves every payment in the terminal
```

| Path | What it is |
|---|---|
| `mcp_server/` | `campus-customs` MCP server (FastMCP) with 17 tools. See [mcp_server/README.md](mcp_server/README.md). |
| `backend/agents.py` | Builds the five agents, their tool access, full-mesh delegation, and the human approval gate. |
| `backend/models.py` | Data types: approval requests and decisions, run context, agent reports. |
| `backend/prompts/` | One prompt file per agent, with that agent's scope and shop rules. |
| `backend/run_tickets.py` | Full run: resets the database, then the Boss works every open ticket. |
| `data/campus_customs_new.db` | Working database the agents update. |
| `data/campus_customs_original.db` | Untouched original (read-only), used for resets. |
| `scripts/reset_db.py` | Restores the working database to the original values. |
| `tests/` | Offline tests for the shop rules and the team wiring (no API key needed). |
| `output/harness.md` | Running design notes: tables, tickets, tools, agents, rules. |
| `dashboard/` | React dashboard from the first scaffold. Not wired to the new backend yet. |

## Setup
Needs Python 3.10+ and a Portkey API key (https://app.portkey.ai/api-keys) with access to `gpt-6-luna`. Requests go through the Portkey gateway (`OPENAI_BASE_URL=https://api.portkey.ai/v1`).

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Open `.env` and paste your Portkey key after `OPENAI_API_KEY=`. `.env` is gitignored.

## Run the tickets
```bash
.venv\Scripts\python -m backend.run_tickets
```

1. The database is reset to the original values first (`--no-reset` skips this).
2. You'll be asked for your name. It's recorded as the approver on any payment.
3. Each time an agent asks to pay a bill or place a purchase order, the run pauses and asks you to approve or reject.
4. The Boss's report, every delegation and tool call, and the changed tables are saved to `output/run_report.json`.

## Tests (no API key, no cost)
```bash
.venv\Scripts\python tests\test_shop_rules.py
.venv\Scripts\python tests\test_team_wiring.py
.venv\Scripts\python scripts\mcp_smoke.py
```
