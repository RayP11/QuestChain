"""First-run onboarding flow for Genie."""

import asyncio
import os
import random

from rich.panel import Panel
from rich.text import Text

from genie.agent import build_input
from genie.config import get_onboarded_marker_path

GENIE_ART = (
    " ██████╗ ███████╗███╗   ██╗██╗███████╗\n"
    "██╔════╝ ██╔════╝████╗  ██║██║██╔════╝\n"
    "██║  ███╗█████╗  ██╔██╗ ██║██║█████╗\n"
    "██║   ██║██╔══╝  ██║╚██╗██║██║██╔══╝\n"
    "╚██████╔╝███████╗██║ ╚████║██║███████╗\n"
    " ╚═════╝ ╚══════╝╚═╝  ╚═══╝╚═╝╚══════╝"
)

TAGLINES = [
    "Your wish is my command — but first, let's get acquainted.",
    "Three wishes? Please. I've got unlimited tool calls.",
    "Freshly summoned and ready to work.",
    "No lamp required — just a terminal and a dream.",
    "I live in your shell now. Let's make it cozy.",
    "Locally powered, globally capable.",
    "Think of me as your co-pilot, but I actually read the docs.",
    "I promise not to turn you into a frog. Probably.",
    "All the power of AI, none of the cloud bills.",
    "I've been waiting in that lamp for ages. What did I miss?",
]

OPENING_QUESTION = (
    "Hey, nice to meet you! Tell me a bit about yourself — what should I call you, "
    "what kind of stuff will we be working on together, and how do you like to "
    "communicate? Just riff, I'll pick it up from here."
)

ONBOARDING_SYSTEM = """\
You are onboarding a new user for Genie. The user just introduced themselves \
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
    """Build the first-run welcome panel with ASCII art and a random tagline."""
    content = Text()
    for line in GENIE_ART.strip().splitlines():
        content.append(line + "\n", style="bold magenta")
    content.append("\n")
    content.append("  🧞 ", style="bold")
    content.append(random.choice(TAGLINES), style="italic cyan")
    content.append("\n\n")
    content.append("  Let's get to know each other — answer a few quick questions\n", style="dim")
    content.append("  and I'll remember your preferences for next time.", style="dim")
    return Panel(content, border_style="magenta", title="[bold magenta] Welcome [/bold magenta]", subtitle="[dim]Ctrl+C to skip[/dim]")


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


async def _setup_credentials(console, prompt_session) -> None:
    """Prompt for any missing API keys / Telegram credentials and persist to .env."""
    needs_tavily = not os.getenv("TAVILY_API_KEY")
    needs_telegram = not os.getenv("TELEGRAM_BOT_TOKEN")

    if not needs_tavily and not needs_telegram:
        return

    console.print()
    console.print(Panel(
        "Some optional integrations aren't configured yet.\n"
        "Press [bold]Enter[/bold] to skip anything you don't want to set up now.",
        title="Setup",
        border_style="cyan",
    ))

    try:
        from dotenv import find_dotenv, set_key
        env_path = find_dotenv() or ".env"
    except ImportError:
        env_path = None

    def _save(key: str, value: str) -> None:
        os.environ[key] = value
        if env_path:
            try:
                from dotenv import set_key
                set_key(env_path, key, value)
            except Exception:
                pass

    if needs_tavily:
        console.print("\n[bold]Web Search — Tavily[/bold]")
        console.print("  Free API key at [cyan]https://tavily.com[/cyan]")
        key = await _prompt_input(prompt_session, console, "  Tavily API key (Enter to skip): ")
        if key:
            _save("TAVILY_API_KEY", key)
            console.print("  [green]✓ Saved[/green]")
        else:
            console.print("  [dim]Skipped[/dim]")

    if needs_telegram:
        console.print("\n[bold]Telegram Bot[/bold]")
        console.print(
            "  1. Message [cyan]@BotFather[/cyan] on Telegram → /newbot → copy the token\n"
            "  2. Message [cyan]@userinfobot[/cyan] on Telegram → copy your numeric user ID"
        )
        token = await _prompt_input(
            prompt_session, console,
            "  Bot token (Enter to skip): ",
            password=True,
        )
        if token:
            _save("TELEGRAM_BOT_TOKEN", token)
            owner_id = await _prompt_input(
                prompt_session, console, "  Your Telegram user ID: "
            )
            if owner_id:
                _save("TELEGRAM_OWNER_ID", owner_id)
            console.print("  [green]✓ Saved[/green]")
        else:
            console.print("  [dim]Skipped[/dim]")

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
    import asyncio

    try:
        if prompt_session:
            raw = await prompt_session.prompt_async("\n🧞 You > ")
        else:
            raw = await asyncio.to_thread(input, "\n🧞 You > ")
        return raw.strip()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[dim]Onboarding skipped.[/dim]")
        return None


async def run_onboarding(agent, console, prompt_session=None) -> bool:
    """Run the interactive onboarding conversation.

    Returns True if onboarding completed, False if skipped.
    """
    # Collect any missing credentials before anything else
    await _setup_credentials(console, prompt_session)

    config = {"configurable": {"thread_id": "onboarding"}, "recursion_limit": 200}

    # Show the welcome banner
    console.print()
    console.print(_build_welcome_panel())

    # Hardcoded first question — no AI latency, instant personality
    console.print("\n[bold magenta]Genie[/bold magenta]")
    console.print(OPENING_QUESTION)

    # Get the user's intro
    user_input = await _prompt_user(prompt_session, console)
    if not user_input:
        return False

    # Send user's intro + system context to the agent for follow-up
    first_message = f"[System: {ONBOARDING_SYSTEM}]\n\nUser's introduction: {user_input}"
    console.print("\n[bold magenta]Genie[/bold magenta]")
    full_response = await _stream_agent(agent, first_message, config, console)

    if "ONBOARDING_COMPLETE" in full_response:
        mark_onboarded()
        return True

    # Conversation loop for follow-up questions
    while True:
        user_input = await _prompt_user(prompt_session, console)
        if not user_input:
            return False

        console.print("\n[bold magenta]Genie[/bold magenta]")
        full_response = await _stream_agent(agent, user_input, config, console)

        if "ONBOARDING_COMPLETE" in full_response:
            mark_onboarded()
            return True
