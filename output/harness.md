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
