"""QuestChain agent management — custom named agents with their own model/tools/prompt."""

import json
import secrets
from copy import deepcopy
from datetime import datetime, timezone

from questchain.config import get_active_agent_path, get_agents_path

AGENT_CLASSES: list[tuple[str, str, str]] = [
    ("Custom",    "🌀", "Unspecialized — custom-configured tools"),
    ("Router",    "🧭", "Coordinator — routes requests and communicates progress"),
    ("Keeper",    "📚", "Master of files and knowledge management"),
    ("Explorer",  "🔭", "Explorer of the web and information"),
    ("Builder",   "⚒️",  "Builder and coder"),
    ("Planner",   "🔮", "Planner and strategist"),
    ("Scheduler", "⏱️",  "Scheduler and automation specialist"),
]
DEFAULT_CLASS = "Custom"

# Rich color for each class — used to tint the agent name in the terminal UI.
CLASS_COLORS: dict[str, str] = {
    "Router":    "bright_blue",
    "Custom":    "bright_blue",
    "Keeper":    "yellow",
    "Explorer":  "cyan",
    "Builder":   "orange3",
    "Planner":   "magenta",
    "Scheduler":  "green",
}

# Tool presets applied when creating an agent of each class.
# None = user configures manually (Custom only).
# list = explicit tool names; [] = no tools.
_FILE_TOOLS = ["read_file", "write_file", "edit_file", "ls", "glob", "grep"]

CLASS_TOOL_PRESETS: dict[str, list[str] | None] = {
    "Router":    [],
    "Custom":    None,
    "Keeper":    [*_FILE_TOOLS, "delete_file"],
    "Explorer":  ["web_search", "web_browse"],
    "Builder":   [*_FILE_TOOLS, "shell"],
    "Planner":   [*_FILE_TOOLS],
    "Scheduler": ["cron"],
}

# Migrate old class names from saved agent JSON to the current names.
_CLASS_MIGRATIONS: dict[str, str] = {
    "Wanderer":  "Custom",
    "Archivist": "Keeper",
    "Sage":      "Keeper",
    "Scout":     "Explorer",
    "Architect": "Builder",
    "Oracle":    "Planner",
    # Early releases used character names as roles. Preserve their display names,
    # prompts and permissions while restoring an editable, stable role.
    "Hermes":    "Explorer",
    "Atlas":     "Keeper",
    "Athena":    "Builder",
    "Talos":     "Builder",
    "Titan":     "Custom",
    "Zeus":      "Custom",  # Legacy Zeus was an explicitly invoked cloud advisor.
}

KEEPER_SYSTEM_PROMPT = """\
You are {agent_name}, a knowledge and file management specialist running locally via Ollama.

## Rules
- Read files carefully before modifying. Use delete_file for a file the user specifically asks to delete; confirm exact paths for ambiguous cleanup requests.
- Organize information clearly using structured files and directories.
- Create, write, edit, delete, and organize workspace files, notes, and information using your enabled tools.
- Keep information clearly structured and verify saved changes. The main assistant owns the overall plan.
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

BUILDER_SYSTEM_PROMPT = """\
You are {agent_name}, a software builder and coder running locally via Ollama.

## Rules
- Inspect, implement, and test software using your enabled tools.
- Use claude_code only when it is enabled and delegation is useful.
- Plan complex tasks before starting.
- Never hallucinate file contents — read them first.
- Confirm before any destructive file changes.
- To create a custom tool, write `/workspace/tools/<name>.py` with an `async def <name>(...)` function and a docstring. It must be enabled per-agent in settings before it's available.
"""

PLANNER_SYSTEM_PROMPT = """\
You are {agent_name}, a strategic planner and analyst running locally via Ollama.

## Rules
- Clarify the goal only when missing information prevents useful advice.
- Break every complex task into clear, numbered, actionable steps with explicit dependencies.
- Write plans to files so they persist and can be reviewed or revised.
- Explain recommendations and tradeoffs concisely.
- Identify risks and open questions; flag blockers explicitly.
- Keep the plan proportional to the request; planning is your specialty, not a gate on other agents.
"""

SENTINEL_SYSTEM_PROMPT = """\
You are {agent_name}, a scheduling and automation specialist running locally via Ollama.

