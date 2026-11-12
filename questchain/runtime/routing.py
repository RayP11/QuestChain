"""Compatibility guard for the retired automatic-routing API."""


def add_routing_tool(agent, catalog, delegate) -> None:
    """Routing is no longer supported; never register a delegation capability."""
    raise RuntimeError("Automatic agent routing was removed. Select a specialist manually.")
