"""Tool registry and @tool decorator for the QuestChain engine."""

from __future__ import annotations

import asyncio
import inspect
import re
from dataclasses import dataclass
from typing import Any, Callable, get_type_hints


@dataclass
class ToolDef:
    name: str
    description: str
    fn: Callable
    schema: dict  # Ollama-compatible JSON schema


class ToolRegistry:
    """Registry of tools available to the agent."""

    def __init__(self):
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool_def: ToolDef) -> None:
        self._tools[tool_def.name] = tool_def

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def schemas(self) -> list[dict]:
        """Return Ollama-compatible tool schemas."""
        return [t.schema for t in self._tools.values()]

    async def execute(self, name: str, args: dict) -> str:
        """Execute a single tool call, returning its string result."""
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: unknown tool '{name}'"
        try:
            if asyncio.iscoroutinefunction(tool.fn):
                result = await tool.fn(**args)
            else:
                result = await asyncio.to_thread(tool.fn, **args)
            return str(result) if result is not None else ""
        except Exception as e:
            return f"Error running {name}: {e}"

    async def execute_parallel(self, calls: list[dict]) -> list[dict]:
        """Execute multiple tool calls concurrently. Returns tool result messages."""
        results = await asyncio.gather(
            *[self.execute(c["name"], c["args"]) for c in calls],
            return_exceptions=True,
        )
        messages = []
        for call, result in zip(calls, results):
            content = str(result) if not isinstance(result, Exception) else f"Error: {result}"
            messages.append({
                "role": "tool",
                "name": call["name"],
                "content": content,
            })
        return messages

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


def tool(fn=None, *, name: str | None = None, description: str | None = None):
    """Decorator to register a function as a tool.

    Generates an Ollama-compatible JSON schema from the function's type hints
    and docstring. Works on both sync and async functions.

    Usage:
        @tool
        async def read_file(path: str) -> str:
            "Read a file."
            ...

        @tool(name="my_tool", description="Custom description")
        def my_tool(x: int) -> str:
            ...
    """
    def decorator(f):
        tool_name = name or f.__name__
        tool_desc = description or (inspect.getdoc(f) or "").split("\n")[0]
        schema = _build_schema(f, tool_name, tool_desc)
        f._tool_def = ToolDef(name=tool_name, description=tool_desc, fn=f, schema=schema)
        return f

    if fn is not None:
        return decorator(fn)
    return decorator


def make_registry(*items) -> ToolRegistry:
    """Build a ToolRegistry from decorated tool functions, ToolDef objects, or modules."""
    registry = ToolRegistry()
    for item in items:
        if item is None:
            continue
        if isinstance(item, ToolDef):
            registry.register(item)
        elif hasattr(item, "_tool_def"):
            registry.register(item._tool_def)
        elif inspect.ismodule(item):
            for attr in vars(item).values():
                if hasattr(attr, "_tool_def"):
                    registry.register(attr._tool_def)
        elif isinstance(item, list):
            for sub in item:
                if hasattr(sub, "_tool_def"):
                    registry.register(sub._tool_def)
                elif isinstance(sub, ToolDef):
                    registry.register(sub)
    return registry


def wrap_lc_tool(lc_tool) -> ToolDef:
    """Bridge a LangChain BaseTool into our ToolDef format."""
    # Extract JSON schema from the LC tool's args_schema (Pydantic model)
    params: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
    if hasattr(lc_tool, "args_schema") and lc_tool.args_schema:
        try:
            raw = lc_tool.args_schema.model_json_schema()
            params = {
                "type": "object",
                "properties": raw.get("properties", {}),
                "required": raw.get("required", []),
            }
        except Exception:
            pass

    schema = {
        "type": "function",
        "function": {
            "name": lc_tool.name,
            "description": lc_tool.description,
            "parameters": params,
        },
    }

    async def fn(**kwargs):
        if len(kwargs) == 1 and "input" in kwargs:
            result = await lc_tool.arun(kwargs["input"])
        elif not kwargs:
            result = await lc_tool.arun("")
        else:
            result = await lc_tool.arun(kwargs)
        return str(result)

    return ToolDef(name=lc_tool.name, description=lc_tool.description, fn=fn, schema=schema)


# ---------------------------------------------------------------------------
# Internal schema builder
# ---------------------------------------------------------------------------

def _build_schema(fn: Callable, name: str, description: str) -> dict:
    """Build an Ollama-compatible tool schema from a function's type hints."""
    sig = inspect.signature(fn)
    hints: dict = {}
    try:
        hints = get_type_hints(fn)
    except Exception:
        pass

    properties: dict[str, dict] = {}
    required: list[str] = []
    doc = inspect.getdoc(fn) or ""

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue

        hint = hints.get(param_name, str)
        prop = _type_to_schema(hint)

        # Pull per-param description from "Args:" docstring section
        match = re.search(rf"^\s+{param_name}:\s+(.+)$", doc, re.MULTILINE)
        if match:
            prop["description"] = match.group(1).strip()

        properties[param_name] = prop
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def _type_to_schema(hint) -> dict:
    """Convert a Python type hint to a JSON Schema type dict."""
    if hint in (str, "str"):
        return {"type": "string"}
    if hint in (int, "int"):
        return {"type": "integer"}
    if hint in (float, "float"):
        return {"type": "number"}
    if hint in (bool, "bool"):
        return {"type": "boolean"}
    if hint is list or (hasattr(hint, "__origin__") and hint.__origin__ is list):
        return {"type": "array", "items": {"type": "string"}}
    # Handle Optional[X] → Union[X, None]
    if hasattr(hint, "__args__"):
        args = [a for a in hint.__args__ if a is not type(None)]
        if args:
            return _type_to_schema(args[0])
    return {"type": "string"}
