"""Genie custom tools."""

from genie.tools.web_search import create_search_tool
from genie.tools.web_browse import create_browse_tool


def get_custom_tools(api_key: str | None = None):
    """Return all custom tools for the Genie agent."""
    tools = []
    if api_key:
        tools.append(create_search_tool(api_key))
        tools.append(create_browse_tool(api_key))
    return tools
