"""Genie custom tools."""

from collections.abc import Awaitable, Callable

from genie.tools.claude_code import create_claude_code_tool
from genie.tools.cron import create_cron_tools
from genie.tools.web_search import create_search_tool
from genie.tools.web_browse import create_browse_tool
from genie.tools.speak import create_speak_tool


def get_custom_tools(
    api_key: str | None = None,
    on_audio: Callable[[bytes], Awaitable[None]] | None = None,
):
    """Return all custom tools for the Genie agent."""
    tools = [create_claude_code_tool()]
    tools.extend(create_cron_tools())
    if api_key:
        tools.append(create_search_tool(api_key))
        tools.append(create_browse_tool(api_key))
    if on_audio:
        tools.append(create_speak_tool(on_audio))
    return tools
