"""QuestChain agent — thin factory that wires the engine together."""

from questchain.config import OLLAMA_MODEL, TAVILY_API_KEY, WORKSPACE_DIR, ensure_memory_dir
from questchain.engine.agent import Agent
from questchain.engine.model import OllamaModel
from questchain.engine.tools import make_registry, wrap_lc_tool
from questchain.engine.skills import SkillsManager
from questchain.engine.builtins import filesystem, shell, planning

SYSTEM_PROMPT = """\
You are {agent_name}, a capable AI assistant running locally via Ollama.

## Rules
- Never hallucinate file contents, URLs, or facts — verify with tools first.
- Coding tasks → use `claude_code`. Need current info → `web_search` then `web_browse`.
- All virtual file paths start with `/` (e.g. `/workspace/memory/ABOUT.md`).
- For complex multi-step tasks, plan with `write_todos` first.
- Confirm before risky or destructive actions.
- Be concise and direct.
"""


def create_questchain_agent(
    model_name: str | None = None,
    system_prompt_override: str | None = None,
    tools_filter: list[str] | None = None,
    skills_filter: list[str] | None = None,
    agent_name: str = "QuestChain",
    on_audio=None,
    injected_files=None,
    personality_hint: str = "",
    # Legacy params accepted but unused (kept for call-site compatibility)
    checkpointer=None,
    store=None,
) -> Agent:
    """Create the QuestChain agent.

    Args:
        model_name: Ollama model to use. Defaults to config value.
        system_prompt_override: Replace the default SYSTEM_PROMPT when set.
        tools_filter: Restrict custom tools to this subset by name; None = all.
        skills_filter: Restrict skills to this subset by dir-name; None = all.
        agent_name: Display name injected into the system prompt.
        on_audio: TTS callback for the speak tool.
    """
    model_name = model_name or OLLAMA_MODEL
    model = OllamaModel(model_name)

    ensure_memory_dir()

    # Built-in tools
    builtin_fns = [
        filesystem.read_file,
        filesystem.write_file,
        filesystem.edit_file,
        filesystem.ls,
        filesystem.glob,
        filesystem.grep,
        shell.execute,
        planning.write_todos,
        planning.read_todos,
    ]

    # Skills (lazy-loaded on demand by the agent; filtered per agent def)
    skills = SkillsManager(skills_filter=skills_filter)

    # Registry: builtins + read_skill
    registry = make_registry(*builtin_fns, skills.make_read_skill_tool())

    # Custom tools (web, claude_code, speak, cron) — bridged from LangChain
    from questchain.tools import get_custom_tools
    lc_tools = get_custom_tools(TAVILY_API_KEY, on_audio=on_audio, tools_filter=tools_filter)
    for lc_tool in lc_tools:
        registry.register(wrap_lc_tool(lc_tool))

    system_prompt = (system_prompt_override or SYSTEM_PROMPT).format(agent_name=agent_name)

    return Agent(
        model=model,
        tools=registry,
        skills=skills,
        system_prompt=system_prompt,
        agent_name=agent_name,
        injected_files=injected_files,
        personality_hint=personality_hint,
    )


def make_agent_from_def(agent_def: dict, audio_router=None) -> "Agent":
    """Create a QuestChain agent from an agent definition dict.

    Moved here from cli.py so quest_runner.py and scheduler.py can import it
    without creating a circular dependency through cli.py.
    """
    from pathlib import Path
    from questchain.progression import ProgressionManager, level_personality
    skills_raw = agent_def.get("skills")  # None/"all" → all; list → filtered
    skills_filter = None if (skills_raw is None or skills_raw == "all") else skills_raw

    # profile.md is injected into every agent; ABOUT.md only for the default agent.
    memory_dir = WORKSPACE_DIR / "workspace" / "memory"
    injected_files = [memory_dir / "profile.md"]
    if agent_def.get("id") == "default":
        injected_files.append(memory_dir / "ABOUT.md")

    pm = ProgressionManager(
        agent_def.get("id", "default"),
        agent_def.get("class_name", "Custom"),
    )
    record = pm.load()
    hint = level_personality(record.level)

    return create_questchain_agent(
        model_name=agent_def.get("model"),
        on_audio=audio_router,
        system_prompt_override=agent_def.get("system_prompt"),
        tools_filter=None if agent_def.get("tools") == "all" else agent_def.get("tools"),
        skills_filter=skills_filter,
        agent_name=agent_def.get("name", "QuestChain"),
        injected_files=injected_files,
        personality_hint=hint,
    )
