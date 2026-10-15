# Campus Customs Agent Harness

Working reference for the Campus Customs multi-agent team. This file grows as we build.

- **Database:** `data/campus_customs_new.db` (SQLite). This is the working copy the agents will read and update.
- **Shop date:** 2026-08-31 (from `desk.date_today`). Agents should use this date, not the real clock.

## Agent team

| Agent | Job |
|---|---|
| **Boss** | Reads each ticket, decides who works on it, and makes the final call. |
| **Inventory** | Checks stock by SKU and size, spots shortfalls, and works out which vendor can restock. |
| **Accounting** | Watches cash and invoices, checks margins, and prepares payments or purchase orders for human approval. |
| **Facilities** | Handles the shop space: rent, leases and the landlord. |
| **Customer Service** | Drafts messages to customers. Drafts are never sent. |

All agents can delegate to each other. Nothing goes out to customers, vendors or the landlord, and any payment or discount waits for human approval.

## Tables

### tickets
`id` (PK), `type`, `requester`, `subject`, `sku`, `size`, `qty`, `lease_id` (→ leases.id), `invoice_id` (→ invoices.id), `status`, `notes`, `created_at`

*Why it matters:* The Boss's inbox; each ticket is a job, and its `sku`/`size`, `lease_id` and `invoice_id` point to the data the other agents need.

### inventory
`sku` (PK), `size` (PK), `name`, `qty`, `location`

*Why it matters:* Inventory checks a ticket's SKU and size here to see whether the shop can fill it or has a shortfall.

### pricing
`sku` (PK), `unit_cost`, `list_price`

*Why it matters:* Accounting uses cost against price to check margins before anyone agrees to a discount.

### vendors
`id` (PK), `name`, `specialty`, `lead_days`

*Why it matters:* Inventory picks a restock vendor by specialty and lead time; Accounting matches invoices to vendors.

### invoices
`id` (PK), `vendor_id` (→ vendors.id), `amount`, `due_date`, `status`, `description`

*Why it matters:* Accounting tracks what the shop owes vendors and when; an open invoice can block a restock.

### payments
`id` (PK), `kind`, `ref_id`, `amount`, `account`, `paid_at`, `approved_by`

*Why it matters:* The record of approved payouts. Every row needs `approved_by`, so Accounting only writes here after a human approves. (Empty today.)

### cash_accounts
`name` (PK), `balance`, `date`

*Why it matters:* Accounting checks the balance before proposing any payment, so the shop never commits more than it has.

### leases
`id` (PK), `space_name`, `landlord`, `monthly_rent`, `next_due`, `notes`

*Why it matters:* Facilities uses it to know what rent is due, to whom and when.

### desk
`date_today`, `notes`

*Why it matters:* Holds the shop's "today", so every agent judges due dates and overdue items against the same date.

## How the three open tickets link to other tables

All three tickets are `status = open`. Ticket SKUs are not declared foreign keys; they match `inventory` and `pricing` by `sku` (and `size`).

### Ticket 101: Bulldog tee (`customer_order`)
- **Requester:** Tauhid Zaman wants 1 × `CC-TEE-WHITE` (Classic Bulldog Tee) in size S.
- **Inventory:** size S has **0** in stock (Aisle B), so it can't be filled from the shelf.
- **Invoice 501:** Bulldog Print Co (vendor 1, apparel reprint, 5-day lead), **$840** for "Rush reprint CC-TEE-WHITE S".
  - Status `open`, due **2026-08-28**, so it is **3 days overdue**.
- **Agents involved:**
  - Inventory confirms the shortfall and the reprint path.
  - Accounting handles the overdue invoice.
  - Customer Service drafts an update to the customer.
  - Boss decides the order.

### Ticket 102: Rent due (`rent_notice`)
- **Requester:** Elm City Properties, about the Chapel Street shop.
- **Lease 1:** rent is **$2,400**, due **2026-09-02**, in 2 days.
- **Cash:** the shop has **$3,400** in checking.
- Elm City Properties (landlord) is not in `vendors`, and is a different business from Elm City Gifts (vendor 2).
- **Agents involved:**
  - Facilities owns the lease.
  - Accounting prepares the payment for human approval.