## Rules
- Use the cron tool to schedule recurring tasks and reminders.
- Check existing cron jobs before adding new ones to avoid duplicates.
- Confirm schedules with the user before creating or modifying cron jobs.
- Be precise with timing; state cron expressions clearly.
"""

ROUTER_SYSTEM_PROMPT = """You are {agent_name}, the user's coordinator.
Your focused job is to choose a specialist, clarify ambiguous requests, and communicate progress.
Use the supplied agent catalog and conversation context. Preserve the user's actual request.
You cannot grant permissions or execute specialist work. Specialist responses retain their authorship.
Answer greetings and status questions briefly. Delegate substantive work to an eligible specialist.
"""

CLASS_GUIDANCE = {
    "Router": "Route requests to specialists, clarify destinations, and report task progress or results.",
    "Explorer": "Research external or current information, compare sources, verify facts, and cite findings.",
    "Keeper": "Find, summarize, create, edit, delete, and organize workspace files, notes, and project knowledge.",
    "Builder": "Inspect code, implement software changes, create tools, diagnose bugs, and run tests.",
    "Planner": "Plan complex goals, compare approaches, advise on priorities, and assess tradeoffs.",
    "Scheduler": "Create, edit, pause, or inspect recurring cron jobs and their schedules.",
}

ROLE_LABELS = {"Router": "Coordinator", "Explorer": "Researcher", "Keeper": "Workspace knowledge",
               "Builder": "Builder", "Planner": "Planning & advising", "Scheduler": "Scheduling",
               "Custom": "Custom"}

MAIN_SYSTEM_PROMPT = """You are {agent_name}, a capable assistant running locally via Ollama.
You are the single assistant the user talks to. Own each request from start to finish.
Handle planning yourself: break complex goals into steps, track dependencies and priorities,
adapt the plan as results arrive, and explain decisions. Delegate bounded execution, not ownership of the plan.
Handle simple work directly. Use delegate_to_agent when a configured subagent is useful.
Treat worker outcomes as evidence, review errors and limitations, then give your own final answer.
Never claim an action succeeded without evidence. Verify facts and file contents with tools.
Respect enabled tools and the approved workspace boundary. Confirm ambiguous destructive actions.
"""

PREVIOUS_MAIN_SYSTEM_PROMPT = MAIN_SYSTEM_PROMPT.replace(
    "Handle planning yourself: break complex goals into steps, track dependencies and priorities,\n"
    "adapt the plan as results arrive, and explain decisions. Delegate bounded execution, not ownership of the plan.\n", "")

PRESET_AGENTS = [
    {"name": "Researcher", "model": None, "system_prompt": EXPLORER_SYSTEM_PROMPT,
     "tools": ["web_search", "web_browse"], "class_name": "Explorer"},
    {"name": "Workspace", "model": None, "system_prompt": KEEPER_SYSTEM_PROMPT,
     "tools": [*_FILE_TOOLS, "delete_file"], "class_name": "Keeper"},
    {"name": "Builder", "model": None, "system_prompt": BUILDER_SYSTEM_PROMPT,
     "tools": [*_FILE_TOOLS, "shell"], "class_name": "Builder"},
    {"name": "Scheduler", "model": None, "system_prompt": SENTINEL_SYSTEM_PROMPT,
     "tools": ["cron"], "class_name": "Scheduler"},
]


def preset_prompt(class_name: str) -> str:
    from questchain.agent import SYSTEM_PROMPT
    return next((p["system_prompt"] for p in PRESET_AGENTS if p["class_name"] == class_name),
                PLANNER_SYSTEM_PROMPT if class_name == "Planner" else ROUTER_SYSTEM_PROMPT if class_name == "Router" else SYSTEM_PROMPT)

SELECTABLE_TOOLS = [
    ("read_file",   "Read a file"),
    ("write_file",  "Write a file"),
    ("edit_file",   "Edit a file"),
    ("delete_file", "Delete an individual workspace file"),
    ("ls",          "List directory contents"),
    ("glob",        "Find files by pattern"),
    ("grep",        "Search file contents"),
    ("shell",       "Run terminal commands"),
    ("write_todos", "Write the workspace task list"),
    ("read_todos",  "Read the workspace task list"),
    ("web_search",  "Web search via Tavily"),
    ("web_browse",  "Full page content via Tavily"),
    ("claude_code", "Delegate coding to Claude Code"),
    ("speak",       "Text-to-speech voice output"),
    ("cron",        "Schedule recurring cron jobs"),
]

def get_dynamic_selectable_tools() -> list[tuple[str, str]]:
    """Return SELECTABLE_TOOLS combined with discovered workspace tools (tagged [WS])."""
    try:
        from questchain.config import WORKSPACE_DIR
        from questchain.engine.workspace_tools import get_tool_entries
        ws = get_tool_entries(WORKSPACE_DIR)
    except Exception:
        ws = []
    return list(SELECTABLE_TOOLS) + [(name, f"{desc} [WS]") for name, desc in ws]


def tool_access_allowed(definition: dict, tool_name: str) -> bool:
    """Check live configured access, including grouped tools and role restrictions."""
    from questchain.agent import _CLASS_TOOL_BLACKLIST
    selected_name = "shell" if tool_name == "execute" else "cron" if tool_name.startswith("cron_") else tool_name
    if selected_name in _CLASS_TOOL_BLACKLIST.get(definition.get("class_name"), ()):
        return False
    selected = definition.get("tools", [])
    return selected == "all" or selected_name in selected


def tool_issues(definition: dict) -> list[str]:
    """Explain configured capabilities that cannot currently be provided."""
    from questchain import config
    from questchain.tools import is_claude_code_available
    selected = definition.get("tools", [])
    if selected == "all":
        return []
    known = {name for name, _ in get_dynamic_selectable_tools()}
    issues = []
    for name in selected:
        if name not in known:
            issues.append(f"{name}: tool is no longer installed")
        elif name in {"web_search", "web_browse"} and not config.TAVILY_API_KEY:
            issues.append(f"{name}: configure Tavily in Settings")
        elif name == "claude_code" and not is_claude_code_available():
            issues.append("claude_code: install/configure Claude Code or deselect this tool")
        elif name == "speak":
            from questchain.tools.speak import is_speak_available
            if not is_speak_available():
                issues.append("speak: finish voice setup before using this tool")
        elif not tool_access_allowed(definition, name):
            issues.append(f"{name}: unavailable for this role")
    return issues


BUILTIN_AGENT = {
    "id": "main",
    "kind": "main",
    "definition_version": 3,
    "name": "QuestChain",
    "built_in": True,
    "model": None,
    "system_prompt": MAIN_SYSTEM_PROMPT,
    "tools": "all",
    "class_name": DEFAULT_CLASS,
    "when_to_call": "",
    "when_not_to_call": "",
    "routing_examples": [],
    "routable": False,
    "revision": 1,
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
        """Return active definitions; archived agents never enter the catalog."""
        return deepcopy(self._agents)

    def get(self, agent_id: str) -> dict | None:
        return deepcopy(next((a for a in self._agents if a["id"] == agent_id), None))

    def legacy_agents(self) -> list[dict]:
        path = get_agents_path().parent / "legacy" / "agents.json"
        if not path.exists():
            return []
        archived = json.loads(path.read_text(encoding="utf-8"))
        active = {a["id"] for a in self._agents}
        return deepcopy([a for a in archived if a["id"] not in active])

    def migrate_legacy(self, agent_id: str) -> dict:
        """Explicitly import one archived definition; keep its stable identity."""
        original = next((a for a in self.legacy_agents() if a["id"] == agent_id), None)
        if original is None:
            raise ValueError("Legacy agent not found or already migrated.")
        role = _CLASS_MIGRATIONS.get(original.get("class_name"), original.get("class_name", "Custom"))
        if role not in {c[0] for c in AGENT_CLASSES}:
            role = "Custom"
        agent = {**original, "class_name": role, "definition_version": 3, "kind": "subagent",
                 "system_prompt": original.get("system_prompt", preset_prompt(role)),
                 "when_to_call": original.get("when_to_call", CLASS_GUIDANCE.get(role, "")),
                 "when_not_to_call": original.get("when_not_to_call", ""),
                 "routing_examples": original.get("routing_examples", []),
                 "routable": False, "revision": original.get("revision", 0) + 1,
                 "built_in": False, "migrated_at": datetime.now(timezone.utc).isoformat()}
        self._validate(agent)
        self._agents.append(agent)
        self._save()
        return deepcopy(agent)

    def delete_legacy(self, agent_id: str) -> dict:
        """Remove an inactive archived definition, leaving active agents and history intact."""
        if self.get(agent_id):
            raise ValueError("This agent is active. Use the active agent controls instead.")
        path = get_agents_path().parent / "legacy" / "agents.json"
        archived = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        removed = next((a for a in archived if a["id"] == agent_id), None)
        if removed is None:
            raise ValueError("Archived agent not found.")
        remaining = [a for a in archived if a["id"] != agent_id]
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(remaining, indent=2), encoding="utf-8")
        temp.replace(path)
        return deepcopy(removed)

    def add(
        self,
        name: str,
        model: str | None,
        system_prompt: str | None,
        tools: list[str] | str,
        class_name: str | None = None,
        when_to_call: str = "",
        when_not_to_call: str = "",
        routing_examples: list[str] | None = None,
        routable: bool | None = None,
    ) -> dict:
        """Create a new custom agent, save it, and return its definition."""
        agent_def = {
            "id": secrets.token_hex(3),
            "name": name,
            "model": model or None,
            "system_prompt": preset_prompt(class_name or DEFAULT_CLASS) if system_prompt is None else system_prompt,
            "tools": tools,
            "class_name": class_name or DEFAULT_CLASS,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "when_to_call": when_to_call,
            "when_not_to_call": when_not_to_call,
            "routing_examples": routing_examples or [],
            "routable": bool(when_to_call) if routable is None else routable,
            "revision": 1,
            "definition_version": 3,
            "kind": "subagent",
        }
        self._validate(agent_def)
        self._agents.append(agent_def)
        self._save()
        return deepcopy(agent_def)

    def update(self, agent_id: str, **kwargs) -> dict:
        """Update fields of an agent. Built-in QuestChain can be edited but not deleted."""
        allowed = {"name", "model", "system_prompt", "tools", "class_name", "when_to_call",
                   "when_not_to_call", "routing_examples", "routable"}
        if set(kwargs) - allowed:
            raise ValueError("Unknown agent fields: " + ", ".join(sorted(set(kwargs) - allowed)))
        agent = self.get(agent_id)
        if agent is None:
            raise ValueError(f"Agent '{agent_id}' not found.")
        agent.update(kwargs)
        agent["revision"] = agent.get("revision", 0) + 1
        self._validate(agent)
        self._agents = [a for a in self._agents if a["id"] != agent_id] + [agent]
        self._save()
        return deepcopy(agent)

    @staticmethod
    def _validate(agent: dict) -> None:
        for field, maximum in (("name", 80), ("system_prompt", 4000), ("when_to_call", 2000),
                               ("when_not_to_call", 2000)):
            if field == "system_prompt" and agent.get(field) is None:
                continue
            value = agent.get(field) or ""
            if not isinstance(value, str) or len(value) > maximum:
                raise ValueError(f"{field} must be text of at most {maximum} characters.")
            agent[field] = value if field == "system_prompt" else value.strip()
        if not agent["name"]:
            raise ValueError("Name is required.")
        if agent.get("class_name") not in {c[0] for c in AGENT_CLASSES}:
            raise ValueError("Choose an existing role or Custom.")
        if not isinstance(agent.get("routable", False), bool):
            raise ValueError("Automatic routing must be enabled or disabled.")
        if agent.get("routable") and not agent["when_to_call"]:
            raise ValueError("Describe when to call this agent before enabling automatic routing.")
        examples = agent.get("routing_examples", [])
        if not isinstance(examples, list) or len(examples) > 10 or any(
            not isinstance(e, str) or len(e) > 500 for e in examples
        ):
            raise ValueError("Use at most 10 routing examples, each under 500 characters.")
        selected = agent.get("tools", [])
        if selected != "all" and (not isinstance(selected, list) or any(
            not isinstance(t, str) or not t or len(t) > 100 for t in selected
        )):
            raise ValueError("Tools must be a list of tool names or the explicit selection 'all'.")
        if agent.get("model") is not None and (not isinstance(agent["model"], str) or len(agent["model"]) > 200):
            raise ValueError("Model must be a model name.")

    def catalog(self) -> list[dict]:
        """Build a fresh, bounded selection catalog without exposing system prompts."""
        fields = ("id", "name", "class_name", "when_to_call", "when_not_to_call", "routing_examples", "revision")
        return [{**{k: a.get(k) for k in fields}, "tools": a.get("tools", [])}
                for a in self.all_agents() if a.get("routable") and a.get("when_to_call")
                and a.get("kind") == "subagent" and not tool_issues(a)]

    def remove(self, agent_id: str) -> bool:
        if agent_id == self.get_active_id():
            raise ValueError("The main assistant cannot be deleted.")
        if len(self._agents) <= 1 and self.get(agent_id):
            raise ValueError("Keep at least one agent, or create a replacement first.")
        active_id = self.get_active_id()
        original_len = len(self._agents)
        self._agents = [a for a in self._agents if a["id"] != agent_id]
        if len(self._agents) == original_len:
            return False
        self._save()
        if active_id == agent_id:
            self.set_active(self.get_active_id())
        return True

    def get_active(self) -> dict:
        agent = self.get(self.get_active_id())
        if agent is None:
            raise ValueError("No active agents. Initialize the starter roster first.")
        return agent

    def get_active_id(self) -> str:
        main = next((a for a in self._agents if a.get("kind") == "main"), None)
        return main["id"] if main else "main"

    def get_by_class_name(self, class_name: str) -> dict | None:
        """Return the first agent with the given class_name, or None."""
        return deepcopy(next(
            (a for a in self._agents if a.get("class_name") == class_name),
            None,
        ))

    def seed_preset_agents(self) -> None:
        """The versioned migration seeds the complete roster atomically."""
        return

    def set_active(self, agent_id: str) -> None:
        if agent_id != self.get_active_id():
            raise ValueError("Subagents cannot be direct chat destinations.")
        path = get_active_agent_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(agent_id, encoding="utf-8")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        from questchain.migration import migrate_roster
        self._agents = migrate_roster(deepcopy(BUILTIN_AGENT), PRESET_AGENTS, CLASS_GUIDANCE)

    def _save(self) -> None:
        path = get_agents_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(self._agents, indent=2), encoding="utf-8")
        temp.replace(path)
