"""QuestChain Telegram bot adapter."""

import asyncio
import json
import logging
import os
import tempfile
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

from questchain.agents import AGENT_CLASSES, AgentManager, CLASS_TOOL_PRESETS, DEFAULT_CLASS, SELECTABLE_TOOLS, CLASS_GUIDANCE, preset_prompt, get_dynamic_selectable_tools, ROLE_LABELS
from questchain.progression import ProgressionManager, TOTAL_ACHIEVEMENTS
from questchain.stats import MetricsManager
from questchain.config import (
    OLLAMA_MODEL,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_OWNER_ID,
    get_thread_ids_path,
)
from questchain.onboarding import ONBOARDING_SYSTEM, OPENING_QUESTION, is_onboarded, mark_onboarded

logger = logging.getLogger(__name__)

# Silence the full traceback that python-telegram-bot logs when the polling
# loop hits a NetworkError (e.g. offline, DNS failure).  The bot retries
# automatically; we show a single dim line in the CLI instead.
logging.getLogger("telegram.ext._utils.networkloop").setLevel(logging.CRITICAL)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Map chat_id -> thread_id for conversation persistence (loaded from disk)
def _load_thread_ids() -> dict[int, str]:
    path = get_thread_ids_path()
    if path.exists():
        try:
            return {int(k): v for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
        except Exception:
            pass
    return {}


def _save_thread_ids() -> None:
    path = get_thread_ids_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({str(k): v for k, v in _thread_ids.items()}), encoding="utf-8")


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
    if TELEGRAM_OWNER_ID is None:
        logger.warning(
            "TELEGRAM_OWNER_ID is not set — rejecting all users. "
            "Set it in .env to your Telegram user ID."
        )
        return False
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
        "Hey! I'm QuestChain, your personal AI agent.\n\n"
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
    context.chat_data.pop("last_run_id", None)
    await update.message.reply_text(f"Conversation reset. New thread: {new_id[:8]}...")


async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /model command — show current model."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    manager = context.bot_data.get("agent_manager")
    if manager is None:
        return await update.message.reply_text("Agent manager not available.")
    definition = manager.get(context.chat_data.get("agent_id", manager.get_active_id())) or manager.get_active()
    runtime = context.bot_data.get("runtime")
    default_model = runtime.default_model if runtime else context.bot_data.get("model_name", OLLAMA_MODEL)
    model_name = definition.get("model") or default_model
    await update.message.reply_text(f"{definition['name']} · Current model: {model_name}")