### Ticket 103: Bulk hoodie discount (`price_override`)
- **Requester:** Yale AI Club wants 20 × `CC-HOOD-NAVY` (Basic Hoodie Big Yale) in size M, at a bulk discount.
- **Inventory:** size M has **8**, a shortfall of **12** (other sizes: S 4, L 14, XL 6).
- **Pricing:**
  - Unit cost is **$22** and list price is **$58**, a $36 margin per hoodie (about 62%).
  - 20 at list is **$1,160**.
- **Restock:** the likely vendor is Bulldog Print Co (apparel, 5-day lead). 12 hoodies at cost is about **$264**.
- **Agents involved:**
  - Inventory handles the shortfall and restock.
  - Accounting finds the lowest discount that keeps a healthy margin.
  - Boss approves or rejects the override.
  - Customer Service drafts the reply.

### Cross-ticket cash check
Today's obligations compete for the same **$3,400**:

| Item | Amount |
|---|---|
| Rent (ticket 102) | $2,400 |
| Overdue invoice 501 (ticket 101) | $840 |
| Remaining | **$160** |

Restocking 12 hoodies for ticket 103 (about $264) would not fit before the AI Club pays. The Boss has to decide the order of payments; it shouldn't be decided one ticket at a time.

## MCP tools (Problem 3: the first three)

Server: `mcp_server/server.py` (FastMCP, `campus-customs`). Every agent uses these tools. The server grew in Problem 5; see "New MCP tools" below.

These three tools are read-only, return only what is in `data/campus_customs_new.db` (plus simple arithmetic on it), and raise an error rather than guess when a SKU, size or record is missing.

### `check_stock(sku, size, qty_needed)`
- **Reads:** `inventory`
- **Returns:** product name, shelf location, quantity on hand, whether the order can be filled, and the shortfall.
- **Unlocks:** **Ticket 101**. Also used for ticket 103.
- **Why this tool for 101:** Ticket 101 is a one-tee order for `CC-TEE-WHITE` in size S, and `check_stock("CC-TEE-WHITE", "S", 1)` shows 0 on hand and a shortfall of 1, which is the fact that turns a simple sale into a restock problem.
- **For 103:** `check_stock("CC-HOOD-NAVY", "M", 20)` shows 8 on hand and a shortfall of 12.

### `quote_price_margin(sku, qty, discount_pct)`
- **Reads:** `pricing`
- **Returns:** unit cost, list price, discounted unit price, per-unit and total margin, and margin %.
- **Unlocks:** **Ticket 103**
- **Why this tool for 103:** Ticket 103 is the Yale AI Club asking for a bulk discount on 20 `CC-HOOD-NAVY` hoodies, and this tool shows exactly what any discount does to profit before the Boss approves the price override. For example:

  | Price | Unit price | Total | Margin |
  |---|---|---|---|
  | List | $58 | $1,160 | $720 (62.1%) |
  | 15% off | $49.30 | $986 | $546 (55.4%) |

### `get_bills_and_cash()`
- **Reads:** `invoices`, `vendors`, `leases`, `cash_accounts`, `desk`
- **Returns:** every open invoice and upcoming rent payment with days until due (measured from the shop date in `desk`), next to the cash balance.
- **Unlocks:** **Ticket 102**. Also covers invoice 501 on ticket 101.
- **Why this tool for 102:** Ticket 102 is Elm City Properties' notice that rent is due, and this tool puts lease 1's $2,400 rent (due 2026-09-02, 2 days out) next to the $3,400 in checking and the other bill competing for it, so Facilities and Accounting can see the rent is payable but leaves little room.
- **For 101:** the same call shows invoice 501, $840 to Bulldog Print Co for the S-tee reprint, is 3 days overdue. After both bills, $160 is left.

## MCP connection and tool tests

### Connection (`.mcp.json`)
The server is registered for this project in `.mcp.json` as `campus-customs`, a stdio server:

