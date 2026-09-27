<div align="center"><img src="../assets/explorer.png" alt="" width="280"/></div>

# What Can It Do?

QuestChain is a general-purpose agent — if you can describe it, your agent can attempt it. Here's what it does well.

---

## Research & web search

Your Explorer agent can search the web and read full pages — not just headlines, but the actual content.

> *"Find the top 5 Python async libraries in 2026 and summarize what each one is best for. Save it to my notes."*

> *"Look up the latest news on Qwen3 and give me a two-paragraph summary."*

> *"Search for tutorials on FastAPI WebSocket authentication and pull out the key steps."*

Powered by [Tavily](https://tavily.com) — set up in one command with `/tavily`.

---

## File management

Your Keeper agent can read, write, edit, search, and organize files on your real filesystem.

> *"Go through all the markdown files in my notes folder and create a summary document."*

> *"Find every file in my project that imports requests and list them."*

> *"Edit config.yaml — change the port from 3000 to 8080."*

It reads files before editing them and confirms before anything destructive.

---

## Coding & development

Your Builder agent delegates programming work to [Claude Code](https://claude.ai/code) — Anthropic's coding agent — giving it full access to your filesystem to implement, test, and ship.

> *"Add input validation to the login form in auth.py."*

> *"Refactor the database connection to use async/await."*

> *"There's a bug where the search returns duplicate results — fix it."*

QuestChain's own Builder agent has been writing its own features and pushing commits to the repo.

---

## Scheduled jobs

Your Scheduler agent can set up recurring tasks that run automatically and report back.

> *"Every morning at 8am, check the weather and send me a summary on Telegram."*

> *"Run a backup of my project folder every night at midnight."*

> *"Every Monday, search for the top AI news from the past week and save it to my notes."*

Use `/cron` to see and manage all scheduled jobs.

---

## Automated jobs

Use the Cron Jobs page or `/cron` to schedule recurring work, choose its agent and timezone, and inspect results. Jobs run while QuestChain is open.

[→ Learn more about Cron Jobs](cron-jobs.md)

---

## Voice output

QuestChain can speak its responses aloud using local text-to-speech — no cloud required. Works in the terminal and sends voice messages on Telegram.

---

## Memory & personality

QuestChain remembers who you are across sessions. Run `/onboard` to teach it your name, what you work on, your preferences, and how you like to communicate. It stores this locally and uses it to personalize every response.

Inspect `profile.md` and `ABOUT.md` in your workspace's `workspace/memory` directory to review the saved profile. Use `/onboard` to update it.

---

## Remote access via Telegram

Once set up, you can talk to your agent from your phone while QuestChain is running on your machine. Agent definitions and saved memory are shared; each Telegram chat has its own conversation history.

[→ Telegram Setup](telegram.md)
