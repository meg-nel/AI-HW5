# AI Prompts Log — AI Foundations HW5

A log of the prompts I typed to the AI assistant while building the Campus Customs multi-agent operations project, grouped by problem. Follow-up prompts note what the earlier prompt was missing.

---

## Problem 1: Vibe Coder Prompts

### Initial prompt

> Hello, we are working on a vibe coding project today - call it AI Foundations HW5. We're building three pieces that interact with each other - an MCP server, a FastAPI backend with a multi-agent team, and a React dashboard so I can watch the agents at work and approve requests. This is for the Campus Customs Multi-Agent Operations agentic team to run a shop. The agent team should have full connectivity and any agent may delegate tasks to another agent for help. We'll go through the agent team and build them in detail later on. Do not email customers or call real vendors, all of these will remain as drafts on the board

### Follow-up prompts

**Follow-up 1**

> Pls keep everything in my github AI-HW5 repository

*What was lacking:* The first prompt didn't say where the project should live, so the code was built in a temporary session folder instead of my GitHub repo.

**Follow-up 2**

> Git isn't installed but in settings I see it's a connector, can you use that?

*What was lacking:* The previous prompt assumed the assistant could reach GitHub, but Git wasn't installed and no GitHub connector was available to the session.

**Follow-up 3**

> Install Git with winget and push to my AI-HW5 repo. The URL is https://github.com/<my-username>/AI-HW5

*What was lacking:* The connector route didn't work, so this gave explicit permission to install Git, but the URL still had a placeholder instead of my username.

**Follow-up 4**

> My username is meg-nel

*What was lacking:* Follow-up 3 left `<my-username>` unfilled, so the repo address was incomplete.

**Follow-up 5**

> I finished signing in. Check whether the push went through.

*What was lacking:* The push needed a GitHub browser sign-in that only I could complete; this confirmed it was done.

**Follow-up 6**

> I have API you can use

*What was lacking:* The project couldn't run its agents live without an Anthropic API key, and the first prompt didn't mention one.

**Follow-up 7**

> Pls create AI_prompts.md and keep updating it as we work, this should be a log of what I type to you. Keep one section for each problem, each section must include the problem number and title, the prompts I type for the problem, and a follow up prompt if needed with a sentence on what was lacking on the first prompt. You can keep this and the previous prompt under Problem 1: Vibe Coder Prompts

*What was lacking:* The homework needs a record of the prompts used, which none of the earlier prompts asked for.

---

## Problem 2: Study the Campus Customs Database

### Initial prompt

> @"C:\Users\megha\Downloads\data (1)\data\campus_customs_new.db"
> Next is Problem 2: Study the Campus Customs Database. See the attached file and save as data/campus_customs_new.db, later we'll update this as our working copy. Study the three open tickets so you understand how they link to other tables. Start output/harness.md. For each table, list the fields and one short line on why that table matters for the agents. Our harness file will keep growing. These are the agents we are building. Boss: reads each ticket, decides who should work on it, and make final calls. Inventory: checks stock by SKU and size, spots shortfalls, and figures out which vendor can restock. Accounting: watches cash and invoices, checks margins, and prepares payments or purchase orders for human approval. Facilities: handless shop space (e.g. rent, leases, etc.). Customer Service: Drafts messages for customers

### Follow-up prompts

**Follow-up 1**

> Commit and push today's changes to AI-HW5.

*What was lacking:* The first prompt didn't say to save the new database, harness file and other changes to GitHub, so they were only on my computer.

---

## Problem 3: Build the MCP Server

### Initial prompt

> Next is Problem 3: Build the MCP Server. Write an MCP server in mcp_server/ using Fast MCP. It will talk to data/campus_customs_new.db. We don't have to connect or run it yet. Every agent will use the tools in this MCP server. Write three tools we will need for the tickets in the database - keep the names clear, never invent data, and only use information in the database. In output/harness.md, list each of the MCP tools and for every tool, include which table it reads, which ticket it helps unlock (e.g. 101, 102, or 103), and one sentence on why that tool is the right one for that ticket - don't be vague, tie the tool to the ticket. Also add a short mcp_server/README.md file that explains what the MCP server is for, which database file it uses, and the three tools it has

---

## Problem 4: Add the MCP Server to Vibe Coder and Test Each Tool

### Initial prompt

> Next is Problem 4: Add the MCP Server to Vibe Coder and Test Each Tool. Add the MCP server to this project so you can call the tools and save the connection JSON text in .mcp.json

### Follow-up prompts

**Follow-up 1**

> I approved the campus-customs MCP server. Call each tool and record the results.

*What was lacking:* Claude Code only loads a new project MCP server after the user approves it, and the first prompt didn't mention that step, so the tools couldn't be called until I approved it. The first prompt also didn't say where to record the test results.

**Follow-up 2**

> Commit and push Problems 3 and 4 to AI-HW5.

*What was lacking:* The Problem 3 and 4 prompts didn't say to save the work to GitHub, so the MCP server, `.mcp.json` and test results were only on my computer.

**Follow-up 3**

