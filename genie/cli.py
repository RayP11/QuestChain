"""Genie terminal UI and REPL loop."""

import asyncio
import uuid

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from genie import __version__
from genie.agent import build_input, create_genie_agent
from genie.config import (
    DEFAULT_BUSY_WORK_MINUTES,
    OLLAMA_MODEL,
    TAVILY_API_KEY,
    get_history_path,
)
from genie.onboarding import clear_onboarded, is_onboarded, run_onboarding
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


def print_banner(model_name: str):
    """Display the Genie welcome banner."""
    banner = Text()
    banner.append("GENIE", style="bold magenta")
    banner.append(f" v{__version__}", style="dim")
    banner.append("\n")
    banner.append(f"Model: {model_name}", style="cyan")
    if TAVILY_API_KEY:
        banner.append(" | Web search: enabled", style="green")
    else:
        banner.append(" | Web search: disabled (no TAVILY_API_KEY)", style="yellow")
    banner.append("\n")
    banner.append("Type /help for commands, /quit to exit", style="dim")
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

    if cmd == "/onboard":
        clear_onboarded()
        session_state["run_onboard"] = True
        return True

    if cmd == "/help":
        help_text = (
            "[bold]Commands:[/bold]\n"
            "  /new        - Start a new conversation\n"
            "  /model      - Show current model and available models\n"
            "  /thread     - Show current thread ID\n"
            "  /busy       - Show busy work status\n"
            "  /onboard    - Re-run the onboarding flow\n"
            "  /clear      - Clear the screen\n"
            "  /quit       - Exit Genie\n"
            "  /help       - Show this help message"
        )
        console.print(Panel(help_text, title="Help", border_style="blue"))
        return True

    return None


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


async def _maybe_start_telegram(agent, model_name: str):
    """Start Telegram bot alongside the CLI if token is configured.

    Returns ``(send_fn, stop_fn, telegram_queue)`` or ``(None, None, None)``.
    """
    from genie.config import TELEGRAM_BOT_TOKEN
    if not TELEGRAM_BOT_TOKEN:
        return None, None, None
    try:
        from genie.telegram import run_telegram_alongside_cli
        telegram_queue: asyncio.Queue = asyncio.Queue()
        send_fn, stop_fn = await run_telegram_alongside_cli(agent, model_name, telegram_queue)
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

    # Session state
    session_state = {
        "thread_id": thread_id or str(uuid.uuid4()),
        "model_name": model_name,
    }

    # Print welcome banner
    print_banner(model_name)
    console.print(f"[dim]Thread: {session_state['thread_id']}[/dim]")
    console.print()

    # Set up prompt with history
    history_path = get_history_path()
    session = PromptSession(history=FileHistory(str(history_path)))

    # Create agent and run REPL (checkpointer needs async context manager)
    if use_memory:
        async with create_checkpointer() as checkpointer:
            try:
                agent = create_genie_agent(
                    model_name=model_name,
                    checkpointer=checkpointer,
                    store=store,
                    on_audio=_play_audio,
                )
            except Exception as e:
                console.print(f"[bold red]Failed to create agent:[/bold red] {e}")
                return
            telegram_send, telegram_stop, telegram_queue = await _maybe_start_telegram(agent, model_name)
            if telegram_send:
                console.print("[dim]Telegram: bot active[/dim]")
            try:
                await _run_with_busy_work(
                    session, agent, session_state, busy_work_minutes,
                    use_memory=True, telegram_send=telegram_send,
                    telegram_queue=telegram_queue,
                )
            finally:
                if telegram_stop:
                    await telegram_stop()
    else:
        try:
            agent = create_genie_agent(model_name=model_name, on_audio=_play_audio)
        except Exception as e:
            console.print(f"[bold red]Failed to create agent:[/bold red] {e}")
            return
        telegram_send, telegram_stop, telegram_queue = await _maybe_start_telegram(agent, model_name)
        if telegram_send:
            console.print("[dim]Telegram: bot active[/dim]")
        try:
            await _run_with_busy_work(
                session, agent, session_state, busy_work_minutes,
                use_memory=False, telegram_send=telegram_send,
                telegram_queue=telegram_queue,
            )
        finally:
            if telegram_stop:
                await telegram_stop()


async def _run_with_busy_work(
    session: PromptSession,
    agent,
    session_state: dict,
    busy_work_minutes: int | None,
    use_memory: bool = True,
    telegram_send=None,
    telegram_queue=None,
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
            agent=agent,
            send_callback=merged_callback,
            interval_minutes=busy_work_minutes,
        )
        await runner.start()
        session_state["busy_work_runner"] = runner
        console.print(f"[dim]Busy work: every {busy_work_minutes} min[/dim]")

    # First-run onboarding — jump straight into the conversation
    if use_memory and not is_onboarded():
        await run_onboarding(agent, console, prompt_session=session)

    try:
        await _repl_loop(session, agent, session_state, telegram_queue=telegram_queue)
    finally:
        if runner:
            await runner.stop()


async def _repl_loop(
    session: PromptSession,
    agent,
    session_state: dict,
    telegram_queue: asyncio.Queue | None = None,
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
                except (EOFError, KeyboardInterrupt):
                    console.print("\n[dim]Goodbye![/dim]")
                    break
                except Exception:
                    console.print("\n[dim]Goodbye![/dim]")
                    break
            else:
                user_text, agent_config, response_future = queue_task.result()
                user_input = user_text
                source = "telegram"
                console.print(f"\n[bold blue]📱 Telegram[/bold blue] > {user_input}")
        else:
            try:
                user_input = await session.prompt_async("\n🧞 You > ")
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye![/dim]")
                break

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
                    await run_onboarding(agent, console, prompt_session=session)
                continue

        if agent_config is None:
            agent_config = {"configurable": {"thread_id": session_state["thread_id"]}}

        try:
            console.print()
            full_response = await run_agent_stream(agent, user_input, agent_config)
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
