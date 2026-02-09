"""Tavily web search tool for Genie."""

import os

from langchain_tavily import TavilySearch


def create_search_tool(api_key: str, max_results: int = 5) -> TavilySearch:
    """Create a Tavily web search tool.

    Args:
        api_key: Tavily API key.
        max_results: Maximum number of search results to return.

    Returns:
        Configured TavilySearch tool.
    """
    # TavilySearch reads from TAVILY_API_KEY env var
    os.environ.setdefault("TAVILY_API_KEY", api_key)

    return TavilySearch(
        max_results=max_results,
        search_depth="advanced",
        name="web_search",
    )