async def cmd_tools(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /tools command — list available tools."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    manager = context.bot_data.get("agent_manager")
    if manager is None:
        return await update.message.reply_text("Agent manager not available.")
    from questchain.agents import tool_issues
    definition = manager.get(context.chat_data.get("agent_id", manager.get_active_id())) or manager.get_active()
    tools = definition.get("tools", [])
    selected = "all available" if tools == "all" else ", ".join(tools) or "none"
    text = f"{definition['name']} · selected tools: {selected}"
    issues = tool_issues(definition)
    if issues:
        text += "\n" + "\n".join(issues)
    await update.message.reply_text(text)





async def cmd_cron(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manage the same persistent jobs as the terminal and web UI."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)
    from questchain.cron_commands import execute
    text = update.message.text or ""
    command = text.partition(" ")[2]
    try:
        result = execute(command)
    except (ValueError, KeyError, RuntimeError) as exc:
        result = str(exc)
    for chunk in _split_message(result):
        await update.message.reply_text(chunk)


async def cmd_onboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /onboard command — re-run onboarding."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    from questchain.onboarding import clear_onboarded
    clear_onboarded()
    # Set active so the next message goes to the AI as the user's intro
    context.chat_data["onboarding_active"] = True
    context.chat_data.pop("onboarding_intro_sent", None)
    await update.message.reply_text(OPENING_QUESTION)


async def cmd_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /level command — show XP, level, and achievements."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    agent_manager: AgentManager | None = context.bot_data.get("agent_manager")
    if agent_manager is None:
        await update.message.reply_text("Agent manager not available.")
        return

    active = agent_manager.get(context.chat_data.get("agent_id", agent_manager.get_active_id())) or agent_manager.get_active()
    agent_id = active.get("id", "default")
    class_name = active.get("class_name", DEFAULT_CLASS)
    pm = ProgressionManager(agent_id, class_name)
    record = pm.load()

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

    lines = [
        f"📊 {active.get('name', 'QuestChain')} · Level {record.level}",
        f"[{bar}] {xp_display}",
        f"Total XP: {record.total_xp}  Turns: {record.turns_completed}  Jobs: {record.jobs_completed}",
    ]
    if record.current_streak > 1:
        streak_bonus = " (+50% XP)" if record.current_streak >= 7 else ""
        lines.append(f"🔥 Streak: {record.current_streak} days{streak_bonus}")
    if record.prestige:
        lines.append(f"{'✦' * record.prestige} Prestige {record.prestige}")
    if top_tools:
        lines.append("\nTop tools:")
        for tool, count in top_tools:
            lines.append(f"  {tool}: {count}")
    lines.append(f"\nAchievements ({len(record.achievements)}/{TOTAL_ACHIEVEMENTS}):")
    if record.achievements:
        for a in record.achievements:
            lines.append(f"  ★ {a.name} — {a.description}  ({a.earned_at[:10]})")
    else:
        lines.append("  None yet — start chatting!")

    await update.message.reply_text("\n".join(lines))


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stats command — show all-time metrics."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    agent_manager: AgentManager | None = context.bot_data.get("agent_manager")
    if agent_manager is None:
        await update.message.reply_text("Agent manager not available.")
        return

    active = agent_manager.get(context.chat_data.get("agent_id", agent_manager.get_active_id())) or agent_manager.get_active()
    agent_id = active.get("id", "default")
    mm = MetricsManager(agent_id)
    mm.load()
    rec = mm.get_record()

    model_line = rec.model_name or "(unknown)"
    if rec.model_params:
        model_line += f"  ·  {rec.model_params}"
    if rec.model_size_gb:
        model_line += f"  ·  {rec.model_size_gb} GB"

    lines = [
        "⚙ Agent Stats",
        "",
        f"Model:         {model_line}",
        f"Context:       {rec.context_window:,} tokens",
        f"Tools:         {rec.num_tools} registered",
        "",
        f"Prompts:       {rec.prompt_count}",
        f"Tokens used:   ~{rec.tokens_used:,}",
        f"Total errors:  {rec.total_errors}",
        f"Highest Chain: {rec.highest_chain} tool loops",
    ]
    await update.message.reply_text("\n".join(lines))


async def cmd_agent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /agents command — show agents inline keyboard."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    agent_manager: AgentManager | None = context.bot_data.get("agent_manager")
    if agent_manager is None:
        await update.message.reply_text("Agent manager not available.")
        return

    active_id = context.chat_data.get("agent_id", agent_manager.get_active_id())
    keyboard = []
    for agent_def in agent_manager.all_agents():
        agent_id = agent_def["id"]
        name = agent_def["name"]
        model = agent_def.get("model") or OLLAMA_MODEL
        is_active = agent_id == active_id
        try:
            pm = ProgressionManager(agent_id, agent_def.get("class_name", DEFAULT_CLASS))
            lv = pm.get_record().level
            level_tag = f" Lv.{lv}"
        except Exception:
            level_tag = ""
        label = f"{'✓ ' if is_active else ''}{name} · {ROLE_LABELS.get(agent_def.get('class_name'), 'Custom')}{level_tag}"
        row = [InlineKeyboardButton(label, callback_data=f"agent:pick:{agent_id}")]
        row.append(InlineKeyboardButton("✏️", callback_data=f"agent:edit:{agent_id}"))
        if not agent_def.get("built_in"):
            row.append(InlineKeyboardButton("🗑️", callback_data=f"agent:delete:{agent_id}"))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("➕ New agent", callback_data="agent:build")])
    for archived in agent_manager.legacy_agents():
        keyboard.append([InlineKeyboardButton(f"Migrate legacy: {archived['name']}", callback_data=f"agent:migrate:{archived['id']}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🔗 Agents", reply_markup=reply_markup)


async def callback_agent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle agent: inline keyboard callbacks."""
    query = update.callback_query
    if not _is_owner(query.from_user.id):
        await query.answer("This bot is private.")
        return

    await query.answer()
    data = query.data

    agent_manager: AgentManager | None = context.bot_data.get("agent_manager")

    if data.startswith("agent:migrate:"):
        if agent_manager is None:
            return await query.edit_message_text("Agent manager not available.")
        try:
            saved = agent_manager.migrate_legacy(data[len("agent:migrate:"):])
            await query.edit_message_text(f"Migrated {saved['name']} with its original ID. Automatic routing is off. Use /agents to review its settings.")
        except ValueError as exc:
            await query.edit_message_text(str(exc))
        return

    if data.startswith("agent:pick:"):
        agent_id = data[len("agent:pick:"):]
        if agent_manager is None:
            await query.edit_message_text("Agent manager not available.")
            return
        active_id = context.chat_data.get("agent_id", agent_manager.get_active_id())
        if agent_id == active_id:
            return  # Already active — silently ignore
        agent_def = agent_manager.get(agent_id)
        if agent_def is None:
            await query.edit_message_text(f"Agent not found: {agent_id}")
            return
        # The runtime resolves this definition and its model when work starts.
        # Selection belongs to this chat, not the shared bot configuration.
        context.chat_data["agent_id"] = agent_id
        await query.edit_message_text(f"🔗 Switched to '{agent_def['name']}'.")

    elif data == "agent:build":
        context.chat_data["building_agent"] = {"step": "name", "data": {}}
        await query.edit_message_text(
            "Let's create a new agent. Send /cancel at any time.\n\n"
            "Name — What's the agent's name?"
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
            "step": "name",
            "data": {
                **agent_def,
                "edit_id": agent_id,
                "name": agent_def["name"],
                "model": agent_def.get("model"),
                "tools": agent_def.get("tools", "all"),
                "system_prompt": agent_def.get("system_prompt"),
            },
        }
        await query.edit_message_text(
            f"Editing '{agent_def['name']}'. Send '-' to keep the current value.\n\n"
            f"Name — New name? (current: {agent_def['name']})"
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
    state = context.chat_data.get("building_agent")
    if state is None:
        return False
    text = (update.message.text or "").strip()
    if text.lower() == "/cancel":
        context.chat_data.pop("building_agent", None)
        await update.message.reply_text("Cancelled.")
        return True
    data = state["data"]
    step = state["step"]
    tools = get_dynamic_selectable_tools()
    steps = ["name", "model", "class", "tools", "prompt", "guidance", "routable", "exclusions", "examples", "confirm"]
    try:
        if step == "name":
            if text != "-":
                data["name"] = text
            if not data.get("name"):
                raise ValueError("Name is required.")
        elif step == "model":
            if text != "-":
                data["model"] = text or None
            data.setdefault("model", None)
        elif step == "class":
            if text != "-":
                if not text.isdigit() or not 1 <= int(text) <= len(AGENT_CLASSES):
                    raise ValueError("Choose a role number or '-' for the current/default role.")
                data["class_name"] = AGENT_CLASSES[int(text) - 1][0]
            data.setdefault("class_name", DEFAULT_CLASS)
            data.setdefault("tools", CLASS_TOOL_PRESETS.get(data["class_name"]) or [])
        elif step == "tools":
            if text.lower() == "all":
                data["tools"] = "all"
            elif text.lower() == "none":
                data["tools"] = []
            elif text != "-":
                indices = [part.strip() for part in text.split(",")]
                if any(not i.isdigit() or not 1 <= int(i) <= len(tools) for i in indices):
                    raise ValueError("Use tool numbers, 'none', 'all', or '-' to keep the shown selection.")
                data["tools"] = [tools[int(i) - 1][0] for i in indices]
            if data.get("class_name") == "Router" and data.get("tools"):
                raise ValueError("A coordinator uses routing and status only. Select 'none'.")
        elif step == "prompt":
            if text != "-":
                data["system_prompt"] = text
            data["system_prompt"] = data.get("system_prompt") or preset_prompt(data.get("class_name", DEFAULT_CLASS))
        elif step == "guidance":
            if text != "-":
                data["when_to_call"] = "" if text.lower() == "none" else text
            data.setdefault("when_to_call", CLASS_GUIDANCE.get(data.get("class_name"), ""))
        elif step == "routable":
            if text.lower() not in ("yes", "no", "-", "y", "n"):
                raise ValueError("Send yes or no.")
            if text != "-":
                data["routable"] = text.lower() in ("yes", "y")
            data.setdefault("routable", bool(data.get("when_to_call")))
            if data["routable"] and not data.get("when_to_call"):
                state["step"] = "guidance"
                raise ValueError("Describe when to call this agent before enabling routing. Send that guidance now.")
        elif step == "exclusions":
            if text != "-":
                data["when_not_to_call"] = "" if text.lower() == "none" else text
        elif step == "examples":
            if text != "-":
                data["routing_examples"] = [] if text.lower() == "none" else [e.strip() for e in text.split(";") if e.strip()]
        elif step == "confirm":
            if text.lower() in ("yes", "y"):
                manager = context.bot_data["agent_manager"]
                keys = ("name", "model", "class_name", "tools", "system_prompt", "when_to_call", "routable", "when_not_to_call", "routing_examples")
                values = {key: data[key] for key in keys if key in data}
                saved = manager.update(data["edit_id"], **values) if data.get("edit_id") else manager.add(**values)
                await update.message.reply_text(f"Saved {saved['name']}. Use /agents to chat directly. Routing catalog refreshed.")
            else:
                await update.message.reply_text("Cancelled.")
            context.chat_data.pop("building_agent", None)
            return True
        next_step = steps[steps.index(step) + 1]
        state["step"] = next_step
        prompts = {
            "model": f"Model [{data.get('model') or OLLAMA_MODEL}]. Send '-' to keep the default/current value.",
            "class": "Role — send a number, or '-' to keep:\n" + "\n".join(f"{i}. {ROLE_LABELS.get(c[0], c[0])}" for i, c in enumerate(AGENT_CLASSES, 1)),
            "tools": f"Tools [{data.get('tools', [])}]. Select numbers, 'none', 'all', or '-' to keep:\n" + "\n".join(f"{i}. {name} — {desc}" for i, (name, desc) in enumerate(tools, 1)),
            "prompt": "System prompt — how should this agent work? Send '-' for current or role preset.",
            "guidance": "When should the coordinator call this agent?\nCurrent/preset: " + (data.get("when_to_call") or CLASS_GUIDANCE.get(data.get("class_name"), "(none)")) + "\nSend '-' to keep or 'none' for direct chat only.",
            "routable": "Allow automatic routing? yes / no (direct chat remains available).",
            "exclusions": "When NOT to call? Send exclusions, '-' to keep, or 'none'.",
            "examples": "Example requests? Separate with ';', send '-' to keep, or 'none'.",
            "confirm": "Confirm agent:\n" + "\n".join(f"{k}: {str(v)[:600]}" for k, v in data.items() if k in ("name", "class_name", "model", "tools", "system_prompt", "when_to_call", "routable", "when_not_to_call", "routing_examples")) + "\n\nSend yes to save, anything else to cancel.",
        }
        for chunk in _split_message(prompts[next_step]):
            await update.message.reply_text(chunk)
    except (ValueError, TypeError) as exc:
        await update.message.reply_text(str(exc))
    return True


def _command_arguments(update) -> str:
    parts = (update.message.text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else ""


def _chat_runs(runtime, chat_id: int, conversation_id: str | None = None) -> list[dict]:
    """Saved user requests owned by this Telegram chat, excluding child runs."""
    return [run for run in runtime.store.runs(conversation_id)
            if run.get("source") == "telegram" and run.get("destination") == str(chat_id)
            and run["conversation_id"].startswith("telegram-") and not run.get("parent_run_id")]


def _current_run(update, context) -> dict:
    runtime = context.bot_data.get("runtime")
    if runtime is None:
        raise ValueError("The task runtime is not ready yet.")
    chat_id = update.effective_chat.id
    conversation = "telegram-" + _get_thread_id(chat_id)
    run_id = _command_arguments(update)
    runs = _chat_runs(runtime, chat_id, conversation)
    if not run_id:
        if not runs:
            raise ValueError("No runs in this conversation. Use /runs to list saved work.")
        return runs[-1]
    run = next((run for run in runs if run["id"] == run_id), None)
    if run is None:
        raise ValueError("Run not found in this conversation. Use /runs to list saved work.")
    return run


async def _reply_chunks(update, text: str) -> None:
    for chunk in _split_message(text):
        await update.message.reply_text(chunk)


def _page(items: list, arguments: str) -> tuple[list, int, int]:
    parts = arguments.split()
    if not parts:
        number = 1
    elif len(parts) == 2 and parts[0].lower() == "page" and parts[1].isdigit():
        number = int(parts[1])
    else:
        raise ValueError("Use page followed by a page number, for example: page 2.")
    total = max(1, (len(items) + 19) // 20)
    if not 1 <= number <= total:
        raise ValueError(f"Choose a page from 1 to {total}.")
    return items[(number - 1) * 20:number * 20], number, total


def _run_transcript(run: dict) -> str:
    author = run.get("result_agent_name") or run["agent_name"]
    text = f"Run {run['id']} · {run['status']}\nYou: {run['text']}\n\n{author}: {run['result'] or '(No response saved yet)'}"
    if run.get("error"):
        text += "\n\nError: " + run["error"]
    return text


async def cmd_runs(update, context):
    if not _is_owner(update.effective_user.id):
        return await _reject(update)
    runtime = context.bot_data.get("runtime")
    if runtime is None:
        return await update.message.reply_text("The task runtime is not ready yet.")
    arguments = _command_arguments(update)
    try:
        if arguments and arguments.split()[0].lower() != "page":
            return await _reply_chunks(update, _run_transcript(_current_run(update, context)))
        chat_id = update.effective_chat.id
        runs = _chat_runs(runtime, chat_id, "telegram-" + _get_thread_id(chat_id))
        rows, number, total = _page(list(reversed(runs)), arguments)
        lines = [f"Runs · page {number}/{total}"]
        for run in rows:
            author = run.get("result_agent_name") or run["agent_name"]
            preview = " ".join(run["text"].split())[:80]
            lines.append(f"{run['id']} · {author} · {run['status']}\n{preview}")
        if not rows:
            lines.append("No runs in this conversation.")
        lines.append("Use /runs ID for a saved result, /retry [ID], or /cancel [ID].")
        if total > 1:
            lines.append("Use /runs page N for another page.")
        await _reply_chunks(update, "\n\n".join(lines))
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def cmd_history(update, context):
    if not _is_owner(update.effective_user.id):
        return await _reject(update)
    runtime = context.bot_data.get("runtime")
    if runtime is None:
        return await update.message.reply_text("The task runtime is not ready yet.")
    chat_id = update.effective_chat.id
    conversations = {}
    for run in _chat_runs(runtime, chat_id):
        conversations.setdefault(run["conversation_id"], []).append(run)
    arguments = _command_arguments(update)
    try:
        if arguments and arguments.split()[0].lower() != "page":
            conversation = "telegram-" + arguments.removeprefix("telegram-")
            runs = conversations.get(conversation)
            if not runs:
                raise ValueError("Conversation not found in this Telegram chat. Use /history to list saved conversations.")
            thread_id = conversation.removeprefix("telegram-")
            _thread_ids[chat_id] = thread_id
            _save_thread_ids()
            context.chat_data.pop("last_run_id", None)
            await update.message.reply_text(f"Resumed conversation {thread_id}. Showing the latest 10 requests; use /runs for older results.")
            for run in runs[-10:]:
                await _reply_chunks(update, _run_transcript(run))
            return
        ordered = sorted(conversations.items(), key=lambda pair: pair[1][-1]["created_at"], reverse=True)
        rows, number, total = _page(ordered, arguments)
        current = "telegram-" + _get_thread_id(chat_id)
        lines = [f"Conversation history · page {number}/{total}"]
        for conversation, runs in rows:
            preview = " ".join(runs[0]["text"].split())[:80]
            marker = " (current)" if conversation == current else ""
            lines.append(f"{conversation.removeprefix('telegram-')}{marker}\n{runs[-1]['created_at']} · {preview}")
        if not rows:
            lines.append("No saved conversations in this Telegram chat.")
        lines.append("Use /history ID to resume a conversation, or /new to start fresh.")
        if total > 1:
            lines.append("Use /history page N for another page.")
        await _reply_chunks(update, "\n\n".join(lines))
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def cmd_cancel(update, context):
    if not _is_owner(update.effective_user.id):
        return await _reject(update)
    if not _command_arguments(update) and context.chat_data.pop("building_agent", None) is not None:
        await update.message.reply_text("Agent creation cancelled.")
        return
    try:
        from questchain.runtime import TERMINAL
        run = _current_run(update, context)
        if run["status"] in TERMINAL:
            raise ValueError("This run has already finished. Use /runs to find a queued or running task.")
        context.bot_data["runtime"].cancel(run["id"])
        await update.message.reply_text("Cancellation requested.")
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def cmd_retry(update, context):
    if not _is_owner(update.effective_user.id):
        return await _reject(update)
    try:
        run = _current_run(update, context)
        runtime = context.bot_data["runtime"]
        new_id = runtime.retry(run["id"], audio_callback=_voice_delivery(update))
        context.chat_data["last_run_id"] = new_id
        await _deliver_runtime_result(runtime, new_id, update)
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def _deliver_runtime_result(runtime, run_id, update):
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(update.effective_chat, stop_typing))
    try:
        result = await runtime.wait(run_id)
        author = result.get("result_agent_name", result["agent_name"])
        text = f"{author} · {result['status']}\n\n{result['result']}"
        if result["error"]:
            text += "\n\n" + result["error"]
        for chunk in _split_message(text):
            try:
                await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.message.reply_text(chunk)
        runtime.mark_delivered(run_id)
    except Exception as exc:
        runtime.mark_delivered(run_id, str(exc))
        logger.warning("Telegram result delivery failed: %s", exc)
    finally:
        stop_typing.set()
        await typing_task


def _voice_delivery(update):
    async def deliver(wav_bytes):
        import io
        await update.message.reply_voice(voice=io.BytesIO(wav_bytes))
    return deliver


async def _submit_runtime_message(update, context, text):
    from questchain.runtime import TaskRequest
    runtime = context.bot_data.get("runtime")
    manager = context.bot_data.get("agent_manager")
    if not runtime or not manager:
        await update.message.reply_text("The task runtime is not ready yet.")
        return
    chat_id = update.effective_chat.id
    message_id = getattr(update.message, "message_id", None)
    try:
        run_id = runtime.submit(TaskRequest(text, context.chat_data.get("agent_id", manager.get_active_id()),
            "telegram-" + _get_thread_id(chat_id), "telegram", destination=str(chat_id),
            occurrence_key=f"telegram:{chat_id}:{message_id}" if message_id is not None else None,
            audio_callback=_voice_delivery(update)))
    except (ValueError, TypeError) as exc:
        await update.message.reply_text(str(exc))
        return
    context.chat_data["last_run_id"] = run_id
    await _deliver_runtime_result(runtime, run_id, update)


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
        thread_id = config.get("configurable", {}).get("thread_id", "telegram")
        async for token in agent.run(user_text, thread_id=thread_id):
            full_response += token
    except Exception:
        logger.exception("Agent error")
        full_response = "Sorry, an internal error occurred."
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


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle voice/audio messages — transcribe offline then forward to agent."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    from questchain.stt import is_available, transcribe

    if not is_available():
        await update.message.reply_text(
            "Voice input is not available. Install faster-whisper:\n`pip install faster-whisper`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    voice = update.message.voice or update.message.audio
    if voice is None:
        return

    await update.effective_chat.send_action(ChatAction.TYPING)

    tg_file = await context.bot.get_file(voice.file_id)

    suffix = ".ogg" if update.message.voice else ".mp3"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name

    try:
        await tg_file.download_to_drive(tmp_path)
        text = await asyncio.to_thread(transcribe, tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError as exc:
            logger.debug("Could not delete temp voice file %s: %s", tmp_path, exc)

    if not text:
        await update.message.reply_text("(Could not transcribe voice message.)")
        return

    # Forward transcribed text directly to the agent via the telegram queue
    # (same path as a normal typed message)
    if await _handle_build_agent_wizard(update, context):
        return

    chat_id = update.effective_chat.id
    await _submit_runtime_message(update, context, text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages — invoke the QuestChain agent."""
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
        # Onboarding has a small, explicit file-writing role; the selected router
        # keeps its tool-free configuration.
        from questchain.agent import create_questchain_agent
        agent = create_questchain_agent(model_name=context.bot_data.get("model_name", OLLAMA_MODEL),
                    tools_filter=["read_file", "write_file"], system_prompt_override=ONBOARDING_SYSTEM,
                    agent_name="QuestChain")
        thread_id = "onboarding-" + str(chat_id)
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 200}
        await update.effective_chat.send_action(ChatAction.TYPING)

        if not context.chat_data.get("onboarding_intro_sent", False):
            context.chat_data["onboarding_intro_sent"] = True
            message = f"[System: {ONBOARDING_SYSTEM}]\n\nUser's introduction: {user_text}"
        else:
            message = user_text

        if audio_router is not None:
            audio_router.set_telegram(update)
        runtime = context.bot_data.get("runtime")
        async with runtime.lock if runtime else asyncio.Lock():
            full_response = await _run_agent_collect(agent, message, config, update)
        if audio_router is not None:
            audio_router.set_cli()
        if "ONBOARDING_COMPLETE" in full_response:
            mark_onboarded()
            context.chat_data["onboarding_active"] = False
            context.chat_data.pop("onboarding_intro_sent", None)
        return

    await _submit_runtime_message(update, context, user_text)


# One catalog drives handler registration, /help, and Telegram's command menu.
_COMMANDS = (
    ("start", "Introduction and command list", cmd_start),
    ("new", "Start a fresh conversation", cmd_new),
    ("model", "Show the selected agent's current model", cmd_model),
    ("tools", "Show the selected agent's tools", cmd_tools),
    ("cron", "Manage scheduled cron jobs", cmd_cron),
    ("onboard", "Re-run the onboarding flow", cmd_onboard),
    ("agents", "Manage agents: list, switch, create, edit", cmd_agent),
    ("runs", "List runs; /runs ID shows a result; /runs page N for more", cmd_runs),
    ("history", "Browse conversations; /history ID resumes; /history page N for more", cmd_history),
    ("cancel", "Cancel agent creation or a run in this conversation: /cancel [ID]", cmd_cancel),
    ("retry", "Retry a run in this conversation: /retry [ID]", cmd_retry),
    ("level", "Show agent level and achievements", cmd_level),
    ("stats", "Show agent metrics: prompts, tokens, errors", cmd_stats),
    ("help", "Show all commands", cmd_help),
)
_HELP_TEXT = "Commands:\n" + "\n".join(f"/{name} — {description}" for name, description, _ in _COMMANDS)
_HELP_TEXT += "\n\nSend a voice message to speak to the agent directly."


async def run_telegram_alongside_cli(
    agent_holder: dict,
    model_name: str,
    telegram_queue: asyncio.Queue,
    audio_router,
    agent_manager: "AgentManager | None" = None,
    busy_lock=None,
    runtime=None,
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

    builder = Application.builder().token(TELEGRAM_BOT_TOKEN)
    if hasattr(builder, "concurrent_updates"):
        builder = builder.concurrent_updates(4)
    app = builder.build()

    app.bot_data["agent_holder"] = agent_holder
    app.bot_data["agent"] = agent_holder["agent"]  # legacy fallback
    app.bot_data["model_name"] = model_name
    app.bot_data["audio_router"] = audio_router
    app.bot_data["telegram_queue"] = telegram_queue
    app.bot_data["runtime"] = runtime
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

    from questchain.scheduler import CronScheduler, set_scheduler

    scheduler = CronScheduler(
        agent=agent_holder["agent"],
        send_callback=send_to_owner,
        agent_manager=agent_manager,
        busy_lock=busy_lock,
        runtime=runtime,
    )
    set_scheduler(scheduler)

    # Register handlers
    for name, _, handler in _COMMANDS:
        app.add_handler(CommandHandler(name, handler))
    app.add_handler(CallbackQueryHandler(callback_agent, pattern="^agent:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice_message))

    async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        from telegram.error import NetworkError, TimedOut
        err = context.error
        if isinstance(err, (NetworkError, TimedOut)):
            logger.debug("Telegram network error (will retry): %s", err)
        else:
            logger.error("Telegram error", exc_info=err)

    app.add_error_handler(_error_handler)

    await app.initialize()
    await app.bot.set_my_commands([BotCommand(name, description) for name, description, _ in _COMMANDS])
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
