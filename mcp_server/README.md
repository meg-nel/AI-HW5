# Campus Customs MCP Server

This MCP server gives the Campus Customs agent team (Boss, Inventory, Accounting, Facilities, Customer Service) one shared, read-only way to look up shop data. Every agent uses the same tools, so they all work from the same numbers.

It is built with FastMCP (`mcp.server.fastmcp`).

## Database
`data/campus_customs_new.db` (SQLite), opened read-only. To use a different file, set `CAMPUS_CUSTOMS_DB` to its path.

The shop's "today" comes from the database's `desk` table, not the computer clock.

## Tools

| Tool | Reads | What it answers |
|---|---|---|
| `check_stock(sku, size, qty_needed)` | `inventory` | How many of a SKU in a size are on the shelf, and the shortfall against an order. |
| `quote_price_margin(sku, qty, discount_pct)` | `pricing` | The price and margin for a quantity of a SKU, at list price or with a discount. |
| `get_bills_and_cash()` | `invoices`, `vendors`, `leases`, `cash_accounts`, `desk` | Every open invoice and upcoming rent payment, days until each is due, and the cash available. |

The tools only return data from the database (plus simple arithmetic on it). If a SKU, size or record doesn't exist, they return an error instead of guessing.

## Running it
From the project root:

```bash
python -m mcp_server.server
```

This starts the server over stdio. It isn't connected to the agents yet.
