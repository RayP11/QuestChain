"""Genie Telegram bot adapter."""

import asyncio
import json
import logging
import uuid

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from genie.agent import build_input
from genie.agents import AgentManager, SELECTABLE_TOOLS
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
    "/agents — Manage agents (list, switch, create, edit)\n"
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


async def cmd_agent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /agent command — show agents inline keyboard."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    agent_manager: AgentManager | None = context.bot_data.get("agent_manager")
    if agent_manager is None:
        await update.message.reply_text("Agent manager not available.")
        return

    active_id = agent_manager.get_active_id()
    keyboard = []
    for agent_def in agent_manager.all_agents():
        agent_id = agent_def["id"]
        name = agent_def["name"]
        model = agent_def.get("model") or OLLAMA_MODEL
        is_active = agent_id == active_id
        label = f"{'✓ ' if is_active else '  '}{name}  ({model})"
        row = [InlineKeyboardButton(label, callback_data=f"agent:pick:{agent_id}")]
        row.append(InlineKeyboardButton("✏️", callback_data=f"agent:edit:{agent_id}"))
        if not agent_def.get("built_in"):
            row.append(InlineKeyboardButton("🗑️", callback_data=f"agent:delete:{agent_id}"))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("➕ New agent", callback_data="agent:build")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🧞 Agents", reply_markup=reply_markup)


