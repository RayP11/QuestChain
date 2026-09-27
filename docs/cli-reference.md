<div align="center"><img src="../assets/sage1.png" alt="" width="280"/></div>

# Command Guide

## Starting QuestChain

```bash
questchain start --web                  # Start with web UI (recommended)
questchain start --web -m qwen3:4b      # Use a lighter model
questchain start -t <thread-id>         # Resume a specific conversation
```

Once running, open **[http://127.0.0.1:8765](http://127.0.0.1:8765)** in your browser.

---

## In-app commands

Type these in the terminal. Use the web Cron Jobs page for browser automation management.

| Command | What it does |
|---|---|
| `/help` | Show all available commands |
| `/new` | Start a fresh conversation |
| `/agents` | Switch agents, create a new one, or edit existing ones |
| `/stats` | See your agent's level, XP, top tools, and achievements |
| `/memory` | View your saved user profile (what QuestChain knows about you) |
| `/model` | Show the current model and switch to a different one |
| `/tools` | Show the selected agent’s configured tools |
| `/legacy [migrate ID]` | List archived agents or explicitly migrate one |
| `/history` | Resume new conversations or read legacy transcripts |
| `/runs` | List this conversation’s saved runs |
| `/retry [run ID]` | Retry a task as a new attempt |
| `/cancel [run ID]` | Cancel queued or running work in this conversation |
| `/cron` | Open the cron manager — create, edit, run, pause, resume, or delete jobs |
| `/instructions` | View your agent's current personality and rules |
| `/tavily` | Set up web search (free Tavily API key) |
| `/telegram` | Set up Telegram remote access |
| `/onboard` | Re-run the setup conversation |
| `/thread` | Show the current conversation ID |
| **Ctrl+D** | Exit |

---

## Tips

**Switching agents mid-conversation:** Use `/agents` to pick a different agent. Each one has its own focus, tools, and history.

**Resuming a conversation:** Every conversation has a thread ID (shown with `/thread`). Pass it with `-t <id>` at startup to pick up exactly where you left off.

**Changing models on the fly:** Use `/model` to see what's available and switch without restarting.

See [Your Agents](agent-classes.md) for coordinator routing, custom-agent fields, and optional legacy migration.
