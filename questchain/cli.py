"""QuestChain terminal UI and REPL loop."""

import asyncio
import random
import shutil
import uuid

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.filters import Condition
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

_SEP = "─"

from questchain import __version__
from questchain.agent import create_questchain_agent, make_agent_from_def
from questchain.agents import AGENT_CLASSES, AgentManager, BUILTIN_AGENT, CLASS_COLORS, CLASS_SKILL_PRESETS, CLASS_TOOL_PRESETS, DEFAULT_CLASS, SELECTABLE_TOOLS, SKILL_CLASS_RESTRICTIONS, SKILL_REQUIRED_TOOLS
from questchain.progression import ProgressionManager, TOTAL_ACHIEVEMENTS, XPGrant, level_personality
from questchain.stats import MetricsManager
from questchain.config import (
    DEFAULT_BUSY_WORK_MINUTES,
    OLLAMA_MODEL,
    TAVILY_API_KEY,
    get_history_path,
)
from questchain.onboarding import (
    QUESTCHAIN_ART, TAGLINES,
    clear_onboarded, is_onboarded, run_onboarding,
    is_overnight_onboarded, run_overnight_onboarding,
    run_setup_claude_code,
)
from questchain.memory.store import get_thread_history
from questchain.models import check_ollama_connection, list_available_models, wait_for_ollama

console = Console()

_progression: ProgressionManager | None = None
_metrics: MetricsManager | None = None


def _get_class_display(class_name: str) -> str:
    """Return 'icon Name' for a class, e.g. '🔭 Scout'."""
    for cname, icon, _ in AGENT_CLASSES:
        if cname == class_name:
            return f"{icon} {cname}"
    return class_name


def _build_agent_label(agent_def: dict, prog: ProgressionManager | None) -> str:
    """Return a Rich-markup label like '[cyan]Aria[/cyan] · Lv.3 🔭 Scout'."""
    name = agent_def.get("name", "QuestChain")
    class_name = agent_def.get("class_name", DEFAULT_CLASS)
    class_display = _get_class_display(class_name)
    color = CLASS_COLORS.get(class_name, "bright_white")
    record = prog.get_record() if prog is not None else None
    level = record.level if record is not None else 1
    prestige_badge = (" [bold yellow]" + "✦" * record.prestige + "[/bold yellow]") if (record is not None and record.prestige) else ""
    return f"[{color}]{name}[/{color}][dim] · Lv.{level} {class_display}[/dim]{prestige_badge}"


def _init_progression(agent_def: dict) -> ProgressionManager:
    """Load (or create) the ProgressionManager for *agent_def* and set the global."""
    global _progression
    agent_id = agent_def.get("id", "default")
    class_name = agent_def.get("class_name", DEFAULT_CLASS)
    _progression = ProgressionManager(agent_id, class_name)
    _progression.load()
    return _progression


def _init_metrics(agent_def: dict, agent) -> MetricsManager:
    """Load (or create) the MetricsManager for *agent_def* and set the global."""
    global _metrics
    mm = MetricsManager(agent_def.get("id", "default"))
    mm.load()
    mm.update_static(
        model_name=agent.model.model_name,
        num_tools=len(agent.tools),
        num_skills=len(agent.skills),
        context_window=agent.model.num_ctx,
    )
    try:
        mm.fetch_model_info()
    except Exception:
        pass
    _metrics = mm
    return mm


async def _user_prompt(session: PromptSession, agent_label: str = "") -> str:
    """Render the framed input box and return the user's raw input."""
    width = shutil.get_terminal_size().columns
    if agent_label:
        console.rule(agent_label, style="dim", characters=_SEP)
    else:
        console.print(_SEP * width, style="dim")
    result = await session.prompt_async("❯ ")
    console.print(_SEP * width, style="dim")
    return result


async def _play_audio(wav_bytes: bytes) -> None:
    """Play WAV bytes on laptop speakers using sounddevice."""
    import io
    import wave

    import numpy as np
    import sounddevice as sd

    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        sample_rate = wf.getframerate()
        n_channels = wf.getnchannels()
        frames = wf.readframes(wf.getnframes())

    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32767.0
    if n_channels > 1:
        audio = audio.reshape(-1, n_channels)

    sd.play(audio, samplerate=sample_rate)
    sd.wait()


class _AudioRouter:
    """Routes TTS audio to CLI speakers or a Telegram voice message.

    Call set_telegram(update) before Telegram-originated agent invocations
    and set_cli() before CLI-originated ones so the speak tool always reaches
    the right destination.
    """

    def __init__(self):
        self._source = "cli"
        self._update = None

    def set_telegram(self, update) -> None:
        self._source = "telegram"
        self._update = update

    def set_cli(self) -> None:
        self._source = "cli"
        self._update = None

    async def __call__(self, wav_bytes: bytes) -> None:
        if self._source == "telegram" and self._update is not None:
            import io
            await self._update.message.reply_voice(voice=io.BytesIO(wav_bytes))
        else:
            await _play_audio(wav_bytes)


def _make_agent_from_def(agent_def: dict, audio_router=None, **_ignored) -> object:
    """Create a QuestChain agent from an agent definition dict."""
    return make_agent_from_def(agent_def, audio_router)


def print_banner(model_name: str):
    """Display the QuestChain welcome banner."""
    banner = Text()
    for line in QUESTCHAIN_ART.strip("\n").splitlines():
        banner.append(line + "\n", style="bold blue")
    banner.append("\n")
    banner.append("  🔗 ", style="bold")
    banner.append(random.choice(TAGLINES), style="italic cyan")
    banner.append("\n\n")
    banner.append(f"  v{__version__}", style="dim")
    banner.append("  |  ", style="dim")
    banner.append(f"Model: {model_name}", style="cyan")
    banner.append("\n")
    if TAVILY_API_KEY:
        banner.append("  Web search: enabled", style="blue")
    else:
        banner.append("  Web search: disabled  ", style="yellow")
        banner.append("/tavily to set up", style="dim")
    banner.append("\n")
    from questchain.tools import is_claude_code_available
    if is_claude_code_available():
        banner.append("  Claude Code: enabled", style="blue")
    else:
        banner.append("  Claude Code: disabled  ", style="yellow")
        banner.append("/claudecode to set up", style="dim")
    banner.append("\n")
    banner.append("  Type /help for commands, Ctrl+D to exit", style="dim")
    console.print(Panel(banner, border_style="blue", padding=(1, 2)))


def print_tool_call(tool_name: str, tool_input: dict):
    """Display a tool call indicator."""
    console.print(f"  [dim]> Using tool:[/dim] [cyan]{tool_name}[/cyan]")


def print_level_up(grant: XPGrant, class_name: str) -> None:
    """Display a dramatic level-up panel."""
    from rich.text import Text as RichText
    class_display = _get_class_display(class_name)
    t = RichText()
    t.append(f"⚔  LEVEL UP — Level {grant.new_level}", style="bold yellow")
    t.append(f"  ·  {class_display}", style="yellow")
    console.print(Panel(t, border_style="yellow", padding=(1, 2)))


def print_achievement_unlock(achievement) -> None:
    """Display a single achievement unlock notification."""
    console.print(
        f"  [bold yellow]✦[/bold yellow] Achievement unlocked: "
        f"[bold]{achievement.name}[/bold] — {achievement.description}"
    )


