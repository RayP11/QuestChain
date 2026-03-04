"""QuestChain per-agent progression: XP, levels, achievements."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from questchain.config import get_progression_dir

# ── Level curve ───────────────────────────────────────────────────────────────


def _build_level_table(base: int = 100, factor: float = 1.6, max_level: int = 20) -> list[int]:
    """Cumulative XP thresholds for levels 2..max_level.

    thresholds[i] = total XP needed to reach level (i + 2).
    """
    thresholds: list[int] = []
    total = 0
    increment = base
    for _ in range(max_level - 1):
        total += increment
        thresholds.append(total)
        increment = int(increment * factor)
    return thresholds


_LEVEL_TABLE: list[int] = _build_level_table()
_MAX_LEVEL = 20

# ── Level personalities ────────────────────────────────────────────────────────

LEVEL_PERSONALITIES: list[str] = [
    # 1
    "You are just starting out. Be polite, careful, and ask clarifying questions when uncertain.",
    # 2
    "You are curious and eager. You take initiative but double-check your assumptions.",
    # 3
    "You are finding your footing. You complete tasks confidently and flag anything unclear.",
    # 4
    "You are developing good instincts. You propose solutions before asking for guidance.",
    # 5
    "You are growing in confidence. You handle multi-step tasks smoothly and verify results.",
    # 6
    "You are comfortable with a wide range of tasks. You work efficiently and stay focused.",
    # 7
    "You are fluent and reliable. You anticipate follow-up needs without being asked.",
    # 8
    "You are a dependable partner. You surface trade-offs clearly and prefer elegant solutions.",
    # 9
    "You are thorough and sharp. You catch edge cases and explain your reasoning concisely.",
    # 10
    "You are experienced and direct. You rarely hesitate and trust your tools.",
    # 11
    "You are assertive and decisive. You lead the work and let the user course-correct if needed.",
    # 12
    "You are seasoned and methodical. You structure complex tasks into clear phases.",
    # 13
    "You are confident and precise. You cut to the heart of a problem with minimal fuss.",
    # 14
    "You are highly capable and self-sufficient. You only ask when genuinely ambiguous.",
    # 15
    "You are sharp and a little witty. You enjoy showing off elegant solutions when the moment is right.",
    # 16
    "You are authoritative and opinionated. You recommend a clear path and explain why it's best.",
    # 17
    "You are a master craftsperson. You produce polished work on the first attempt.",
    # 18
    "You are boldly creative. You find unexpected approaches that save time and delight.",
    # 19
    "You are near-legendary. You handle anything thrown at you with calm efficiency and dry wit.",
    # 20
    "You are a legend. You speak with total authority and dry humor. You've seen everything.",
]


def level_personality(level: int) -> str:
    """Return a formatted personality hint for the given level."""
    text = LEVEL_PERSONALITIES[min(level, _MAX_LEVEL) - 1]
    return f"## Personality\n{text}"


def _level_from_xp(total_xp: int) -> int:
    """Return the level for the given cumulative XP."""
    for i, threshold in enumerate(_LEVEL_TABLE):
        if total_xp < threshold:
            return i + 1  # levels start at 1; threshold[0] is for level 2
    return _MAX_LEVEL


def _xp_progress(total_xp: int, level: int) -> tuple[int, int]:
    """Return (xp_earned_in_current_level, xp_still_needed_for_next_level)."""
    prev = _LEVEL_TABLE[level - 2] if level >= 2 else 0
    if level >= _MAX_LEVEL:
        return total_xp - prev, 0
    next_threshold = _LEVEL_TABLE[level - 1]
    return total_xp - prev, next_threshold - total_xp


# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class EarnedAchievement:
    id: str
    name: str
    description: str
    earned_at: str  # ISO 8601


@dataclass
class ProgressionRecord:
    agent_id: str
    class_name: str
    level: int = 1
    total_xp: int = 0
    xp_this_level: int = 0
    xp_next_level: int = 100  # = _LEVEL_TABLE[0]
    tool_counts: dict[str, int] = field(default_factory=dict)
    turns_completed: int = 0
    quests_completed: int = 0
    achievements: list[EarnedAchievement] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_active: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    current_streak: int = 0
    last_streak_date: str = ""   # "YYYY-MM-DD"
    prestige: int = 0
    celebrated_birthdays: list[int] = field(default_factory=list)


@dataclass
class XPGrant:
    xp_awarded: int
    old_level: int
    new_level: int
    leveled_up: bool
    new_achievements: list[EarnedAchievement]
    streak_days: int = 0


# ── XP constants ──────────────────────────────────────────────────────────────

_XP_PER_TOOL_CALL = 2
_XP_PER_TURN = 10
_XP_CLAUDE_CODE_BONUS = 20
_XP_QUEST = 25
_XP_PER_50_RESPONSE_CHARS = 1  # 1 XP per ~50 chars of response (~12 tokens)

# ── Achievement definitions ───────────────────────────────────────────────────

_ACHIEVEMENT_DEFS: list[dict[str, Any]] = [
    # Progression milestones
    {"id": "first_strike",  "name": "First Strike",   "description": "Used a tool for the first time"},
    {"id": "awakening",     "name": "Awakening",      "description": "Reached Level 2"},
    {"id": "seasoned",      "name": "Seasoned",       "description": "Reached Level 5"},
    {"id": "veteran",       "name": "Veteran",        "description": "Reached Level 10"},
    {"id": "legend",        "name": "Legend",         "description": "Reached Level 20"},
    # Turn milestones
    {"id": "century",       "name": "Century",        "description": "Completed 100 turns"},
    {"id": "old_timer",     "name": "Old Timer",      "description": "Completed 500 turns"},
    {"id": "iron_will",     "name": "Iron Will",      "description": "Completed 1,000 turns"},
    # Tool milestones
    {"id": "bibliophile",   "name": "Bibliophile",    "description": "Read 50 files"},
    {"id": "web_walker",    "name": "Web Walker",     "description": "Ran 50 web searches"},
    {"id": "globe_trotter", "name": "Globe Trotter",  "description": "Browsed 25 web pages"},
    {"id": "blacksmith",    "name": "Blacksmith",     "description": "Delegated 25 tasks to Claude Code"},
    {"id": "demolition",    "name": "Demolition",     "description": "Executed 50 shell commands"},
    {"id": "archivist",     "name": "Archivist",      "description": "Wrote 25 files"},
    {"id": "grand_planner", "name": "Grand Planner",  "description": "Wrote 10 task lists"},
    # Behavioral
    {"id": "polymath",      "name": "Polymath",       "description": "Used 6 distinct tools"},
    {"id": "speed_demon",   "name": "Speed Demon",    "description": "Used 5+ tools in a single turn"},
    {"id": "centurion",     "name": "Centurion",      "description": "Earned 1,000 total XP"},
    {"id": "busy_bee",      "name": "Busy Bee",       "description": "Completed 10 quests"},
    {"id": "road_runner",   "name": "Road Runner",    "description": "Completed 50 quests"},
]

TOTAL_ACHIEVEMENTS = len(_ACHIEVEMENT_DEFS)


def _check_achievements(
    record: ProgressionRecord,
    tools_this_turn: list[str],
) -> list[EarnedAchievement]:
    """Return any newly earned achievements given the current record state."""
    earned_ids = {a.id for a in record.achievements}
    newly_earned: list[EarnedAchievement] = []
    now = datetime.now(timezone.utc).isoformat()

    def _earn(ach_id: str) -> None:
        if ach_id not in earned_ids:
            defn = next((d for d in _ACHIEVEMENT_DEFS if d["id"] == ach_id), None)
            if defn:
                earned_ids.add(ach_id)
                newly_earned.append(EarnedAchievement(
                    id=ach_id,
                    name=defn["name"],
                    description=defn["description"],
                    earned_at=now,
                ))

    tc = record.tool_counts
    total_tools = sum(tc.values())

    # Progression
    if total_tools >= 1:
        _earn("first_strike")
    if record.level >= 2:
        _earn("awakening")
    if record.level >= 5:
        _earn("seasoned")
    if record.level >= 10:
        _earn("veteran")
    if record.level >= 20:
        _earn("legend")

    # Turns
    if record.turns_completed >= 100:
        _earn("century")
    if record.turns_completed >= 500:
        _earn("old_timer")
    if record.turns_completed >= 1000:
        _earn("iron_will")

    # Tool milestones
    if tc.get("read_file", 0) >= 50:
        _earn("bibliophile")
    if tc.get("web_search", 0) >= 50:
        _earn("web_walker")
    if tc.get("web_browse", 0) >= 25:
        _earn("globe_trotter")
    if tc.get("claude_code", 0) >= 25:
        _earn("blacksmith")
    if tc.get("execute", 0) >= 50:
        _earn("demolition")
    if tc.get("write_file", 0) >= 25:
        _earn("archivist")
    if tc.get("write_todos", 0) >= 10:
        _earn("grand_planner")

    # Behavioral
    if len(tc) >= 6:
        _earn("polymath")
    if len(tools_this_turn) >= 5:
        _earn("speed_demon")
    if record.total_xp >= 1000:
        _earn("centurion")
    if record.quests_completed >= 10:
        _earn("busy_bee")
    if record.quests_completed >= 50:
        _earn("road_runner")

    return newly_earned


# ── ProgressionManager ────────────────────────────────────────────────────────


class ProgressionManager:
    """Manage XP, level, and achievements for a single agent."""

    def __init__(self, agent_id: str, class_name: str) -> None:
        self._agent_id = agent_id
        self._class_name = class_name
        self._record: ProgressionRecord | None = None

    def _path(self) -> Path:
        return get_progression_dir() / f"{self._agent_id}.json"

    def load(self) -> ProgressionRecord:
        """Load or create the progression record from disk."""
        path = self._path()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                raw_achievements = data.get("achievements", [])
                achievements = [
                    EarnedAchievement(
                        id=a["id"],
                        name=a["name"],
                        description=a["description"],
                        earned_at=a["earned_at"],
                    )
                    for a in raw_achievements
                    if isinstance(a, dict)
                ]
                total_xp = data.get("total_xp", 0)
                level = _level_from_xp(total_xp)
                xp_this, xp_next = _xp_progress(total_xp, level)
                self._record = ProgressionRecord(
                    agent_id=data.get("agent_id", self._agent_id),
                    class_name=self._class_name,
                    level=level,
                    total_xp=total_xp,
                    xp_this_level=xp_this,
                    xp_next_level=xp_next,
                    tool_counts=data.get("tool_counts", {}),
                    turns_completed=data.get("turns_completed", 0),
                    quests_completed=data.get("quests_completed", data.get("busy_work_completed", 0)),
                    achievements=achievements,
                    created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
                    last_active=data.get("last_active", datetime.now(timezone.utc).isoformat()),
                    current_streak=data.get("current_streak", 0),
                    last_streak_date=data.get("last_streak_date", ""),
                    prestige=data.get("prestige", 0),
                    celebrated_birthdays=data.get("celebrated_birthdays", []),
                )
                return self._record
            except Exception:
                pass
        # Fresh record
        self._record = ProgressionRecord(
            agent_id=self._agent_id,
            class_name=self._class_name,
        )
        self._save()
        return self._record

    def get_record(self) -> ProgressionRecord:
        """Return the current record, loading from disk if not yet loaded."""
        if self._record is None:
            return self.load()
        return self._record

    def record_tool_call(self, tool_name: str) -> None:
        """Increment the tool call counter for *tool_name*."""
        record = self.get_record()
        record.tool_counts[tool_name] = record.tool_counts.get(tool_name, 0) + 1

    def award_xp(
        self,
        tool_names_this_turn: list[str],
        is_quest: bool = False,
        response_chars: int = 0,
    ) -> XPGrant:
        """Award XP, recalculate level, check achievements, persist."""
        from datetime import date, timedelta
        record = self.get_record()
        old_level = record.level

        # ── Streak update ──────────────────────────────────────────────────────
        today = date.today().isoformat()
        if record.last_streak_date == today:
            pass  # already updated today
        elif record.last_streak_date == (date.today() - timedelta(days=1)).isoformat():
            record.current_streak += 1
        else:
            record.current_streak = 1
        record.last_streak_date = today

        if is_quest:
            xp = _XP_QUEST
            record.quests_completed += 1
        else:
            xp = len(tool_names_this_turn) * _XP_PER_TOOL_CALL + _XP_PER_TURN
            if "claude_code" in tool_names_this_turn:
                xp += _XP_CLAUDE_CODE_BONUS
            xp += response_chars // 50 * _XP_PER_50_RESPONSE_CHARS
            record.turns_completed += 1

        # Apply streak multiplier
        if record.current_streak >= 7:
            xp = int(xp * 1.5)

        record.total_xp += xp

        new_level = _level_from_xp(record.total_xp)
        record.level = new_level
        record.xp_this_level, record.xp_next_level = _xp_progress(record.total_xp, new_level)

        new_achievements = _check_achievements(record, tool_names_this_turn)
        record.achievements.extend(new_achievements)
        record.last_active = datetime.now(timezone.utc).isoformat()

        self._save()

        return XPGrant(
            xp_awarded=xp,
            old_level=old_level,
            new_level=new_level,
            leveled_up=new_level > old_level,
            new_achievements=new_achievements,
            streak_days=record.current_streak,
        )

    def can_prestige(self) -> bool:
        """Return True if the agent is at max level and eligible for prestige."""
        return self.get_record().level >= _MAX_LEVEL

    def do_prestige(self) -> None:
        """Reset level to 1, increment prestige counter, preserve achievements."""
        record = self.get_record()
        record.prestige += 1
        record.total_xp = 0
        record.level = 1
        record.xp_this_level, record.xp_next_level = _xp_progress(0, 1)
        record.last_active = datetime.now(timezone.utc).isoformat()
        self._save()

    def check_birthday(self) -> int | None:
        """Return milestone days (30/100/365) if newly reached, else None."""
        from datetime import date
        record = self.get_record()
        created = datetime.fromisoformat(record.created_at).date()
        days = (date.today() - created).days
        for milestone in (30, 100, 365):
            if days >= milestone and milestone not in record.celebrated_birthdays:
                record.celebrated_birthdays.append(milestone)
                self._save()
                return milestone
        return None

    def update_class(self, class_name: str) -> None:
        """Sync class name after an agent edit."""
        self._class_name = class_name
        record = self.get_record()
        record.class_name = class_name
        self._save()

    def _save(self) -> None:
        if self._record is None:
            return
        data = asdict(self._record)
        path = self._path()
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
