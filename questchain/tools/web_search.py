"""Web search provider selection and the backward-compatible Tavily factory."""

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
    kwargs = {
        "max_results": max_results,
        "search_depth": "advanced",
        "name": "web_search",
        "description": (
            "Search the web for current information, news, or documentation. "
            "Use web_browse to read the full content of a specific URL."
        ),
    }
    try:
        return TavilySearch(tavily_api_key=api_key, **kwargs)
    except TypeError:
        # Older langchain-tavily versions don't accept tavily_api_key= directly
        os.environ.setdefault("TAVILY_API_KEY", api_key)
        return TavilySearch(**kwargs)


def search_configuration_issue(api_key: str | None = None) -> str | None:
    """Explain unavailable search without disclosing configuration values."""
    from questchain import config
    from questchain.tools.searxng import validate_endpoint
    if config.WEB_SEARCH_PROVIDER == "ddgs":
        from questchain.tools.ddgs_search import dependency_issue
        return dependency_issue()
    if config.WEB_SEARCH_PROVIDER == "none":
        return "web search disabled (WEB_SEARCH_PROVIDER=none)"
    if config.WEB_SEARCH_PROVIDER == "tavily":
        return None if (config.TAVILY_API_KEY if api_key is None else api_key) else "configure Tavily with /tavily"
    if config.WEB_SEARCH_PROVIDER == "searxng":
        try:
            validate_endpoint(config.SEARXNG_SEARCH_URL)
        except ValueError:
            return "configure a valid SEARXNG_SEARCH_URL (see web search documentation)"
        return None
    return "WEB_SEARCH_PROVIDER must be ddgs, tavily, searxng, or none"


def create_configured_search_tool(api_key: str | None = None):
    from questchain import config
    from questchain.tools.searxng import create_searxng_tool
    if search_configuration_issue(api_key):
        return None
    if config.WEB_SEARCH_PROVIDER == "ddgs":
        from questchain.tools.ddgs_search import create_ddgs_tool
        return create_ddgs_tool()
    if config.WEB_SEARCH_PROVIDER == "searxng":
        return create_searxng_tool(config.SEARXNG_SEARCH_URL)
    return create_search_tool(config.TAVILY_API_KEY if api_key is None else api_key)


def search_provider_label() -> str:
    from questchain import config
    return {
        "ddgs": "DDGS / DuckDuckGo (experimental, external)",
        "searxng": "SearXNG (configured service)",
        "tavily": "Tavily (external API)",
        "none": "Disabled",
    }.get(config.WEB_SEARCH_PROVIDER, "Invalid provider")
