# AI Foundations HW5 — Campus Customs Multi-Agent Operations

A PydanticAI agent team (Boss, Inventory, Accounting, Facilities, Customer Service) that works the shop's tickets through a shared MCP server over the Campus Customs SQLite database.

```
board / browser ──HTTP──▶ backend/main.py (FastAPI) ──▶ agent team (PydanticAI, gpt-6-luna) ──MCP──▶ mcp_server/ (FastMCP) ──▶ data/campus_customs_new.db
                          human approves → route pays      any agent can delegate to any other      shop rules enforced here
```

| Path | What it is |
|---|---|
| `backend/main.py` | FastAPI board API: tickets, run a ticket, events, approvals (the approve route is what pays), cash, reset. |
| `mcp_server/` | `campus-customs` MCP server (FastMCP) with 21 tools. See [mcp_server/README.md](mcp_server/README.md). |
| `backend/agents.py` | Builds the five agents, their tool access, full-mesh delegation, and the human approval gate. |
| `backend/models.py` | Data types: approval requests and decisions, run context, agent reports. |
| `backend/prompts/` | One prompt file per agent, with that agent's scope and shop rules. |
| `backend/run_tickets.py` | Full run: resets the database, then the Boss works every open ticket. |
| `data/campus_customs.db` | The database file provided with the assignment (same contents as the original). |
| `data/campus_customs_new.db` | Working database the agents update. |
| `data/campus_customs_original.db` | Untouched original (read-only), used for resets. |
| `scripts/reset_db.py` | Restores the working database to the original values. |
| `frontend/` | Agent dashboard (React + Vite + TypeScript): tickets, live agents, approvals, cash, summaries. |
| `backend/demo.py` | Scripted stand-in agents for trying the board without model calls (`CAMPUS_CUSTOMS_DEMO=1`). |
| `tests/` | Offline tests for the shop rules, the team wiring and the API routes (no API key needed). |
| `output/harness.md` | Running design notes: tables, tickets, tools, agents, rules, routes. |
| `output/design.md` | Why the dashboard looks the way it does, with screenshots. |

## Setup
Needs Python 3.10+ and a Portkey API key (https://app.portkey.ai/api-keys) with access to `gpt-6-luna`. Requests go through the Portkey gateway (`OPENAI_BASE_URL=https://api.portkey.ai/v1`).

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Open `.env` and paste your Portkey key after `OPENAI_API_KEY=`. `.env` is gitignored.

## Run the board API
From the `backend/` folder:

```bash
..\.venv\Scripts\uvicorn main:app --reload --port 8000
```

Open http://localhost:8000/docs to try the routes. Each route is listed in `output/harness.md`, under "Backend routes".

## Run the dashboard
Needs Node.js 18+. In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Pick a ticket, start the team, and approve or reject payments when the board asks; your approval is what pays.

To try the board without spending tokens, start the API in demo mode instead. These are PowerShell commands, run from `backend/`. Demo runs really write to the database, so reset it afterwards with the board's "Fresh start" button.

```powershell
$env:CAMPUS_CUSTOMS_DEMO = "1"
..\.venv\Scripts\uvicorn main:app --reload --port 8000
```

## Run all tickets from the terminal
```bash
.venv\Scripts\python -m backend.run_tickets
```

1. The database is reset to the original values first (`--no-reset` skips this).
2. You'll be asked for your name. It's recorded as the approver on any payment.
3. Each time an agent asks to pay a bill or place a purchase order, the run pauses and asks you to approve or reject. Your approval is what pays; agents only prepare payments.
4. The Boss's report, every delegation and tool call, and the changed tables are saved to `output/run_report.json` (this run only).
5. Every agent-loop step is appended to `output/audit_trail.json`, which keeps every run.

## Tests (no API key, no cost)
```bash
.venv\Scripts\python tests\test_shop_rules.py
.venv\Scripts\python tests\test_team_wiring.py
.venv\Scripts\python tests\test_api.py
.venv\Scripts\python scripts\mcp_smoke.py
```
