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
| `/stats` | Show agent metrics: prompts, tokens, errors |
| `/level` | Show agent level, XP, top tools, and achievements |
| `/prestige` | Prestige reset; requires Level 20 |
| `/model` | Change the global default model; restart to apply |
| `/tools` | Show the selected agent’s configured tools |
| `/legacy [migrate ID]` | List archived agents or explicitly migrate one |
| `/history` | Resume new conversations or read legacy transcripts |
| `/runs` | List this conversation’s saved runs |
| `/retry [run ID]` | Retry the last run or a specified run in this conversation |
| `/cancel [run ID]` | Cancel queued or running work in this conversation |
| `/cron` | Open the cron manager — create, edit, run, pause, resume, or delete jobs |
| `/tavily` | Set up web search (free Tavily API key) |
| `/claudecode` | Set up Claude Code CLI integration |
| `/telegram` | Set up Telegram remote access |
| `/speak` | Set up Kokoro TTS voice output |
| `/onboard` | Re-run the setup conversation |
| `/exit` | Exit QuestChain |
| **Ctrl+C** / **Ctrl+D** | Exit QuestChain |

---

## Tips

**Switching agents mid-conversation:** Use `/agents` to pick a different agent. Each one has its own focus, tools, and history.

**Resuming a conversation:** Use `/history` to select a saved terminal conversation. Its full thread ID appears when you select it; pass that ID with `-t <id>` at startup to resume it directly. `/new` starts fresh without deleting the saved history.

**Changing models:** Use `/model` to choose the saved default and optionally clear per-agent overrides. Restart QuestChain to apply the new default to the active session. Telegram's `/model` reports the selected agent's current model; it does not change it.

See [Your Agents](agent-classes.md) for coordinator routing, custom-agent fields, and optional legacy migration.
