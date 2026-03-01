<div align="center">

<img src="assets/QuestChain.png" alt="QuestChain" width="400"/>

# Truly Local. Always On. Ready for Quests.

### Your AI assistant — running on your hardware, working for you around the clock.

[![Python](https://img.shields.io/badge/Python-3.13%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Ollama](https://img.shields.io/badge/Ollama-Local%20LLM-black?logo=ollama&logoColor=white)](https://ollama.com)
[![License](https://img.shields.io/badge/License-MIT-green)](https://github.com/RayP11/QuestChain/blob/master/LICENSE)

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

**How the experience works:**
- **20 levels** — exponential curve; each level is ~1.6× harder than the last
- **21 achievements** — milestones across leveling, tool mastery, and behavior
- **7 agent classes** — each with its own identity, tool loadout, and independent progression

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

Most AI tools assume cloud infrastructure — fast servers, huge memory, unlimited compute. QuestChain runs on the hardware you already own.

> *"All the power of AI, none of the cloud bills."*

The engine is purpose-built for small models and constrained hardware:

- **No bloat.** The entire agent loop is ~100 lines of Python — no framework overhead, nothing between the model and your machine.
- **Context is managed automatically.** Each model runs with a tuned memory budget. When it fills up, QuestChain summarizes older conversation into a single block and keeps going — no crashes, no cutoffs.
- **Tools run in parallel.** When the agent needs to search the web, read a file, and run a command at once, it does all three simultaneously.

---

## The OpenClaw for Edge AI

Most AI agent frameworks are built for cloud servers — large models, massive memory, always-online. QuestChain delivers the same agentic capability on hardware you already own, running reliably on models as small as **3B parameters**.

It's faster because it's lean — no framework overhead, no bloated prompts, no unnecessary round-trips. Your data never leaves your machine, so there's nothing to intercept. Because the whole stack is local and open, you stay in control with no accounts or API keys required to get started.

Want to go further? Two optional integrations are a single command away: [Tavily](https://tavily.com) for live web search, and [Claude Code](https://claude.ai/code) for delegating coding tasks. Both are opt-in and only activate when you call them.

---

## It Codes Itself

QuestChain can delegate programming tasks to [Claude Code](https://claude.ai/code) — Anthropic's coding agent — with full access to your filesystem. It uses this to develop its own codebase: describe a bug or feature, and QuestChain hands it off, reviews the result, and reports back. Features in QuestChain were written by QuestChain itself.

This creates a loop where the agent improves over time without you writing a line of code.

> **No Claude Code?** Run a local coder model instead — `deepseek-coder-v2:16b` for maximum capability, or `qwen2.5-coder:7b` for a lighter option.

---

## The Night Owl

The **Night Owl** is a prepackaged agent built to work while you sleep. Every 30 minutes between midnight and 6 AM, it reads your `overnight.md` task file and gets to work — researching topics, writing reports, running code — then logs what it did before going quiet.

When you first activate the Night Owl, it walks you through a short setup: what topics to research each night, what standing tasks to prepare for you each morning, and anything else you want done in the background. It generates a structured `overnight.md` from your answers and runs from it every night.

Add one-off tasks at any time with `/overnight` — type the command, enter your task, and it gets queued for tonight.

---

## Install

### Step 1 — Install Ollama

Download and install Ollama from [ollama.com/download](https://ollama.com/download), then start it:

```bash
ollama serve
```

Leave it running, then open a new terminal for the next step.

### Step 2 — Install QuestChain

**Windows** — open PowerShell and run:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/RayP11/QuestChain/main/install.ps1 | iex"
```

**macOS / Linux** — open a terminal and run:

```bash
curl -fsSL https://raw.githubusercontent.com/RayP11/QuestChain/main/install.sh | bash
```

What gets installed:
- **Python 3.13** — if not already installed (Windows only; uv manages Python on Mac/Linux)
- **uv** — fast Python package manager
- **QuestChain** — installed and added to PATH
- **qwen3:8b** — default model pulled and ready

Takes ~5 minutes depending on your internet speed (the model download is the slow part).

### Step 3 — Run

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

## Autonomous Work

QuestChain can work autonomously in the background on a timer. Every 60 minutes (configurable), it reads `workspace/HEARTBEAT.md` and acts on anything that needs attention. If nothing does, it stays silent.

`HEARTBEAT.md` is a plain Markdown file — write whatever standing tasks or instructions you want the agent to follow each tick:

```markdown
# HEARTBEAT.md

- **Research**: Check for new developments in AI tooling and log findings to workspace/notes.md
- **Maintenance**: Scan for broken links or stale entries in ABOUT.md
- **Prep**: Draft a morning briefing from recent news and save to workspace/briefing.md
```

The agent interprets the file, uses all its tools to complete what needs doing, and sends you a summary in the terminal and on Telegram if configured. It stays silent if there's nothing to act on.

```bash
# Run with a custom interval (minutes)
questchain start --busy-work 30

# Disable background work entirely
questchain start --no-busy-work
```

Use `/busy` to check scheduler status and `/tasks` to view your current `HEARTBEAT.md`.

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
| `qwen3:4b` | ~3 GB | Compact Qwen3 — solid tool calling, native thinking |
| `qwen3:1.7b` | ~2 GB | Ultra-light Qwen3 — runs on CPU or minimal VRAM |
| `qwen2.5:3b` | ~2.5 GB | Smallest reliable tool-calling model |
| `llama3.2:3b` | ~2.5 GB | Meta's 3B — fast, decent tool use |
| `phi4-mini:3.8b` | ~3 GB | Microsoft Phi-4 Mini — punches above its size |
| `gemma3:4b` | ~3 GB | Google Gemma 3 4B — efficient, good instruction following |

```bash
questchain start --list-models   # see all presets with descriptions
questchain start -m <any-model>  # use any model installed in Ollama
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
