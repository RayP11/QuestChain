"""QuestChain custom tools."""

import shutil
from collections.abc import Awaitable, Callable

from questchain.tools.claude_code import create_claude_code_tool
from questchain.tools.cron import create_cron_tools
from questchain.tools.web_search import create_search_tool
from questchain.tools.web_browse import create_browse_tool
from questchain.tools.speak import create_speak_tool


def is_claude_code_available() -> bool:
    """True if the 'claude' CLI is on PATH."""
    return shutil.which("claude") is not None


def get_custom_tools(
    api_key: str | None = None,
    on_audio: Callable[[bytes], Awaitable[None]] | None = None,
    tools_filter: list[str] | None = None,
):
    """Return custom tools for the QuestChain agent.

    Args:
        api_key: Tavily API key; omit to skip web tools.
        on_audio: Callback for TTS audio; omit to skip speak tool.
        tools_filter: When provided, only include tools whose name appears in
            this list. ``"cron"`` expands to all three cron tools. ``None``
            keeps the current behaviour (all applicable tools included).
    """
    def _want(name: str) -> bool:
        if tools_filter is None:
            return True
        return name in tools_filter

    tools = []

    if _want("claude_code") and is_claude_code_available():
        tools.append(create_claude_code_tool())

    if _want("cron"):
        tools.extend(create_cron_tools())

    if api_key and _want("web_search"):
        tools.append(create_search_tool(api_key))
    if api_key and _want("web_browse"):
        tools.append(create_browse_tool(api_key))

    if on_audio and _want("speak"):
        tools.append(create_speak_tool(on_audio))

    return tools
