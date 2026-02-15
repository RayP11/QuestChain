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
from genie.agent import create_genie_agent
from genie.config import (
    OLLAMA_MODEL,
    TAVILY_API_KEY,
    get_history_path,
)
from genie.memory.store import create_checkpointer, create_memory_store
from genie.models import check_ollama_connection, list_available_models

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

    if cmd == "/help":
        help_text = (
            "[bold]Commands:[/bold]\n"
            "  /new     - Start a new conversation\n"
            "  /model   - Show current model and available models\n"
            "  /thread  - Show current thread ID\n"
            "  /clear   - Clear the screen\n"
            "  /quit    - Exit Genie\n"
            "  /help    - Show this help message"
        )
        console.print(Panel(help_text, title="Help", border_style="blue"))
        return True

    return None


async def run_agent_stream(agent, user_input: str, config: dict):
    """Stream agent response to the console."""
    console.print()

    full_response = ""
    tool_calls_shown = set()

    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": user_input}]},
        config=config,
        version="v2",
    ):
        kind = event["event"]

        # Stream text tokens
        if kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            if hasattr(chunk, "content") and isinstance(chunk.content, str):
                full_response += chunk.content
                console.print(chunk.content, end="")

        # Show tool calls
        elif kind == "on_tool_start":
            tool_name = event.get("name", "unknown")
            tool_input = event.get("data", {}).get("input", {})
            call_id = f"{tool_name}:{id(event)}"
            if call_id not in tool_calls_shown:
                tool_calls_shown.add(call_id)
                console.print()
                print_tool_call(tool_name, tool_input)

        elif kind == "on_tool_end":
            pass

    console.print()


async def repl(model_name: str, thread_id: str | None = None, use_memory: bool = True):
    """Run the main REPL loop."""
    # Check Ollama connection
    if not check_ollama_connection():
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
            await _repl_loop(session, agent, session_state)
    else:
        try:
            agent = create_genie_agent(model_name=model_name, on_audio=_play_audio)
        except Exception as e:
            console.print(f"[bold red]Failed to create agent:[/bold red] {e}")
            return
        await _repl_loop(session, agent, session_state)


async def _repl_loop(session: PromptSession, agent, session_state: dict):
    """Inner REPL loop."""
    while True:
        try:
            user_input = await asyncio.to_thread(
                session.prompt, "\n🧞 You > "
            )
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # Handle slash commands
        if user_input.startswith("/"):
            result = handle_command(user_input, session_state)
            if result is False:
                break
            if result is True:
                continue

        # Run agent
        config = {"configurable": {"thread_id": session_state["thread_id"]}}
        try:
            console.print("\n[bold magenta]Genie[/bold magenta]", end="")
            await run_agent_stream(agent, user_input, config)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]")
        except Exception as e:
            console.print(f"\n[bold red]Error:[/bold red] {e}")


def main(model_name: str | None = None, thread_id: str | None = None, use_memory: bool = True):
    """Entry point for the Genie CLI."""
    model_name = model_name or OLLAMA_MODEL
    asyncio.run(repl(model_name, thread_id, use_memory))
