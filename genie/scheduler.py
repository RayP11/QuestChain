"""Genie cron job scheduler."""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Awaitable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from genie.config import get_cron_jobs_path

logger = logging.getLogger(__name__)

# Module-level singleton
_scheduler_instance: "CronScheduler | None" = None


def get_scheduler() -> "CronScheduler":
    """Get the singleton CronScheduler.

    Raises RuntimeError if not initialized (e.g. in CLI mode).
    """
    if _scheduler_instance is None:
        raise RuntimeError(
            "CronScheduler not initialized. "
            "Cron jobs are only available in Telegram mode (--telegram)."
        )
    return _scheduler_instance


def set_scheduler(scheduler: "CronScheduler | None") -> None:
    """Set or clear the singleton CronScheduler instance."""
    global _scheduler_instance
    _scheduler_instance = scheduler


class CronScheduler:
    """Manages persistent cron jobs for the Genie agent."""

    def __init__(
        self,
        agent,
        send_callback: Callable[[str], Awaitable[None]],
        jobs_path: Path | None = None,
    ):
        self._agent = agent
        self._send_callback = send_callback
        self._jobs_path = jobs_path or get_cron_jobs_path()
        self._scheduler = AsyncIOScheduler()
        self._jobs: list[dict[str, Any]] = []

    async def start(self) -> None:
        """Load persisted jobs, register with APScheduler, start."""
        self._load_jobs()
        for job in self._jobs:
            if job.get("enabled", True):
                self._register_job(job)
        self._scheduler.start()
        logger.info("CronScheduler started with %d job(s)", len(self._jobs))

    async def stop(self) -> None:
        """Shut down the scheduler."""
        self._scheduler.shutdown(wait=False)
        logger.info("CronScheduler stopped")

    # --- CRUD (called by tools) ---

    def add_job(
        self,
        name: str,
        cron_expression: str,
        prompt: str,
        timezone_str: str = "UTC",
    ) -> dict[str, Any]:
        """Create a new cron job, persist it, register with APScheduler.

        Raises ValueError if cron_expression is invalid.
        """
        fields = cron_expression.strip().split()
        if len(fields) != 5:
            raise ValueError(
                f"Expected 5-field cron expression (minute hour day month weekday), "
                f"got {len(fields)} fields: '{cron_expression}'"
            )

        # Validate by constructing a trigger (raises on bad input)
        CronTrigger(
            minute=fields[0], hour=fields[1], day=fields[2],
            month=fields[3], day_of_week=fields[4], timezone=timezone_str,
        )

        job = {
            "id": uuid.uuid4().hex[:8],
            "name": name,
            "cron_expression": cron_expression,
            "timezone": timezone_str,
            "prompt": prompt,
            "enabled": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._jobs.append(job)
        self._save_jobs()
        self._register_job(job)
        return job

    def remove_job(self, job_id: str) -> dict[str, Any]:
        """Remove a job by ID. Raises KeyError if not found."""
        for i, job in enumerate(self._jobs):
            if job["id"] == job_id:
                removed = self._jobs.pop(i)
                self._save_jobs()
                try:
                    self._scheduler.remove_job(f"cron:{job_id}")
                except Exception:
                    pass
                return removed
        raise KeyError(f"No cron job with ID '{job_id}'")

    def list_jobs(self) -> list[dict[str, Any]]:
        """Return all jobs."""
        return list(self._jobs)

    # --- Internal ---

    def _register_job(self, job: dict) -> None:
        """Register a single job with APScheduler."""
        fields = job["cron_expression"].split()
        trigger = CronTrigger(
            minute=fields[0], hour=fields[1], day=fields[2],
            month=fields[3], day_of_week=fields[4],
            timezone=job.get("timezone", "UTC"),
        )
        self._scheduler.add_job(
            self._execute_job,
            trigger=trigger,
            id=f"cron:{job['id']}",
            args=[job],
            replace_existing=True,
        )

    async def _execute_job(self, job: dict) -> None:
        """Fire when a cron job triggers. Invoke agent, send response."""
        job_id = job["id"]
        job_name = job["name"]
        prompt = job["prompt"]
        thread_id = f"cron:{job_id}"

        logger.info("Executing cron job '%s' (id=%s)", job_name, job_id)

        try:
            config = {"configurable": {"thread_id": thread_id}}
            full_response = ""

            async for event in self._agent.astream_events(
                {"messages": [{"role": "user", "content": prompt}]},
                config=config,
                version="v2",
            ):
                if event["event"] == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if hasattr(chunk, "content") and isinstance(chunk.content, str):
                        full_response += chunk.content

            if not full_response.strip():
                full_response = "(No response generated)"

            header = f"[Cron: {job_name}]\n\n"
            await self._send_callback(header + full_response)

        except Exception as e:
            logger.exception("Cron job '%s' failed", job_name)
            try:
                await self._send_callback(f"[Cron: {job_name}] Error: {e}")
            except Exception:
                logger.exception("Failed to send cron error message")

    def _load_jobs(self) -> None:
        """Load jobs from JSON file."""
        if self._jobs_path.exists():
            try:
                data = json.loads(self._jobs_path.read_text(encoding="utf-8"))
                self._jobs = data if isinstance(data, list) else []
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load cron jobs: %s", e)
                self._jobs = []
        else:
            self._jobs = []

    def _save_jobs(self) -> None:
        """Persist jobs to JSON file."""
        self._jobs_path.parent.mkdir(parents=True, exist_ok=True)
        self._jobs_path.write_text(
            json.dumps(self._jobs, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
