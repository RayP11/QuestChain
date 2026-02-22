"""Genie terminal UI and REPL loop."""

import asyncio
import random
import uuid

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from genie import __version__
from genie.agent import build_input, create_genie_agent
from genie.agents import AgentManager, SELECTABLE_TOOLS
from genie.config import (
    DEFAULT_BUSY_WORK_MINUTES,
    OLLAMA_MODEL,
    TAVILY_API_KEY,
    get_history_path,
)
from genie.onboarding import GENIE_ART, TAGLINES, clear_onboarded, is_onboarded, run_onboarding
from genie.memory.store import create_checkpointer, create_memory_store
from genie.models import check_ollama_connection, list_available_models, wait_for_ollama

console = Console()


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


def _make_agent_from_def(agent_def: dict, checkpointer, store, audio_router) -> object:
    """Create a Genie agent from an agent definition dict."""
    return create_genie_agent(
        model_name=agent_def.get("model"),
        checkpointer=checkpointer,
        store=store,
        on_audio=audio_router,
        system_prompt_override=agent_def.get("system_prompt"),
        tools_filter=None if agent_def.get("tools") == "all" else agent_def.get("tools"),
    )


def print_banner(model_name: str):
    """Display the Genie welcome banner."""
    banner = Text()
    for line in GENIE_ART.strip().splitlines():
        banner.append(line + "\n", style="bold magenta")
    banner.append("\n")
    banner.append("  🧞 ", style="bold")
    banner.append(random.choice(TAGLINES), style="italic cyan")
    banner.append("\n\n")
    banner.append(f"  v{__version__}", style="dim")
    banner.append("  |  ", style="dim")
    banner.append(f"Model: {model_name}", style="cyan")
    banner.append("\n")
    if TAVILY_API_KEY:
        banner.append("  Web search: enabled", style="green")
    else:
        banner.append("  Web search: disabled (no TAVILY_API_KEY)", style="yellow")
    banner.append("\n")
    banner.append("  Type /help for commands, Ctrl+D to exit", style="dim")
    console.print(Panel(banner, border_style="magenta"))


