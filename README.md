<div align="center">

```
  ██████╗ ██╗   ██╗███████╗███████╗████████╗
 ██╔═══██╗██║   ██║██╔════╝██╔════╝╚══██╔══╝
 ██║   ██║██║   ██║█████╗  ███████╗   ██║
 ██║▄▄ ██║██║   ██║██╔══╝  ╚════██║   ██║
 ╚██████╔╝╚██████╔╝███████╗███████║   ██║
  ╚══▀▀═╝  ╚═════╝ ╚══════╝╚══════╝   ╚═╝
  ██████╗██╗  ██╗ █████╗ ██╗███╗   ██╗
 ██╔════╝██║  ██║██╔══██╗██║████╗  ██║
 ██║     ███████║███████║██║██╔██╗ ██║
 ██║     ██╔══██║██╔══██║██║██║╚██╗██║
 ╚██████╗██║  ██║██║  ██║██║██║ ╚████║
  ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝
```

### Your personal AI agent — fully local, fully private, fully capable.

[![Python](https://img.shields.io/badge/Python-3.13%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Ollama](https://img.shields.io/badge/Ollama-Local%20LLM-black?logo=ollama&logoColor=white)](https://ollama.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-Deep%20Agents-1C3C3C?logo=langchain&logoColor=white)](https://github.com/langchain-ai/deepagents)
[![Runs Locally](https://img.shields.io/badge/Runs-100%25%20Locally-brightgreen?logo=homeassistant&logoColor=white)]()
[![No Cloud](https://img.shields.io/badge/No%20Cloud-No%20Cost-success)]()

</div>

---

## Why QuestChain?

Most AI assistants send your conversations to the cloud, charge per token, and forget everything the moment you close the tab. **QuestChain is different.**

QuestChain runs entirely on your own hardware using [Ollama](https://ollama.com). Your data never leaves your machine. There are no API bills, no rate limits, no terms-of-service watching your every message. It works offline. It's yours.

And it's not a chatbot. QuestChain is a full **agentic loop** — it can search the web, read and write files, execute shell commands, schedule recurring tasks, send you Telegram messages, and work autonomously in the background while you focus on something else.

> *"All the power of AI, none of the cloud bills."*

---

## Local vs. Cloud

| | QuestChain | Cloud AI |
|---|---|---|
| **Your data** | Stays on your machine | Sent to third-party servers |
| **Cost** | $0 after hardware | $/token or subscription |
| **Works offline** | ✅ | ❌ |
| **File & shell access** | Full, real filesystem | Sandboxed or unavailable |
| **Memory** | Persistent across sessions | Usually resets every chat |
| **Autonomous tasks** | Background busy work loop | Manual only |
| **Remote access** | Built-in Telegram bot | Separate product |
| **Model choice** | Any Ollama model | Locked to provider |

---

## What It Can Do

- 🔍 **Web Search & Browse** — Find current information and extract full page content via Tavily
- 📁 **File Operations** — Read, write, edit, list, search files on your real filesystem
- 💻 **Shell Commands** — Run terminal commands and scripts directly
- 🧠 **Planning** — Break down complex tasks into steps with built-in todo tools
- 🤖 **Sub-agents** — Delegate subtasks to focused child agents
- 🖥️ **Code with Claude** — Delegate coding tasks to Claude Code with configurable complexity
- ⏰ **Cron Jobs** — Schedule recurring tasks that run automatically and report back
- 📱 **Telegram Bot** — Access QuestChain remotely from your phone
- 💾 **Persistent Memory** — Learns your preferences and saves notes across sessions
- 🗣️ **Voice Output** — Speak responses aloud via Kokoro TTS (CLI) or Telegram voice messages
- 🔄 **Busy Work** — Autonomously checks your task list and works in the background on a timer

---

## How It Works

```
                     ┌──────────────────────────────┐
      You type       │          QuestChain           │
  ────────────────▶  │                               │
  (CLI or Telegram)  │  ┌────────────────────────┐  │
                     │  │  LangGraph             │  │
                     │  │  Deep Agent Loop       │  │    ┌─────────────┐
                     │  │                        │◀─┼───▶│   Ollama    │
                     │  │  plan → act → review   │  │    │  (on-device)│
                     │  └──────────┬─────────────┘  │    └─────────────┘
                     │             │                 │
                     │      ┌──────┴──────┐          │
                     │      ▼             ▼          │
                     │  ┌──────┐   ┌──────────┐     │
                     │  │Tools │   │ Memory   │     │
                     │  │      │   │          │     │
                     │  │ • ls │   │ ABOUT.md │     │
                     │  │ • sh │   │ AGENTS.md│     │
                     │  │ • web│   │ SQLite   │     │
                     │  └──────┘   └──────────┘     │
                     └──────────────────────────────┘
```

The agent runs a **plan → act → review** loop. It can call as many tools as it needs before giving you a final answer. Every conversation is checkpointed to SQLite so you can pick up exactly where you left off.

---

## Install

Open **PowerShell** and run:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/RayP11/QuestChain/main/install.ps1 | iex"
```

That's it. The installer handles everything automatically:
- **Ollama** — local LLM runtime
- **Python 3.13** — if not already installed
- **uv** — fast Python package manager
- **QuestChain** — installed and added to PATH
- **qwen3:8b** — default model pulled and ready

Takes ~5–10 minutes depending on your internet speed (the model download is the slow part).

Then run:

```
questchain start
```

On first run, QuestChain walks you through a short onboarding conversation and optionally sets up Telegram. After that, it remembers who you are.

> **Web search (optional):** Run `/tavily` inside QuestChain to set up your free [Tavily API key](https://tavily.com) and enable web search and browsing.

---

## Usage

```bash
# Start QuestChain
questchain start

# Use a specific model
questchain start -m qwen2.5:14b-instruct

# Resume a previous conversation by thread ID
questchain start -t <thread-id>

# Run without persistent memory
questchain start --no-memory

# Set the busy work interval (minutes)
questchain start --busy-work 30

# Disable background busy work
questchain start --no-busy-work

# List available model presets
questchain start --list-models
```

---

## Terminal Commands

| Command | Description |
|---|---|
| `/help` | Show all available commands |
| `/new` | Start a fresh conversation |
| `/model` | Show current model and list available ones |
| `/thread` | Show current conversation thread ID |
| `/busy` | Show busy work scheduler status |
| `/tools` | List all available agent tools |
| `/instructions` | Show the agent's system prompt |
| `/memory` | Show your saved user profile |
| `/tasks` | Show the current workspace task list |
| `/cron` | List scheduled cron jobs |
| `/onboard` | Re-run the onboarding conversation |
| `/tavily` | Set up Tavily web search API key |
| `/telegram` | Set up Telegram bot credentials |
| `/clear` | Clear the screen |
| **Ctrl+D** | Exit QuestChain |

---

## Telegram Setup

QuestChain runs alongside the CLI as a Telegram bot, giving you remote access from your phone.

Run `/telegram` inside QuestChain and it walks you through the setup:

1. Message [@BotFather](https://t.me/botfather) on Telegram → `/newbot` → copy the token
2. Message [@userinfobot](https://t.me/userinfobot) → copy your numeric user ID
3. Paste both into the `/telegram` wizard — credentials are saved automatically

Restart QuestChain and the bot starts alongside the CLI. The same conversation thread and memory is shared between CLI and Telegram — switch between them mid-conversation.

---

## Busy Work

QuestChain can work autonomously in the background on a timer. Drop tasks into `workspace/TASKS.md`:

```markdown
- [ ] Research the latest news on quantum computing and summarize key developments
- [ ] Check if any of my Python packages have available updates
- [ ] Draft a weekly status email based on my recent work
```

QuestChain picks up one task per tick, completes it using all its tools, marks it done, and sends you a summary — in the terminal and on Telegram if configured.

```bash
# Run with a 30-minute busy work interval
python -m questchain --busy-work 30
```

---

## Configuration

All settings via environment variables or a `.env` file in the project root:

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_MODEL` | `qwen3:8b` | Default model to use |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_NUM_GPU` | *(auto)* | GPU layers to offload (`-1` = all) |
| `OLLAMA_NUM_THREAD` | *(auto)* | CPU threads for inference |
| `TAVILY_API_KEY` | — | Web search API key (free tier at tavily.com) |
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token |
| `TELEGRAM_OWNER_ID` | — | Your Telegram user ID (access control) |
| `QUESTCHAIN_DATA_DIR` | `~/.questchain` | Checkpoints, history, cron jobs |
| `QUESTCHAIN_WORKSPACE_DIR` | Project root | Workspace and memory root |
| `QUESTCHAIN_RESPONSE_CACHE` | `false` | Cache identical LLM responses to SQLite |

---

## Model Presets

Any Ollama model works. These are pre-tuned for the best agentic experience:

| Model | VRAM | Notes |
|---|---|---|
| `qwen3:8b` | ~6 GB | **Default** — Fast, excellent tool calling |
| `qwen2.5:7b-instruct` | ~6 GB | Top-tier tool calling |
| `qwen2.5:14b-instruct` | ~10 GB | More capable |
| `llama3.1:8b-instruct` | ~6 GB | Strong tool calling (BFCL 77-81%) |
| `llama3.3:8b-instruct` | ~6 GB | Newer Llama, strong tool use |
| `mistral:7b` | ~5 GB | Fast, low resource |
| `mistral-nemo:12b` | ~8 GB | Stronger Mistral variant |
| `dolphin3:latest` | ~6 GB | Uncensored, good for agents |
| `deepseek-r1:7b` | ~6 GB | Strong reasoning |
| `deepseek-r1:14b` | ~10 GB | Stronger reasoning |
| `deepseek-coder-v2:16b` | ~12 GB | Best local code generation |

```bash
python -m questchain --list-models   # see all presets with descriptions
python -m questchain -m <any-model>  # use any model installed in Ollama
```

---

## Project Structure

```
(project root)/
├── questchain/
│   ├── __main__.py         Entry point
│   ├── cli.py              Terminal UI and REPL loop
│   ├── agent.py            LangGraph agent wiring and system prompt
│   ├── config.py           Settings, model presets, paths
│   ├── models.py           ChatOllama setup and helpers
│   ├── telegram.py         Telegram bot adapter
│   ├── scheduler.py        Cron job runner
│   ├── busy_work.py        Background autonomous work loop
│   ├── onboarding.py       First-run onboarding flow
│   ├── tools/
│   │   ├── web_search.py   Tavily search
│   │   ├── web_browse.py   Tavily page extract
│   │   ├── claude_code.py  Claude Code delegation
│   │   ├── cron.py         Cron management tools
│   │   └── speak.py        Kokoro TTS voice output
│   └── memory/
│       └── store.py        SQLite checkpointer + memory store
├── skills/                 Agent skill definitions
└── workspace/
    ├── TASKS.md            Drop tasks here for busy work
    └── memory/
        ├── ABOUT.md        Your profile (written during onboarding)
        └── AGENTS.md       Agent's own persistent notes
```

---

## Built With

<div align="center">

[![LangGraph](https://img.shields.io/badge/LangGraph-Deep%20Agents-1C3C3C?logo=langchain&logoColor=white&style=for-the-badge)](https://github.com/langchain-ai/deepagents)
[![Ollama](https://img.shields.io/badge/Ollama-Local%20Inference-black?logo=ollama&logoColor=white&style=for-the-badge)](https://ollama.com)
[![Tavily](https://img.shields.io/badge/Tavily-Web%20Search-blue?style=for-the-badge)](https://tavily.com)
[![Telegram](https://img.shields.io/badge/Telegram-Bot%20API-26A5E4?logo=telegram&logoColor=white&style=for-the-badge)](https://core.telegram.org/bots)
[![Rich](https://img.shields.io/badge/Rich-Terminal%20UI-purple?style=for-the-badge)](https://github.com/Textualize/rich)
[![SQLite](https://img.shields.io/badge/SQLite-Persistence-003B57?logo=sqlite&logoColor=white&style=for-the-badge)](https://sqlite.org)

</div>

- **[LangGraph Deep Agents](https://github.com/langchain-ai/deepagents)** — Agentic loop with planning, filesystem, sub-agents, skills, and memory middleware
- **[Ollama](https://ollama.com)** — Run any open-weight LLM locally with one command
- **[Tavily](https://tavily.com)** — Web search and full-page extraction API
- **[python-telegram-bot](https://python-telegram-bot.org)** — Telegram bot SDK
- **[APScheduler](https://apscheduler.readthedocs.io)** — Async cron job scheduling
- **[Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx)** — Fast local text-to-speech
- **[Rich](https://github.com/Textualize/rich)** — Beautiful terminal output
- **[prompt-toolkit](https://python-prompt-toolkit.readthedocs.io)** — Interactive terminal input with history

---

<div align="center">
<sub>No cloud. No cost. No compromise.</sub>
</div>
