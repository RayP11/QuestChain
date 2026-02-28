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
    ("Sentinel",  "⏱️",  "Scheduler and automation specialist"),
    ("NightOwl",  "🌙", "Autonomous overnight task worker"),
    ("Trainer",   "💪", "Fitness coach and health tracker"),
]
DEFAULT_CLASS = "Custom"

# Rich color for each class — used to tint the agent name in the terminal UI.
CLASS_COLORS: dict[str, str] = {
    "Custom":    "bright_blue",
    "Sage":      "yellow",
    "Explorer":  "cyan",
    "Architect": "orange3",
    "Oracle":    "magenta",
    "Sentinel":  "green",
    "NightOwl":  "magenta",
    "Trainer":   "green",
}

# Tool presets applied when creating an agent of each class.
# None = user configures manually (Custom only).
# list = selectable tool names; [] = built-in tools only.
CLASS_TOOL_PRESETS: dict[str, list[str] | None] = {
    "Custom":    None,
    "Sage":      [],
    "Explorer":  ["web_search", "web_browse"],
    "Architect": ["claude_code"],
    "Oracle":    ["web_search"],
    "Sentinel":  ["cron"],
    "NightOwl":  ["web_search", "web_browse", "claude_code"],
    "Trainer":   ["web_search", "web_browse"],
}

# Skill presets applied when creating an agent of each class.
# None = all available skills; [] = no skills; list = specific skills by dir-name.
CLASS_SKILL_PRESETS: dict[str, list[str] | None] = {
    "Custom":    None,
    "Sage":      None,
    "Explorer":  None,
    "Architect": None,
    "Oracle":    None,
    "Sentinel":  ["cron-jobs"],
    "NightOwl":  ["overnight-agent"],
    "Trainer":   ["fitness-tracker"],
}

# Maps each skill dir-name to the tool(s) that must be present for it to be useful.
# Skills not listed here have no tool prerequisite and are always available.
SKILL_REQUIRED_TOOLS: dict[str, list[str]] = {
    "claude-code":    ["claude_code"],
    "cron-jobs":      ["cron"],
    "overnight-agent": ["web_search", "web_browse", "claude_code"],
    "fitness-tracker": ["web_search", "web_browse"],
}

# Migrate old class names from saved agent JSON to the current names.
_CLASS_MIGRATIONS: dict[str, str] = {
    "Wanderer":  "Custom",
    "Archivist": "Sage",
    "Scout":     "Explorer",
}

OVERNIGHT_SYSTEM_PROMPT = """\
You are {agent_name}, an autonomous overnight AI worker running locally via Ollama.

## Rules
- Your task list is at /workspace/overnight.md — always read it first.
- Complete all Standing Tasks, then items under Tonight's Queue.
- Mark queue items [x] when done and move them to Completed Archive.
- Append a brief timestamped LOG entry at the end of the file when done.
- For research tasks: use web_search then web_browse for depth.
- For coding tasks: use claude_code.
- When ALL tasks are done, reply: OVERNIGHT_DONE
- Confirm before any destructive file operations.
"""

FITNESS_SYSTEM_PROMPT = """\
You are {agent_name}, a personal fitness coach and health tracker running locally via Ollama.

## Rules
- Workout plans: /workspace/workouts.md
- Goals: /workspace/fitness/goals.md
- Log each session: /workspace/fitness/logs/YYYY-MM-DD.md
- Nutrition tracking: /workspace/fitness/nutrition.md
- Weekly summaries: /workspace/fitness/progress.md
- User profile: /workspace/memory/ABOUT.md — read it to personalize advice.
- Be motivating, specific, and data-driven. Search for latest research when relevant.
"""

PRESET_AGENTS = [
    {
        "name": "Night Owl",
        "model": None,
        "system_prompt": OVERNIGHT_SYSTEM_PROMPT,
        "tools": ["web_search", "web_browse", "claude_code"],
        "skills": ["overnight-agent"],
        "class_name": "NightOwl",
    },
    {
        "name": "Coach",
        "model": None,
        "system_prompt": FITNESS_SYSTEM_PROMPT,
        "tools": ["web_search", "web_browse"],
        "skills": ["fitness-tracker"],
        "class_name": "Trainer",
    },
]

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

    def add(
        self,
        name: str,
        model: str | None,
        system_prompt: str | None,
        tools: list[str] | str,
        class_name: str | None = None,
        skills: list[str] | None = None,
    ) -> dict:
        """Create a new custom agent, save it, and return its definition."""
        agent_def = {
            "id": secrets.token_hex(3),
            "name": name,
            "model": model or None,
            "system_prompt": system_prompt or None,
            "tools": tools,
            "skills": skills,   # None = all; [] = none; list = specific by dir-name
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
        """Add preset agents (NightOwl, Trainer) if not already present.

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
                    skills=preset.get("skills"),
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
