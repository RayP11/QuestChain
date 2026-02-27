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

### A self-improving AI agent — built for edge hardware, running entirely on-device.

[![Python](https://img.shields.io/badge/Python-3.13%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Ollama](https://img.shields.io/badge/Ollama-Local%20LLM-black?logo=ollama&logoColor=white)](https://ollama.com)
[![Custom Engine](https://img.shields.io/badge/Engine-Custom%20Async%20ReAct-orange)]()
[![Runs Locally](https://img.shields.io/badge/Runs-100%25%20Locally-brightgreen?logo=homeassistant&logoColor=white)]()
[![No Cloud](https://img.shields.io/badge/No%20Cloud-No%20Cost-success)]()

</div>

---

## Built for the Edge

Most AI agent frameworks are designed around cloud inference — they assume fast APIs, abundant context windows, and predictable latency. QuestChain is built for the opposite: **consumer GPUs, local models, and constrained hardware.**

The core engine is a custom async ReAct loop written from scratch to be lightweight and efficient. No heavy framework dependencies, no unnecessary overhead. Just a tight plan-act-observe cycle tuned to get the most out of small, fast local models like Qwen3 and DeepSeek.

> *"All the power of AI, none of the cloud bills."*

**What "edge-optimized" means in practice:**
- A **custom async streaming engine** — not a general-purpose framework bolted onto a local model. Every design decision prioritizes low overhead and responsiveness on modest hardware.
- **Token budget management** — context is compacted automatically so long-running sessions don't balloon memory usage.
- **Lazy skill loading** — the system prompt stays short (~550 chars). Full skill content is only loaded into context when the agent actually needs it.
- **`<think>` tag filtering** — reasoning traces from models like DeepSeek-R1 and Qwen3 are stripped before they reach the token budget, keeping responses clean and context lean.
- **Parallel tool execution** — independent tool calls run concurrently, cutting wall-clock latency significantly on tasks that touch multiple tools.

---

## It Codes Itself

QuestChain has a `claude_code` tool that delegates programming tasks to Claude Code — Anthropic's AI coding agent running locally in your terminal. QuestChain uses this tool to develop its own codebase.

When QuestChain identifies a bug, wants a new feature, or needs to refactor something, it can hand off a coding task to Claude Code with full filesystem access, then review the result. This has already happened: features in QuestChain's codebase were written by QuestChain itself, using Claude Code as its hands.

This creates a feedback loop where the agent's own capabilities improve over time — without you writing a line of code.

```
  You: "add a command that summarizes my TASKS.md"
     ↓
  QuestChain reasons about what needs to change
     ↓
  Calls claude_code("add /summary command to cli.py that reads TASKS.md...")
     ↓
  Claude Code edits the files, runs tests, commits
     ↓
  QuestChain reviews the result and reports back
```

---

## Why QuestChain?

Most AI assistants send your conversations to the cloud, charge per token, and forget everything the moment you close the tab. QuestChain is different.

QuestChain runs entirely on your own hardware using [Ollama](https://ollama.com). Your data never leaves your machine. No API bills, no rate limits, no terms-of-service watching your messages. It works offline. It's yours.

And it's not a chatbot. QuestChain is a full **agentic loop** — it can search the web, read and write files, execute shell commands, schedule recurring tasks, send you Telegram messages, and work autonomously in the background while you focus on something else.

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
| **Self-improvement** | Codes its own codebase | ❌ |

---

## What It Can Do

- 🔍 **Web Search & Browse** — Find current information and extract full page content via Tavily
- 📁 **File Operations** — Read, write, edit, list, search files on your real filesystem
- 💻 **Shell Commands** — Run terminal commands and scripts directly
- 🧠 **Planning** — Break down complex tasks into steps with built-in todo tools
- 🖥️ **Self-Coding** — Delegate programming tasks to Claude Code; modify its own codebase
- ⏰ **Cron Jobs** — Schedule recurring tasks that run automatically and report back
- 📱 **Telegram Bot** — Access QuestChain remotely from your phone
- 💾 **Persistent Memory** — Learns your preferences and saves notes across sessions
- 🗣️ **Voice Output** — Speak responses aloud via Kokoro TTS (CLI) or Telegram voice messages
- 🔄 **Busy Work** — Autonomously checks your task list and works in the background on a timer
- 🧩 **Skills** — Extend the agent with Markdown skill files it can load on demand

---

## How It Works

```
                     ┌─────────────────────────────────────┐
      You type       │            QuestChain                │
  ────────────────▶  │                                      │
  (CLI or Telegram)  │  ┌─────────────────────────────┐    │
                     │  │   Custom Async ReAct Engine  │    │
                     │  │                             │    │    ┌─────────────┐
                     │  │  think → act → observe      │◀───┼───▶│   Ollama    │
                     │  │  (streaming, parallel tools) │    │    │  (on-device)│
                     │  └──────────────┬──────────────┘    │    └─────────────┘
                     │                 │                    │
                     │        ┌────────┴────────┐           │
                     │        ▼                 ▼           │
                     │   ┌─────────┐     ┌──────────────┐  │
                     │   │  Tools  │     │   Context    │  │
                     │   │         │     │              │  │
                     │   │ • files │     │ JSONL history│  │
                     │   │ • shell │     │ token budget │  │
                     │   │ • web   │     │ compaction   │  │
                     │   │ • cron  │     └──────────────┘  │
                     │   │ • claude│                        │
                     │   │   _code │                        │
                     │   └─────────┘                        │
                     └─────────────────────────────────────┘
```

The engine runs a **think → act → observe** loop. It streams tokens from Ollama, detects tool calls in real time, executes them (in parallel where possible), and feeds results back into the next iteration. Conversation history is stored as human-readable JSONL, compacted automatically when it approaches the token budget.

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
| `/agents` | Manage agent profiles (list, switch, create, edit) |
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
questchain start --busy-work 30
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
| `QUESTCHAIN_DATA_DIR` | `~/.questchain` | Session history, cron jobs |
| `QUESTCHAIN_WORKSPACE_DIR` | Project root | Workspace and memory root |

---

## Model Presets

Any Ollama model works. These are pre-tuned for the best agentic experience on edge hardware:

| Model | VRAM | Notes |
|---|---|---|
| `qwen3:8b` | ~6 GB | **Default** — Fast, excellent tool calling, native thinking |
| `qwen2.5:7b-instruct` | ~6 GB | Top-tier tool calling |
| `qwen2.5:14b-instruct` | ~10 GB | More capable |
| `llama3.1:8b-instruct` | ~6 GB | Strong tool calling (BFCL 77-81%) |
| `llama3.3:8b-instruct` | ~6 GB | Newer Llama, strong tool use |
| `mistral:7b` | ~5 GB | Fast, low resource |
| `mistral-nemo:12b` | ~8 GB | Stronger Mistral variant |
| `dolphin3:latest` | ~6 GB | Uncensored, good for agents |
| `deepseek-r1:7b` | ~6 GB | Strong reasoning, `<think>` filtered automatically |
| `deepseek-r1:14b` | ~10 GB | Stronger reasoning |
| `deepseek-coder-v2:16b` | ~12 GB | Best local code generation |

```bash
questchain start --list-models   # see all presets with descriptions
questchain start -m <any-model>  # use any model installed in Ollama
```

---

## Project Structure

```
(project root)/
├── questchain/
│   ├── __main__.py         Entry point
│   ├── cli.py              Terminal UI and REPL loop
│   ├── agent.py            Agent factory — wires engine together
│   ├── config.py           Settings, model presets, paths
│   ├── telegram.py         Telegram bot adapter
│   ├── scheduler.py        Cron job runner
│   ├── busy_work.py        Background autonomous work loop
│   ├── onboarding.py       First-run onboarding flow
│   ├── engine/             Custom async ReAct runtime
│   │   ├── agent.py        Core think→act→observe loop
│   │   ├── model.py        OllamaModel: streaming + <think> filtering
│   │   ├── tools.py        ToolRegistry, @tool decorator, parallel exec
│   │   ├── context.py      JSONL history, token budget, compaction
│   │   ├── skills.py       Lazy skill loader
│   │   └── builtins/       filesystem, shell, planning tools
│   ├── tools/
│   │   ├── web_search.py   Tavily search
│   │   ├── web_browse.py   Tavily page extract
│   │   ├── claude_code.py  Delegate coding tasks to Claude Code
│   │   ├── cron.py         Cron management tools
│   │   └── speak.py        Kokoro TTS voice output
│   └── memory/
│       └── store.py        Thread history shim
├── skills/                 Agent skill definitions (Markdown)
└── workspace/
    ├── TASKS.md            Drop tasks here for busy work
    └── memory/
        ├── ABOUT.md        Your profile (written during onboarding)
        └── AGENTS.md       Agent's own persistent notes
```

---

## Built With

<div align="center">

[![Ollama](https://img.shields.io/badge/Ollama-Local%20Inference-black?logo=ollama&logoColor=white&style=for-the-badge)](https://ollama.com)
[![Tavily](https://img.shields.io/badge/Tavily-Web%20Search-blue?style=for-the-badge)](https://tavily.com)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-Self%20Coding-orange?style=for-the-badge)](https://claude.ai/code)
[![Telegram](https://img.shields.io/badge/Telegram-Bot%20API-26A5E4?logo=telegram&logoColor=white&style=for-the-badge)](https://core.telegram.org/bots)
[![Rich](https://img.shields.io/badge/Rich-Terminal%20UI-purple?style=for-the-badge)](https://github.com/Textualize/rich)

</div>

- **Custom async ReAct engine** — purpose-built for edge AI; lightweight, streaming, parallel tool execution
- **[Ollama](https://ollama.com)** — Run any open-weight LLM locally with one command
- **[Claude Code](https://claude.ai/code)** — Anthropic's coding agent; QuestChain delegates programming tasks to it
- **[Tavily](https://tavily.com)** — Web search and full-page extraction API
- **[python-telegram-bot](https://python-telegram-bot.org)** — Telegram bot SDK
- **[APScheduler](https://apscheduler.readthedocs.io)** — Async cron job scheduling
- **[Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx)** — Fast local text-to-speech
- **[Rich](https://github.com/Textualize/rich)** — Beautiful terminal output
- **[prompt-toolkit](https://python-prompt-toolkit.readthedocs.io)** — Interactive terminal input with history

---

<div align="center">
<sub>No cloud. No cost. No compromise. And it's getting smarter on its own.</sub>
</div>
