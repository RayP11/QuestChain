"""First-run onboarding flow for QuestChain."""

import asyncio
import os
import random
import shutil
from pathlib import Path

from rich.panel import Panel
from rich.text import Text

_SEP = "─"

from questchain.agent import build_input
from questchain.config import QUESTCHAIN_DATA_DIR, get_onboarded_marker_path

QUESTCHAIN_ART = (
    "  ██████╗ ██╗   ██╗███████╗███████╗████████╗\n"
    " ██╔═══██╗██║   ██║██╔════╝██╔════╝╚══██╔══╝\n"
    " ██║   ██║██║   ██║█████╗  ███████╗   ██║\n"
    " ██║▄▄ ██║██║   ██║██╔══╝  ╚════██║   ██║\n"
    " ╚██████╔╝╚██████╔╝███████╗███████║   ██║\n"
    "  ╚══▀▀═╝  ╚═════╝ ╚══════╝╚══════╝   ╚═╝\n"
    "     ██████╗██╗  ██╗ █████╗ ██╗███╗   ██╗\n"
    "    ██╔════╝██║  ██║██╔══██╗██║████╗  ██║\n"
    "    ██║     ███████║███████║██║██╔██╗ ██║\n"
    "    ██║     ██╔══██║██╔══██║██║██║╚██╗██║\n"
    "    ╚██████╗██║  ██║██║  ██║██║██║ ╚████║\n"
    "     ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝"
)

TAGLINES = [
    "What's the quest today?",
    "Locally powered, globally capable.",
    "All the power of AI, none of the cloud bills.",
    "Your data stays home. Your answers don't.",
    "Every task is a quest. Let's complete it.",
    "No cloud. No rate limits. No nonsense.",
    "Your machine. Your model. Your rules.",
    "One prompt away from getting it done.",
    "The agent that actually runs on your hardware.",
    "Think of me as your co-pilot, but I actually read the docs.",
]

OPENING_QUESTION = (
    "Hey, nice to meet you! Tell me a bit about yourself — what should I call you, "
    "what kind of stuff will we be working on together, and how do you like to "
    "communicate? Just riff, I'll pick it up from here."
)

ONBOARDING_SYSTEM = """\
You are onboarding a new user for QuestChain. The user just introduced themselves \
in response to an opening question. Continue the conversation naturally to \
learn more about them.

Topics to weave in (you don't need to cover all — skip what they already told you):
1. What they want help with most (coding, research, writing, system admin, etc.)
2. How they like to communicate (concise vs detailed, casual vs formal)
3. What kind of tasks they'll typically throw at you
4. Any tools, languages, frameworks, or workflows they use regularly
5. Anything else they'd like you to know

After you've learned enough (or the user says "done"), write a user profile \
summarizing what you learned to `/workspace/memory/ABOUT.md`. Use markdown \
with clear sections. This file will be loaded into your context in future \
conversations so you can personalize your responses.

After writing the file, end your FINAL message with the exact token: \
ONBOARDING_COMPLETE

Important:
- Ask only ONE question at a time. Wait for the user's answer before the next.
- Keep it conversational and fun, not like a form or survey.
- 2-4 follow-up questions is usually enough. Read the vibe — if they want to get going, wrap up.
- If they already told you a lot in their first message, you can wrap up sooner.
"""


def _build_welcome_panel() -> Panel:
    """Build the first-run welcome panel with a tagline and onboarding prompt."""
    content = Text()
    content.append("  🔗 ", style="bold")
    content.append(random.choice(TAGLINES), style="italic cyan")
    content.append("\n\n")
    content.append("  Let's get to know each other — answer a few quick questions\n", style="dim")
    content.append("  and I'll remember your preferences for next time.", style="dim")
    return Panel(content, border_style="green", title="[bold green] Welcome [/bold green]", subtitle="[dim]Ctrl+C to skip[/dim]")


def is_onboarded() -> bool:
    """Check if the user has completed onboarding."""
    return get_onboarded_marker_path().exists()


def mark_onboarded() -> None:
    """Create the onboarded marker file."""
    path = get_onboarded_marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("done")


def clear_onboarded() -> None:
    """Delete the onboarded marker file."""
    path = get_onboarded_marker_path()
    if path.exists():
        path.unlink()


def _get_env_path() -> Path:
    """Return the canonical ~/.questchain/.env path for persisting credentials."""
    path = QUESTCHAIN_DATA_DIR / ".env"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _save_env_key(key: str, value: str) -> None:
    """Write a key=value to os.environ and to ~/.questchain/.env."""
    os.environ[key] = value
    try:
        from dotenv import set_key
        set_key(str(_get_env_path()), key, value)
    except Exception:
        pass


async def _prompt_input(
    prompt_session, console, prompt_str: str, password: bool = False
) -> str:
    """Prompt for a single value. Returns empty string if skipped or interrupted."""
    try:
        if prompt_session:
            return (await prompt_session.prompt_async(prompt_str, is_password=password)).strip()
        return (await asyncio.to_thread(input, prompt_str)).strip()
    except (EOFError, KeyboardInterrupt):
        return ""


async def run_setup_tavily(console, prompt_session) -> bool:
    """Interactive wizard to configure the Tavily web search API key.

    Saves to ~/.questchain/.env.  Returns True if a key was saved.
    """
    current = os.getenv("TAVILY_API_KEY", "")
    console.print()
    console.print(Panel(
        "[bold]Web Search — Tavily[/bold]\n\n"
        "Get a free API key at [cyan]https://tavily.com[/cyan]\n"
        + (f"Current key: [dim]{current[:8]}…[/dim]" if current else "Not configured yet."),
        border_style="cyan",
        title="Tavily Setup",
    ))
    key = await _prompt_input(prompt_session, console, "  API key (Enter to skip): ")
    if key:
        _save_env_key("TAVILY_API_KEY", key)
        console.print("  [green]✓ Saved to ~/.questchain/.env — restart QuestChain to enable web search.[/green]")
        return True
    console.print("  [dim]Skipped.[/dim]")
    return False


