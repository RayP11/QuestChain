"""Genie Telegram bot adapter."""

import asyncio
import json
import logging
import uuid

from telegram import BotCommand, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from genie.agent import build_input
from genie.config import (
    OLLAMA_MODEL,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_OWNER_ID,
    get_thread_ids_path,
)
from genie.onboarding import ONBOARDING_SYSTEM, OPENING_QUESTION, is_onboarded, mark_onboarded

logger = logging.getLogger(__name__)

# Map chat_id -> thread_id for conversation persistence (loaded from disk)
def _load_thread_ids() -> dict[int, str]:
    path = get_thread_ids_path()
    if path.exists():
        try:
            return {int(k): v for k, v in json.loads(path.read_text()).items()}
        except Exception:
            pass
    return {}


def _save_thread_ids() -> None:
    path = get_thread_ids_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({str(k): v for k, v in _thread_ids.items()}))


_thread_ids: dict[int, str] = _load_thread_ids()


class _AudioSender:
    """Callable that sends WAV audio as a Telegram voice message.

    The `.update` attribute is set before each agent invocation so the
    callback always targets the correct chat.
    """

    def __init__(self):
        self.update: Update | None = None

    async def __call__(self, wav_bytes: bytes) -> None:
        if self.update is None:
            logger.warning("AudioSender called but no update is set")
            return
        import io
        await self.update.message.reply_voice(voice=io.BytesIO(wav_bytes))


def _get_thread_id(chat_id: int) -> str:
    """Get or create a persistent thread ID for a Telegram chat."""
    if chat_id not in _thread_ids:
        _thread_ids[chat_id] = str(uuid.uuid4())
        _save_thread_ids()
    return _thread_ids[chat_id]


def _reset_thread(chat_id: int) -> str:
    """Reset the thread for a chat, returning the new thread ID."""
    new_id = str(uuid.uuid4())
    _thread_ids[chat_id] = new_id
    _save_thread_ids()
    return new_id


def _is_owner(user_id: int) -> bool:
    """Check if the user is the configured owner."""
    return user_id == TELEGRAM_OWNER_ID


