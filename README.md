# Genie

A terminal-based AI agent powered by local LLMs via [Ollama](https://ollama.com) and [LangGraph Deep Agents](https://github.com/langchain-ai/deepagents).

Genie can search the web, read/write files, run shell commands, break down complex tasks with planning, and remember context across sessions — all running locally on your machine.

## Quick Start

### Prerequisites

- [Python 3.13+](https://python.org)
- [Ollama](https://ollama.com) installed and running
- A [Tavily API key](https://tavily.com) for web search (free tier available)

### Setup

```bash
# Clone and enter the project
cd Genie

# Install dependencies
uv sync

# Copy and configure environment variables
cp .env.example .env
# Edit .env and add your TAVILY_API_KEY

# Pull a model (if you haven't already)
ollama pull qwen3:8b

# Run Genie
python -m genie
```

### Usage

```bash
# Start with default model (qwen3:8b)
python -m genie

# Use a specific model
python -m genie -m dolphin3:latest

# List available model presets
python -m genie --list-models

# Resume a previous conversation
python -m genie -t <thread-id>

# Run without persistent memory
python -m genie --no-memory
```

### REPL Commands

| Command   | Description                              |
|-----------|------------------------------------------|
| `/help`   | Show available commands                  |
| `/new`    | Start a new conversation                 |
| `/model`  | Show current model and available models  |
| `/thread` | Show current thread ID                   |
| `/clear`  | Clear the screen                         |
| `/quit`   | Exit Genie                               |

## Capabilities

- **Web Search** — Search the web for current information via Tavily
- **Web Browse** — Extract and read full content from web pages
- **File Operations** — Read, write, edit, list, and search files
- **Shell Commands** — Execute terminal commands
- **Planning** — Break down complex tasks into steps with built-in todo tools
- **Sub-agents** — Delegate subtasks to focused child agents
- **Persistent Memory** — Saves notes and context to `workspace/memory/` across sessions
- **Conversation History** — Resume previous conversations via SQLite checkpointing

## Project Structure

```
Genie/
├── pyproject.toml              # Dependencies and project config
├── .env                        # API keys and settings (not committed)
├── genie/
│   ├── __main__.py             # Entry point (python -m genie)
│   ├── cli.py                  # Terminal UI and REPL loop
│   ├── agent.py                # Deep Agent wiring and system prompt
│   ├── config.py               # Settings, model presets, paths
│   ├── models.py               # ChatOllama setup and Ollama helpers
│   ├── tools/
│   │   ├── web_search.py       # Tavily search tool
│   │   └── web_browse.py       # Tavily extract tool
│   └── memory/
│       └── store.py            # SQLite checkpointer + memory store
└── workspace/
    └── memory/                 # Agent's persistent notes and knowledge
```

## Configuration

All settings are managed via environment variables (or `.env` file):

| Variable              | Default                    | Description                  |
|-----------------------|----------------------------|------------------------------|
| `OLLAMA_MODEL`        | `qwen3:8b`                 | Default Ollama model         |
| `OLLAMA_BASE_URL`     | `http://localhost:11434`   | Ollama server URL            |
| `TAVILY_API_KEY`      | —                          | Tavily API key for web tools |
| `GENIE_DATA_DIR`      | `~/.genie`                 | Checkpoints and history      |
| `GENIE_WORKSPACE_DIR` | Project root               | Workspace root directory     |

## Model Presets

| Model                       | Description                                    |
|-----------------------------|------------------------------------------------|
| `qwen3:8b`                  | Qwen 3 8B — Fast, strong tool calling (default)|
| `qwen2.5:7b`                | Qwen 2.5 7B — Fast, good tool calling          |
| `qwen2.5:14b`               | Qwen 2.5 14B — More capable, needs ~10GB VRAM  |
| `deepseek-r1:7b`            | DeepSeek R1 7B — Strong reasoning               |
| `deepseek-r1:14b`           | DeepSeek R1 14B — Stronger reasoning            |
| `dolphin3:latest`           | Dolphin 3 8B — Uncensored, good for agents      |
| `llama3.1:8b-instruct-q4_0` | Llama 3.1 8B — Well-rounded                    |
| `mistral:7b`                | Mistral 7B — Fast and efficient                 |

Any Ollama model can be used via `python -m genie -m <model-name>`, even if not in the presets.

## Built With

- [LangGraph Deep Agents](https://github.com/langchain-ai/deepagents) — Agent harness with planning, filesystem, and sub-agents
- [LangChain](https://langchain.com) — LLM framework
- [Ollama](https://ollama.com) — Local LLM inference
- [Tavily](https://tavily.com) — Web search and extract API
- [Rich](https://github.com/Textualize/rich) — Terminal formatting
- [prompt-toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) — Interactive input
