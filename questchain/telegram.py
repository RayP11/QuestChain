"""QuestChain Telegram bot adapter."""

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

from questchain.agents import AGENT_CLASSES, AgentManager, CLASS_TOOL_PRESETS, DEFAULT_CLASS, SELECTABLE_TOOLS
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
    "/tools — List available tools\n"
    "/quest <text> — Add a new quest\n"
    "/quests — List pending quests with descriptions\n"
    "/tasks — Show pending quests (filenames only)\n"
    "/cron — List scheduled cron jobs\n"
    "/onboard — Re-run the onboarding flow\n"
    "/agents — Manage agents (list, switch, create, edit)\n"
    "/level — Show agent level and achievements\n"
    "/stats — Show agent metrics (prompts, tokens, errors)\n"
    "/help — Show this help message"
)


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
    await update.message.reply_text(f"Conversation reset. New thread: {new_id[:8]}...")


async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /model command — show current model."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    model_name = context.bot_data.get("model_name", OLLAMA_MODEL)
    await update.message.reply_text(f"Current model: {model_name}")



async def cmd_tools(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /tools command — list available tools."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    from questchain.config import TAVILY_API_KEY
    text = (
        "Built-in tools (always available):\n"
        "  read_file, write_file, edit_file, ls, glob, grep, execute\n\n"
        "Custom tools:\n"
        "  claude_code — delegate coding tasks to Claude Code\n"
        "  cron_add, cron_list, cron_remove — scheduled jobs\n"
    )
    if TAVILY_API_KEY:
        text += "  web_search, web_browse — enabled"
    else:
        text += "  web_search, web_browse — disabled (no TAVILY_API_KEY)"
    await update.message.reply_text(text)




async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /tasks command — list pending quests."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    from questchain.config import WORKSPACE_DIR
    quests_dir = WORKSPACE_DIR / "workspace" / "quests"
    if not quests_dir.exists():
        await update.message.reply_text("No quests pending.")
        return
    quest_files = sorted(quests_dir.glob("*.md"))
    if not quest_files:
        await update.message.reply_text("No quests pending.")
        return
    lines = [f.name for f in quest_files]
    await update.message.reply_text("Pending quests:\n" + "\n".join(f"• {l}" for l in lines))


async def cmd_quest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /quest — start the two-step quest creation wizard."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    context.chat_data["creating_quest"] = {"step": "title"}
    await update.message.reply_text(
        "New quest — send /cancel at any time.\n\nStep 1/2 — What's the quest title?"
    )


async def _handle_quest_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Process wizard steps for quest creation. Returns True if message was consumed."""
    state = context.chat_data.get("creating_quest")
    if state is None:
        return False

    text = (update.message.text or "").strip()

    if text.lower() == "/cancel":
        context.chat_data.pop("creating_quest", None)
        await update.message.reply_text("Cancelled.")
        return True

    step = state["step"]

    if step == "title":
        if not text:
            await update.message.reply_text("Title can't be empty. What's the quest title?")
            return True
        state["title"] = text
        state["step"] = "content"
        await update.message.reply_text("Step 2/2 — Describe what the agent should do:")

    elif step == "content":
        if not text:
            await update.message.reply_text("Content can't be empty. Describe the quest:")
            return True

        import re
        from questchain.config import WORKSPACE_DIR

        title = state["title"]
        quests_dir = WORKSPACE_DIR / "workspace" / "quests"
        quests_dir.mkdir(parents=True, exist_ok=True)

        words = re.sub(r"[^a-z0-9\s]", "", title.lower()).split()
        slug = "-".join(words[:5]) or "quest"
        path = quests_dir / f"{slug}.md"
        counter = 2
        while path.exists():
            path = quests_dir / f"{slug}-{counter}.md"
            counter += 1

        path.write_text(f"# {title}\n\n{text}", encoding="utf-8")
        context.chat_data.pop("creating_quest", None)
        await update.message.reply_text(
            f"✓ Quest added: `{path.name}`", parse_mode=ParseMode.MARKDOWN
        )

    return True


async def cmd_quests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /quests command — list pending quests with titles and descriptions."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    from questchain.config import WORKSPACE_DIR
    quests_dir = WORKSPACE_DIR / "workspace" / "quests"
    if not quests_dir.exists():
        await update.message.reply_text("No quests pending.")
        return
    quest_files = sorted(quests_dir.glob("*.md"))
    if not quest_files:
        await update.message.reply_text("No quests pending.")
        return

    lines = [f"*Pending quests ({len(quest_files)}):*\n"]
    for f in quest_files:
        title = None
        description = None
        try:
            for raw_line in f.read_text(encoding="utf-8").splitlines():
                stripped = raw_line.strip()
                if not stripped:
                    continue
                if title is None:
                    title = stripped.lstrip("#").strip() if stripped.startswith("#") else stripped
                elif description is None and not stripped.startswith("#"):
                    description = stripped
                    break
        except Exception:
            pass
        title = title or f.stem
        entry = f"• *{title}*"
        if description:
            entry += f"\n  _{description[:120]}{'…' if len(description) > 120 else ''}_"
        lines.append(entry)

    try:
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text("\n".join(lines))


async def cmd_cron(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cron command — list scheduled cron jobs."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    import json
    from questchain.config import get_cron_jobs_path
    jobs_path = get_cron_jobs_path()
    jobs = []
    if jobs_path.exists():
        try:
            jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
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

    active = agent_manager.get_active()
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
        f"Total XP: {record.total_xp}  Turns: {record.turns_completed}  Quests: {record.quests_completed}",
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

    active = agent_manager.get_active()
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
        try:
            pm = ProgressionManager(agent_id, agent_def.get("class_name", DEFAULT_CLASS))
            lv = pm.get_record().level
            level_tag = f" Lv.{lv}"
        except Exception:
            level_tag = ""
        label = f"{'✓ ' if is_active else '  '}{name}{level_tag}  ({model})"
        row = [InlineKeyboardButton(label, callback_data=f"agent:pick:{agent_id}")]
        row.append(InlineKeyboardButton("✏️", callback_data=f"agent:edit:{agent_id}"))
        if not agent_def.get("built_in"):
            row.append(InlineKeyboardButton("🗑️", callback_data=f"agent:delete:{agent_id}"))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("➕ New agent", callback_data="agent:build")])

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
        from questchain.cli import _make_agent_from_def
        try:
            new_agent = _make_agent_from_def(agent_def, audio_router)
            agent_holder["agent"] = new_agent
            context.bot_data["model_name"] = agent_def.get("model") or OLLAMA_MODEL
            agent_manager.set_active(agent_id)
            await query.edit_message_text(f"🔗 Switched to '{agent_def['name']}'.")
        except Exception as e:
            await query.edit_message_text(f"Failed to switch agent: {e}")

    elif data == "agent:build":
        context.chat_data["building_agent"] = {"step": "name", "data": {}}
        await query.edit_message_text(
            "Let's create a new agent. Send /cancel at any time.\n\n"
            "Step 1/5 — What's the agent's name?"
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
            f"Step 1/5 — New name? (current: {agent_def['name']})"
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

    # ── Create flow  (name → model → class → tools[if Custom] → prompt → confirm) ────

    if step == "name":
        if not text:
            await update.message.reply_text("Name cannot be empty. What's the agent's name?")
            return True
        data["name"] = text
        state["step"] = "model"
        await update.message.reply_text(
            f"Step 2/5 — Which model? (send empty for default: {OLLAMA_MODEL})"
        )

    elif step == "model":
        data["model"] = text if text else None
        state["step"] = "class"
        class_lines = "\n".join(
            f"  {i}. {icon} {cname} — {desc}"
            for i, (cname, icon, desc) in enumerate(AGENT_CLASSES, 1)
        )
        await update.message.reply_text(
            f"Step 3/5 — Agent class:\n\n{class_lines}\n\n"
            f"Send a number (1-{len(AGENT_CLASSES)}) or empty for Custom (custom tools)."
        )

    elif step == "class":
        chosen_class = DEFAULT_CLASS
        if text.isdigit():
            idx = int(text) - 1
            if 0 <= idx < len(AGENT_CLASSES):
                chosen_class = AGENT_CLASSES[idx][0]
        data["class_name"] = chosen_class
        preset = CLASS_TOOL_PRESETS.get(chosen_class)
        if preset is None:
            # Custom: ask for tools
            state["step"] = "tools"
            tool_lines = "\n".join(
                f"  {i}. {name} — {desc}"
                for i, (name, desc) in enumerate(SELECTABLE_TOOLS, 1)
            )
            await update.message.reply_text(
                f"Step 4/5 — Which tools? (filesystem tools always available)\n\n"
                f"{tool_lines}\n\n"
                f"Send comma-separated numbers (e.g. '1,2'), or 'all' for all tools."
            )
        else:
            # Non-Custom: apply preset, skip tools step
            data["tools"] = preset
            state["step"] = "prompt"
            preset_display = ", ".join(preset) if preset else "built-in tools only"
            await update.message.reply_text(
                f"Tools preset for {chosen_class}: {preset_display}\n\n"
                f"Step 4/4 — System prompt? (send empty to use the default QuestChain prompt)"
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
            "Step 5/5 — System prompt? (send empty to use the default QuestChain prompt)"
        )

    elif step == "prompt":
        data["system_prompt"] = text if text else None
        state["step"] = "confirm"
        _tools = data.get("tools", "all")
        tools_display = _tools if _tools == "all" else (", ".join(_tools) if _tools else "built-in only")
        model_display = data.get("model") or f"{OLLAMA_MODEL} (default)"
        prompt_display = data.get("system_prompt") or "(default QuestChain prompt)"
        await update.message.reply_text(
            f"Confirm new agent:\n\n"
            f"Name: {data['name']}\n"
            f"Class: {data.get('class_name', DEFAULT_CLASS)}\n"
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
                tools=data.get("tools", "all"),
                class_name=data.get("class_name", DEFAULT_CLASS),
            )
            context.chat_data.pop("building_agent", None)
            await update.message.reply_text(
                f"✓ Agent '{data['name']}' created!\nUse /agents to activate it."
            )
        else:
            context.chat_data.pop("building_agent", None)
            await update.message.reply_text("Agent creation cancelled.")

    # ── Edit flow  (edit_name → edit_model → edit_class → edit_tools → edit_prompt → edit_confirm) ──

    elif step == "edit_name":
        if text and text != "-":
            data["name"] = text
        state["step"] = "edit_model"
        current_model = data.get("model") or OLLAMA_MODEL
        await update.message.reply_text(
            f"Step 2/5 — New model? (current: {current_model}, send '-' to keep)"
        )

    elif step == "edit_model":
        if text and text != "-":
            data["model"] = text
        state["step"] = "edit_class"
        current_class = data.get("class_name", DEFAULT_CLASS)
        class_lines = "\n".join(
            f"  {i}. {icon} {cname} — {desc}"
            for i, (cname, icon, desc) in enumerate(AGENT_CLASSES, 1)
        )
        await update.message.reply_text(
            f"Step 3/5 — Agent class? (current: {current_class})\n\n{class_lines}\n\n"
            f"Send a number (1-{len(AGENT_CLASSES)}) or '-' to keep current."
        )

    elif step == "edit_class":
        if text and text != "-" and text.isdigit():
            idx = int(text) - 1
            if 0 <= idx < len(AGENT_CLASSES):
                data["class_name"] = AGENT_CLASSES[idx][0]
        state["step"] = "edit_tools"
        current_tools = data.get("tools", "all")
        tools_display = current_tools if current_tools == "all" else (", ".join(current_tools) if current_tools else "built-in only")
        current_class = data.get("class_name", DEFAULT_CLASS)
        preset = CLASS_TOOL_PRESETS.get(current_class)
        preset_hint = ""
        if preset is not None:
            preset_display = ", ".join(preset) if preset else "built-in only"
            preset_hint = f"\nClass preset ({current_class}): {preset_display}"
        tool_lines = "\n".join(
            f"  {i}. {name} — {desc}"
            for i, (name, desc) in enumerate(SELECTABLE_TOOLS, 1)
        )
        await update.message.reply_text(
            f"Step 4/5 — Tools? (current: {tools_display}){preset_hint}\n\n"
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
            f"Step 5/5 — System prompt?\n"
            f"Current: {current_prompt[:100]}{'…' if len(current_prompt) > 100 else ''}\n\n"
            f"Send new prompt, or '-' to keep current."
        )

    elif step == "edit_prompt":
        if text and text != "-":
            data["system_prompt"] = text
        state["step"] = "edit_confirm"
        current_tools = data.get("tools", "all")
        tools_display = current_tools if current_tools == "all" else (", ".join(current_tools) if current_tools else "built-in only")
        model_display = data.get("model") or f"{OLLAMA_MODEL} (default)"
        prompt_display = data.get("system_prompt") or "(default QuestChain prompt)"
        await update.message.reply_text(
            f"Confirm updated agent:\n\n"
            f"Name: {data['name']}\n"
            f"Class: {data.get('class_name', DEFAULT_CLASS)}\n"
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
                class_name=data.get("class_name", DEFAULT_CLASS),
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
        thread_id = config.get("configurable", {}).get("thread_id", "telegram")
        async for token in agent.run(user_text, thread_id=thread_id):
            full_response += token
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
    """Handle incoming text messages — invoke the QuestChain agent."""
    if not _is_owner(update.effective_user.id):
        return await _reject(update)

    user_text = update.message.text
    if not user_text:
        return

    # Intercept wizard messages first
    if await _handle_quest_wizard(update, context):
        return
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
        return None, None, None

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

    from questchain.scheduler import CronScheduler, set_scheduler

    scheduler = CronScheduler(
        agent=agent_holder["agent"],
        send_callback=send_to_owner,
        agent_manager=agent_manager,
    )
    set_scheduler(scheduler)

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CommandHandler("tools", cmd_tools))
    app.add_handler(CommandHandler("quest", cmd_quest))
    app.add_handler(CommandHandler("quests", cmd_quests))
    app.add_handler(CommandHandler("tasks", cmd_tasks))
    app.add_handler(CommandHandler("cron", cmd_cron))
    app.add_handler(CommandHandler("onboard", cmd_onboard))
    app.add_handler(CommandHandler("agents", cmd_agent))
    app.add_handler(CommandHandler("level", cmd_level))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CallbackQueryHandler(callback_agent, pattern="^agent:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        from telegram.error import NetworkError, TimedOut
        err = context.error
        if isinstance(err, (NetworkError, TimedOut)):
            logger.debug("Telegram network error (will retry): %s", err)
        else:
            logger.error("Telegram error", exc_info=err)

    app.add_error_handler(_error_handler)

    await app.initialize()
    await app.bot.set_my_commands([
        BotCommand("new", "Start a fresh conversation"),
        BotCommand("model", "Show current model"),
        BotCommand("tools", "List available tools"),
        BotCommand("quest", "Add a new quest — /quest <description>"),
        BotCommand("quests", "List pending quests with descriptions"),
        BotCommand("tasks", "Show pending quests (filenames)"),
        BotCommand("cron", "List scheduled cron jobs"),
        BotCommand("onboard", "Re-run the onboarding flow"),
        BotCommand("agents", "Manage agents — list, switch, create, edit"),
        BotCommand("level", "Show agent level and achievements"),
        BotCommand("stats", "Show agent metrics (prompts, tokens, errors)"),
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

    def set_runner(runner) -> None:
        """Called by the CLI after the QuestRunner is started."""
        app.bot_data["quest_runner"] = runner

    return send_to_owner, stop_fn, set_runner