async def show_stats(agent_def: dict) -> None:
    """Render a stats panel for the given agent definition."""
    agent_id = agent_def.get("id", "default")
    class_name = agent_def.get("class_name", DEFAULT_CLASS)
    pm = ProgressionManager(agent_id, class_name)
    record = pm.load()

    class_display = _get_class_display(record.class_name)

    # XP progress bar (20 chars wide)
    bar_width = 20
    if record.xp_next_level > 0:
        level_span = record.xp_this_level + record.xp_next_level
        filled = int(bar_width * record.xp_this_level / level_span) if level_span else 0
        xp_display = f"{record.xp_this_level}/{level_span} XP to Lv.{record.level + 1}"
    else:
        filled = bar_width
        xp_display = "MAX LEVEL"
    bar = "█" * filled + "░" * (bar_width - filled)

    top_tools = sorted(record.tool_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    prestige_badge = (" [bold yellow]" + "✦" * record.prestige + "[/bold yellow]") if record.prestige else ""
    lines: list[str] = [
        f"[bold]{agent_def.get('name', 'QuestChain')}[/bold]  ·  {class_display}  ·  [bold cyan]Level {record.level}[/bold cyan]{prestige_badge}",
        f"  [{bar}]  {xp_display}",
        f"  Total XP: [cyan]{record.total_xp}[/cyan]   Turns: [cyan]{record.turns_completed}[/cyan]   Busy-work: [cyan]{record.busy_work_completed}[/cyan]",
    ]
    if record.current_streak > 1:
        streak_bonus = " [bold yellow](+50% XP)[/bold yellow]" if record.current_streak >= 7 else ""
        lines.append(f"  🔥 Streak: [bold orange1]{record.current_streak}[/bold orange1] days{streak_bonus}")
    if top_tools:
        lines.append("")
        lines.append("[bold]Top tools:[/bold]")
        for tool, count in top_tools:
            lines.append(f"  {tool}: {count}")
    lines.append("")
    ach_count = len(record.achievements)
    lines.append(f"[bold]Achievements ({ach_count}/{TOTAL_ACHIEVEMENTS}):[/bold]")
    if record.achievements:
        for a in record.achievements:
            lines.append(
                f"  [bold yellow]★[/bold yellow] {a.name} — {a.description}"
                f"  [dim]{a.earned_at[:10]}[/dim]"
            )
    else:
        lines.append("  [dim]None yet — start chatting![/dim]")

    console.print(Panel("\n".join(lines), title="📊 Level", border_style="cyan"))


def _birthday_message(days: int) -> str:
    msgs = {
        30:  "🎂 30 days old! Your agent has been running for a whole month.",
        100: "🎂 100 days! A hundred-day milestone of being awesome.",
        365: "🎂 One year together! Your agent has been with you for a full year.",
    }
    return msgs.get(days, f"🎂 {days}-day milestone!")


async def _handle_prestige(session: PromptSession) -> None:
    """Handle the /prestige command."""
    if _progression is None or not _progression.can_prestige():
        console.print("[yellow]Prestige is only available at Level 20.[/yellow]")
        return
    record = _progression.get_record()
    console.print(Panel(
        f"[bold yellow]⚡ PRESTIGE[/bold yellow]\n\n"
        f"You are Level 20. Prestige resets you to Level 1 but grants a "
        f"[bold]✦ Prestige {record.prestige + 1}[/bold] badge.\n"
        f"Your achievements and tools are kept.",
        border_style="yellow",
    ))
    confirm = await _prompt_line(session, "Type PRESTIGE to confirm, or Enter to cancel: ")
    if confirm.strip().upper() == "PRESTIGE":
        _progression.do_prestige()
        console.print("[bold yellow]✦ Prestige complete! You are Level 1 again.[/bold yellow]")
    else:
        console.print("[dim]Cancelled.[/dim]")


def show_metrics(mm: MetricsManager) -> None:
    """Render a metrics panel for the given MetricsManager."""
    rec = mm.get_record()
    model_line = rec.model_name
    if rec.model_params:
        model_line += f"  ·  {rec.model_params}"
    if rec.model_size_gb:
        model_line += f"  ·  {rec.model_size_gb} GB"
    lines = [
        f"[bold]Model[/bold]         {model_line}",
        f"[bold]Context[/bold]       {rec.context_window:,} tokens",
        f"[bold]Tools[/bold]         {rec.num_tools} registered",
        f"[bold]Skills[/bold]        {rec.num_skills} available",
        "",
        f"[bold]Prompts[/bold]          {rec.prompt_count}",
        f"[bold]Tokens used[/bold]      ~{rec.tokens_used:,}",
        f"[bold]Total errors[/bold]     {rec.total_errors}",
        f"[bold]Highest Chain[/bold]  {rec.highest_chain} tool loops",
    ]
    console.print(Panel("\n".join(lines), title="[bold]⚙  Agent Stats[/bold]", border_style="cyan"))


# Sorted list of (command, description) pairs shown in the autocomplete dropdown.
_SLASH_COMMANDS: list[tuple[str, str]] = [
    ("/agents",       "Manage agent profiles (list, switch, create, edit)"),
    ("/busy",         "Show busy work scheduler status"),
    ("/claudecode",   "Set up Claude Code CLI integration"),
    ("/clear",        "Clear the screen"),
    ("/cron",         "List scheduled cron jobs"),
    ("/exit",         "Exit QuestChain"),
    ("/help",         "Show all available commands"),
    ("/history",      "Show past conversations with timestamps"),
    ("/instructions", "Show the agent's system prompt"),
    ("/level",        "Show agent level and achievements"),
    ("/memory",       "Show your saved user profile"),
    ("/model",        "Show current model and list available ones"),
    ("/new",          "Start a fresh conversation"),
    ("/onboard",      "Re-run the onboarding conversation"),
    ("/overnight",    "Add a task to tonight's Night Owl queue (prompts for task)"),
    ("/prestige",     "Prestige reset — reach Level 20 to unlock"),
    ("/quit",         "Exit QuestChain"),
    ("/stats",        "Show agent metrics (prompts, tokens, errors)"),
    ("/quest",        "Manage quests — one-off tasks for the agent to complete"),
    ("/tavily",       "Set up Tavily web search API key"),
    ("/telegram",     "Set up Telegram bot credentials"),
    ("/thread",       "Show current conversation thread ID"),
    ("/tools",        "List all available agent tools"),
]


class _SlashCompleter(Completer):
    """Autocomplete slash commands with inline descriptions."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        word = text.lower()
        for cmd, desc in _SLASH_COMMANDS:
            if cmd.startswith(word):
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display=cmd,
                    display_meta=desc,
                )


# ── Completion dropdown style (dark background, blue highlight) ───────────────

_COMPLETION_STYLE = Style.from_dict({
    "completion-menu":                         "bg:#1e1e2e #cdd6f4",
    "completion-menu.completion":              "bg:#1e1e2e #cdd6f4",
    "completion-menu.completion.current":      "bg:#1d6fbd #ffffff bold",
    "completion-menu.meta.completion":         "bg:#2a2a3e #7f849c",
    "completion-menu.meta.completion.current": "bg:#1a5fa8 #cdd6f4",
    "scrollbar.background":                    "bg:#313244",
    "scrollbar.button":                        "bg:#6c7086",
})


def _completions_visible() -> bool:
    """True when the autocomplete menu is open with any completions."""
    from prompt_toolkit.application import get_app
    try:
        state = get_app().current_buffer.complete_state
        return state is not None and bool(state.completions)
    except Exception:
        return False


def _typing_slash() -> bool:
    """True when the current input starts with '/'."""
    from prompt_toolkit.application import get_app
    try:
        return get_app().current_buffer.text.startswith("/")
    except Exception:
        return False


_slash_kb = KeyBindings()


@_slash_kb.add("enter", filter=Condition(_completions_visible), eager=True)
def _enter_accept_completion(event):
    """Accept the highlighted completion (or first if none highlighted) then submit."""
    buf = event.current_buffer
    state = buf.complete_state
    completion = state.current_completion
    if completion is None and state.completions:
        completion = state.completions[0]
    if completion is not None:
        buf.apply_completion(completion)
    buf.validate_and_handle()


@_slash_kb.add("backspace", filter=Condition(_typing_slash), eager=True)
def _backspace_reopen_menu(event):
    """Delete one char and re-trigger completions if still in a slash command."""
    buf = event.current_buffer
    buf.delete_before_cursor()
    if buf.text.startswith("/"):
        buf.start_completion(select_first=False)


def handle_command(command: str, session_state: dict) -> bool | None:
    """Handle slash commands.

    Returns:
        True to continue REPL, False to exit, None if not a command.
    """
    cmd = command.strip().lower()

    if cmd == "/quit" or cmd == "/exit":
        console.print("[dim]Goodbye![/dim]")
        return False

    if cmd == "/clear":
        console.clear()
        return True

    if cmd == "/new":
        session_state["thread_id"] = str(uuid.uuid4())
        console.print(f"[blue]New session started.[/blue] Thread: [dim]{session_state['thread_id']}[/dim]")
        return True

    if cmd == "/model":
        console.print(f"[cyan]Current model:[/cyan] {session_state['model_name']}")
        models = list_available_models()
        if models:
            console.print("[cyan]Available on Ollama:[/cyan]")
            for m in models:
                console.print(f"  - {m}")
        return True

    if cmd == "/thread":
        console.print(f"[cyan]Thread ID:[/cyan] {session_state['thread_id']}")
        return True

    if cmd == "/busy":
        runner = session_state.get("busy_work_runner")
        if runner and runner.running:
            console.print(f"[blue]Busy work:[/blue] active (every {runner.interval_minutes} min)")
        else:
            console.print("[yellow]Busy work:[/yellow] disabled")
        return True

    if cmd == "/tools":
        from questchain.config import TAVILY_API_KEY
        text = (
            "[bold]Built-in tools[/bold] (filesystem, shell, planning, sub-agents):\n"
            "  read_file, write_file, edit_file, ls, glob, grep\n"
            "  execute, write_todos, read_todos, task\n"
            "\n[bold]Custom tools:[/bold]\n"
            "  claude_code — delegate coding tasks to Claude Code\n"
            "  cron_add, cron_list, cron_remove — scheduled jobs (Telegram)\n"
        )
        if TAVILY_API_KEY:
            text += "  web_search, web_browse — [blue]enabled[/blue]\n"
        else:
            text += "  web_search, web_browse — [yellow]disabled (no TAVILY_API_KEY)[/yellow]\n"
        console.print(Panel(text, title="Tools", border_style="cyan"))
        return True

    if cmd == "/instructions":
        from questchain.agent import SYSTEM_PROMPT
        console.print(Panel(SYSTEM_PROMPT, title="System Instructions", border_style="cyan"))
        return True

    if cmd == "/memory":
        from questchain.config import MEMORY_DIR
        about = MEMORY_DIR / "ABOUT.md"
        if about.exists():
            console.print(Panel(about.read_text(encoding="utf-8"), title="Memory — ABOUT.md", border_style="cyan"))
        else:
            console.print("[dim]No memory file yet. Run /onboard to create one.[/dim]")
        return True

    if cmd == "/quest":
        session_state["run_quest_menu"] = True
        return True

    if cmd == "/cron":
        import json
        from questchain.config import get_cron_jobs_path
        jobs_path = get_cron_jobs_path()
        jobs = []
        if jobs_path.exists():
            try:
                jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        if jobs:
            lines = []
            for j in jobs:
                status = "[blue]on[/blue]" if j.get("enabled", True) else "[dim]off[/dim]"
                lines.append(f"  [{j['id']}] {j['name']} — {j['cron_expression']} ({status})")
            console.print(Panel("\n".join(lines), title="Cron Jobs", border_style="cyan"))
        else:
            console.print("[dim]No cron jobs configured.[/dim]")
        return True

    if cmd == "/onboard":
        clear_onboarded()
        session_state["run_onboard"] = True
        return True

    if cmd == "/tavily":
        session_state["run_setup_tavily"] = True
        return True

    if cmd == "/claudecode":
        session_state["run_setup_claudecode"] = True
        return True

    if cmd == "/telegram":
        session_state["run_setup_telegram"] = True
        return True

    if cmd == "/agents":
        session_state["run_agent_menu"] = True
        return True

    if cmd == "/overnight":
        from questchain.config import WORKSPACE_DIR
        overnight_path = WORKSPACE_DIR / "workspace" / "overnight.md"
        if not overnight_path.exists():
            console.print("[yellow]overnight.md not found — switch to Night Owl first to set up.[/yellow]")
            return True
        session_state["run_overnight_queue"] = True
        return True

    if cmd == "/prestige":
        session_state["run_prestige"] = True
        return True

    if cmd == "/level":
        session_state["run_level"] = True
        return True

    if cmd == "/stats":
        session_state["run_stats_metrics"] = True
        return True

    if cmd == "/history":
        session_state["run_history"] = True
        return True

    if cmd == "/help":
        help_text = (
            "[bold]Commands:[/bold]\n"
            "  /new                   - Start a new conversation\n"
            "  /model                 - Show current model and available models\n"
            "  /thread                - Show current thread ID\n"
            "  /busy                  - Show busy work status\n"
            "  /tools                 - List available tools\n"
            "  /instructions          - Show agent system prompt\n"
            "  /memory                - Show your saved user profile\n"
            "  /quest                 - Manage quests (one-off agent tasks)\n"
            "  /cron                  - List scheduled cron jobs\n"
            "  /onboard               - Re-run the onboarding flow\n"
            "  /overnight             - Add a task to Night Owl's queue\n"
            "  /tavily                - Set up Tavily web search API key\n"
            "  /claudecode            - Set up Claude Code CLI integration\n"
            "  /telegram              - Set up Telegram bot credentials\n"
            "  /agents                - Manage agents (list, switch, create)\n"
            "  /level                 - Show agent level and achievements\n"
            "  /prestige              - Prestige reset (requires Level 20)\n"
            "  /stats                 - Show agent metrics (prompts, tokens, errors)\n"
            "  /history               - Show past conversations with timestamps\n"
            "  /clear                 - Clear the screen\n"
            "  /quit                  - Exit QuestChain\n"
            "  /help                  - Show this help message"
        )
        console.print(Panel(help_text, title="Help", border_style="blue"))
        return True

    return None


async def _prompt_line(session: PromptSession, prompt_text: str) -> str:
    """Prompt for a line of input, returning stripped text."""
    try:
        return (await session.prompt_async(prompt_text)).strip()
    except (EOFError, KeyboardInterrupt):
        return ""


async def _inline_file_editor(file_path, title: str) -> bool:
    """Open *file_path* in a prompt_toolkit full-screen text editor.

    Returns True if the file was saved, False if cancelled.
    Ctrl+S saves, Ctrl+G opens the system editor, Esc cancels.
    """
    from prompt_toolkit import Application
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit, Window, FloatContainer, Float
    from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style as PTStyle
    from pathlib import Path

    path = Path(file_path)
    initial_text = path.read_text(encoding="utf-8") if path.exists() else ""

    buf = Buffer(text=initial_text, multiline=True, name="editor")
    result: list[bool] = [False]

    kb = KeyBindings()

    @kb.add("c-s")
    def _save(event):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(buf.text, encoding="utf-8")
        result[0] = True
        event.app.exit()

    @kb.add("c-g")
    def _open_system_editor(event):
        import os, tempfile, subprocess
        editor = os.environ.get("EDITOR", "notepad" if os.name == "nt" else "nano")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as tf:
            tf.write(buf.text)
            tmp = tf.name
        def _edit():
            subprocess.call([editor, tmp])
        from prompt_toolkit.application.run_in_terminal import run_in_terminal
        def _run():
            import threading
            t = threading.Thread(target=_edit)
            t.start()
            t.join()
            new_text = Path(tmp).read_text(encoding="utf-8")
            Path(tmp).unlink(missing_ok=True)
            buf.set_document(buf.document.__class__(text=new_text, cursor_position=len(new_text)))
        run_in_terminal(_run)

    @kb.add("escape")
    def _cancel(event):
        event.app.exit()

    header = FormattedTextControl(text=f" Quests: {title} ")
    footer = FormattedTextControl(text=" Ctrl+S to save  ·  Ctrl+G to open in editor  ·  Esc to cancel ")

    layout = Layout(
        HSplit([
            Window(header, height=1, style="class:header"),
            Window(BufferControl(buffer=buf), style="class:editor"),
            Window(footer, height=1, style="class:footer"),
        ])
    )

    style = PTStyle.from_dict({
        "header": "bg:#004080 #ffffff bold",
        "footer": "bg:#333333 #aaaaaa",
        "editor": "bg:#1a1a1a #e0e0e0",
    })

    app = Application(layout=layout, key_bindings=kb, style=style, full_screen=True)
    await app.run_async()
    if result[0]:
        console.print("[green]Saved.[/green]")
    return result[0]


async def _quest_menu(session: PromptSession) -> None:
    """Keyboard-driven quest management menu (arrow keys + Enter)."""
    from prompt_toolkit import Application
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style as PTStyle
    from questchain.config import WORKSPACE_DIR

    quests_dir = WORKSPACE_DIR / "workspace" / "quests"
    quests_dir.mkdir(parents=True, exist_ok=True)

    def _load_quests():
        return sorted(quests_dir.glob("*.md"))

    quest_files = _load_quests()
    state = {"idx": 0, "files": quest_files, "exit": False, "open_editor": None, "new_quest": False, "delete": False}

    def _render():
        lines = [("class:header", " Quests   [n] new  [d] delete  [Esc] close\n")]
        lines.append(("class:sep", " " + "─" * 42 + "\n"))
        files = state["files"]
        if not files:
            lines.append(("class:dim", " No quests yet. Press n to create one.\n"))
        else:
            for i, f in enumerate(files):
                if i == state["idx"]:
                    lines.append(("class:selected", f" ▶ {f.name}\n"))
                else:
                    lines.append(("class:item", f"   {f.name}\n"))
        return lines

    content = FormattedTextControl(text=_render, focusable=True)

    kb = KeyBindings()

    @kb.add("up")
    def _up(event):
        if state["files"] and state["idx"] > 0:
            state["idx"] -= 1
            content.text = _render

    @kb.add("down")
    def _down(event):
        if state["files"] and state["idx"] < len(state["files"]) - 1:
            state["idx"] += 1
            content.text = _render

    @kb.add("enter")
    def _enter(event):
        if state["files"]:
            state["open_editor"] = state["files"][state["idx"]]
            event.app.exit()

    @kb.add("n")
    def _new(event):
        state["new_quest"] = True
        event.app.exit()

    @kb.add("d")
    def _delete(event):
        if state["files"]:
            state["delete"] = True
            event.app.exit()

    @kb.add("escape")
    @kb.add("c-c")
    def _close(event):
        state["exit"] = True
        event.app.exit()

    layout = Layout(Window(content))
    style = PTStyle.from_dict({
        "header":   "bold #aaddff",
        "sep":      "dim",
        "selected": "bg:#004080 #ffffff bold",
        "item":     "#cccccc",
        "dim":      "dim italic",
    })
    app = Application(layout=layout, key_bindings=kb, style=style, full_screen=True)

    while True:
        state["open_editor"] = None
        state["new_quest"] = False
        state["delete"] = False
        state["exit"] = False
        state["files"] = _load_quests()
        if state["idx"] >= len(state["files"]):
            state["idx"] = max(0, len(state["files"]) - 1)
        content.text = _render

        await app.run_async()

        if state["exit"]:
            break

        if state["new_quest"]:
            name = await _prompt_line(session, "Quest name (slug, no spaces): ")
            if name.strip():
                slug = name.strip().rstrip(".md")
                new_path = quests_dir / f"{slug}.md"
                new_path.write_text("", encoding="utf-8")
                await _inline_file_editor(new_path, new_path.name)
            continue

        if state["delete"] and state["files"]:
            target = state["files"][state["idx"]]
            confirm = await _prompt_line(session, f"Delete '{target.name}'? [y/N]: ")
            if confirm.lower() in ("y", "yes"):
                target.unlink(missing_ok=True)
                console.print(f"[red]Deleted[/red] {target.name}")
            continue

        if state["open_editor"]:
            await _inline_file_editor(state["open_editor"], state["open_editor"].name)
            continue

        break


async def _prompt_model_line(session: PromptSession, prompt_text: str) -> str:
    """List installed Ollama models; last choice is custom text entry.

    Returns the selected model name, or "" to keep the caller's default.
    """
    models = list_available_models()
    if not models:
        return await _prompt_line(session, prompt_text)

    console.print()
    for i, m in enumerate(models, 1):
        console.print(f"  {i}. [cyan]{m}[/cyan]")
    custom_idx = len(models) + 1
    console.print(f"  {custom_idx}. [dim]Custom...[/dim]")
    console.print()

    raw = await _prompt_line(session, f"Pick [1-{custom_idx}], Enter=keep default: ")
    if not raw:
        return ""
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(models):
            return models[idx]
        if idx == len(models):
            return await _prompt_line(session, "Model name: ")
    return raw  # typed a name directly


async def run_agent_menu(
    console: Console,
    session: PromptSession,
    agent_manager: AgentManager,
) -> dict | None:
    """Show agent list, switch by number, or create a new one.

    Returns the chosen agent dict to switch to, or None.
    """
    agents = agent_manager.all_agents()
    active_id = agent_manager.get_active_id()

    console.print()
    console.print("[bold]🔗 Agents:[/bold]")
    for i, agent_def in enumerate(agents, 1):
        marker = "*" if agent_def["id"] == active_id else " "
        name = agent_def["name"]
        if agent_def.get("built_in"):
            name += " (built-in)"
        model = agent_def.get("model") or OLLAMA_MODEL
        try:
            pm = ProgressionManager(agent_def["id"], agent_def.get("class_name", DEFAULT_CLASS))
            lv = pm.get_record().level
            level_tag = f"Lv.{lv}"
        except Exception:
            level_tag = "Lv.?"
        console.print(f"  {i}. {marker} [cyan]{name:<28}[/cyan]  {level_tag:<6}  {model}")
    console.print()

    selection_raw = await _prompt_line(
        session, f"Pick [1-{len(agents)}], n=new, Enter=cancel: "
    )
    if not selection_raw:
        console.print("[dim]Cancelled.[/dim]")
        return None

    stripped = selection_raw.strip()

    if stripped.lower() == "n":
        await _run_create_wizard(console, session, agent_manager)
        return None

    if stripped.isdigit():
        idx = int(stripped) - 1
        if 0 <= idx < len(agents):
            return await _agent_action_menu(console, session, agent_manager, agents[idx], active_id)
        else:
            console.print("[yellow]Invalid selection.[/yellow]")
            return None

    console.print("[yellow]Invalid input.[/yellow]")
    return None


async def _agent_action_menu(
    console: Console,
    session: PromptSession,
    agent_manager: AgentManager,
    agent_def: dict,
    active_id: str,
) -> dict | None:
    """Sub-menu shown after the user picks an agent: Switch / Edit / Delete."""
    name = agent_def["name"]
    model = agent_def.get("model") or OLLAMA_MODEL
    is_active = agent_def["id"] == active_id
    is_builtin = agent_def.get("built_in", False)

    console.print()
    suffix = "  [dim](active)[/dim]" if is_active else ""
    console.print(f"[bold]{name}[/bold]  [dim]{model}[/dim]{suffix}")

    options: list[tuple[str, str]] = []
    if not is_active:
        options.append(("Switch to this agent", "switch"))
    options.append(("Edit", "edit"))
    if not is_builtin:
        options.append(("Delete", "delete"))

    for i, (label, action) in enumerate(options, 1):
        style = "red" if action == "delete" else "cyan"
        console.print(f"  {i}. [{style}]{label}[/{style}]")
    console.print()

    raw = await _prompt_line(session, f"Pick [1-{len(options)}], Enter=cancel: ")
    if not raw or not raw.isdigit():
        console.print("[dim]Cancelled.[/dim]")
        return None

    choice = int(raw) - 1
    if not (0 <= choice < len(options)):
        console.print("[yellow]Invalid selection.[/yellow]")
        return None

    action = options[choice][1]

    if action == "switch":
        console.print(f"[blue]🔗 Switched to '[bold]{name}[/bold]'.[/blue]")
        return agent_def

    if action == "edit":
        await _run_edit_wizard(console, session, agent_manager, agent_def)
        # If the edited agent is currently active, return the updated def so
        # the caller rebuilds agent_holder["agent"] with the new settings.
        if is_active:
            return agent_manager.get(agent_def["id"])
        return None

    if action == "delete":
        confirm = await _prompt_line(session, f"Delete '{name}'? [y/N]: ")
        if confirm.lower() in ("y", "yes"):
            agent_manager.remove(agent_def["id"])
            console.print(f"[red]✓ Agent '[bold]{name}[/bold]' deleted.[/red]")
        else:
            console.print("[dim]Cancelled.[/dim]")
        return None

    return None


def _get_available_skills(
    tools: list[str] | str | None = None,
    class_name: str | None = None,
) -> list[tuple[str, str]]:
    """Return [(name, description)] for skills compatible with the given tool set and class.

    Filters out skills whose required tools are missing and skills restricted to
    other agent classes.
    """
    from questchain.engine.skills import SkillsManager
    sm = SkillsManager()
    result = []
    for s in sm.list_skills():
        # Class restriction: skip if this skill is locked to other classes
        allowed_classes = SKILL_CLASS_RESTRICTIONS.get(s.name)
        if allowed_classes is not None and class_name not in allowed_classes:
            continue
        # Tool requirement: skip if a required tool isn't in the selected set
        if tools is not None and tools != "all":
            if not all(t in tools for t in SKILL_REQUIRED_TOOLS.get(s.name, [])):
                continue
        result.append((s.name, s.description))
    return result


def _tool_availability_tag(tool_name: str) -> str:
    """Return a Rich markup tag like ' [dim](no API key)[/dim]' if a tool needs setup."""
    from questchain.config import TAVILY_API_KEY
    from questchain.tools import is_claude_code_available
    if tool_name in ("web_search", "web_browse") and not TAVILY_API_KEY:
        return "  [dim](no Tavily key — /tavily)[/dim]"
    if tool_name == "claude_code" and not is_claude_code_available():
        return "  [dim](claude not found — /claudecode)[/dim]"
    return ""


def _parse_skill_selection(raw: str, available: list[tuple[str, str]], fallback) -> list[str] | None:
    """Parse comma-separated skill indices from raw input.

    Returns a list of skill names, or *fallback* if nothing valid was parsed.
    """
    selected: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(available):
                selected.append(available[idx][0])
    return selected if selected else fallback


def _parse_tool_selection(raw: str, fallback) -> list[str] | str:
    """Parse comma-separated tool indices from raw input.

    Returns a list of tool names, or *fallback* if nothing valid was parsed.
    """
    selected: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(SELECTABLE_TOOLS):
                selected.append(SELECTABLE_TOOLS[idx][0])
    return selected if selected else fallback


async def _ask_skills(
    session: PromptSession,
    console: Console,
    class_name: str,
    current_skills,
    tools: list[str] | str | None = None,
) -> list[str] | None:
    """Prompt the user to select skills for an agent.

    Only skills whose required tools are present in *tools* are shown.
    Returns a list of skill names (possibly empty), or None meaning "all".
    *current_skills* is the existing value to fall back to on Enter.
    """
    available = _get_available_skills(tools, class_name)
    if not available:
        return []  # no applicable skills for these tools

    console.print()
    console.print("[bold]Skills[/bold] (loaded into agent context on demand):")
    for i, (skill_name, desc) in enumerate(available, 1):
        console.print(f"  {i}. [cyan]{skill_name}[/cyan] — {desc}")
    console.print()

    if current_skills is None or current_skills == "all":
        current_display = "all"
    else:
        current_display = ", ".join(current_skills) if current_skills else "none"

    raw = await _prompt_line(
        session, f"Select skills (numbers, 'none', Enter=all) current=[{current_display}]: "
    )
    if raw.strip() == "":
        return None  # all
    if raw.strip().lower() == "none":
        return []    # no skills
    return _parse_skill_selection(raw, available, current_skills)


async def _run_create_wizard(
    console: Console,
    session: PromptSession,
    agent_manager: AgentManager,
) -> dict | None:
    """Inline create wizard for a new agent."""
    console.print()
    console.print(Panel("[bold]Create a new agent[/bold]", border_style="blue"))

    name = await _prompt_line(session, "Agent name: ")
    if not name:
        console.print("[yellow]Cancelled.[/yellow]")
        return None

    model_raw = await _prompt_model_line(session, f"Model [{OLLAMA_MODEL}]: ")
    model = model_raw if model_raw else None

    console.print()
    console.print("[bold]Agent class:[/bold]")
    for i, (cname, icon, desc) in enumerate(AGENT_CLASSES, 1):
        console.print(f"  {i}. {icon} [cyan]{cname}[/cyan] — {desc}")
    class_raw = await _prompt_line(session, f"Pick [1-{len(AGENT_CLASSES)}], Enter={DEFAULT_CLASS}: ")
    chosen_class = DEFAULT_CLASS
    if class_raw.isdigit():
        idx = int(class_raw) - 1
        if 0 <= idx < len(AGENT_CLASSES):
            chosen_class = AGENT_CLASSES[idx][0]

    preset = CLASS_TOOL_PRESETS.get(chosen_class)
    if preset is None:
        # Custom: user configures tools manually
        console.print()
        console.print("[bold]Custom tools[/bold] (filesystem/shell/planning always included):")
        for i, (tool_name, description) in enumerate(SELECTABLE_TOOLS, 1):
            tag = _tool_availability_tag(tool_name)
            console.print(f"  {i}. [cyan]{tool_name}[/cyan] — {description}{tag}")
        console.print()
        include_all_raw = await _prompt_line(session, "Include all tools? [Y/n or numbers]: ")
        if include_all_raw.lower() in ("", "y", "yes"):
            tools: list[str] | str = "all"
        elif include_all_raw.lower() in ("n", "no"):
            selection_raw = await _prompt_line(session, "Select (comma-separated numbers): ")
            tools = _parse_tool_selection(selection_raw, "all")
        else:
            tools = _parse_tool_selection(include_all_raw, "all")
    else:
        tools = preset
        preset_names = ", ".join(preset) if preset else "built-in only"
        console.print(f"  [dim]Tools preset for {chosen_class}: {preset_names}[/dim]")

    skills = await _ask_skills(session, console, chosen_class, None, tools)

    console.print()
    console.print("System prompt (Enter for default QuestChain prompt):")
    prompt_raw = await _prompt_line(session, "> ")
    system_prompt = prompt_raw if prompt_raw else None

    agent_def = agent_manager.add(name, model, system_prompt, tools, class_name=chosen_class, skills=skills)
    console.print()
    console.print(f"[blue]✓ Agent '[bold]{name}[/bold]' created.[/blue] Use [cyan]/agents[/cyan] to activate it.")
    return agent_def


async def _run_edit_wizard(
    console: Console,
    session: PromptSession,
    agent_manager: AgentManager,
    agent_def: dict,
) -> None:
    """Inline edit wizard for an existing agent. Enter keeps the current value."""
    name = agent_def["name"]
    console.print()
    console.print(Panel(f"[bold]Editing '{name}'[/bold] — Enter to keep current value.", border_style="blue"))

    name_raw = await _prompt_line(session, f"Name [{name}]: ")
    new_name = name_raw if name_raw else name

    current_model_display = agent_def.get("model") or OLLAMA_MODEL
    model_raw = await _prompt_model_line(session, f"Model [{current_model_display}]: ")
    new_model = model_raw if model_raw else agent_def.get("model")

    current_tools = agent_def.get("tools", "all")
    if current_tools == "all":
        current_tools_display = "all"
    else:
        current_tools_display = ", ".join(current_tools) if current_tools else "none"

    # Show class preset hint
    _edit_class_for_hint = agent_def.get("class_name", DEFAULT_CLASS)
    _preset = CLASS_TOOL_PRESETS.get(_edit_class_for_hint)
    _preset_hint = (
        f"  [dim]Class preset ({_edit_class_for_hint}): {', '.join(_preset) if _preset else 'built-in only'}[/dim]"
        if _preset is not None else ""
    )

    console.print()
    console.print("[bold]Custom tools[/bold] (filesystem/shell/planning always included):")
    if _preset_hint:
        console.print(_preset_hint)
    for i, (tool_name, description) in enumerate(SELECTABLE_TOOLS, 1):
        tag = _tool_availability_tag(tool_name)
        console.print(f"  {i}. [cyan]{tool_name}[/cyan] — {description}{tag}")
    console.print()

    include_all_raw = await _prompt_line(
        session, f"Include all tools? current=[{current_tools_display}] [Y/n or numbers]: "
    )
    if include_all_raw.lower() in ("", "y", "yes"):
        new_tools: list[str] | str = "all"
    elif include_all_raw.lower() in ("n", "no"):
        sel_raw = await _prompt_line(session, "Select (comma-separated numbers): ")
        new_tools = _parse_tool_selection(sel_raw, current_tools) if sel_raw else current_tools
    else:
        new_tools = _parse_tool_selection(include_all_raw, current_tools)

    console.print()
    console.print("System prompt (Enter to keep current):")
    prompt_raw = await _prompt_line(session, "> ")
    new_system_prompt = prompt_raw if prompt_raw else agent_def.get("system_prompt")

    current_class = agent_def.get("class_name", DEFAULT_CLASS)
    console.print()
    console.print(f"[bold]Agent class:[/bold] (current: {_get_class_display(current_class)})")
    for i, (cname, icon, desc) in enumerate(AGENT_CLASSES, 1):
        console.print(f"  {i}. {icon} [cyan]{cname}[/cyan] — {desc}")
    class_raw = await _prompt_line(session, f"Pick [1-{len(AGENT_CLASSES)}], Enter=keep current: ")
    new_class = current_class
    if class_raw.isdigit():
        idx = int(class_raw) - 1
        if 0 <= idx < len(AGENT_CLASSES):
            new_class = AGENT_CLASSES[idx][0]

    new_skills = await _ask_skills(session, console, new_class, agent_def.get("skills"), new_tools)

    agent_manager.update(
        agent_def["id"],
        name=new_name,
        model=new_model,
        tools=new_tools,
        skills=new_skills,
        system_prompt=new_system_prompt,
        class_name=new_class,
    )
    if _progression is not None and _progression._agent_id == agent_def["id"]:
        _progression.update_class(new_class)
    console.print()
    console.print(f"[blue]✓ Agent '[bold]{new_name}[/bold]' updated.[/blue]")


async def show_history(session: PromptSession, session_state: dict) -> None:
    """Display past conversations and optionally switch to one."""
    from rich.table import Table
    from questchain.memory.store import get_thread_history

    rows = get_thread_history()
    if not rows:
        console.print("[dim]No past conversations found.[/dim]")
        return

    current_tid = session_state.get("thread_id", "")
    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
    table.add_column("#", style="dim", width=3)
    table.add_column("Thread", width=10)
    table.add_column("Last Active", width=18)
    table.add_column("First Message")

    for i, entry in enumerate(rows, 1):
        tid = entry["thread_id"]
        tid_short = tid[:8]
        last_active = entry["last_active"]
        if last_active:
            local_dt = last_active.astimezone()
            ts_str = local_dt.strftime("%b %d  %I:%M %p")
        else:
            ts_str = "—"
        first_msg = entry["first_message"] or "—"
        if len(first_msg) > 58:
            first_msg = first_msg[:55] + "…"
        first_msg = first_msg.replace("[", "\\[")
        is_current = tid == current_tid
        tid_display = f"[bold blue]{tid_short} *[/bold blue]" if is_current else tid_short
        table.add_row(str(i), tid_display, ts_str, first_msg)

    console.print(Panel(table, title="Conversation History", border_style="cyan"))

    raw = await _prompt_line(session, f"Switch to [1-{len(rows)}], Enter=cancel: ")
    if not raw:
        console.print("[dim]Cancelled.[/dim]")
        return
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(rows):
            chosen = rows[idx]
            session_state["thread_id"] = chosen["thread_id"]
            preview = (chosen["first_message"] or "")[:50].replace("[", "\\[")
            console.print(f"[blue]Switched to thread[/blue] [dim]{chosen['thread_id']}[/dim]")
            if preview:
                console.print(f"[dim]{preview}[/dim]")
            return
    console.print("[yellow]Invalid selection.[/yellow]")


async def run_agent_stream(
    agent,
    user_input: str,
    config: dict,
    agent_name: str = "QuestChain",
    progression: ProgressionManager | None = None,
    is_busy_work: bool = False,
) -> tuple[str, XPGrant | None]:
    """Stream agent response to the console, returning (full_text, xp_grant)."""
    from rich.live import Live
    from rich.spinner import Spinner

    thread_id = config.get("configurable", {}).get("thread_id", "default")
    full_response = ""
    past_spinner = False
    tools_this_turn: list[str] = []

    live = Live(
        Spinner("dots", text=Text(" " + random.choice([
            "Casting…", "Channeling…", "Weaving…", "Conjuring…",
            "Enchanting…", "On the quest…", "Scouting…", "Forging…",
        ]), style="blue"), style="blue"),
        console=console,
        refresh_per_second=10,
        transient=True,
    )
    live.start(refresh=True)

    def _stop_spinner():
        nonlocal past_spinner
        if not past_spinner:
            past_spinner = True
            live.stop()
            if progression is not None:
                rec = progression.get_record()
                color = CLASS_COLORS.get(rec.class_name, "bright_white")
                console.print(f"[bold {color}]{agent_name}[/bold {color}]  [dim]Lv.{rec.level}[/dim]")
            else:
                console.print(f"[bold blue]{agent_name}[/bold blue]")

    async def _on_tool_call(tool_name: str, tool_args: dict) -> None:
        _stop_spinner()
        console.print()
        print_tool_call(tool_name, tool_args)
        tools_this_turn.append(tool_name)
        if progression is not None:
            progression.record_tool_call(tool_name)

    # Stream tokens into a Live Markdown display that updates in-place.
    live_md: Live | None = None

    async for token in agent.run(user_input, thread_id=thread_id, on_tool_call=_on_tool_call):
        if live_md is None:
            _stop_spinner()
            live_md = Live(
                Markdown(""),
                console=console,
                refresh_per_second=8,
                transient=False,
            )
            live_md.start(refresh=True)
        full_response += token
        live_md.update(Markdown(full_response))

    if live_md is not None:
        live_md.stop()

    _stop_spinner()  # no-op if already stopped; handles the zero-token edge case
    console.print()

    xp_grant: XPGrant | None = None
    if progression is not None:
        xp_grant = progression.award_xp(
            tools_this_turn,
            is_busy_work=is_busy_work,
            response_chars=len(full_response),
        )
    if _metrics is not None and not is_busy_work:
        _metrics.record_turn(
            response_chars=len(full_response),
            tool_errors=agent.last_tool_errors,
            chain_depth=agent.last_iterations,
        )
    return full_response, xp_grant


async def _maybe_start_telegram(agent_holder: dict, model_name: str, audio_router: "_AudioRouter", agent_manager: "AgentManager"):
    """Start Telegram bot alongside the CLI if token is configured.

    Returns ``(send_fn, stop_fn, telegram_queue, set_runner)`` or four Nones.
    """
    from questchain.config import TELEGRAM_BOT_TOKEN
    if not TELEGRAM_BOT_TOKEN:
        return None, None, None, None
    try:
        from questchain.telegram import run_telegram_alongside_cli
        telegram_queue: asyncio.Queue = asyncio.Queue()
        send_fn, stop_fn, set_runner = await run_telegram_alongside_cli(
            agent_holder, model_name, telegram_queue, audio_router, agent_manager
        )
        return send_fn, stop_fn, telegram_queue, set_runner
    except Exception as e:
        console.print(f"[yellow]Telegram: failed to start ({e})[/yellow]")
        return None, None, None, None


async def repl(
    model_name: str,
    thread_id: str | None = None,
    use_memory: bool = True,
    busy_work_minutes: int | None = DEFAULT_BUSY_WORK_MINUTES,
):
    """Run the main REPL loop."""
    # Check Ollama connection — retry for a few seconds in case it's still starting
    if not check_ollama_connection():
        console.print("[dim]Waiting for Ollama…[/dim]")
        if not await wait_for_ollama():
            console.print(
                "[bold red]Cannot connect to Ollama![/bold red]\n"
                "Make sure Ollama is running: [cyan]ollama serve[/cyan]"
            )
            return

    # Load agent manager and seed built-in preset agents (idempotent)
    agent_manager = AgentManager()
    agent_manager.seed_preset_agents()
    active_def = agent_manager.get_active()
    effective_model = active_def.get("model") or model_name

    # Verify the model is actually pulled — fail early with a clear message
    available = list_available_models()
    if available and not any(m.startswith(effective_model.split(":")[0]) for m in available):
        console.print(
            f"[bold red]Model '{effective_model}' is not pulled.[/bold red]\n"
            f"Run: [cyan]ollama pull {effective_model}[/cyan]\n\n"
            f"Available models: {', '.join(available) or 'none'}"
        )
        return

    # Session state
    session_state = {
        "thread_id": thread_id or str(uuid.uuid4()),
        "model_name": effective_model,
        "agent_manager": agent_manager,
    }

    # Load progression before display so we can show the level
    _init_progression(active_def)

    # Print welcome banner
    print_banner(effective_model)
    console.print(f"[dim]Thread: {session_state['thread_id']}[/dim]")
    console.print(_build_agent_label(active_def, _progression))
    console.print()

    # Set up prompt with history
    history_path = get_history_path()
    session = PromptSession(
        history=FileHistory(str(history_path)),
        completer=_SlashCompleter(),
        complete_style=CompleteStyle.COLUMN,
        complete_while_typing=True,
        style=_COMPLETION_STYLE,
        key_bindings=_slash_kb,
    )

    # Auto-highlight the first completion whenever the dropdown appears.
    def _auto_select_first(buf):
        state = buf.complete_state
        if state and state.completions and state.current_completion is None:
            state.go_to_index(0)

    try:
        session.default_buffer.on_completions_changed += _auto_select_first
    except AttributeError:
        pass

    audio_router = _AudioRouter()

    try:
        agent = _make_agent_from_def(active_def, audio_router)
    except Exception as e:
        console.print(f"[bold red]Failed to create agent:[/bold red] {e}")
        return

    _init_metrics(active_def, agent)
    agent_holder = {"agent": agent}
    telegram_send, telegram_stop, telegram_queue, telegram_set_runner = await _maybe_start_telegram(
        agent_holder, effective_model, audio_router, agent_manager
    )
    if telegram_send:
        console.print("[dim]Telegram: bot active[/dim]")
    try:
        await _run_with_busy_work(
            session, agent_holder, session_state, busy_work_minutes,
            telegram_send=telegram_send,
            telegram_queue=telegram_queue,
            telegram_set_runner=telegram_set_runner,
            audio_router=audio_router,
            agent_manager=agent_manager,
        )
    finally:
        if telegram_stop:
            await telegram_stop()


async def _run_with_busy_work(
    session: PromptSession,
    agent_holder: dict,
    session_state: dict,
    busy_work_minutes: int | None,
    telegram_send=None,
    telegram_queue=None,
    telegram_set_runner=None,
    audio_router=None,
    agent_manager: "AgentManager | None" = None,
):
    """Start busy work (if enabled), run the REPL, then clean up."""
    from questchain.busy_work import BusyWorkRunner, OvernightRunner

    runner: BusyWorkRunner | None = None
    scheduler = None
    overnight_runner: OvernightRunner | None = None
    # Shared lock: held by the REPL while running agent; quest runner checks before ticking.
    agent_lock = asyncio.Lock()

    if busy_work_minutes is not None:
        async def merged_callback(text: str) -> None:
            console.print()
            console.print(Panel(text, title="[bold blue]Busy Work[/bold blue]", border_style="blue"))
            console.print()
            if _progression is not None:
                grant = _progression.award_xp([], is_busy_work=True)
                if grant.leveled_up:
                    print_level_up(grant, _progression.get_record().class_name)
                    if telegram_send:
                        try:
                            await telegram_send(f"⚔ LEVEL UP (busy work) — now Level {grant.new_level}!")
                        except Exception:
                            pass
                for ach in grant.new_achievements:
                    print_achievement_unlock(ach)
            if telegram_send:
                try:
                    await telegram_send(text)
                except Exception:
                    pass

        runner = BusyWorkRunner(
            agent_holder=agent_holder,
            send_callback=merged_callback,
            interval_minutes=busy_work_minutes,
            busy_lock=agent_lock,
        )
        await runner.start()
        session_state["busy_work_runner"] = runner
        if telegram_set_runner is not None:
            telegram_set_runner(runner)
        console.print(f"[dim]Busy work: every {busy_work_minutes} min[/dim]")

    # CronScheduler — enabled in CLI mode (Telegram mode creates its own instance)
    # Guard against double-initialization when Telegram is active.
    if not telegram_send and agent_manager is not None:
        from questchain.scheduler import CronScheduler, set_scheduler

        async def cron_callback(text: str) -> None:
            console.print()
            console.print(Panel(text, title="[bold cyan]Scheduled Task[/bold cyan]", border_style="cyan"))
            console.print()
            if telegram_send:
                try:
                    await telegram_send(text)
                except Exception:
                    pass

        scheduler = CronScheduler(
            agent=agent_holder["agent"],
            send_callback=cron_callback,
            agent_manager=agent_manager,
            audio_router=audio_router,
        )
        set_scheduler(scheduler)
        await scheduler.start()
        console.print("[dim]Scheduler: active[/dim]")

        # OvernightRunner — runs Night Owl agent every 30 min during 12 AM–6 AM
        overnight_runner = OvernightRunner(
            agent_manager=agent_manager,
            send_callback=cron_callback,
            busy_lock=agent_lock,
        )
        await overnight_runner.start()
        session_state["overnight_runner"] = overnight_runner
        console.print("[dim]Overnight runner: active[/dim]")

    # First-run onboarding — guard with the lock so a fast quest tick can't interfere
    if not is_onboarded():
        async with agent_lock:
            completed = await run_onboarding(agent_holder["agent"], console, prompt_session=session)
        if completed and agent_manager is not None:
            # Reload so the name (and any other changes) take effect immediately
            new_def = agent_manager.get_active()
            try:
                agent_holder["agent"] = _make_agent_from_def(new_def, audio_router)
                session_state["model_name"] = new_def.get("model") or OLLAMA_MODEL
                _init_progression(new_def)
                _init_metrics(new_def, agent_holder["agent"])
            except Exception:
                pass

    if _progression is not None:
        milestone = _progression.check_birthday()
        if milestone:
            msg = _birthday_message(milestone)
            console.print(Panel(msg, border_style="magenta"))
            if telegram_send:
                try:
                    await telegram_send(msg)
                except Exception:
                    pass

    try:
        await _repl_loop(
            session, agent_holder, session_state,
            telegram_queue=telegram_queue,
            audio_router=audio_router,
            agent_manager=agent_manager,
            busy_lock=agent_lock,
            telegram_send=telegram_send,
        )
    finally:
        if runner:
            await runner.stop()
        if overnight_runner:
            await overnight_runner.stop()
        if scheduler:
            from questchain.scheduler import set_scheduler
            await scheduler.stop()
            set_scheduler(None)


async def _repl_loop(
    session: PromptSession,
    agent_holder: dict,
    session_state: dict,
    telegram_queue: asyncio.Queue | None = None,
    audio_router: "_AudioRouter | None" = None,
    agent_manager: "AgentManager | None" = None,
    busy_lock: asyncio.Lock | None = None,
    telegram_send=None,
):
    """Inner REPL loop.

    When *telegram_queue* is provided, the loop races between waiting for CLI
    input and waiting for a queued Telegram message.  Whichever arrives first
    is processed through the same streaming display.  The queue item is a
    ``(user_text, agent_config, response_future)`` tuple; the future is
    resolved with the full response text so the Telegram handler can send it
    back to the user.
    """
    while True:
        source = "cli"
        response_future = None
        agent_config = None
        telegram_update = None

        # Build label for the separator line
        _agent_label = ""
        if agent_manager is not None:
            _agent_label = _build_agent_label(agent_manager.get_active(), _progression)

        if telegram_queue is not None:
            prompt_task = asyncio.create_task(_user_prompt(session, agent_label=_agent_label))
            queue_task = asyncio.create_task(telegram_queue.get())
            done, pending = await asyncio.wait(
                [prompt_task, queue_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

            if prompt_task in done:
                try:
                    user_input = prompt_task.result()
                except EOFError:
                    console.print("\n[dim]Goodbye![/dim]")
                    break
                except KeyboardInterrupt:
                    console.print("\n[dim]Press Ctrl+D to exit.[/dim]")
                    continue
                except Exception:
                    console.print("\n[dim]Goodbye![/dim]")
                    break
            else:
                user_text, agent_config, response_future, telegram_update = queue_task.result()
                user_input = user_text
                source = "telegram"
                console.print(f"\n[bold blue]📱 Telegram[/bold blue] > {user_input}")
        else:
            try:
                user_input = await _user_prompt(session, agent_label=_agent_label)
            except EOFError:
                console.print("\n[dim]Goodbye![/dim]")
                break
            except KeyboardInterrupt:
                console.print("\n[dim]Press Ctrl+D to exit.[/dim]")
                continue

        user_input = user_input.strip()
        if not user_input:
            if response_future and not response_future.done():
                response_future.set_result("")
            continue

        # Slash commands are CLI-only
        if source == "cli" and user_input.startswith("/"):
            result = handle_command(user_input, session_state)
            if result is False:
                break
            if result is True:
                if session_state.pop("run_onboard", False):
                    await run_onboarding(agent_holder["agent"], console, prompt_session=session)

                if session_state.pop("run_setup_tavily", False):
                    from questchain.onboarding import run_setup_tavily
                    await run_setup_tavily(console, session)

                if session_state.pop("run_setup_claudecode", False):
                    await run_setup_claude_code(console, session)

                if session_state.pop("run_setup_telegram", False):
                    from questchain.onboarding import run_setup_telegram
                    await run_setup_telegram(console, session)

                if session_state.pop("run_history", False):
                    await show_history(session, session_state)

                if session_state.pop("run_quest_menu", False):
                    await _quest_menu(session)

                if session_state.pop("run_overnight_queue", False):
                    task_text = await _prompt_line(session, "Task for tonight: ")
                    if task_text.strip():
                        from questchain.config import WORKSPACE_DIR
                        overnight_path = WORKSPACE_DIR / "workspace" / "overnight.md"
                        content = overnight_path.read_text(encoding="utf-8")
                        new_item = f"- [ ] {task_text.strip()}"
                        if "## Tonight's Queue" in content:
                            content = content.replace(
                                "## Tonight's Queue",
                                f"## Tonight's Queue\n{new_item}",
                                1,
                            )
                        else:
                            content = content.rstrip() + f"\n\n## Tonight's Queue\n{new_item}\n"
                        overnight_path.write_text(content, encoding="utf-8")
                        console.print(f"[blue]Added to tonight's queue:[/blue] {task_text.strip()}")
                    else:
                        console.print("[dim]Cancelled.[/dim]")

                if session_state.pop("run_agent_menu", False) and agent_manager is not None:
                    chosen = await run_agent_menu(console, session, agent_manager)
                    if chosen is not None:
                        try:
                            new_agent = _make_agent_from_def(chosen, audio_router)
                            agent_holder["agent"] = new_agent
                            session_state["model_name"] = chosen.get("model") or OLLAMA_MODEL
                            agent_manager.set_active(chosen["id"])
                            _init_progression(chosen)
                            _init_metrics(chosen, new_agent)
                        except Exception as e:
                            console.print(f"[bold red]Failed to switch agent:[/bold red] {e}")
                        else:
                            # Per-agent first-run onboarding for preset agents
                            chosen_class = chosen.get("class_name", "")
                            if chosen_class == "NightOwl" and not is_overnight_onboarded():
                                await run_overnight_onboarding(agent_holder["agent"], console, prompt_session=session)

                if session_state.pop("run_prestige", False):
                    await _handle_prestige(session)

                if session_state.pop("run_level", False) and agent_manager is not None:
                    await show_stats(agent_manager.get_active())

                if session_state.pop("run_stats_metrics", False) and _metrics is not None:
                    show_metrics(_metrics)

                continue

        if agent_config is None:
            agent_config = {"configurable": {"thread_id": session_state["thread_id"]}, "recursion_limit": 200}

        if audio_router is not None:
            if source == "telegram" and telegram_update is not None:
                audio_router.set_telegram(telegram_update)
            else:
                audio_router.set_cli()

        active_name = agent_manager.get_active()["name"] if agent_manager else "QuestChain"
        try:
            console.print()
            # Interrupt any in-progress busy work tick so the lock is freed promptly.
            # asyncio's async-with guarantees the lock is released on cancellation.
            for _rkey in ("busy_work_runner", "overnight_runner"):
                _runner = session_state.get(_rkey)
                if _runner is not None:
                    await _runner.interrupt()
            async with busy_lock if busy_lock else asyncio.Lock():
                full_response, xp_grant = await run_agent_stream(
                    agent_holder["agent"], user_input, agent_config,
                    agent_name=active_name, progression=_progression,
                )
            if xp_grant and xp_grant.leveled_up and _progression is not None:
                print_level_up(xp_grant, _progression.get_record().class_name)
                if telegram_send:
                    try:
                        await telegram_send(f"⚔ LEVEL UP — now Level {xp_grant.new_level}!")
                    except Exception:
                        pass
            if xp_grant:
                for ach in xp_grant.new_achievements:
                    print_achievement_unlock(ach)
                    if telegram_send:
                        try:
                            await telegram_send(
                                f"✦ Achievement unlocked: {ach.name} — {ach.description}"
                            )
                        except Exception:
                            pass
            if response_future and not response_future.done():
                response_future.set_result(full_response)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]")
            if response_future and not response_future.done():
                response_future.set_result("")
        except Exception as e:
            if "does not support tools" in str(e):
                bad_model = session_state.get("model_name", OLLAMA_MODEL)
                console.print(
                    f"\n[yellow]⚠ '{bad_model}' doesn't support tool calling.[/yellow]\n"
                    f"  Switching to [cyan]{OLLAMA_MODEL}[/cyan] and retrying…"
                )
                try:
                    fallback = _make_agent_from_def(BUILTIN_AGENT, audio_router)
                    agent_holder["agent"] = fallback
                    session_state["model_name"] = OLLAMA_MODEL
                    if agent_manager:
                        agent_manager.set_active("default")
                    _init_progression(BUILTIN_AGENT)
                    _init_metrics(BUILTIN_AGENT, fallback)
                    console.print()
                    async with busy_lock if busy_lock else asyncio.Lock():
                        full_response, xp_grant = await run_agent_stream(
                            fallback, user_input, agent_config,
                            agent_name="QuestChain", progression=_progression,
                        )
                    if xp_grant and xp_grant.leveled_up and _progression is not None:
                        print_level_up(xp_grant, _progression.get_record().class_name)
                        if telegram_send:
                            try:
                                await telegram_send(f"⚔ LEVEL UP — now Level {xp_grant.new_level}!")
                            except Exception:
                                pass
                    if xp_grant:
                        for ach in xp_grant.new_achievements:
                            print_achievement_unlock(ach)
                            if telegram_send:
                                try:
                                    await telegram_send(
                                        f"✦ Achievement unlocked: {ach.name} — {ach.description}"
                                    )
                                except Exception:
                                    pass
                    if response_future and not response_future.done():
                        response_future.set_result(full_response)
                except Exception as retry_err:
                    console.print(f"\n[bold red]Error:[/bold red] {retry_err}")
                    if response_future and not response_future.done():
                        response_future.set_exception(retry_err)
            else:
                console.print(f"\n[bold red]Error:[/bold red] {e}")
                if response_future and not response_future.done():
                    response_future.set_exception(e)


def main(
    model_name: str | None = None,
    thread_id: str | None = None,
    use_memory: bool = True,
    busy_work_minutes: int | None = DEFAULT_BUSY_WORK_MINUTES,
):
    """Entry point for the QuestChain CLI."""
    model_name = model_name or OLLAMA_MODEL
    asyncio.run(repl(model_name, thread_id, use_memory, busy_work_minutes))
