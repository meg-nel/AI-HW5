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
