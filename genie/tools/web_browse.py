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
            "Fetch and extract the main text content from one or more web page URLs. "
            "Use this when you already have a URL and need to read the full page content.\n\n"
            "INPUT: A list of valid URL strings (e.g. ['https://example.com/page']).\n\n"
            "USE THIS TOOL WHEN YOU NEED TO:\n"
            "- Read the full content of a web page you already have the URL for\n"
            "- Extract article text, documentation, or blog post content\n"
            "- Follow up on a URL found via web_search to get full details\n\n"
            "WORKFLOW: Use web_search first to find relevant URLs, "
            "then use web_browse to read their content.\n\n"
            "Do NOT use this tool to search for information — "
            "use the web_search tool for that."
        ),
    )
