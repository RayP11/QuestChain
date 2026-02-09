"""Tavily web browsing (extract) tool for Genie."""

import os

from langchain_tavily import TavilyExtract


def create_browse_tool(api_key: str) -> TavilyExtract:
    """Create a web page content extraction tool using Tavily Extract.

    Args:
        api_key: Tavily API key.

    Returns:
        Configured TavilyExtract tool.
    """
    os.environ.setdefault("TAVILY_API_KEY", api_key)

    return TavilyExtract(
        name="web_browse",
        description=(
            "Fetch and extract the main content from one or more web page URLs. "
            "Use this when you need to read the full content of a specific web page. "
            "Input should be a list of valid URL strings."
        ),
    )
