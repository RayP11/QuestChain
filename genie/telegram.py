"""Genie Telegram bot adapter."""

import asyncio
import logging
import uuid

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from genie.agent import create_genie_agent
from genie.config import (
    OLLAMA_MODEL,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_OWNER_ID,
)
from genie.memory.store import create_checkpointer, create_memory_store
from genie.onboarding import ONBOARDING_SYSTEM, OPENING_QUESTION, is_onboarded, mark_onboarded

logger = logging.getLogger(__name__)

# Map chat_id -> thread_id for conversation persistence
_thread_ids: dict[int, str] = {}


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
    """Get or create a thread ID for a Telegram chat."""
    if chat_id not in _thread_ids:
        _thread_ids[chat_id] = str(uuid.uuid4())
    return _thread_ids[chat_id]


def _reset_thread(chat_id: int) -> str:
    """Reset the thread for a chat, returning the new thread ID."""
    new_id = str(uuid.uuid4())
    _thread_ids[chat_id] = new_id
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


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    await update.message.reply_text(
        "Hey! I'm Genie, your personal AI agent.\n\n"
        "Just send me a message and I'll help out.\n\n"
        "Commands:\n"
        "/new — Start a fresh conversation\n"
        "/model — Show current model"
    )


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


async def _run_agent_collect(agent, user_text: str, config: dict, update: Update) -> str:
    """Run the agent, collect full response, and send it to the user."""
    stop_typing = asyncio.Event()

    async def typing_loop():
        while not stop_typing.is_set():
            try:
                await update.effective_chat.send_action(ChatAction.TYPING)
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop_typing.wait(), timeout=4.0)
            except asyncio.TimeoutError:
                pass

    typing_task = asyncio.create_task(typing_loop())

    try:
        full_response = ""
        async for event in agent.astream_events(
            {"messages": [{"role": "user", "content": user_text}]},
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

    # First-run onboarding: intercept the first message
    onboarding_active = context.chat_data.get("onboarding_active", False)
    if not is_onboarded() and not onboarding_active:
        # Send hardcoded opening question, then start onboarding with user's reply
        context.chat_data["onboarding_active"] = True
        await update.message.reply_text(OPENING_QUESTION)
        return

    if onboarding_active:
        # Continue onboarding conversation on a dedicated thread
        thread_id = "onboarding"
        config = {"configurable": {"thread_id": thread_id}}
        await update.effective_chat.send_action(ChatAction.TYPING)

        # First reply from user gets wrapped with system context
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

    thread_id = _get_thread_id(chat_id)
    config = {"configurable": {"thread_id": thread_id}}

    # Send typing indicator
    await update.effective_chat.send_action(ChatAction.TYPING)

    # Keep typing indicator alive during long agent runs
    stop_typing = asyncio.Event()

    async def typing_loop():
        while not stop_typing.is_set():
            try:
                await update.effective_chat.send_action(ChatAction.TYPING)
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop_typing.wait(), timeout=4.0)
            except asyncio.TimeoutError:
                pass

    typing_task = asyncio.create_task(typing_loop())

    try:
        full_response = ""
        tool_names = []

        async for event in agent.astream_events(
            {"messages": [{"role": "user", "content": user_text}]},
            config=config,
            version="v2",
        ):
            kind = event["event"]

            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if hasattr(chunk, "content") and isinstance(chunk.content, str):
                    full_response += chunk.content

            elif kind == "on_tool_start":
                tool_name = event.get("name", "unknown")
                if tool_name not in tool_names:
                    tool_names.append(tool_name)

    except Exception as e:
        logger.exception("Agent error")
        full_response = f"Error: {e}"
    finally:
        stop_typing.set()
        await typing_task

    if not full_response.strip():
        full_response = "(No response generated)"

    # Send response, splitting if needed
    chunks = _split_message(full_response)
    for chunk in chunks:
        try:
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            # Fallback to plain text if markdown parsing fails
            await update.message.reply_text(chunk)

    # Show tool usage summary
    if tool_names:
        summary = "Tools used: " + ", ".join(tool_names)
        await update.message.reply_text(summary)


async def run_telegram_bot(
    model_name: str | None = None,
    busy_work_minutes: int | None = 60,
) -> None:
    """Start the Telegram bot (blocking)."""
    model_name = model_name or OLLAMA_MODEL

    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set. "
            "Get a token from @BotFather and add it to your .env file."
        )

    if not TELEGRAM_OWNER_ID:
        raise SystemExit(
            "TELEGRAM_OWNER_ID is not set. "
            "Add your Telegram user ID to your .env file."
        )

    store = create_memory_store()

    audio_sender = _AudioSender()

    async with create_checkpointer() as checkpointer:
        agent = create_genie_agent(
            model_name=model_name,
            checkpointer=checkpointer,
            store=store,
            on_audio=audio_sender,
        )

        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        # Store agent, model name, and audio sender in bot_data for handlers
        app.bot_data["agent"] = agent
        app.bot_data["model_name"] = model_name
        app.bot_data["audio_sender"] = audio_sender

        # Set up cron scheduler
        from genie.scheduler import CronScheduler, set_scheduler

        async def send_to_owner(text: str) -> None:
            """Send a cron job result to the bot owner."""
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

        scheduler = CronScheduler(
            agent=agent,
            send_callback=send_to_owner,
        )
        set_scheduler(scheduler)

        # Register handlers
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("new", cmd_new))
        app.add_handler(CommandHandler("model", cmd_model))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        logger.info("Starting Genie Telegram bot (model: %s)...", model_name)
        print(f"Genie Telegram bot started (model: {model_name})")
        print("Press Ctrl+C to stop.")

        # Run polling within the checkpointer context
        await app.initialize()
        await app.start()
        await app.updater.start_polling()

        # Start cron scheduler
        await scheduler.start()

        # Start busy work (if enabled)
        busy_work = None
        if busy_work_minutes is not None:
            from genie.busy_work import BusyWorkRunner

            busy_work = BusyWorkRunner(
                agent=agent,
                send_callback=send_to_owner,
                interval_minutes=busy_work_minutes,
            )
            await busy_work.start()
            logger.info("Busy work started (every %d min)", busy_work_minutes)

        # Block until interrupted
        stop_event = asyncio.Event()
        try:
            await stop_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            if busy_work:
                await busy_work.stop()
            await scheduler.stop()
            set_scheduler(None)
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
