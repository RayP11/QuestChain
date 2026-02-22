"""Ollama model configuration and initialization."""

import httpx
from langchain_ollama import ChatOllama

from genie.config import (
    GENIE_RESPONSE_CACHE,
    MODEL_PRESETS,
    OLLAMA_BASE_URL,
    OLLAMA_NUM_GPU,
    OLLAMA_NUM_THREAD,
    get_response_cache_path,
)

_cache_initialized = False


def _maybe_init_cache() -> None:
    """Set up LangChain's global LLM response cache on first call (if enabled)."""
    global _cache_initialized
    if _cache_initialized or not GENIE_RESPONSE_CACHE:
        return
    from genie.cache import setup_llm_cache
    setup_llm_cache(get_response_cache_path())
    _cache_initialized = True


def get_model(model_name: str, base_url: str | None = None) -> ChatOllama:
    """Create a ChatOllama instance for the given model.

    Reads GPU/thread settings from config (OLLAMA_NUM_GPU, OLLAMA_NUM_THREAD).
    Also initializes the LLM response cache the first time if GENIE_RESPONSE_CACHE=true.

    Args:
        model_name: Ollama model name (e.g. 'qwen2.5:7b')
        base_url: Ollama server URL. Defaults to config value.

    Returns:
        Configured ChatOllama instance.
    """
    _maybe_init_cache()

    base_url = base_url or OLLAMA_BASE_URL
    preset = MODEL_PRESETS.get(model_name, {})
    num_ctx = preset.get("num_ctx", 32768)

    kwargs: dict = {
        "model": model_name,
        "base_url": base_url,
        "temperature": preset.get("temperature", 0.7),
        "num_ctx": num_ctx,
        "num_predict": preset.get("num_predict", 4096),
    }

    # GPU offload: -1 = all layers to GPU, 0 = CPU only, N = N layers to GPU.
    # Only set if the user explicitly configured OLLAMA_NUM_GPU; otherwise let
    # Ollama use its own default (usually determined by available VRAM).
    if OLLAMA_NUM_GPU is not None:
        kwargs["num_gpu"] = OLLAMA_NUM_GPU

    # CPU thread count. Leave unset for Ollama's auto-detection.
    if OLLAMA_NUM_THREAD is not None:
        kwargs["num_thread"] = OLLAMA_NUM_THREAD

    model = ChatOllama(**kwargs)

    # Set profile so deepagents SummarizationMiddleware uses fraction-based
    # thresholds (85% trigger, 10% keep) instead of the 170K token fallback
    # which is unreachable with local model context windows.
    model.profile = {"max_input_tokens": num_ctx}

    return model


def check_ollama_connection(base_url: str | None = None) -> bool:
    """Check if Ollama server is reachable."""
    base_url = base_url or OLLAMA_BASE_URL
    try:
        response = httpx.get(f"{base_url}/api/tags", timeout=5.0)
        return response.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


async def wait_for_ollama(
    base_url: str | None = None,
    retries: int = 4,
    delay: float = 2.0,
) -> bool:
    """Retry connecting to Ollama with a fixed delay between attempts.

    Returns True as soon as the server responds, False if all retries fail.
    """
    import asyncio
    base_url = base_url or OLLAMA_BASE_URL
    for attempt in range(retries):
        if check_ollama_connection(base_url):
            return True
        if attempt < retries - 1:
            await asyncio.sleep(delay)
    return False


def list_available_models(base_url: str | None = None) -> list[str]:
    """List models available on the Ollama server."""
    base_url = base_url or OLLAMA_BASE_URL
    try:
        response = httpx.get(f"{base_url}/api/tags", timeout=5.0)
        if response.status_code == 200:
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
    except (httpx.ConnectError, httpx.TimeoutException):
        pass
    return []
