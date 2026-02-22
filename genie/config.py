"""Genie configuration management."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from current directory or project root
load_dotenv()

# --- Ollama settings ---
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")

# Number of GPU layers to offload to VRAM. -1 = all layers (full GPU), 0 = CPU only.
# Leave unset (empty string) to use Ollama's server-side default.
_num_gpu_env = os.getenv("OLLAMA_NUM_GPU", "")
OLLAMA_NUM_GPU: int | None = int(_num_gpu_env) if _num_gpu_env else None

# Number of CPU threads for inference. Leave unset to let Ollama auto-detect.
_num_thread_env = os.getenv("OLLAMA_NUM_THREAD", "")
OLLAMA_NUM_THREAD: int | None = int(_num_thread_env) if _num_thread_env else None

# --- Response cache settings ---
# When enabled, identical LLM prompts are served from a SQLite cache instead
# of re-invoking Ollama. Useful when the same question is asked repeatedly.
# Set GENIE_RESPONSE_CACHE=true in your .env to enable.
GENIE_RESPONSE_CACHE = os.getenv("GENIE_RESPONSE_CACHE", "false").lower() in ("1", "true", "yes")

# --- Tavily settings ---
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# --- Telegram settings ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_OWNER_ID = int(os.getenv("TELEGRAM_OWNER_ID") or "0")

# --- Data directory ---
GENIE_DATA_DIR = Path(os.getenv("GENIE_DATA_DIR", Path.home() / ".genie"))

# --- Workspace memory directory (agent-accessible notes/knowledge) ---
WORKSPACE_DIR = Path(os.getenv("GENIE_WORKSPACE_DIR", Path(__file__).resolve().parent.parent))
MEMORY_DIR = WORKSPACE_DIR / "workspace" / "memory"

# --- Model presets ---
MODEL_PRESETS = {
    # -- Top-tier tool calling (recommended) --
    # Quantization note: Ollama defaults to Q4_K_M. For higher quality use
    # the :fp16 tag; for lower VRAM use :q4_0 or :q3_K_M (e.g. "qwen3:8b-q4_0").
    "qwen3:8b": {
        "description": "Qwen 3 8B — Fast, excellent tool calling (default)",
        "num_ctx": 32768, "num_predict": 4096, "temperature": 0.7,
    },
    "qwen2.5:7b-instruct": {
        "description": "Qwen 2.5 7B Instruct — Top-tier tool calling",
        "num_ctx": 32768, "num_predict": 4096, "temperature": 0.7,
    },
    "qwen2.5:14b-instruct": {
        "description": "Qwen 2.5 14B Instruct — More capable, ~10GB VRAM",
        "num_ctx": 32768, "num_predict": 4096, "temperature": 0.7,
    },
    "llama3.1:8b-instruct": {
        "description": "Llama 3.1 8B Instruct — Best overall tool calling (BFCL 77-81%)",
        "num_ctx": 32768, "num_predict": 4096, "temperature": 0.7,
    },
    "llama3.3:8b-instruct": {
        "description": "Llama 3.3 8B Instruct — Newer Llama, strong tool use",
        "num_ctx": 32768, "num_predict": 4096, "temperature": 0.7,
    },
    # -- Good alternatives --
    "mistral:7b": {
        "description": "Mistral 7B — Fast, low resource, good tool calling",
        "num_ctx": 32768, "num_predict": 4096, "temperature": 0.7,
    },
    "mistral-nemo:12b": {
        "description": "Mistral Nemo 12B — Stronger Mistral variant",
        "num_ctx": 32768, "num_predict": 4096, "temperature": 0.7,
    },
    "dolphin3:latest": {
        "description": "Dolphin 3 8B — Uncensored, good for agents",
        "num_ctx": 32768, "num_predict": 4096, "temperature": 0.7,
    },
    # -- Reasoning-focused (weaker at tool calling) --
    "deepseek-r1:7b": {
        "description": "DeepSeek R1 7B — Strong reasoning (not ideal for tool calling)",
        "num_ctx": 32768, "num_predict": 4096, "temperature": 0.6,
    },
    "deepseek-r1:14b": {
        "description": "DeepSeek R1 14B — Stronger reasoning, ~10GB VRAM",
        "num_ctx": 32768, "num_predict": 4096, "temperature": 0.6,
    },
    # -- Code-focused --
    "deepseek-coder-v2:16b": {
        "description": "DeepSeek Coder V2 16B — Best local code generation",
        "num_ctx": 32768, "num_predict": 4096, "temperature": 0.6,
    },
}


def ensure_data_dir() -> Path:
    """Create the Genie data directory if it doesn't exist."""
    GENIE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return GENIE_DATA_DIR


def ensure_memory_dir() -> Path:
    """Create the workspace memory directory if it doesn't exist."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    return MEMORY_DIR


def get_db_path() -> Path:
    """Get the path to the SQLite checkpoint database."""
    return ensure_data_dir() / "checkpoints.db"


def get_history_path() -> Path:
    """Get the path to the command history file."""
    return ensure_data_dir() / "history"


def get_cron_jobs_path() -> Path:
    """Get the path to the cron jobs JSON file."""
    return ensure_data_dir() / "cron_jobs.json"


def get_response_cache_path() -> Path:
    """Get the path to the LLM response cache SQLite database."""
    return ensure_data_dir() / "response_cache.db"


def get_thread_ids_path() -> Path:
    """Get the path to the Telegram thread IDs JSON file."""
    return ensure_data_dir() / "telegram_threads.json"


def get_onboarded_marker_path() -> Path:
    """Get the path to the onboarded marker file."""
    return ensure_data_dir() / "onboarded"


def get_agents_path() -> Path:
    """Get the path to the agents JSON file."""
    return ensure_data_dir() / "agents.json"


def get_active_agent_path() -> Path:
    """Get the path to the active agent ID file."""
    return ensure_data_dir() / "active_agent"


# --- Busy work settings ---
DEFAULT_BUSY_WORK_MINUTES = 60
