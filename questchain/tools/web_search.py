"""Tavily web search tool for QuestChain."""

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
    kwargs = dict(
        max_results=max_results,
        search_depth="advanced",
        name="web_search",
        description=(
            "Search the web for current information, news, or documentation. "
            "Use web_browse to read the full content of a specific URL."
        ),
    )
    try:
        return TavilySearch(tavily_api_key=api_key, **kwargs)
    except TypeError:
        # Older langchain-tavily versions don't accept tavily_api_key= directly
        os.environ.setdefault("TAVILY_API_KEY", api_key)
        return TavilySearch(**kwargs)
