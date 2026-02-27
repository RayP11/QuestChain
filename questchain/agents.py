"""QuestChain agent management — custom named agents with their own model/tools/prompt."""

import json
import secrets
from datetime import datetime, timezone

from questchain.config import get_active_agent_path, get_agents_path

AGENT_CLASSES: list[tuple[str, str, str]] = [
    ("Wanderer",  "🌀", "Unspecialized — custom-configured tools"),
    ("Archivist", "📚", "Master of files and knowledge management"),
    ("Scout",     "🔭", "Explorer of the web and information"),
    ("Architect", "⚒️",  "Builder and coder"),
    ("Oracle",    "🔮", "Planner and strategist"),
    ("Sentinel",  "⏱️",  "Scheduler and automation specialist"),
]
DEFAULT_CLASS = "Wanderer"

# Tool presets applied when creating an agent of each class.
# None = user configures manually (Wanderer only).
# list = selectable tool names; [] = built-in tools only.
CLASS_TOOL_PRESETS: dict[str, list[str] | None] = {
    "Wanderer":  None,
    "Archivist": [],
    "Scout":     ["web_search", "web_browse"],
    "Architect": ["claude_code"],
    "Oracle":    ["web_search"],
    "Sentinel":  ["cron"],
}

SELECTABLE_TOOLS = [
    ("web_search",  "Web search via Tavily"),
    ("web_browse",  "Full page content via Tavily"),
    ("claude_code", "Delegate coding to Claude Code"),
    ("speak",       "Text-to-speech voice output"),
    ("cron",        "Schedule recurring cron jobs"),
]

BUILTIN_AGENT = {
    "id": "default",
    "name": "QuestChain",
    "built_in": True,
    "model": None,
    "system_prompt": None,
    "tools": "all",
    "class_name": DEFAULT_CLASS,
}


class AgentManager:
    """Manage custom named agents stored in ~/.questchain/agents.json."""

    def __init__(self):
        self._agents: list[dict] = []
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def all_agents(self) -> list[dict]:
        """Return built-in QuestChain agent followed by all user agents."""
        saved_default = next((a for a in self._agents if a["id"] == "default"), None)
        default_agent = saved_default if saved_default else BUILTIN_AGENT
        user_agents = [a for a in self._agents if a["id"] != "default"]
        return [default_agent] + user_agents

    def get(self, agent_id: str) -> dict | None:
        """Return an agent definition by ID, or None if not found."""
        if agent_id == "default":
            saved_default = next((a for a in self._agents if a["id"] == "default"), None)
            return saved_default if saved_default else BUILTIN_AGENT
        return next((a for a in self._agents if a["id"] == agent_id), None)

    def add(self, name: str, model: str | None, system_prompt: str | None, tools: list[str] | str, class_name: str | None = None) -> dict:
        """Create a new custom agent, save it, and return its definition."""
        agent_def = {
            "id": secrets.token_hex(3),
            "name": name,
            "model": model or None,
            "system_prompt": system_prompt or None,
            "tools": tools,
            "class_name": class_name or DEFAULT_CLASS,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._agents.append(agent_def)
        self._save()
        return agent_def

    def update(self, agent_id: str, **kwargs) -> dict:
        """Update fields of an agent. Built-in QuestChain can be edited but not deleted."""
        if agent_id == "default":
            saved_default = next((a for a in self._agents if a["id"] == "default"), None)
            if saved_default is None:
                saved_default = dict(BUILTIN_AGENT)
                self._agents.insert(0, saved_default)
            for key, value in kwargs.items():
                saved_default[key] = value
            self._save()
            return saved_default
        agent = next((a for a in self._agents if a["id"] == agent_id), None)
        if agent is None:
            raise ValueError(f"Agent '{agent_id}' not found.")
        for key, value in kwargs.items():
            agent[key] = value
        self._save()
        return agent

    def remove(self, agent_id: str) -> bool:
        """Remove a custom agent by ID. Raises ValueError for built-in agents."""
        if agent_id == "default":
            raise ValueError("Cannot delete the built-in QuestChain agent.")
        original_len = len(self._agents)
        self._agents = [a for a in self._agents if a["id"] != agent_id]
        if len(self._agents) == original_len:
            return False
        # If we just removed the active agent, reset to default
        if self.get_active_id() == agent_id:
            self.set_active("default")
        self._save()
        return True

    def get_active(self) -> dict:
        """Return the currently active agent definition."""
        active_id = self.get_active_id()
        agent = self.get(active_id)
        if agent is None:
            # Active agent was deleted; fall back to default
            self.set_active("default")
            return BUILTIN_AGENT
        return agent

    def get_active_id(self) -> str:
        """Return the currently active agent ID."""
        path = get_active_agent_path()
        if path.exists():
            try:
                return path.read_text(encoding="utf-8").strip()
            except Exception:
                pass
        return "default"

    def set_active(self, agent_id: str) -> None:
        """Persist the active agent ID to disk."""
        path = get_active_agent_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(agent_id, encoding="utf-8")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        path = get_agents_path()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._agents = data
            except Exception:
                self._agents = []

    def _save(self) -> None:
        path = get_agents_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._agents, indent=2), encoding="utf-8")
