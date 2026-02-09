"""Ollama model configuration and initialization."""

import httpx
from langchain_ollama import ChatOllama

from genie.config import MODEL_PRESETS, OLLAMA_BASE_URL


def get_model(model_name: str, base_url: str | None = None) -> ChatOllama:
    """Create a ChatOllama instance for the given model.

    Args:
        model_name: Ollama model name (e.g. 'qwen2.5:7b')
        base_url: Ollama server URL. Defaults to config value.

    Returns:
        Configured ChatOllama instance.
    """
    base_url = base_url or OLLAMA_BASE_URL
    preset = MODEL_PRESETS.get(model_name, {})

    return ChatOllama(
        model=model_name,
        base_url=base_url,
        temperature=preset.get("temperature", 0.7),
        num_ctx=preset.get("num_ctx", 32768),
    )


def check_ollama_connection(base_url: str | None = None) -> bool:
    """Check if Ollama server is reachable."""
    base_url = base_url or OLLAMA_BASE_URL
    try:
        response = httpx.get(f"{base_url}/api/tags", timeout=5.0)
        return response.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
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
