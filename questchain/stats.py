"""QuestChain all-time metrics tracking per agent."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from questchain.config import get_metrics_dir


@dataclass
class MetricsRecord:
    agent_id: str
    # Static info — refreshed at session start
    model_name: str = ""
    model_size_gb: float = 0.0
    model_params: str = ""
    num_tools: int = 0
    num_skills: int = 0
    context_window: int = 0
    # All-time counters
    prompt_count: int = 0
    tokens_used: int = 0
    total_errors: int = 0
    highest_chain: int = 0


class MetricsManager:
    def __init__(self, agent_id: str) -> None:
        self._agent_id = agent_id
        self._path: Path = get_metrics_dir() / f"{agent_id}.json"
        self._record: MetricsRecord = MetricsRecord(agent_id=agent_id)

    def load(self) -> MetricsRecord:
        """Load metrics from disk, or create a fresh zeroed record if none exists."""
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                # Only load known fields to handle forward-compat
                known = {f for f in MetricsRecord.__dataclass_fields__}
                filtered = {k: v for k, v in data.items() if k in known}
                self._record = MetricsRecord(**{"agent_id": self._agent_id, **filtered})
            except Exception:
                self._record = MetricsRecord(agent_id=self._agent_id)
        else:
            self._record = MetricsRecord(agent_id=self._agent_id)
        return self._record

    def get_record(self) -> MetricsRecord:
        return self._record

    def update_static(
        self,
        model_name: str,
        num_tools: int,
        num_skills: int,
        context_window: int,
    ) -> None:
        """Refresh static fields each session start. Does NOT reset counters."""
        rec = self._record
        rec.model_name = model_name
        rec.num_tools = num_tools
        rec.num_skills = num_skills
        rec.context_window = context_window
        self._save()

    def fetch_model_info(self) -> None:
        """Best-effort: populate model_size_gb and model_params from Ollama."""
        import ollama
        try:
            info = ollama.show(self._record.model_name)
            self._record.model_params = info.details.parameter_size or ""
        except Exception:
            pass
        try:
            for m in ollama.list().models:
                if m.model == self._record.model_name:
                    self._record.model_size_gb = round(m.size / 1e9, 2)
                    break
        except Exception:
            pass
        self._save()

    def record_turn(
        self,
        response_chars: int,
        tool_errors: int,
        chain_depth: int,
    ) -> None:
        """Accumulate per-turn stats into all-time counters."""
        rec = self._record
        rec.prompt_count += 1
        rec.tokens_used += response_chars // 4
        rec.total_errors += tool_errors
        rec.highest_chain = max(rec.highest_chain, chain_depth)
        self._save()

    def _save(self) -> None:
        self._path.write_text(
            json.dumps(asdict(self._record), indent=2),
            encoding="utf-8",
        )
