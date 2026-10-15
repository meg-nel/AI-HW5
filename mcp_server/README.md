# Campus Customs MCP Server

This MCP server is the one shared toolbox for the Campus Customs agent team (Boss, Inventory, Accounting, Facilities, Customer Service). Every shop fact the agents use comes through these tools, and the shop rules are enforced here so no agent can get around them.

It is built with FastMCP (the `fastmcp` package).

## Database
`data/campus_customs_new.db` (SQLite), the working copy. To use a different file, set `CAMPUS_CUSTOMS_DB` to its path. `scripts/reset_db.py` restores it from `data/campus_customs_original.db`.

The server adds two helper tables to the working copy and re-creates them after a reset:
- `approvals`: payment and purchase-order requests, with the human's decision.
- `drafts`: customer messages, which are never sent.

## Tools (20)

**Shop date and tickets**

| Tool | Reads / writes | What it does |
|---|---|---|
| `get_shop_date()` | reads `desk` | The shop's "today". |
| `list_open_tickets()` | reads `tickets`, `desk` | Every ticket that isn't resolved. |
| `get_ticket(ticket_id)` | reads `tickets`, `inventory`, `pricing`, `invoices`, `vendors`, `leases`, `desk` | One ticket with everything it links to. |
| `update_ticket(ticket_id, status, note, updated_by)` | writes `tickets` | Set status and add a note stamped with the shop date. |

**Stock, pricing, vendors**

| Tool | Reads / writes | What it does |
|---|---|---|
| `check_stock(sku, size, qty_needed)` | reads `inventory` | On-hand quantity and shortfall for one SKU and size. |
| `list_inventory(sku)` | reads `inventory` | Every size of a SKU (or the whole shelf), with out-of-stock flags. |
| `quote_price_margin(sku, qty, discount_pct)` | reads `pricing` | Price and margin at list price or a discount. |
| `list_vendors()` | reads `vendors`, `invoices`, `desk` | Lead times, open unpaid invoices, whether each vendor will ship, and earliest arrival. |

**Money**

| Tool | Reads / writes | What it does |
|---|---|---|
| `get_bills_and_cash()` | reads `invoices`, `vendors`, `leases`, `cash_accounts`, `desk` | Every open bill with days until due, next to cash. |
| `get_lease(lease_id)` | reads `leases`, `payments`, `desk` | One lease and the rent paid against it. |
| `list_payments()` | reads `payments` | Every payment made, and the total paid out. |
| `request_payment(kind, ref_id, requested_by, reason)` | writes `approvals` | Ask a human to approve paying an invoice or rent. The amount comes from the database. |
| `request_purchase_order(vendor_id, sku, size, qty, requested_by, reason)` | writes `approvals` | Ask a human to approve a restock. Shows cash on hand and any shortfall. Refused if the vendor has an open unpaid invoice. |
| `get_approval(approval_id)` | reads `approvals` | The status of one request. |
| `list_approvals(status)` | reads `approvals` | Every request and the human's decision. Read-only. |
| `pay_bill(approval_id, account)` | writes `payments`, `cash_accounts`, `invoices` / `leases`, `approvals` | Pay a human-approved bill. Refuses without approval or without enough cash. |

**Customer messages (drafts only)**

| Tool | Reads / writes | What it does |
|---|---|---|
| `draft_customer_message(ticket_id, subject, body, author)` | writes `drafts` | Save a draft to the ticket's requester. Never sent. |
| `discard_draft(draft_id, reason, author)` | writes `drafts` | Mark an outdated draft as discarded. It stays on record. |
| `list_drafts(ticket_id)` | reads `drafts` | Drafts saved so far. |

**Human only (hidden from every agent)**

| Tool | Reads / writes | What it does |
|---|---|---|
| `admin_decide_approval(approval_id, approved, decided_by, note)` | writes `approvals` | Record a human's approve or reject decision. |

## Rules enforced by the server
- **Shop date:** "today" is `desk.date_today`, and overdue and due-soon are measured from it.
- **Lead times:** they come from `vendors.lead_days`, and arrival = shop date + lead days.
- **Blocked vendors:** a vendor with an open unpaid invoice won't ship, so purchase orders to it are refused.
- **Human approval:** a payment needs a human-approved request, and the approval can only be used once.
- **Cash limits:** `pay_bill` refuses when cash is short, and a database trigger blocks any negative balance.
- **No incoming cash:** cash only goes out, and no tool adds money.
- **No guessing:** unknown SKUs, sizes, tickets, vendors, invoices, or leases return an error instead of a guess.

## Running it
From the project root:

```bash
python mcp_server/server.py
```

This starts the server over stdio. The agent team starts it automatically, and Claude Code uses it through `.mcp.json`.
