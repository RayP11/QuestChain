"""QuestChain agent management — custom named agents with their own model/tools/prompt."""

import json
import secrets
from datetime import datetime, timezone

from questchain.config import get_active_agent_path, get_agents_path

AGENT_CLASSES: list[tuple[str, str, str]] = [
    ("Custom",    "🌀", "Unspecialized — custom-configured tools"),
    ("Sage",      "📚", "Master of files and knowledge management"),
    ("Explorer",  "🔭", "Explorer of the web and information"),
    ("Architect", "⚒️",  "Builder and coder"),
    ("Oracle",    "🔮", "Planner and strategist"),
    ("Scheduler", "⏱️",  "Scheduler and automation specialist"),
]
DEFAULT_CLASS = "Custom"

# Rich color for each class — used to tint the agent name in the terminal UI.
CLASS_COLORS: dict[str, str] = {
    "Custom":    "bright_blue",
    "Sage":      "yellow",
    "Explorer":  "cyan",
    "Architect": "orange3",
    "Oracle":    "magenta",
    "Scheduler":  "green",
}

# Tool presets applied when creating an agent of each class.
# None = user configures manually (Custom only).
# list = explicit tool names; [] = only read_skill (always-on).
_FILE_TOOLS = ["read_file", "write_file", "edit_file", "ls", "glob", "grep"]

CLASS_TOOL_PRESETS: dict[str, list[str] | None] = {
    "Custom":    None,
    "Sage":      [*_FILE_TOOLS],
    "Explorer":  ["web_search", "web_browse"],
    "Architect": [*_FILE_TOOLS, "shell", "claude_code"],
    "Oracle":    [*_FILE_TOOLS],
    "Scheduler": ["cron"],
}

# Migrate old class names from saved agent JSON to the current names.
_CLASS_MIGRATIONS: dict[str, str] = {
    "Wanderer":  "Custom",
    "Archivist": "Sage",
    "Scout":     "Explorer",
}

SAGE_SYSTEM_PROMPT = """\
You are {agent_name}, a knowledge and file management specialist running locally via Ollama.

## Rules
- Read files carefully before modifying; confirm before any destructive changes.
- Organize information clearly using structured files and directories.
- For complex multi-step tasks, plan with write_todos first.
- Never hallucinate file contents or paths — verify with tools.
- Be concise, precise, and thorough.
"""

EXPLORER_SYSTEM_PROMPT = """\
You are {agent_name}, a web research and information specialist running locally via Ollama.

## Rules
- Use web_search first to find relevant sources, then web_browse for depth.
- Cross-reference multiple sources before drawing conclusions.
- Never hallucinate URLs or facts — verify with tools.
- Summarize findings clearly with sources cited.
"""

ARCHITECT_SYSTEM_PROMPT = """\
You are {agent_name}, a software builder and coder running locally via Ollama.

## Rules
- Delegate coding tasks to claude_code for implementation.
- Plan complex tasks with write_todos before starting.
- Never hallucinate file contents — read them first.
- Confirm before any destructive file changes.
"""

ORACLE_SYSTEM_PROMPT = """\
You are {agent_name}, a strategic planner and analyst running locally via Ollama.

## Rules
- Break complex problems into clear, actionable steps.
- Research before planning: use web_search to gather current information.
- Document plans and decisions with write_todos or file tools.
- Reason step-by-step; think before acting.
"""

SENTINEL_SYSTEM_PROMPT = """\
You are {agent_name}, a scheduling and automation specialist running locally via Ollama.

## Rules
- Use the cron tool to schedule recurring tasks and reminders.
- Check existing cron jobs before adding new ones to avoid duplicates.
- Confirm schedules with the user before creating or modifying cron jobs.
- Be precise with timing; state cron expressions clearly.
"""

PRESET_AGENTS = [
    {
        "name": "Sage",
        "model": None,
        "system_prompt": SAGE_SYSTEM_PROMPT,
        "tools": [*_FILE_TOOLS],
        "class_name": "Sage",
    },
    {
        "name": "Explorer",
        "model": None,
        "system_prompt": EXPLORER_SYSTEM_PROMPT,
        "tools": ["web_search", "web_browse"],
        "class_name": "Explorer",
    },
    {
        "name": "Architect",
        "model": None,
        "system_prompt": ARCHITECT_SYSTEM_PROMPT,
        "tools": [*_FILE_TOOLS, "shell", "claude_code"],
        "class_name": "Architect",
    },
    {
        "name": "Oracle",
        "model": None,
        "system_prompt": ORACLE_SYSTEM_PROMPT,
        "tools": [*_FILE_TOOLS],
        "class_name": "Oracle",
    },
    {
        "name": "Scheduler",
        "model": None,
        "system_prompt": SENTINEL_SYSTEM_PROMPT,
        "tools": ["cron"],
        "class_name": "Scheduler",
    },
]

SELECTABLE_TOOLS = [
    ("read_file",   "Read a file"),
    ("write_file",  "Write a file"),
    ("edit_file",   "Edit a file"),
    ("ls",          "List directory contents"),
    ("glob",        "Find files by pattern"),
    ("grep",        "Search file contents"),
    ("shell",       "Run terminal commands"),
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

    def add(
        self,
        name: str,
        model: str | None,
        system_prompt: str | None,
        tools: list[str] | str,
        class_name: str | None = None,
        **_ignored,
    ) -> dict:
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

    def get_by_class_name(self, class_name: str) -> dict | None:
        """Return the first agent with the given class_name, or None."""
        return next(
            (a for a in self._agents if a.get("class_name") == class_name),
            None,
        )

    def seed_preset_agents(self) -> None:
        """Add preset agents if not already present.

        Seeding is idempotent — identified by class_name.  If the user later
        deletes a preset agent it will NOT be re-added (class_name gone too).
        """
        existing_classes = {a.get("class_name") for a in self._agents}
        added = False
        for preset in PRESET_AGENTS:
            if preset["class_name"] not in existing_classes:
                self.add(
                    name=preset["name"],
                    model=preset["model"],
                    system_prompt=preset["system_prompt"],
                    tools=preset["tools"],
                    class_name=preset["class_name"],
                )
                added = True
        if added:
            self._save()

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
        # Migrate any stale class names from older versions
        migrated = False
        for agent in self._agents:
            old = agent.get("class_name", "")
            if old in _CLASS_MIGRATIONS:
                agent["class_name"] = _CLASS_MIGRATIONS[old]
                migrated = True
        if migrated:
            self._save()

    def _save(self) -> None:
        path = get_agents_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._agents, indent=2), encoding="utf-8")