def _split_message(text: str, max_len: int = 4096) -> list[str]:
    """Split a message into chunks that fit Telegram's limit."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break

        # Try to split at a newline near the limit
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1 or split_at < max_len // 2:
            # No good newline break; split at limit
            split_at = max_len

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks


async def _reject(update: Update) -> None:
    """Send a rejection message to unauthorized users."""
    await update.message.reply_text("Sorry, this bot is private.")


_HELP_TEXT = (
    "Commands:\n"
    "/new — Start a fresh conversation\n"
    "/model — Show current model\n"
    "/thread — Show current thread ID\n"
    "/busy — Show busy work status\n"
    "/tools — List available tools\n"
    "/instructions — Show agent system prompt\n"
    "/memory — Show your saved user profile\n"
    "/tasks — Show current task list\n"
    "/cron — List scheduled cron jobs\n"
    "/onboard — Re-run the onboarding flow\n"
    "/help — Show this help message"
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    await update.message.reply_text(
        "Hey! I'm Genie, your personal AI agent.\n\n"
        "Just send me a message and I'll help out.\n\n"
        + _HELP_TEXT
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    await update.message.reply_text(_HELP_TEXT)


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /new command — reset conversation."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    new_id = _reset_thread(update.effective_chat.id)
    await update.message.reply_text(f"Conversation reset. New thread: {new_id[:8]}...")


async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /model command — show current model."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    model_name = context.bot_data.get("model_name", OLLAMA_MODEL)
    await update.message.reply_text(f"Current model: {model_name}")


async def cmd_thread(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /thread command — show current thread ID."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    chat_id = update.effective_chat.id
    thread_id = _get_thread_id(chat_id)
    await update.message.reply_text(f"Thread ID: {thread_id}")


async def cmd_busy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /busy command — show busy work status."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    runner = context.bot_data.get("busy_work_runner")
    if runner and runner.running:
        await update.message.reply_text(
            f"Busy work: active (every {runner.interval_minutes} min)"
        )
    else:
        await update.message.reply_text("Busy work: disabled")


async def cmd_tools(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /tools command — list available tools."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    from genie.config import TAVILY_API_KEY
    text = (
        "Built-in tools (filesystem, shell, planning, sub-agents):\n"
        "  read_file, write_file, edit_file, ls, glob, grep\n"
        "  execute, write_todos, read_todos, task\n\n"
        "Custom tools:\n"
        "  claude_code — delegate coding tasks to Claude Code\n"
        "  cron_add, cron_list, cron_remove — scheduled jobs\n"
    )
    if TAVILY_API_KEY:
        text += "  web_search, web_browse — enabled"
    else:
        text += "  web_search, web_browse — disabled (no TAVILY_API_KEY)"
    await update.message.reply_text(text)


async def cmd_instructions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /instructions command — show system prompt."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    from genie.agent import SYSTEM_PROMPT
    chunks = _split_message(SYSTEM_PROMPT)
    for chunk in chunks:
        await update.message.reply_text(chunk)


async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /memory command — show ABOUT.md."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    from genie.config import MEMORY_DIR
    about = MEMORY_DIR / "ABOUT.md"
    if not about.exists():
        await update.message.reply_text("No memory file yet. Use /onboard to create one.")
        return
    chunks = _split_message(about.read_text())
    for chunk in chunks:
        try:
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.message.reply_text(chunk)


async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /tasks command — show TASKS.md."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    from genie.config import WORKSPACE_DIR
    tasks = WORKSPACE_DIR / "workspace" / "TASKS.md"
    if not tasks.exists():
        await update.message.reply_text("No TASKS.md found in workspace.")
        return
    chunks = _split_message(tasks.read_text())
    for chunk in chunks:
        try:
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.message.reply_text(chunk)


async def cmd_cron(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cron command — list scheduled cron jobs."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    import json
    from genie.config import get_cron_jobs_path
    jobs_path = get_cron_jobs_path()
    jobs = []
    if jobs_path.exists():
        try:
            jobs = json.loads(jobs_path.read_text())
        except Exception:
            pass
    if not jobs:
        await update.message.reply_text("No cron jobs configured.")
        return
    lines = []
    for j in jobs:
        status = "on" if j.get("enabled", True) else "off"
        lines.append(f"[{j['id']}] {j['name']} — {j['cron_expression']} ({status})")
    await update.message.reply_text("\n".join(lines))


async def cmd_onboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /onboard command — re-run onboarding."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    from genie.onboarding import clear_onboarded
    clear_onboarded()
    # Set active so the next message goes to the AI as the user's intro
    context.chat_data["onboarding_active"] = True
    context.chat_data.pop("onboarding_intro_sent", None)
    await update.message.reply_text(OPENING_QUESTION)


async def _keep_typing(chat, stop: asyncio.Event) -> None:
    """Send typing indicators to *chat* until *stop* is set."""
    while not stop.is_set():
        try:
            await chat.send_action(ChatAction.TYPING)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=4.0)
        except asyncio.TimeoutError:
            pass


async def _run_agent_collect(agent, user_text: str, config: dict, update: Update) -> str:
    """Run the agent, collect full response, and send it to the user."""
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(update.effective_chat, stop_typing))

    try:
        full_response = ""
        async for event in agent.astream_events(
            build_input(user_text),
            config=config,
            version="v2",
        ):
            kind = event["event"]
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if hasattr(chunk, "content") and isinstance(chunk.content, str):
                    full_response += chunk.content
    except Exception as e:
        logger.exception("Agent error")
        full_response = f"Error: {e}"
    finally:
        stop_typing.set()
        await typing_task

    if not full_response.strip():
        full_response = "(No response generated)"

    # Strip the ONBOARDING_COMPLETE token from user-visible output
    display_text = full_response.replace("ONBOARDING_COMPLETE", "").strip()
    if display_text:
        chunks = _split_message(display_text)
        for chunk in chunks:
            try:
                await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.message.reply_text(chunk)
    return full_response


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages — invoke the Genie agent."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    user_text = update.message.text
    if not user_text:
        return

    agent = context.bot_data["agent"]
    audio_sender: _AudioSender = context.bot_data["audio_sender"]
    audio_sender.update = update
    chat_id = update.effective_chat.id

    # First-run onboarding: intercept the first message (direct path, not queued)
    onboarding_active = context.chat_data.get("onboarding_active", False)
    if not is_onboarded() and not onboarding_active:
        context.chat_data["onboarding_active"] = True
        await update.message.reply_text(OPENING_QUESTION)
        return

    if onboarding_active:
        thread_id = "onboarding"
        config = {"configurable": {"thread_id": thread_id}}
        await update.effective_chat.send_action(ChatAction.TYPING)

        if not context.chat_data.get("onboarding_intro_sent", False):
            context.chat_data["onboarding_intro_sent"] = True
            message = f"[System: {ONBOARDING_SYSTEM}]\n\nUser's introduction: {user_text}"
        else:
            message = user_text

        full_response = await _run_agent_collect(agent, message, config, update)
        if "ONBOARDING_COMPLETE" in full_response:
            mark_onboarded()
            context.chat_data["onboarding_active"] = False
            context.chat_data.pop("onboarding_intro_sent", None)
        return

    # Normal message: hand off to the CLI REPL loop via queue
    telegram_queue = context.bot_data.get("telegram_queue")
    if telegram_queue is None:
        # Should not happen in alongside mode, but guard anyway
        logger.warning("telegram_queue not set; dropping message")
        await update.message.reply_text("(Bot not ready yet, try again.)")
        return

    thread_id = _get_thread_id(chat_id)
    config = {"configurable": {"thread_id": thread_id}}
    loop = asyncio.get_event_loop()
    response_future: asyncio.Future = loop.create_future()

    await telegram_queue.put((user_text, config, response_future))

    # Keep typing indicator alive while the REPL processes the message
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(update.effective_chat, stop_typing))
    try:
        full_response = await response_future
    except Exception as e:
        full_response = f"Error: {e}"
    finally:
        stop_typing.set()
        await typing_task

    if not full_response:
        return

    chunks = _split_message(full_response)
    for chunk in chunks:
        try:
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.message.reply_text(chunk)


async def run_telegram_alongside_cli(
    agent, model_name: str, telegram_queue: asyncio.Queue
) -> tuple:
    """Start Telegram bot alongside the CLI REPL.

    Returns ``(send_to_owner, stop_fn)`` coroutines, or ``(None, None)`` if
    ``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_OWNER_ID`` are not configured.

    The caller is responsible for calling ``stop_fn()`` on exit.  The bot
    shares the already-created *agent* (and its checkpointer) with the CLI.
    Incoming messages are queued onto *telegram_queue* for the REPL loop to
    process; responses are delivered back via per-message ``asyncio.Future``s.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_OWNER_ID:
        if TELEGRAM_BOT_TOKEN and not TELEGRAM_OWNER_ID:
            logger.warning(
                "TELEGRAM_OWNER_ID is not set — all incoming messages will be "
                "rejected. Set it to your Telegram user ID."
            )
        return None, None

    audio_sender = _AudioSender()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.bot_data["agent"] = agent
    app.bot_data["model_name"] = model_name
    app.bot_data["audio_sender"] = audio_sender
    app.bot_data["telegram_queue"] = telegram_queue

    async def send_to_owner(text: str) -> None:
        """Send a message to the bot owner via Telegram."""
        chunks = _split_message(text)
        for chunk in chunks:
            try:
                await app.bot.send_message(
                    chat_id=TELEGRAM_OWNER_ID,
                    text=chunk,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                await app.bot.send_message(
                    chat_id=TELEGRAM_OWNER_ID,
                    text=chunk,
                )

    from genie.scheduler import CronScheduler, set_scheduler

    scheduler = CronScheduler(agent=agent, send_callback=send_to_owner)
    set_scheduler(scheduler)

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CommandHandler("thread", cmd_thread))
    app.add_handler(CommandHandler("busy", cmd_busy))
    app.add_handler(CommandHandler("tools", cmd_tools))
    app.add_handler(CommandHandler("instructions", cmd_instructions))
    app.add_handler(CommandHandler("memory", cmd_memory))
    app.add_handler(CommandHandler("tasks", cmd_tasks))
    app.add_handler(CommandHandler("cron", cmd_cron))
    app.add_handler(CommandHandler("onboard", cmd_onboard))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await app.initialize()
    await app.bot.set_my_commands([
        BotCommand("new", "Start a fresh conversation"),
        BotCommand("model", "Show current model"),
        BotCommand("thread", "Show current thread ID"),
        BotCommand("busy", "Show busy work status"),
        BotCommand("tools", "List available tools"),
        BotCommand("instructions", "Show agent system prompt"),
        BotCommand("memory", "Show your saved user profile"),
        BotCommand("tasks", "Show current task list"),
        BotCommand("cron", "List scheduled cron jobs"),
        BotCommand("onboard", "Re-run the onboarding flow"),
        BotCommand("help", "Show all commands"),
    ])
    await app.start()
    await app.updater.start_polling()
    await scheduler.start()

    async def stop_fn() -> None:
        await scheduler.stop()
        set_scheduler(None)
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

    return send_to_owner, stop_fn