async def run_setup_telegram(console, prompt_session) -> bool:
    """Interactive wizard to configure Telegram bot credentials.

    Saves to ~/.questchain/.env.  Returns True if credentials were saved.
    """
    current_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    current_owner = os.getenv("TELEGRAM_OWNER_ID", "")
    console.print()
    console.print(Panel(
        "[bold]Telegram Bot[/bold]\n\n"
        "1. Message [cyan]@BotFather[/cyan] on Telegram → /newbot → copy the token\n"
        "2. Message [cyan]@userinfobot[/cyan] on Telegram → copy your numeric user ID\n\n"
        + (f"Current token: [dim]{current_token[:8]}…[/dim]" if current_token else "Not configured yet."),
        border_style="cyan",
        title="Telegram Setup",
    ))
    token = await _prompt_input(
        prompt_session, console, "  Bot token (Enter to skip): ", password=True
    )
    if not token:
        console.print("  [dim]Skipped.[/dim]")
        return False
    _save_env_key("TELEGRAM_BOT_TOKEN", token)
    owner_id = await _prompt_input(prompt_session, console, "  Your Telegram user ID: ")
    if owner_id:
        _save_env_key("TELEGRAM_OWNER_ID", owner_id)
    console.print("  [green]✓ Saved to ~/.questchain/.env — restart QuestChain to activate the bot.[/green]")
    return True


async def _run_integration_setup(console, prompt_session) -> None:
    """Offer Tavily and Telegram setup as optional post-onboarding steps."""
    needs_tavily = not os.getenv("TAVILY_API_KEY")
    needs_telegram = not os.getenv("TELEGRAM_BOT_TOKEN")
    if not needs_tavily and not needs_telegram:
        return

    console.print()
    console.print(Panel(
        "One more thing — a couple of optional integrations can make QuestChain more powerful.\n"
        "Press [bold]Enter[/bold] to skip any you don't want to set up right now.\n"
        "You can always run [cyan]/tavily[/cyan] or [cyan]/telegram[/cyan] later.",
        title="Optional Setup",
        border_style="cyan",
    ))
    if needs_tavily:
        await run_setup_tavily(console, prompt_session)
    if needs_telegram:
        await run_setup_telegram(console, prompt_session)
    console.print()


async def _stream_agent(agent, message: str, config: dict, console) -> str:
    """Send a message to the agent and stream the response. Returns full text."""
    full_response = ""
    async for event in agent.astream_events(
        build_input(message),
        config=config,
        version="v2",
    ):
        kind = event["event"]
        if kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            if hasattr(chunk, "content") and isinstance(chunk.content, str):
                full_response += chunk.content
                console.print(chunk.content, end="")
        elif kind == "on_tool_start":
            tool_name = event.get("name", "unknown")
            console.print()
            console.print(f"  [dim]> Using tool:[/dim] [cyan]{tool_name}[/cyan]")
    console.print()
    return full_response


async def _prompt_user(prompt_session, console) -> str | None:
    """Prompt for user input. Returns stripped text, or None on interrupt."""
    width = shutil.get_terminal_size().columns
    sep = _SEP * width
    console.print(sep, style="dim")
    try:
        if prompt_session:
            raw = await prompt_session.prompt_async("❯ ")
        else:
            raw = await asyncio.to_thread(input, "❯ ")
        console.print(sep, style="dim")
        return raw.strip()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[dim]Onboarding skipped.[/dim]")
        return None


async def run_onboarding(agent, console, prompt_session=None) -> bool:
    """Run the interactive onboarding conversation.

    Returns True if onboarding completed, False if skipped.
    """
    config = {"configurable": {"thread_id": "onboarding"}, "recursion_limit": 200}

    # Show the welcome banner
    console.print()
    console.print(_build_welcome_panel())

    # Hardcoded first question — no AI latency, instant personality
    console.print("\n[bold green]QuestChain[/bold green]")
    console.print(OPENING_QUESTION)

    # Get the user's intro
    user_input = await _prompt_user(prompt_session, console)
    if not user_input:
        return False

    # Ask the user what they'd like to call the agent
    console.print("\n[bold green]QuestChain[/bold green]")
    console.print("What would you like to call me? (Press Enter to keep 'QuestChain')")
    name_input = await _prompt_user(prompt_session, console)
    agent_name = "QuestChain"
    if name_input:
        from questchain.agents import AgentManager
        AgentManager().update("default", name=name_input)
        agent_name = name_input

    # Send user's intro + system context to the agent for follow-up
    first_message = f"[System: {ONBOARDING_SYSTEM}]\n\nUser's introduction: {user_input}"
    console.print(f"\n[bold green]{agent_name}[/bold green]")
    full_response = await _stream_agent(agent, first_message, config, console)

    if "ONBOARDING_COMPLETE" in full_response:
        mark_onboarded()
        await _run_integration_setup(console, prompt_session)
        return True

    # Conversation loop for follow-up questions
    while True:
        user_input = await _prompt_user(prompt_session, console)
        if not user_input:
            return False

        console.print(f"\n[bold green]{agent_name}[/bold green]")
        full_response = await _stream_agent(agent, user_input, config, console)

        if "ONBOARDING_COMPLETE" in full_response:
            mark_onboarded()
            await _run_integration_setup(console, prompt_session)
            return True