def print_tool_call(tool_name: str, tool_input: dict):
    """Display a tool call indicator."""
    console.print(f"  [dim]> Using tool:[/dim] [cyan]{tool_name}[/cyan]")


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
        console.print(f"[green]New session started.[/green] Thread: [dim]{session_state['thread_id']}[/dim]")
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
            console.print(f"[green]Busy work:[/green] active (every {runner.interval_minutes} min)")
        else:
            console.print("[yellow]Busy work:[/yellow] disabled")
        return True

    if cmd == "/tools":
        from genie.config import TAVILY_API_KEY
        text = (
            "[bold]Built-in tools[/bold] (filesystem, shell, planning, sub-agents):\n"
            "  read_file, write_file, edit_file, ls, glob, grep\n"
            "  execute, write_todos, read_todos, task\n"
            "\n[bold]Custom tools:[/bold]\n"
            "  claude_code — delegate coding tasks to Claude Code\n"
            "  cron_add, cron_list, cron_remove — scheduled jobs (Telegram)\n"
        )
        if TAVILY_API_KEY:
            text += "  web_search, web_browse — [green]enabled[/green]\n"
        else:
            text += "  web_search, web_browse — [yellow]disabled (no TAVILY_API_KEY)[/yellow]\n"
        console.print(Panel(text, title="Tools", border_style="cyan"))
        return True

    if cmd == "/instructions":
        from genie.agent import SYSTEM_PROMPT
        console.print(Panel(SYSTEM_PROMPT, title="System Instructions", border_style="cyan"))
        return True

    if cmd == "/memory":
        from genie.config import MEMORY_DIR
        about = MEMORY_DIR / "ABOUT.md"
        if about.exists():
            console.print(Panel(about.read_text(), title="Memory — ABOUT.md", border_style="cyan"))
        else:
            console.print("[dim]No memory file yet. Run /onboard to create one.[/dim]")
        return True

    if cmd == "/tasks":
        from genie.config import WORKSPACE_DIR
        tasks = WORKSPACE_DIR / "workspace" / "TASKS.md"
        if tasks.exists():
            console.print(Panel(tasks.read_text(), title="Tasks", border_style="cyan"))
        else:
            console.print("[dim]No TASKS.md found in workspace.[/dim]")
        return True

    if cmd == "/cron":
        import json
        from genie.config import get_cron_jobs_path
        jobs_path = get_cron_jobs_path()
        jobs = []
        if jobs_path.exists():
            try:
                jobs = json.loads(jobs_path.read_text())
            except Exception:
                pass
        if jobs:
            lines = []
            for j in jobs:
                status = "[green]on[/green]" if j.get("enabled", True) else "[dim]off[/dim]"
                lines.append(f"  [{j['id']}] {j['name']} — {j['cron_expression']} ({status})")
            console.print(Panel("\n".join(lines), title="Cron Jobs", border_style="cyan"))
        else:
            console.print("[dim]No cron jobs configured.[/dim]")
        return True

    if cmd == "/onboard":
        clear_onboarded()
        session_state["run_onboard"] = True
        return True

    if cmd == "/build-agent":
        session_state["run_build_agent"] = True
        return True

    if cmd == "/pick-agent":
        session_state["run_pick_agent"] = True
        return True

    if cmd == "/agents":
        agent_manager: AgentManager | None = session_state.get("agent_manager")
        if agent_manager is None:
            console.print("[dim]Agent manager not available.[/dim]")
            return True
        active_id = agent_manager.get_active_id()
        lines = []
        for agent_def in agent_manager.all_agents():
            marker = "*" if agent_def["id"] == active_id else " "
            name = agent_def["name"]
            if agent_def.get("built_in"):
                name += " (built-in)"
            model = agent_def.get("model") or OLLAMA_MODEL
            lines.append(f"  {marker} {name:<28} {model}")
        console.print(Panel("\n".join(lines), title="Agents", border_style="cyan"))
        return True

    if cmd == "/help":
        help_text = (
            "[bold]Commands:[/bold]\n"
            "  /new           - Start a new conversation\n"
            "  /model         - Show current model and available models\n"
            "  /thread        - Show current thread ID\n"
            "  /busy          - Show busy work status\n"
            "  /tools         - List available tools\n"
            "  /instructions  - Show agent system prompt\n"
            "  /memory        - Show your saved user profile\n"
            "  /tasks         - Show current task list\n"
            "  /cron          - List scheduled cron jobs\n"
            "  /onboard       - Re-run the onboarding flow\n"
            "  /agents        - List all agents, mark active\n"
            "  /build-agent   - Create a new custom agent\n"
            "  /pick-agent    - Switch to a different agent\n"
            "  /clear         - Clear the screen\n"
            "  /quit          - Exit Genie\n"
            "  /help          - Show this help message"
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


async def run_build_agent_wizard(
    console: Console,
    session: PromptSession,
    agent_manager: AgentManager,
) -> dict | None:
    """Interactive wizard to create a new custom agent."""
    console.print()
    console.print(Panel("[bold]Create a new agent[/bold]", border_style="magenta"))

    # Name
    name = await _prompt_line(session, "Agent name: ")
    if not name:
        console.print("[yellow]Cancelled.[/yellow]")
        return None

    # Model
    default_model = OLLAMA_MODEL
    model_raw = await _prompt_line(session, f"Model [{default_model}]: ")
    model = model_raw if model_raw else None  # None → use default at runtime

    # Tool selection
    console.print()
    console.print("[bold]Custom tools[/bold] (filesystem/shell/planning always included):")
    for i, (tool_name, description) in enumerate(SELECTABLE_TOOLS, 1):
        console.print(f"  {i}. [cyan]{tool_name}[/cyan] — {description}")
    console.print()

    include_all_raw = await _prompt_line(session, "Include all tools? [Y/n]: ")
    if include_all_raw.lower() in ("", "y", "yes"):
        tools: list[str] | str = "all"
    else:
        selection_raw = await _prompt_line(session, "Select (comma-separated numbers): ")
        selected_tools: list[str] = []
        for part in selection_raw.split(","):
            part = part.strip()
            if part.isdigit():
                idx = int(part) - 1
                if 0 <= idx < len(SELECTABLE_TOOLS):
                    selected_tools.append(SELECTABLE_TOOLS[idx][0])
        tools = selected_tools if selected_tools else "all"

    # System prompt
    console.print()
    console.print("System prompt (Enter for default Genie prompt):")
    prompt_raw = await _prompt_line(session, "> ")
    system_prompt = prompt_raw if prompt_raw else None

    # Save
    agent_def = agent_manager.add(name, model, system_prompt, tools)
    console.print()
    console.print(f"[green]✓ Agent '[bold]{name}[/bold]' created.[/green] Use [cyan]/pick-agent[/cyan] to activate it.")
    return agent_def


async def run_pick_agent_wizard(
    console: Console,
    session: PromptSession,
    agent_manager: AgentManager,
) -> dict | None:
    """Interactive wizard to pick the active agent. Returns chosen agent or None."""
    agents = agent_manager.all_agents()
    active_id = agent_manager.get_active_id()

    console.print()
    for i, agent_def in enumerate(agents, 1):
        marker = "*" if agent_def["id"] == active_id else " "
        name = agent_def["name"]
        if agent_def.get("built_in"):
            name += " (built-in)"
        model = agent_def.get("model") or OLLAMA_MODEL
        console.print(f"  {i}. {marker} [cyan]{name}[/cyan]  {model}")

    console.print()
    current_idx = next((i for i, a in enumerate(agents, 1) if a["id"] == active_id), 1)
    selection_raw = await _prompt_line(session, f"Select [{current_idx}]: ")
    if not selection_raw:
        console.print("[dim]No change.[/dim]")
        return None

    if selection_raw.isdigit():
        idx = int(selection_raw) - 1
        if 0 <= idx < len(agents):
            chosen = agents[idx]
        else:
            console.print("[yellow]Invalid selection.[/yellow]")
            return None
    else:
        # Try name match
        lower = selection_raw.lower()
        chosen = next((a for a in agents if a["name"].lower() == lower), None)
        if chosen is None:
            console.print("[yellow]Agent not found.[/yellow]")
            return None

    chosen_name = chosen["name"]
    console.print(f"[green]🧞 Switched to '[bold]{chosen_name}[/bold]'. Current thread continues.[/green]")
    return chosen


async def run_agent_stream(agent, user_input: str, config: dict) -> str:
    """Stream agent response to the console, returning the full text."""
    from rich.live import Live
    from rich.spinner import Spinner

    full_response = ""
    tool_calls_shown = set()
    past_spinner = False

    live = Live(
        Spinner("dots", text=" Thinking…"),
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
            console.print("[bold magenta]Genie[/bold magenta]")

    async for event in agent.astream_events(
        build_input(user_input),
        config=config,
        version="v2",
    ):
        kind = event["event"]

        if kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            if hasattr(chunk, "content") and isinstance(chunk.content, str) and chunk.content:
                _stop_spinner()
                full_response += chunk.content
                console.print(chunk.content, end="")

        elif kind == "on_tool_start":
            tool_name = event.get("name", "unknown")
            tool_input = event.get("data", {}).get("input", {})
            call_id = f"{tool_name}:{id(event)}"
            if call_id not in tool_calls_shown:
                tool_calls_shown.add(call_id)
                _stop_spinner()
                console.print()
                print_tool_call(tool_name, tool_input)

        elif kind == "on_tool_end":
            pass

    _stop_spinner()  # Safety: in case no tokens were generated
    console.print()
    return full_response


async def _maybe_start_telegram(agent_holder: dict, model_name: str, audio_router: "_AudioRouter", agent_manager: "AgentManager"):
    """Start Telegram bot alongside the CLI if token is configured.

    Returns ``(send_fn, stop_fn, telegram_queue)`` or ``(None, None, None)``.
    """
    from genie.config import TELEGRAM_BOT_TOKEN
    if not TELEGRAM_BOT_TOKEN:
        return None, None, None
    try:
        from genie.telegram import run_telegram_alongside_cli
        telegram_queue: asyncio.Queue = asyncio.Queue()
        send_fn, stop_fn = await run_telegram_alongside_cli(
            agent_holder, model_name, telegram_queue, audio_router, agent_manager
        )
        return send_fn, stop_fn, telegram_queue
    except Exception as e:
        console.print(f"[yellow]Telegram: failed to start ({e})[/yellow]")
        return None, None, None


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

    # Set up persistence
    store = None
    if use_memory:
        store = create_memory_store()

    # Load agent manager and active agent
    agent_manager = AgentManager()
    active_def = agent_manager.get_active()
    effective_model = active_def.get("model") or model_name

    # Session state
    session_state = {
        "thread_id": thread_id or str(uuid.uuid4()),
        "model_name": effective_model,
        "agent_manager": agent_manager,
    }

    # Print welcome banner
    print_banner(effective_model)
    console.print(f"[dim]Thread: {session_state['thread_id']}[/dim]")
    if active_def["id"] != "default":
        console.print(f"[dim]Agent: {active_def['name']}[/dim]")
    console.print()

    # Set up prompt with history
    history_path = get_history_path()
    session = PromptSession(history=FileHistory(str(history_path)))

    audio_router = _AudioRouter()

    # Create agent and run REPL (checkpointer needs async context manager)
    if use_memory:
        async with create_checkpointer() as checkpointer:
            try:
                agent = _make_agent_from_def(active_def, checkpointer, store, audio_router)
            except Exception as e:
                console.print(f"[bold red]Failed to create agent:[/bold red] {e}")
                return
            agent_holder = {"agent": agent}
            telegram_send, telegram_stop, telegram_queue = await _maybe_start_telegram(
                agent_holder, effective_model, audio_router, agent_manager
            )
            if telegram_send:
                console.print("[dim]Telegram: bot active[/dim]")
            try:
                await _run_with_busy_work(
                    session, agent_holder, session_state, busy_work_minutes,
                    use_memory=True, telegram_send=telegram_send,
                    telegram_queue=telegram_queue,
                    audio_router=audio_router,
                    agent_manager=agent_manager,
                    checkpointer=checkpointer,
                    store=store,
                )
            finally:
                if telegram_stop:
                    await telegram_stop()
    else:
        try:
            agent = _make_agent_from_def(active_def, None, None, audio_router)
        except Exception as e:
            console.print(f"[bold red]Failed to create agent:[/bold red] {e}")
            return
        agent_holder = {"agent": agent}
        telegram_send, telegram_stop, telegram_queue = await _maybe_start_telegram(
            agent_holder, effective_model, audio_router, agent_manager
        )
        if telegram_send:
            console.print("[dim]Telegram: bot active[/dim]")
        try:
            await _run_with_busy_work(
                session, agent_holder, session_state, busy_work_minutes,
                use_memory=False, telegram_send=telegram_send,
                telegram_queue=telegram_queue,
                audio_router=audio_router,
                agent_manager=agent_manager,
                checkpointer=None,
                store=None,
            )
        finally:
            if telegram_stop:
                await telegram_stop()


async def _run_with_busy_work(
    session: PromptSession,
    agent_holder: dict,
    session_state: dict,
    busy_work_minutes: int | None,
    use_memory: bool = True,
    telegram_send=None,
    telegram_queue=None,
    audio_router=None,
    agent_manager: "AgentManager | None" = None,
    checkpointer=None,
    store=None,
):
    """Start busy work (if enabled), run the REPL, then clean up."""
    from genie.busy_work import BusyWorkRunner

    runner: BusyWorkRunner | None = None

    if busy_work_minutes is not None:
        async def merged_callback(text: str) -> None:
            console.print()
            console.print(Panel(text, title="Busy Work", border_style="magenta"))
            console.print()
            if telegram_send:
                await telegram_send(text)

        runner = BusyWorkRunner(
            agent=agent_holder["agent"],
            send_callback=merged_callback,
            interval_minutes=busy_work_minutes,
        )
        await runner.start()
        session_state["busy_work_runner"] = runner
        console.print(f"[dim]Busy work: every {busy_work_minutes} min[/dim]")

    # First-run onboarding — jump straight into the conversation
    if use_memory and not is_onboarded():
        await run_onboarding(agent_holder["agent"], console, prompt_session=session)

    try:
        await _repl_loop(
            session, agent_holder, session_state,
            telegram_queue=telegram_queue,
            audio_router=audio_router,
            agent_manager=agent_manager,
            checkpointer=checkpointer,
            store=store,
        )
    finally:
        if runner:
            await runner.stop()


async def _repl_loop(
    session: PromptSession,
    agent_holder: dict,
    session_state: dict,
    telegram_queue: asyncio.Queue | None = None,
    audio_router: "_AudioRouter | None" = None,
    agent_manager: "AgentManager | None" = None,
    checkpointer=None,
    store=None,
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

        if telegram_queue is not None:
            prompt_task = asyncio.create_task(session.prompt_async("\n🧞 You > "))
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
                user_input = await session.prompt_async("\n🧞 You > ")
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

                if session_state.pop("run_build_agent", False) and agent_manager is not None:
                    await run_build_agent_wizard(console, session, agent_manager)

                if session_state.pop("run_pick_agent", False) and agent_manager is not None:
                    chosen = await run_pick_agent_wizard(console, session, agent_manager)
                    if chosen is not None:
                        try:
                            new_agent = _make_agent_from_def(chosen, checkpointer, store, audio_router)
                            agent_holder["agent"] = new_agent
                            session_state["model_name"] = chosen.get("model") or OLLAMA_MODEL
                            agent_manager.set_active(chosen["id"])
                        except Exception as e:
                            console.print(f"[bold red]Failed to switch agent:[/bold red] {e}")

                continue

        if agent_config is None:
            agent_config = {"configurable": {"thread_id": session_state["thread_id"]}}

        if audio_router is not None:
            if source == "telegram" and telegram_update is not None:
                audio_router.set_telegram(telegram_update)
            else:
                audio_router.set_cli()

        try:
            console.print()
            full_response = await run_agent_stream(agent_holder["agent"], user_input, agent_config)
            if response_future and not response_future.done():
                response_future.set_result(full_response)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]")
            if response_future and not response_future.done():
                response_future.set_result("")
        except Exception as e:
            console.print(f"\n[bold red]Error:[/bold red] {e}")
            if response_future and not response_future.done():
                response_future.set_exception(e)


def main(
    model_name: str | None = None,
    thread_id: str | None = None,
    use_memory: bool = True,
    busy_work_minutes: int | None = DEFAULT_BUSY_WORK_MINUTES,
):
    """Entry point for the Genie CLI."""
    model_name = model_name or OLLAMA_MODEL
    asyncio.run(repl(model_name, thread_id, use_memory, busy_work_minutes))