async def callback_agent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle agent: inline keyboard callbacks."""
    query = update.callback_query
    if not _is_owner(query.from_user.id):
        await query.answer("This bot is private.")
        return

    await query.answer()
    data = query.data

    agent_manager: AgentManager | None = context.bot_data.get("agent_manager")

    if data.startswith("agent:pick:"):
        agent_id = data[len("agent:pick:"):]
        if agent_manager is None:
            await query.edit_message_text("Agent manager not available.")
            return
        active_id = agent_manager.get_active_id()
        if agent_id == active_id:
            return  # Already active — silently ignore
        agent_def = agent_manager.get(agent_id)
        if agent_def is None:
            await query.edit_message_text(f"Agent not found: {agent_id}")
            return
        agent_holder: dict | None = context.bot_data.get("agent_holder")
        checkpointer = context.bot_data.get("checkpointer")
        store = context.bot_data.get("store")
        audio_router = context.bot_data.get("audio_router")
        from genie.cli import _make_agent_from_def
        try:
            new_agent = _make_agent_from_def(agent_def, checkpointer, store, audio_router)
            agent_holder["agent"] = new_agent
            context.bot_data["model_name"] = agent_def.get("model") or OLLAMA_MODEL
            agent_manager.set_active(agent_id)
            await query.edit_message_text(f"🧞 Switched to '{agent_def['name']}'.")
        except Exception as e:
            await query.edit_message_text(f"Failed to switch agent: {e}")

    elif data == "agent:build":
        context.chat_data["building_agent"] = {"step": "name", "data": {}}
        await query.edit_message_text(
            "Let's create a new agent. Send /cancel at any time.\n\n"
            "Step 1/4 — What's the agent's name?"
        )

    elif data.startswith("agent:edit:"):
        agent_id = data[len("agent:edit:"):]
        if agent_manager is None:
            await query.edit_message_text("Agent manager not available.")
            return
        agent_def = agent_manager.get(agent_id)
        if agent_def is None:
            await query.edit_message_text(f"Agent not found: {agent_id}")
            return
        context.chat_data["building_agent"] = {
            "step": "edit_name",
            "data": {
                "edit_id": agent_id,
                "name": agent_def["name"],
                "model": agent_def.get("model"),
                "tools": agent_def.get("tools", "all"),
                "system_prompt": agent_def.get("system_prompt"),
            },
        }
        await query.edit_message_text(
            f"Editing '{agent_def['name']}'. Send '-' to keep the current value.\n\n"
            f"Step 1/4 — New name? (current: {agent_def['name']})"
        )

    elif data.startswith("agent:delete:"):
        agent_id = data[len("agent:delete:"):]
        if agent_manager is None:
            await query.edit_message_text("Agent manager not available.")
            return
        agent_def = agent_manager.get(agent_id)
        if agent_def is None:
            await query.edit_message_text(f"Agent not found: {agent_id}")
            return
        keyboard = [[
            InlineKeyboardButton("Yes, delete", callback_data=f"agent:delete_confirm:{agent_id}"),
            InlineKeyboardButton("Cancel", callback_data="agent:delete_cancel"),
        ]]
        await query.edit_message_text(
            f"Delete '{agent_def['name']}'?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data.startswith("agent:delete_confirm:"):
        agent_id = data[len("agent:delete_confirm:"):]
        if agent_manager is None:
            await query.edit_message_text("Agent manager not available.")
            return
        agent_def = agent_manager.get(agent_id)
        name = agent_def["name"] if agent_def else agent_id
        try:
            agent_manager.remove(agent_id)
            await query.edit_message_text(f"✓ '{name}' deleted.")
        except ValueError as e:
            await query.edit_message_text(str(e))

    elif data == "agent:delete_cancel":
        await query.edit_message_text("Cancelled.")


async def _handle_build_agent_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Process wizard steps for agent creation/editing. Returns True if message was consumed."""
    state = context.chat_data.get("building_agent")
    if state is None:
        return False

    text = (update.message.text or "").strip()

    # Allow cancellation at any step
    if text.lower() == "/cancel":
        context.chat_data.pop("building_agent", None)
        await update.message.reply_text("Cancelled.")
        return True

    step = state["step"]
    data = state["data"]

    # ── Create flow ──────────────────────────────────────────────────────────

    if step == "name":
        if not text:
            await update.message.reply_text("Name cannot be empty. What's the agent's name?")
            return True
        data["name"] = text
        state["step"] = "model"
        await update.message.reply_text(
            f"Step 2/4 — Which model? (send empty for default: {OLLAMA_MODEL})"
        )

    elif step == "model":
        data["model"] = text if text else None
        state["step"] = "tools"
        tool_lines = "\n".join(
            f"  {i}. {name} — {desc}"
            for i, (name, desc) in enumerate(SELECTABLE_TOOLS, 1)
        )
        await update.message.reply_text(
            f"Step 3/4 — Which tools? (filesystem/shell/planning always included)\n\n"
            f"{tool_lines}\n\n"
            f"Send comma-separated numbers (e.g. '1,2'), or 'all' for all tools."
        )

    elif step == "tools":
        if text.lower() in ("", "all"):
            data["tools"] = "all"
        else:
            selected: list[str] = []
            for part in text.split(","):
                part = part.strip()
                if part.isdigit():
                    idx = int(part) - 1
                    if 0 <= idx < len(SELECTABLE_TOOLS):
                        selected.append(SELECTABLE_TOOLS[idx][0])
            data["tools"] = selected if selected else "all"
        state["step"] = "prompt"
        await update.message.reply_text(
            "Step 4/4 — System prompt? (send empty to use the default Genie prompt)"
        )

    elif step == "prompt":
        data["system_prompt"] = text if text else None
        state["step"] = "confirm"
        tools_display = data["tools"] if data["tools"] == "all" else ", ".join(data["tools"])
        model_display = data.get("model") or f"{OLLAMA_MODEL} (default)"
        prompt_display = data.get("system_prompt") or "(default Genie prompt)"
        await update.message.reply_text(
            f"Confirm new agent:\n\n"
            f"Name: {data['name']}\n"
            f"Model: {model_display}\n"
            f"Tools: {tools_display}\n"
            f"Prompt: {prompt_display[:200]}{'…' if len(prompt_display) > 200 else ''}\n\n"
            f"Send 'yes' to create, anything else to cancel."
        )

    elif step == "confirm":
        if text.lower() in ("yes", "y"):
            agent_manager: AgentManager | None = context.bot_data.get("agent_manager")
            if agent_manager is None:
                await update.message.reply_text("Agent manager not available.")
                context.chat_data.pop("building_agent", None)
                return True
            agent_manager.add(
                name=data["name"],
                model=data.get("model"),
                system_prompt=data.get("system_prompt"),
                tools=data["tools"],
            )
            context.chat_data.pop("building_agent", None)
            await update.message.reply_text(
                f"✓ Agent '{data['name']}' created!\nUse /agents to activate it."
            )
        else:
            context.chat_data.pop("building_agent", None)
            await update.message.reply_text("Agent creation cancelled.")

    # ── Edit flow ────────────────────────────────────────────────────────────

    elif step == "edit_name":
        if text and text != "-":
            data["name"] = text
        state["step"] = "edit_model"
        current_model = data.get("model") or OLLAMA_MODEL
        await update.message.reply_text(
            f"Step 2/4 — New model? (current: {current_model}, send '-' to keep)"
        )

    elif step == "edit_model":
        if text and text != "-":
            data["model"] = text
        state["step"] = "edit_tools"
        current_tools = data.get("tools", "all")
        tools_display = current_tools if current_tools == "all" else ", ".join(current_tools)
        tool_lines = "\n".join(
            f"  {i}. {name} — {desc}"
            for i, (name, desc) in enumerate(SELECTABLE_TOOLS, 1)
        )
        await update.message.reply_text(
            f"Step 3/4 — Tools? (current: {tools_display})\n\n"
            f"{tool_lines}\n\n"
            f"Send comma-separated numbers, 'all', or '-' to keep current."
        )

    elif step == "edit_tools":
        if text and text != "-":
            if text.lower() == "all":
                data["tools"] = "all"
            else:
                selected_edit: list[str] = []
                for part in text.split(","):
                    part = part.strip()
                    if part.isdigit():
                        idx = int(part) - 1
                        if 0 <= idx < len(SELECTABLE_TOOLS):
                            selected_edit.append(SELECTABLE_TOOLS[idx][0])
                if selected_edit:
                    data["tools"] = selected_edit
        state["step"] = "edit_prompt"
        current_prompt = data.get("system_prompt") or "(default)"
        await update.message.reply_text(
            f"Step 4/4 — System prompt?\n"
            f"Current: {current_prompt[:100]}{'…' if len(current_prompt) > 100 else ''}\n\n"
            f"Send new prompt, or '-' to keep current."
        )

    elif step == "edit_prompt":
        if text and text != "-":
            data["system_prompt"] = text
        state["step"] = "edit_confirm"
        current_tools = data.get("tools", "all")
        tools_display = current_tools if current_tools == "all" else ", ".join(current_tools)
        model_display = data.get("model") or f"{OLLAMA_MODEL} (default)"
        prompt_display = data.get("system_prompt") or "(default Genie prompt)"
        await update.message.reply_text(
            f"Confirm updated agent:\n\n"
            f"Name: {data['name']}\n"
            f"Model: {model_display}\n"
            f"Tools: {tools_display}\n"
            f"Prompt: {prompt_display[:200]}{'…' if len(prompt_display) > 200 else ''}\n\n"
            f"Send 'yes' to save, anything else to cancel."
        )

    elif step == "edit_confirm":
        if text.lower() in ("yes", "y"):
            agent_manager_edit: AgentManager | None = context.bot_data.get("agent_manager")
            if agent_manager_edit is None:
                await update.message.reply_text("Agent manager not available.")
                context.chat_data.pop("building_agent", None)
                return True
            agent_manager_edit.update(
                data["edit_id"],
                name=data["name"],
                model=data.get("model"),
                tools=data.get("tools", "all"),
                system_prompt=data.get("system_prompt"),
            )
            context.chat_data.pop("building_agent", None)
            await update.message.reply_text(f"✓ Agent '{data['name']}' updated!")
        else:
            context.chat_data.pop("building_agent", None)
            await update.message.reply_text("Edit cancelled.")

    return True


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

    # Intercept wizard messages first
    if await _handle_build_agent_wizard(update, context):
        return

    agent_holder = context.bot_data.get("agent_holder")
    agent = agent_holder["agent"] if agent_holder else context.bot_data.get("agent")
    audio_router = context.bot_data.get("audio_router")
    chat_id = update.effective_chat.id

    # First-run onboarding: intercept the first message (direct path, not queued)
    onboarding_active = context.chat_data.get("onboarding_active", False)
    if not is_onboarded() and not onboarding_active:
        context.chat_data["onboarding_active"] = True
        await update.message.reply_text(OPENING_QUESTION)
        return

    if onboarding_active:
        thread_id = "onboarding"
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 200}
        await update.effective_chat.send_action(ChatAction.TYPING)

        if not context.chat_data.get("onboarding_intro_sent", False):
            context.chat_data["onboarding_intro_sent"] = True
            message = f"[System: {ONBOARDING_SYSTEM}]\n\nUser's introduction: {user_text}"
        else:
            message = user_text

        if audio_router is not None:
            audio_router.set_telegram(update)
        full_response = await _run_agent_collect(agent, message, config, update)
        if audio_router is not None:
            audio_router.set_cli()
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
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 200}
    loop = asyncio.get_event_loop()
    response_future: asyncio.Future = loop.create_future()

    await telegram_queue.put((user_text, config, response_future, update))

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
    agent_holder: dict,
    model_name: str,
    telegram_queue: asyncio.Queue,
    audio_router,
    agent_manager: "AgentManager | None" = None,
) -> tuple:
    """Start Telegram bot alongside the CLI REPL.

    Returns ``(send_to_owner, stop_fn)`` coroutines, or ``(None, None)`` if
    ``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_OWNER_ID`` are not configured.

    The caller is responsible for calling ``stop_fn()`` on exit.  The bot
    shares the already-created *agent_holder* (and its checkpointer) with the CLI.
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

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.bot_data["agent_holder"] = agent_holder
    app.bot_data["agent"] = agent_holder["agent"]  # legacy fallback
    app.bot_data["model_name"] = model_name
    app.bot_data["audio_router"] = audio_router
    app.bot_data["telegram_queue"] = telegram_queue
    if agent_manager is not None:
        app.bot_data["agent_manager"] = agent_manager

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

    scheduler = CronScheduler(agent=agent_holder["agent"], send_callback=send_to_owner)
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
    app.add_handler(CommandHandler("agents", cmd_agent))
    app.add_handler(CallbackQueryHandler(callback_agent, pattern="^agent:"))
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
        BotCommand("agents", "Manage agents — list, switch, create, edit"),
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