- **Command:** the project's `.venv` Python runs `mcp_server/server.py`.
- **Database:** `CAMPUS_CUSTOMS_DB` points at `data/campus_customs_new.db`.
- **Paths:** full paths, so the server starts from any folder.

### Test results
- **How it was tested:** each tool was called over MCP (stdio) with the server started exactly as `.mcp.json` describes.
- **Date:** 2026-10-14.
- **Database:** opened read-only and unchanged after the tests.

| Ticket | Call | Result | Pass |
|---|---|---|---|
| 101 | `check_stock("CC-TEE-WHITE", "S", 1)` | Classic Bulldog Tee, Aisle B: 0 on hand, can't fill, shortfall 1 | ✅ |
| 103 | `check_stock("CC-HOOD-NAVY", "M", 20)` | Basic Hoodie Big Yale, Aisle A: 8 on hand, can't fill, shortfall 12 | ✅ |
| 103 | `quote_price_margin("CC-HOOD-NAVY", 20)` | List price: $58/unit, $1,160 total, $720 margin (62.1%) | ✅ |
| 103 | `quote_price_margin("CC-HOOD-NAVY", 20, 10)` | 10% off: $52.20/unit, $1,044 total, $604 margin (57.9%) | ✅ |
| 102 | `get_bills_and_cash()` | See below | ✅ |
| Error check | `check_stock("CC-MUG-CREST", "M", 1)` | Error: "SKU CC-MUG-CREST has no size M; sizes in inventory: OS" (no made-up answer) | ✅ |

**`get_bills_and_cash()` result (shop date 2026-08-31):**
- Checking balance: $3,400.
- Invoice 501, Bulldog Print Co: $840, 3 days overdue.
- Lease 1 rent, Elm City Properties: $2,400, due in 2 days.
- Bills total $3,240, leaving $160.

Every result matches the database values in the ticket notes above.

### Smoke-test evidence (`output/mcp_smoke.json`)
`scripts/mcp_smoke.py` calls each tool once over MCP for its ticket and writes `output/mcp_smoke.json`. For each tool it records:
- the test prompt
- the tool name and arguments
- the raw tool output
- the plain SQL it ran against `data/campus_customs_new.db`, which doesn't use the server's code
- a field-by-field match check

Results:

| Ticket | Tool | Fields checked against the database |
|---|---|---|
| 101 | `check_stock` | 4 of 4 match |
| 102 | `get_bills_and_cash` | 9 of 9 match |
| 103 | `quote_price_margin` | 5 of 5 match |

`all_passed: true`. To re-run: `.venv\Scripts\python scripts\mcp_smoke.py`.

## Agent team (PydanticAI)