> Test each of the three MCP tools and save the evidence in output/mcp_smoke.json. For every tool, include the prompt used to test the tool, the tool name, and the tool output that matches values in data/campus_customs_new.db

*What was lacking:* The earlier test results were a summary table in harness.md, not a machine-readable evidence file showing the test prompt, the tool and its raw output checked against the database.

**Follow-up 4**

> Commit and push the smoke test to AI-HW5.

*What was lacking:* Follow-up 3 didn't say to save the smoke test to GitHub, so `output/mcp_smoke.json` and its script were only on my computer.

---

## Problem 5: Build the Agent Team and Grow the MCP Tools

### Initial prompt

> Thx. Next is Problem 5: Build the Agent Team and Grow the MCP Tools. Build the agentic team for Campus Customs using PydanticAI: Boss, Inventory, Accounting, Facilities, and Customer Service. Include prompts, models, and agent loops so they can delegate work to each other with full connectivity. Put the agent prompts in backend/prompts/ - one file per agent. Put data types in backend/models.py and the agent files under backend/. Use my API key and only gpt-6-luna for every agent. There are important shop rules all agents should follow. The field desk.date_today is "today" for the shop and use the date to determine what is overdue. Vendor lead times come from the vendors table and a vendor will not ship new product while they still have an open unpaid invoice. Human approval is required for any payments - make sure human approval occurs, and if payment is made, make sure to update the relevant table. If there isn't enough cash, the pay tool must refuse and negative balances are not allowed. Cash only goes out, we don't need to record revenue or money comping in. Before a full run to resolve tickets, reset the database to the original values

### Follow-up prompts

**Follow-up 1**

> Write each prompt with the shop rules the agent needs - be more detailed and ensure all aspects of an agent's work and scope are covered

*What was lacking:* The first prompt listed the shop rules once for the whole team but didn't say each agent's prompt file had to spell out the rules it needs and its full scope of work.

**Follow-up 2**

> where can I put the key?

*What was lacking:* The first prompt said to use my API key but not where the key should be stored so the agents can read it.

**Follow-up 3**

> how can i add my key to .env

*What was lacking:* Knowing the key goes in `.env` wasn't enough; I needed step-by-step instructions for creating the file and adding the key.

**Follow-up 4**

> I added OPENAI_API_KEY to .env. Do a full run on the tickets.

*What was lacking:* The first prompt asked for the team and the reset rule but not for an actual full run, and the run couldn't start until the key was in place.

**Follow-up 5**

> I replaced the key in .env with a new OpenAI key. Try the full run again.

*What was lacking:* The key from Follow-up 4 was rejected by OpenAI (401), so a working key was needed before the run could start.

**Follow-up 6**

> Here is the web address to the gateway for the key: https://app.portkey.ai/api-keys

*What was lacking:* The earlier prompts didn't say the key was for the Portkey gateway rather than OpenAI directly, so the agents were calling OpenAI with a key OpenAI doesn't accept.

**Follow-up 7**

> The full run finished. Check the results and the database.

*What was lacking:* Follow-up 4 asked for the run but not for the results to be verified against the database afterwards.

**Follow-up 8**

> I pressed Enter and the run is going now. Tell me when it finishes and check the results.

*What was lacking:* The run hadn't actually finished; my name was typed at the first prompt but never submitted with Enter, so no agent had started.

**Follow-up 9**

> I answered the approvals and the run finished. Check the results and the database.

