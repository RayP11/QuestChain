"""Tavily web browsing (extract) tool for QuestChain."""

import os

from langchain_tavily import TavilyExtract


def create_browse_tool(api_key: str) -> TavilyExtract:
    """Create a web page content extraction tool using Tavily Extract.

    Args:
        api_key: Tavily API key.

    Returns:
        Configured TavilyExtract tool.
    """
    kwargs = dict(
        name="web_browse",
        description=(
            "Fetch and extract the full text content from one or more URLs. "
            "Use web_search first to find URLs, then this tool to read them."
        ),
    )
    try:
        return TavilyExtract(tavily_api_key=api_key, **kwargs)
    except TypeError:
        # Older langchain-tavily versions don't accept tavily_api_key= directly
        os.environ.setdefault("TAVILY_API_KEY", api_key)
        return TavilyExtract(**kwargs)