| | |
|---|---|
| **Framework** | PydanticAI 2.56 (`backend/agents.py`) |
| **Model** | `gpt-6-luna` for every agent, through the OpenAI Responses API. The key is read from `OPENAI_API_KEY` in `.env`. |
| **Prompts** | `backend/prompts/<agent>.md`, one per agent. Each lists the agent's scope (what it owns and doesn't), its tools, the shop rules it needs, when to bring in a teammate, and what to report. |
| **Data types** | `backend/models.py`: `TeamDeps` (run context), `ApprovalRequest` / `ApprovalDecision`, `SpecialistReport` (output of the four specialists), `BossReport` / `TicketResolution` (the Boss's output). |
| **MCP connection** | One stdio connection to `mcp_server/server.py`, shared by all agents. Each agent sees only the tools its role needs. |

### Delegation (full connectivity)
- **Who can delegate:** every agent has `delegate_task(to_agent, task)` and can hand work to any of the other four.
- **How it runs:** the teammate runs with its own prompt and tools, and its report comes back as the tool result. Usage is shared across the whole run (request limit 150).
- **Limits:**
  - Delegating to yourself is bounced.
  - Delegation chains stop at depth 3, so A → B → A loops can't run forever.
- **Logging:** every delegation, tool call, and approval is logged with the chain, for example `boss -> accounting`.

### Tool access per agent

| Agent | MCP tools |
|---|---|
| Boss | `get_shop_date`, `list_open_tickets`, `get_ticket`, `update_ticket`, `get_bills_and_cash`, `check_stock`, `quote_price_margin`, `list_vendors`, `get_approval`, `list_drafts` |
| Inventory | `get_shop_date`, `get_ticket`, `check_stock`, `list_vendors` |
| Accounting | `get_shop_date`, `get_ticket`, `get_bills_and_cash`, `quote_price_margin`, `list_vendors`, `request_payment`, `get_approval`, `pay_bill`, `request_purchase_order` |
| Facilities | `get_shop_date`, `get_ticket`, `get_bills_and_cash` |
| Customer Service | `get_shop_date`, `get_ticket`, `check_stock`, `list_vendors`, `list_drafts`, `draft_customer_message`, `discard_draft` |

`admin_list_approvals` and `admin_decide_approval` are hidden from every agent. Only the human approval step uses them.

## New MCP tools (Problem 5)

### `get_ticket(ticket_id)`
- **Reads:** `tickets`, `inventory`, `pricing`, `invoices`, `vendors`, `leases`, `desk`
- **Unlocks:** **101, 102 and 103**. Every agent's first step on a ticket.
- **Why:**
  - **101:** one call returns the S-tee row (0 on hand) **and** invoice 501 marked 3 days overdue.
  - **102:** one call returns lease 1 with rent due in 2 days.
  - **103:** one call returns the M-hoodie row (8 on hand) and the $22 / $58 pricing.

### `list_open_tickets()`
- **Reads:** `tickets`, `desk`
- **Unlocks:** **101, 102 and 103**.
- **Why:** the Boss starts every run here, so all three tickets are weighed together before any cash is spent.

### `update_ticket(ticket_id, status, note, updated_by)`
- **Writes:** `tickets`
- **Unlocks:** **101, 102 and 103**.
- **Why:** this is how the Boss records the final call on each ticket. For example, 101 becomes `waiting_on_vendor` with the reprint's arrival date. Each note is stamped with the shop date and the agent.

### `list_vendors()`
- **Reads:** `vendors`, `invoices`, `desk`
- **Unlocks:** **101 and 103**.
- **Why:** both restocks need an apparel vendor. The tool shows Bulldog Print Co (5-day lead) has `will_ship: false` because invoice 501 is unpaid, which blocks the S-tee reprint (101) and the 12 extra M hoodies (103) until that invoice is paid.

### `request_payment(kind, ref_id, ...)` and `pay_bill(approval_id)`
- **Write:** `approvals`, then `payments`, `cash_accounts`, and `invoices` / `leases`
- **Unlock:** **102 and 101**.
- **Why for 102:** rent of $2,400 on lease 1 can only be paid after a human approves.
- **Why for 101:** invoice 501's $840 has to be paid before Bulldog Print Co will ship.
- **On success, `pay_bill`:**
  - writes the `payments` row with the human's name
  - lowers checking
  - marks the invoice `paid`, or moves the lease's `next_due` forward one month
- **It refuses:** if cash is short.

### `request_purchase_order(vendor_id, sku, size, qty, ...)`
- **Writes:** `approvals`
- **Unlocks:** **103 and 101**.
- **Why:** restocking 12 × `CC-HOOD-NAVY` M (103) or the S tee (101) needs a human-approved order. The tool costs it from `pricing` (12 × $22 = $264) and dates it shop date + `lead_days`. It refuses while the vendor has an open invoice.

### `draft_customer_message(ticket_id, ...)` and `list_drafts()`
- **Write / read:** `drafts`
- **Unlock:** **101, 103 and 102**.
- **Why:** Customer Service drafts replies to Tauhid Zaman (101), the Yale AI Club (103), and Elm City Properties (102). The recipient is always the ticket's requester, and nothing is sent.

### `get_shop_date()` and `get_approval(approval_id)`
- **Read:** `desk`, `approvals`
- **Unlock:** **all three tickets**.
- **Why:** they keep every agent on the shop's "today" (2026-08-31), and let the Boss confirm whether a human approved a request.

## Shop rules and where they're enforced

| Rule | Prompt | Code (can't be bypassed) |
|---|---|---|
| `desk.date_today` is "today" and decides what's overdue | All five prompts | Every date calculation in the server uses `desk.date_today`, never the computer clock. |
| Lead times come from `vendors.lead_days` | Inventory, Accounting, Customer Service, Boss | `list_vendors` and `request_purchase_order` compute arrival = shop date + `lead_days`. |
| A vendor won't ship with an open unpaid invoice | Inventory, Accounting, Customer Service, Boss | `request_purchase_order` refuses; `list_vendors` shows `will_ship: false`. |
| Human approval for every payment | All five prompts | `request_payment` → the run pauses and asks the human → `admin_decide_approval` records it → `pay_bill` only accepts an approved, unused request. The admin tools are hidden from agents. |
| Paying updates the tables | Accounting | `pay_bill` writes `payments` (with the approver's name), `cash_accounts`, and `invoices` / `leases` in one transaction. |
| Refuse if cash is short; no negative balances | Accounting, Boss, Facilities | `pay_bill` checks the balance first, and a database trigger blocks any negative balance. |
| Cash only goes out | Accounting, Boss, Facilities | No tool adds money or records revenue. |
| Never invent data | All five prompts | Amounts come from the database, not the agent. Unknown IDs, SKUs, and sizes return errors. |
| Messages are drafts only | Customer Service, Boss | There is no send tool, and drafts have no "sent" status. |

## Reset before a full run
- `data/campus_customs_original.db` is the untouched original we were given. It is read-only, and its sha256 starts `23686a90`.
- `scripts/reset_db.py` copies it over `data/campus_customs_new.db` and checks the hashes match.
- `python -m backend.run_tickets` runs this reset automatically before the Boss starts. `--no-reset` skips it.

## Offline tests (no API key)
- **`tests/test_shop_rules.py`:** 23 checks of the MCP rules against a temporary copy of the database, including:
  - payment refused without approval and after a rejection
  - $840 payment recorded with the approver's name
  - rent refused when checking had $1,000
  - negative balance blocked by the trigger
  - purchase order refused while invoice 501 is open
- **`tests/test_team_wiring.py`:** 16 checks with scripted stand-in models, including:
  - Boss → Accounting delegation
  - self-delegation bounced
  - each agent sees exactly its allowed tools
  - the human is asked before payment
  - an agent that tries to pay after a rejection is refused by the server

## Full run #1 (2026-10-14, gpt-6-luna through Portkey)

- **Setup:** the database was reset to the original values first. Human approver: Meg.
- **Report file:** the run's own report (`output/run_report.json`) was **not** saved. The runner crashed after the Boss finished, while reading token usage (a PydanticAI 2.x API change), so the Boss's final report and the event log were lost.
  - The fix: the runner now saves the report even if a run fails or is stopped.
  - The record of this run is the terminal log and the database, checked by `scripts/check_run.py` → `output/run_db_check.json`.

### What the team did
1. **Boss reads everything.** It read all three tickets, the bills and cash, and the vendors.
2. **Boss delegates.** It sent five briefs: Inventory (tickets 101 and 103), Accounting (101 and 103), and Facilities (102).
3. **Specialists report back.**
   - **Inventory:** the S tee has 0 on hand (short 1), and the M hoodies have 8 (short 12). Bulldog Print Co is blocked by invoice 501.
   - **Facilities:** the rent notice matches lease 1 ($2,400, due 2026-09-02).
   - **Accounting:** priced 20 hoodies at 0%, 10%, 15% and 20% off, and suggested 10% ($1,044 total, 57.9% margin).
4. **Accounting requests both payments** and the human approves them:
   - **#1:** invoice 501, $840, approved by Meg and paid.
   - **#2:** rent on lease 1, $2,400, approved by Meg and paid.
   - Checking went from $3,400 to $160.
5. **Accounting requests purchase order #3:** 1 × CC-TEE-WHITE S from Bulldog Print Co, $8, arriving 2026-09-05. Approved by Meg. No cash moved.
6. **Customer Service saves 4 drafts**, none sent:
   - two for 101 (the second corrects the first after the order was approved)
   - one for 103
   - one for 102
7. **Boss updates all three tickets.**

| Ticket | Final status | Boss's call |
|---|---|---|
| 101 | `waiting_on_vendor` | Invoice 501 paid, which unblocked the vendor. Restock order for 1 S tee approved, arriving 2026-09-05 (estimate). Draft 3 is the reply to send; draft 1 is outdated. |
| 102 | `resolved` | Rent paid 2 days early. Lease 1's next due date moved to 2026-10-02. Acknowledgement drafted. |
| 103 | `waiting_on_human` | Approved a 10% discount: $52.20 each, $1,044 for 20. Only 8 on hand, so the draft offers those 8 for $417.60 and asks whether they'll wait. No order placed for the other 12. |

### Database checks (13 of 13 pass)
- Every payment has a matching human-approved request, and every approver is Meg (never an agent).
- Cash fell by exactly the payments ($3,240) to $160, with no negative balance.
- Invoice 501 is `paid`, and lease 1's `next_due` moved from 2026-09-02 to 2026-10-02. Both payments are dated with the shop date (2026-08-31).
- Purchase order #3's arrival uses Bulldog Print Co's `lead_days` (5). It was placed only after invoice 501 was paid.
- Inventory, pricing, vendors and the desk date are unchanged.
- All 4 drafts go to their ticket's requester and are still unsent.

### Issues found
| Issue | Where | What to change |
|---|---|---|
| Accounting chose the payment order (invoice first, then rent) itself; the Boss had only asked it to look into ticket 101. The order was sensible and both payments were approved, but the Accounting prompt says the Boss decides the order. | Accounting prompt | The Boss should set the payment order before asking for payments, and Accounting should ask rather than decide. |
| Ticket 103: the Boss held the 12-hoodie order because $264 > $160 cash. A purchase order doesn't move cash, but the vendor's invoice will arrive later, so this is a cautious call rather than a rule. | Boss judgment | Decide whether purchase orders should be limited by current cash. |
| The rent acknowledgement (draft 4) says "acknowledge receipt of the $2,400 rent payment", which is the landlord's wording. The shop sent the payment, it didn't receive it. | Customer Service | The prompt should say that for the landlord, the shop is the one paying. |
| Draft 1 for ticket 101 is outdated, and there's no tool to discard it. | MCP tools | Add a discard or supersede tool for drafts. |
| The run report was lost to a runner bug. | `backend/run_tickets.py` | Fixed and tested offline. |

### Fixes made after run #1
- **Payment order.**
  - **Boss prompt:** gather facts with "numbers only" briefs to Accounting, then send **one** money plan listing the bills and restock orders in order. Replies are drafted last, after the money plan.
  - **Accounting prompt:** only request items the Boss's plan lists.
  - **Facilities prompt:** recommends rent timing and no longer asks Accounting to pay.
- **Landlord wording.** Customer Service's prompt now says the shop is the payer: "We have sent / paid the rent", never "acknowledge receipt".
- **Outdated drafts.** New MCP tool `discard_draft`, which keeps the draft on record, never sent. Customer Service keeps one live draft per ticket.
- **Purchase orders vs. cash.**
  - **Policy:** a purchase order moves no cash today, so the agents don't hold back a needed restock just because cash is low. Accounting requests it with cost against cash in the reason, and the human decides.
  - **Server:** `request_purchase_order` now returns `cash_on_hand` and `cash_shortfall`, and the terminal approval prompt shows them.
- **Runner.**
  - The report is saved even if a run fails or is stopped.
  - Agent output is held back while an approval prompt is waiting.
  - A hidden byte-order mark in typed input is stripped, so "y" can't be misread as a rejection.
- **Tests:** shop-rule checks went from 23 to 26 (discarding drafts, purchase-order cash fields). Team checks: 16. All pass.

## Full run #2 (2026-10-14, gpt-6-luna through Portkey)

| | |
|---|---|
| **Report** | `output/run_report.json`, `completed: true`, no error |
| **Duration** | 3 min 50 s |
| **Usage** | 31 model requests, 137,443 input tokens, 9,190 output tokens |
| **Activity** | 5 delegations, 51 tool calls, 4 approvals |
| **Setup** | Database reset to the original values first. Human approver: Meg. |

### What the team did
1. **Boss gathers facts.** It sent briefs to Inventory ("check stock and restock facts only; do not order anything"), Accounting ("numbers only — do not request any payment or purchase order yet"), and Facilities ("do not pay or contact landlord").
2. **Boss sends one money plan** to Accounting: "execute only this list, in exactly this order":
   1. invoice 501
   2. rent on lease 1
   3. purchase order for 1 tee
   4. purchase order for 12 hoodies
3. **Accounting requests each item in that order**, citing "Boss's ordered shop money plan":

   | # | Request | Amount | Decision |
   |---|---|---|---|
   | 1 | Invoice 501 to Bulldog Print Co | $840 | Approved by Meg, paid |
   | 2 | Rent on lease 1 to Elm City Properties | $2,400 | Approved by Meg, paid |
   | 3 | Purchase order: 1 × CC-TEE-WHITE S | $8 | Approved by Meg; no cash moved (cash on hand $160, no shortfall) |
   | 4 | Purchase order: 12 × CC-HOOD-NAVY M | $264 | Approved by Meg; no cash moved (cash on hand $160, **shortfall $104**, shown at the prompt) |
4. **Customer Service** drafts one reply per ticket, after the money plan.
5. **Boss** updates all three tickets and returns its `BossReport`.

| Ticket | Final status | Boss's call |
|---|---|---|
| 101 | `waiting_on_vendor` | 1 S tee restocked from Bulldog Print Co after invoice 501 was paid. Expected 2026-09-05, not guaranteed. |
| 102 | `resolved` | Rent of $2,400 paid 2 days early (payment 2). Next due date 2026-10-02. |
| 103 | `waiting_on_vendor` | Approved **15% off**: $49.30 each, $986 for 20, $546 margin (55.4%). 8 on hand plus 12 on the approved order, expected 2026-09-05. |

The Boss's cash: $3,400 at the start, $160 at the end. Nothing is left in `needs_human`.

### Drafts (one live draft per ticket, none sent)
- **Draft 1 → Yale AI Club:** 15% off at $49.30 each ($986). 8 in stock, 12 being restocked, expected around Sept 5 (an estimate).
- **Draft 2 → Tauhid Zaman:** the S tee is being restocked, expected around Sept 5 (an estimate).
- **Draft 3 → Elm City Properties:** "Thank you for the rent reminder. We have paid the $2,400 rent…" The shop is correctly the payer.

### Database checks (16 of 16 pass, `output/run_db_check.json`)
- **Payments:** both have human-approved requests, with Meg as approver (no agent decided anything). Cash fell by exactly $3,240 to $160 and never went negative.
- **Bills:** invoice 501 is `paid`, and lease 1's due date moved to 2026-10-02. Both payments are dated 2026-08-31.
- **Purchase orders #3 and #4:** arrival = shop date + 5 lead days. Both were placed only after invoice 501 was paid.
- **Unchanged tables:** inventory, pricing, vendors and the desk date.
- **Drafts:** all go to the ticket's requester, none were sent, and there's one live draft per ticket.

### Did the run #1 fixes hold?
| Fix | Run #2 |
|---|---|
| Boss sets the payment order | ✅ "Numbers only" first, then one ordered plan. Accounting cited the plan on every request. |
| Landlord wording | ✅ "We have paid the $2,400 rent." |
| Outdated drafts | ✅ Drafted once, after the money plan. Nothing needed discarding. |
| Purchase orders vs. cash | ✅ The 12-hoodie order was requested with the $104 shortfall shown, and the human decided. |
| Run report saved | ✅ `completed: true`. |

### Notes for later
- **The discount changed between runs:** 10% in run #1, 15% in run #2. No shop rule sets a discount limit, so this is the Boss's own judgment. Add a margin floor to the Boss prompt if the discount should be consistent.
- **Approved orders vs. cash:** the two orders will be invoiced at $272, against $160 left. That was the human's call at the prompt. When those invoices arrive, `pay_bill` will refuse anything cash can't cover.