*What was lacking:* The run paused at a purchase-order approval (#3) that Follow-up 8 didn't anticipate, so I had to answer it before the results could be checked.

**Follow-up 10**

> Fix the agent issues you found (payment order, landlord wording, outdated drafts, PO vs cash), then reset and do a second full run so we get a complete run_report.json.

*What was lacking:* The first run showed gaps the original prompts didn't cover: who sets the payment order, how to word a message to the landlord, what to do with outdated drafts, and whether a purchase order is limited by current cash. A runner bug also lost the run report.

**Follow-up 11**

> Run 2 finished and saved output/run_report.json. Check the report and the database.

*What was lacking:* Follow-up 10 asked for the second run but not for its report and database to be checked once it finished.

**Follow-up 12**

> Commit and push Problem 5 to AI-HW5.

*What was lacking:* None of the Problem 5 prompts said to save the agent team, the fixes and the run results to GitHub.

**Follow-up 13**

> Add any tools the agents need to the MCP server so they can work on the open tickets. Shop facts come from the MCP server over data/campus_customs_new.db - do not invent a second shop tools layer that bypasses MCP. Wire the agents so they append to output/audit_trail.json as they run: for each agent-loop step, record enough to audit later. Append to this file, do not wipe it each run. In output/harness.md, list each agent and each MCP tools including the ones we just added along with which table the tool uses. Also add a short safety section with guardrails a business would want plus limits that keep token use in check. Update mcp_server/README.md so the tool list matches what we have now

*What was lacking:* The team had no lasting, step-by-step record of what each agent did (only the per-run report, which is replaced each run), no token limits beyond a request cap, and a few lookups the agents needed (all sizes of a SKU, a lease, past payments, all approval requests) weren't available as MCP tools.

---

## Problem 6: Plan the Three Tickets

### Initial prompt

> Thx. Next is Problem 6: Plan the Three Tickets. Before wiring the backend, write down what we expect the team to do on each open ticket. Build output/desk_tickets.html - a page we can double click with one tab per ticket (101, 102, and 103)> Also add empty Cash and Reflection tabs for later problems, you can leave them blank for now. On each ticket tab, fill an Expected section and leave room for an Actual section we can fill after running the agents. For each ticket's Expected section, write who the Boss should call first and why, all the agent delegations expected, and which MCP tools the run is expected to use

### Follow-up prompts

**Follow-up 1**

> Make the html page easy to read and pretty with a blue and white theme

*What was lacking:* The first prompt described the page's content and tabs but not how it should look, so the first version used a dark navy header with mixed accent colors.

**Follow-up 2**

> Commit and push Problem 6 and the audit/tools changes to AI-HW5.

*What was lacking:* Neither the Problem 6 prompt nor the audit-trail and new-tools prompt said to save the work to GitHub.

---

## Problem 7: Backend Routes

### Initial prompt

> Perfect thx. Next is Problem 7: Backend Routes. In backend/main.py, use FastAPI and add routes that do the following: return the three tickets and whether each is open or resolved, take a ticket id and run the agent team on the ticket, return recent agent events (what each agent said and which tools they used) so the board can refresh, approve a payment or purchase after a human clicks approve (agents only prepare the pay, this route is what actually changes cash), return the current checking balance from cash_accounts, and reset the data base to the original values when I want to try a fresh run. From the backend/ folder, start the server with uvicorn main:app --reload --port 8000. In output/harness.md, list each route in one line (what URL/what it does)

---

## Problem 8: Agent Dashboard

### Initial prompt

> Next is Problem 8: Agent Dashboard. Build frontend dashboard in frontend/ with React + Vite + TypeScript. The page should call the routes we just built and the board should list all three tickets, let me pick one ticket and start the agent team on it, show each agent and what they're saying/doing while the ticket runs, mark a ticket resolved when the run finishes, show a short summary of what each agent did on the ticket, let a human approve a pay or purchase when asked, and show the checking balance (should drop after an approved pay). Make the dashboard pretty and easy to look through, use relaxing warm colors. It can change like the sunrise going to sunset as the ticket process progresses. Tell the front end to talk to the backend at http://localhost:8000. On the backend, allow the Vite page origin (usually http://localhost:5173) so the browser is allowed to call those routes. Start the board with npm run dev. Write output/design.md with what was chosen for the dashboard look (layout, how agents read differently, how resolved tickets and cash show up) and why

### Follow-up prompts

**Follow-up 1**

> Commit and push Problems 7 and 8 to AI-HW5.

*What was lacking:* Neither the Problem 7 nor the Problem 8 prompt said to save the backend routes and the dashboard to GitHub.

---

## Problem 9: Resolve the Tickets

### Initial prompt

> Thx. Problem 9: Resolve the Tickets. Reset the working database data/campus_customs_new.db so we can start clean. Note the checking balance and then run all three tickets on the board (101, 102, 103) until each is resolved. Open output.desk_tickets.html and on each ticket tab, fill the Actual section from this run - which agents worked, what they delegated, and which tools they used. Keep the Expected section and compare the two. On the Cash tab of output/desk_tickets.html, itemize the money: starting checking balance after the reset, for each ticket how the cash changed when the ticket resolved and why, and ending checking balance (must match cash_accounts). Save output/resolved_tickets.json for each ticket (id, final status, short outcome, what each agent contributed, and any human approvals) and output/resolved_board.html (page you can double click with a screenshot of the React board for each resolved ticket). Append real runs to output/audit_trail.json and finish output/harness.md so it covers tables, MCP tools, the five agents, API routes, the dashboard, and safety rules

### Follow-up prompts

**Follow-up 1** (answer to "who should click approve or reject?")

> You approve as Meg

*What was lacking:* The first prompt asked for every ticket to be resolved but didn't say who makes the human approval decisions on the real payments and orders the runs would pause for.

**Follow-up 2**

> Commit and push Problem 9 to AI-HW5.

*What was lacking:* The Problem 9 prompt didn't say to save the resolved-ticket results, pages and fixes to GitHub.

---

## Problem 10: Reflection

### Initial prompt

> Thx. Last is Problem 10: Reflection. Pls fill out this tab with responses to the following questions: how would you evaluate the performance of the agents on each ticket and why? for each ticket, how did Actual compare to the Expected plan written earlier? What would have been simpler as one agent with tools and why? Describe three new problems Campus Customs might face that this agent team could solve with the tools built. Describe three new problems Campus Customs might face that this agent team could not solve and explain the tools and agents you would need to solve them

### Follow-up prompts

**Follow-up 1**

> Commit and push Problem 10 to AI-HW5.

*What was lacking:* The Problem 10 prompt didn't say to save the Reflection tab to GitHub.
