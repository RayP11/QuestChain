<div align="center">

<img src="assets/QuestChain.png" alt="QuestChain" width="400"/>

# Truly Local. Always On.

### Your AI assistant — running on your hardware, working for you around the clock.

[![Python](https://img.shields.io/badge/Python-3.13%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Ollama](https://img.shields.io/badge/Ollama-Local%20LLM-black?logo=ollama&logoColor=white)](https://ollama.com)
[![Stars](https://img.shields.io/github/stars/RayP11/QuestChain?style=flat&color=yellow)](https://github.com/RayP11/QuestChain/stargazers)
[![License](https://img.shields.io/github/license/RayP11/QuestChain)](https://github.com/RayP11/QuestChain/blob/main/LICENSE)

</div>

---

QuestChain is an AI assistant that runs entirely on your machine. No subscriptions, no usage limits, no data leaving your hardware. It remembers who you are, works with your files and terminal, and keeps running in the background — checking your task list, working through the night, sending you updates on Telegram — whether you're at the keyboard or not.

---

## Contents

- [What It Can Do](#what-it-can-do)
- [RPG Progression](#rpg-progression)
- [Local vs. Cloud](#local-vs-cloud)
- [Built for the Edge](#built-for-the-edge)
- [The OpenClaw for Edge AI](#the-openclaw-for-edge-ai)
- [It Codes Itself](#it-codes-itself)
- [The Night Owl](#the-night-owl)
- [Install](#install)
- [Usage](#usage)
- [Terminal Commands](#terminal-commands)
- [Telegram Setup](#telegram-setup)
- [Busy Work](#busy-work)
- [Configuration](#configuration)
- [Model Presets](#model-presets)
- [Project Structure](#project-structure)
- [Built With](#built-with)

---

## What It Can Do

- 🔍 **Web Search & Browse** — Find current information and extract full page content via Tavily *(optional)*
- 📁 **File Operations** — Read, write, edit, list, search files on your real filesystem
- 💻 **Shell Commands** — Run terminal commands and scripts directly
- 🧠 **Planning** — Break down complex tasks into steps with built-in todo tools
- 🖥️ **Self-Coding** — Delegate programming tasks to Claude Code; modify its own codebase *(optional)*
- ⏰ **Cron Jobs** — Schedule recurring tasks that run automatically and report back
- 📱 **Telegram Bot** — Access QuestChain remotely from your phone
- 💾 **Persistent Memory** — Learns your preferences and saves notes across sessions
- 🗣️ **Voice Output** — Speak responses aloud via Kokoro TTS (CLI) or Telegram voice messages
- 🔄 **Busy Work** — Autonomously checks your task list and works in the background on a timer
- 🧩 **Skills** — Extend the agent with Markdown skill files it can load on demand

---

## RPG Progression

QuestChain isn't just a tool — it's a companion you build over time. Every agent starts at Level 1 and earns XP through real work: tool calls, completed tasks, background jobs, and extended conversations. The more your agent works, the stronger it gets.

**How XP is earned:**
- **10 XP per turn** — base award for each conversation exchange
- **+2 XP per tool call** — reading files, searching the web, running commands, writing, planning
- **+20 XP for Claude Code** — delegating a programming task earns a bonus
- **+25 XP per busy-work task** — autonomous background tasks count toward progression

**What you're building toward:**
- **20 levels** — exponential curve; each level is ~1.6× harder than the last
- **21 achievements** — milestones across leveling, tool mastery, and behavior
- **7 agent classes** — each with its own identity, tool loadout, and independent progression

```
──────────── Aria · Lv.3 🔭 Explorer ────────────
❯ find the latest papers on in-context learning

Aria  Lv.3
  > Using tool: web_search
  > Using tool: web_browse
...
⚔  LEVEL UP — Level 4  ·  🔭 Explorer
  ✦ Achievement unlocked: Bibliophile — Read 50 files
```

Use `/level` to see your agent's XP bar, progress to next level, top tools, and full achievement history. Use `/agents` to build a roster — each agent tracks its own progression independently, so your Night Owl and your Architect each have their own story.

### Achievements

21 milestones unlock across three categories:

**Progression** — *First Strike*, *Awakening*, *Seasoned*, *Veteran*, *Legend* (max level)

**Tool Mastery** — *Bibliophile* (50 files read), *Web Walker* (50 searches), *Globe Trotter* (25 pages browsed), *Blacksmith* (25 Claude Code tasks), *Demolition* (50 shell commands), *Archivist* (25 files written), *Grand Planner* (10 task lists written)

**Behavior** — *Polymath* (6 distinct tools used), *Speed Demon* (5+ tools in one turn), *Centurion* (1,000 XP earned), *Busy Bee* (10 background tasks), *Road Runner* (50 background tasks)

### Classes

Pick a class when creating an agent — it sets the tool loadout, identity, and specialty. Each class tracks its own progression independently.

| Class | Icon | Specialty | Tool Preset |
|---|---|---|---|
| Custom | 🌀 | You decide | You configure |
| Sage | 📚 | Files & knowledge | Built-in tools only |
| Explorer | 🔭 | Research & discovery | Web search + browse |
| Architect | ⚒️ | Code & systems | Claude Code |
| Oracle | 🔮 | Planning & strategy | Web search |
| Sentinel | ⏱️ | Automation | Cron scheduler |
| Night Owl | 🌙 | Overnight work | Web search + browse + Claude Code |

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

## Built for the Edge

Most AI agent frameworks are designed around cloud inference — they assume fast APIs, abundant context windows, and predictable latency. QuestChain is built for the opposite: **consumer GPUs, local models, and constrained hardware.**

The engine is a custom Python async loop — no agent framework, no middleware stack. Just the Ollama Python client, `asyncio`, and a tight streaming loop written specifically to get the most out of small local models.

> *"All the power of AI, none of the cloud bills."*

**How it's optimized for edge hardware:**

- **No framework overhead.** The entire agent loop is ~100 lines of plain Python. Stream from Ollama, detect tool calls, execute, loop. No graph execution engines, no serialization layers, nothing between the model and your hardware.

- **Streaming from the first token.** Text tokens are yielded to the UI as they arrive from Ollama. You see output immediately — critical when you can't afford the latency of waiting for a full response before rendering.

- **`<think>` filtering on the stream.** Reasoning models like DeepSeek-R1 and Qwen3 emit `<think>…</think>` blocks before their actual response. QuestChain strips them using a character-level state machine *as the stream arrives* — they never reach the context buffer, never consume your token budget, and never appear in the UI.

- **Per-model context tuning.** Each model preset specifies its own `num_ctx`, `num_predict`, and `temperature`. You're not running an 8B model with a 128k context window it can't fill — context is sized to match the model's actual capacity.

- **Direct GPU and CPU control.** `OLLAMA_NUM_GPU` and `OLLAMA_NUM_THREAD` pass through directly to Ollama's inference options. Pin layers to GPU, pin thread count — no abstraction layer in the way.

- **Approximate token counting, no tokenizer API.** Budget tracking uses `chars / 4` — a fast local approximation with no round-trip to the model. Context compaction triggers automatically before the window fills up.

- **Auto-compaction via the model itself.** When context gets tight, QuestChain keeps the 6 most recent messages and uses the model to summarise everything older into a single block. The summary replaces the raw history in the JSONL file — reclaiming space while preserving what matters.

- **Parallel tool execution.** When the model issues multiple tool calls in one turn, they run concurrently via `asyncio.gather`. File reads, web searches, and shell commands that don't depend on each other don't wait in line.

- **Plain JSONL history, no database.** Conversation history is stored as one JSON object per line in `~/.questchain/sessions/`. Human-readable, zero-dependency, trivially debuggable.

---

## The OpenClaw for Edge AI

Think of QuestChain as the [OpenClaw](https://github.com/openclaw/openclaw) for edge AI models. OpenClaw is a popular framework built around cloud-scale models and large context windows — it's powerful, but it requires 20B+ parameters and 16K+ token context to run reliably. QuestChain brings that same agentic capability down to the hardware most people actually own, running reliably on models as small as **3B parameters**.

The difference is architectural. Cloud-oriented agents carry heavy overhead by design: system prompts in the thousands of tokens, workspace files injected upfront, and tool calling formats built for models with vast context. QuestChain strips all of that away — a 458 character system prompt, Ollama's native tool protocol, lazy-loaded skills, and a token budget that auto-compacts before it ever fills up. The result is a full agentic loop that works on a laptop GPU, a Raspberry Pi, or anything in between.

Here's what makes it efficient:

- **458 character system prompt.** ~115 tokens. Every token in the system prompt repeats on every turn, so keeping it small compounds over long sessions. A 3B model holds it completely without degradation.

- **Ollama native tool calling.** QuestChain uses Ollama's native Python client directly, keeping tool calls on the native protocol where they work reliably at any model size.

- **Lazy skill loading.** Each skill adds only its name and a one-line description (~24 tokens) to the system prompt. Full content is fetched only when the agent calls for it. A large skill library costs almost nothing at inference time.

- **Token-budgeted context with auto-compaction.** Context is tracked with an explicit token budget tuned per model. When it fills up, QuestChain keeps the 6 most recent messages verbatim and uses the model to summarize everything older into a single block — context stays bounded without losing recent work.

- **No sub-agents, no orchestration overhead.** QuestChain is a single loop: stream from Ollama, detect tool calls, execute in parallel, repeat. Nothing between you and your hardware.

**Fully local by default — optionally connected.** The core works 100% offline with no external accounts required. Two optional integrations let local agents reach further when you want them to: [Tavily](https://tavily.com) for live web search and full-page extraction, and [Claude Code](https://claude.ai/code) for delegating complex coding tasks to Anthropic's CLI agent. Both are opt-in, set up with a single `/tavily` or `/claudecode` command inside QuestChain, and only activate when explicitly called.

---

## It Codes Itself

<p align="center"><img src="assets/QuestChain%20coding.png" alt="QuestChain coding itself with Claude Code" width="380"/></p>

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

## The Night Owl

<p align="center"><img src="assets/Overnight%20Worker%20Quest.png" alt="Night Owl overnight worker agent" width="380"/></p>

Switch to the **Night Owl** agent and it works while you sleep. Every 30 minutes between midnight and 6 AM, it reads your `overnight.md` task file and gets to work — researching topics, writing reports, running code — then logs what it did before going quiet.

When you first activate the Night Owl, it walks you through a short setup: what topics to research each night, what standing tasks to prepare for you each morning, and anything else you want done in the background. It generates a structured `overnight.md` from your answers and runs from it every night.

Add one-off tasks at any time with `/overnight` — type the command, enter your task, and it gets queued for tonight.

---

## Install

One command. The installer handles everything: Ollama, Python, uv, QuestChain, and the default model.

**Windows** — open PowerShell and run:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/RayP11/QuestChain/main/install.ps1 | iex"
```

**macOS / Linux** — open a terminal and run:

```bash
curl -fsSL https://raw.githubusercontent.com/RayP11/QuestChain/main/install.sh | bash
```

> **macOS note:** Ollama is installed via [Homebrew](https://brew.sh). If you don't have Homebrew, install it first or download Ollama manually from [ollama.com](https://ollama.com/download).

What gets installed:
- **Ollama** — local LLM runtime
- **Python 3.13** — if not already installed (Windows only; uv manages Python on Mac/Linux)
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
| `/stats` | Show agent level, XP bar, top tools, and achievements |
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
│   ├── agents.py           Agent profiles — classes, presets, persistence
│   ├── progression.py      XP, levels, achievements per agent
│   ├── config.py           Settings, model presets, paths
│   ├── telegram.py         Telegram bot adapter
│   ├── scheduler.py        Cron job runner
│   ├── busy_work.py        Background autonomous work loop
│   ├── onboarding.py       First-run onboarding flow
│   ├── engine/             Custom Python async agent runtime
│   │   ├── agent.py        Core stream→tools→stream loop
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

- **Custom async agent engine** — purpose-built for edge AI; lightweight, streaming, parallel tool execution
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
<sub>No cloud. No cost. No compromise. Small but mighty — send your hardware on a quest.</sub>
<br><br>
<sub>If QuestChain is meaningful to you, a ⭐ helps others find it.</sub>
</div>
