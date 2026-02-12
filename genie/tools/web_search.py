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
        description=(
            "Search the web for current information, news, documentation, or answers. "
            "Returns a list of search results with titles, URLs, and snippets.\n\n"
            "USE THIS TOOL WHEN YOU NEED TO:\n"
            "- Find current/recent information (news, releases, events)\n"
            "- Look up documentation, tutorials, or how-to guides\n"
            "- Verify facts or claims you are unsure about\n"
            "- Find URLs for specific topics before reading them with web_browse\n\n"
            "EXAMPLES of good queries:\n"
            '- "Python 3.13 new features"\n'
            '- "LangGraph agent tutorial 2025"\n'
            '- "how to fix CORS error in FastAPI"\n\n'
            "Do NOT use this tool to read the content of a specific URL — "
            "use the web_browse tool for that."
        ),
    )
