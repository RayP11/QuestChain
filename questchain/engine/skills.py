"""Lazy skill loader for the QuestChain engine.

Skills are discovered from three locations (lowest → highest priority):
  1. questchain/skills/            — bundled skills shipped with the package
  2. ~/.questchain/skills/         — user-installed skills
  3. ~/questchain/workspace/skills/ — session/project skills (highest priority)

Only name + one-line description are injected into the system prompt.
The agent calls read_skill(name) to fetch full instructions on demand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from questchain.config import QUESTCHAIN_DATA_DIR, WORKSPACE_DIR
from questchain.engine.tools import ToolDef, _build_schema, tool

# Built-in skills bundled inside the package (questchain/skills/).
# Path(__file__) = questchain/engine/skills.py → parent.parent = questchain/
_BUNDLED_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


@dataclass
class SkillMeta:
    name: str
    description: str
    path: Path
    always: bool = False  # always-active: full content injected into system prompt


class SkillsManager:
    """Discovers and lazily loads SKILL.md files from skill directories.

    Directory precedence (highest wins on name collision):
      1. questchain/skills/          — bundled package skills (lowest priority)
      2. ~/.questchain/skills/       — user-installed skills
      3. workspace/skills/           — session/project skills (highest priority)
    """

    _SKILL_DIRS: list[Path] = [
        _BUNDLED_SKILLS_DIR,                       # lowest priority — bundled with package
        QUESTCHAIN_DATA_DIR / "skills",            # user-installed skills
        WORKSPACE_DIR / "workspace" / "skills",    # highest priority — project skills
    ]

    def __init__(self, skills_filter: list[str] | None = None):
        """
        Args:
            skills_filter: Whitelist of skill dir-names to expose.
                           None (default) = all discovered skills.
                           [] = no skills at all.
        """
        self._skills_filter = skills_filter
        self._skills: dict[str, SkillMeta] = {}
        self._scan()

    def _scan(self) -> None:
        for skill_dir in self._SKILL_DIRS:
            if not skill_dir.exists():
                continue
            for entry in skill_dir.iterdir():
                if entry.is_dir():
                    md = entry / "SKILL.md"
                    name = entry.name
                elif entry.suffix == ".md":
                    md = entry
                    name = entry.stem
                else:
                    continue
                if not md.exists():
                    continue
                self._skills[name] = self._parse_meta(name, md)
        # Apply the filter after the full scan so precedence rules still work
        if self._skills_filter is not None:
            self._skills = {
                k: v for k, v in self._skills.items() if k in self._skills_filter
            }

    def _parse_meta(self, name: str, path: Path) -> SkillMeta:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            return SkillMeta(name=name, description="", path=path)

        description = ""
        always = False

        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                fm = text[3:end]
                m = re.search(r"^name:\s*(.+)$", fm, re.MULTILINE)
                if m:
                    name = m.group(1).strip()
                m = re.search(r"^description:\s*(.+)$", fm, re.MULTILINE)
                if m:
                    description = m.group(1).strip()
                always = bool(re.search(r"^always:\s*true", fm, re.MULTILINE))

        if not description:
            body = text[text.find("---", 3) + 3:] if text.startswith("---") else text
            for line in body.splitlines():
                line = line.strip().lstrip("#").strip()
                if line:
                    description = line[:120]
                    break

        return SkillMeta(name=name, description=description, path=path, always=always)

    # ------------------------------------------------------------------
    # System prompt integration
    # ------------------------------------------------------------------

    def skill_list_text(self) -> str:
        """Short skill registry for the system prompt (~24 tokens/skill)."""
        skills = [s for s in self._skills.values() if not s.always]
        if not skills:
            return ""
        lines = [f"- **{s.name}**: {s.description}" for s in skills]
        return (
            "## Skills\n"
            + "\n".join(lines)
            + "\nUse read_skill(name) to get full instructions before using a skill."
        )

    def always_active_text(self) -> str:
        """Full content of always-active skills, injected into every system prompt."""
        always = [s for s in self._skills.values() if s.always]
        if not always:
            return ""
        parts = []
        for s in always:
            try:
                parts.append(f"## Skill: {s.name}\n{s.path.read_text(encoding='utf-8')}")
            except Exception:
                pass
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Tool
    # ------------------------------------------------------------------

    def make_read_skill_tool(self) -> ToolDef:
        """Return a read_skill ToolDef bound to this manager."""
        manager = self

        async def read_skill(name: str) -> str:
            meta = manager._skills.get(name)
            if meta is None:
                available = ", ".join(manager._skills) or "none"
                return f"Skill '{name}' not found. Available: {available}"
            try:
                return meta.path.read_text(encoding="utf-8")
            except Exception as e:
                return f"Error reading skill '{name}': {e}"

        read_skill.__doc__ = (
            "Get full instructions for a skill by name.\n\n"
            "Args:\n    name: Skill name from the skills list"
        )

        schema = _build_schema(read_skill, "read_skill", "Get full instructions for a skill by name.")
        return ToolDef(
            name="read_skill",
            description="Get full instructions for a skill by name.",
            fn=read_skill,
            schema=schema,
        )

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def list_skills(self) -> list[SkillMeta]:
        return list(self._skills.values())

    def get(self, name: str) -> SkillMeta | None:
        return self._skills.get(name)

    def __len__(self) -> int:
        return len(self._skills)
