"""QuestChain cron job scheduler."""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Awaitable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from questchain.config import get_cron_jobs_path

logger = logging.getLogger(__name__)

BUILTIN_CRON_JOBS: list[dict] = []

# Module-level singleton
_scheduler_instance: "CronScheduler | None" = None


def get_scheduler() -> "CronScheduler":
    """Get the singleton CronScheduler.

    Raises RuntimeError if QuestChain has not started its scheduler.
    """
    if _scheduler_instance is None:
        raise RuntimeError(
            "CronScheduler not initialized. "
            "Start QuestChain to manage cron jobs."
        )
    return _scheduler_instance


def set_scheduler(scheduler: "CronScheduler | None") -> None:
    """Set or clear the singleton CronScheduler instance."""
    global _scheduler_instance
    _scheduler_instance = scheduler


class CronScheduler:
    """Manages persistent cron jobs for the QuestChain agent."""

    def __init__(
        self,
        agent,
        send_callback: Callable[[str], Awaitable[None]],
        jobs_path: Path | None = None,
        agent_manager=None,
        checkpointer=None,
        store=None,
        audio_router=None,
        busy_lock=None,
        runtime=None,
    ):
        self._agent = agent
        self._send_callback = send_callback
        self._jobs_path = jobs_path or get_cron_jobs_path()
        self._scheduler = AsyncIOScheduler()
        self._jobs: list[dict[str, Any]] = []
        self._agent_manager = agent_manager
        self._checkpointer = checkpointer
        self._store = store
        self._audio_router = audio_router
        self._busy_lock = busy_lock or asyncio.Lock()
        self._running: set[str] = set()
        self._runtime = runtime

    async def start(self) -> None:
        """Load persisted jobs, seed builtins, register with APScheduler, start."""
        self._load_jobs()
        self.seed_builtin_jobs()
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
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new cron job, persist it, register with APScheduler.

        Raises ValueError if cron_expression is invalid.
        """
        name, prompt = name.strip(), prompt.strip()
        if not name or not prompt:
            raise ValueError("Name and instructions are required.")
        if len(name) > 120 or len(prompt) > 16000:
            raise ValueError("Use at most 120 characters for the name and 16000 for instructions.")
        if not agent_id and self._agent_manager:
            coordinator = self._agent_manager.get_by_class_name("Router")
            agent_id = coordinator["id"] if coordinator else self._agent_manager.get_active_id()
        if agent_id and (not self._agent_manager or not self._agent_manager.get(agent_id)):
            raise ValueError("Choose an existing agent.")
        self._trigger(cron_expression, timezone_str)

        job = {
            "id": uuid.uuid4().hex[:8], "name": name,
            "cron_expression": cron_expression.strip(), "timezone": timezone_str,
            "prompt": prompt, "enabled": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **({"agent_id": agent_id} if agent_id else {}),
        }
        self._register_job(job)
        self._jobs.append(job)
        self._save_jobs()
        self._publish()
        return dict(job)

    @staticmethod
    def _trigger(cron_expression: str, timezone_str: str):
        fields = cron_expression.strip().split()
        if len(fields) != 5:
            raise ValueError(
                f"Expected 5-field cron expression (minute hour day month weekday), "
                f"got {len(fields)} fields: '{cron_expression}'"
            )

        # Validate by constructing a trigger (raises on bad input)
        return CronTrigger(
            minute=fields[0], hour=fields[1], day=fields[2],
            month=fields[3], day_of_week=fields[4], timezone=timezone_str,
        )

    def get_job(self, job_id: str) -> dict:
        for job in self._jobs:
            if job["id"] == job_id:
                return dict(job)
        raise ValueError("Cron job not found.")

    def update_job(self, job_id: str, *, name: str, cron_expression: str,
                   prompt: str, timezone_str: str = "UTC", agent_id: str | None = None) -> dict:
        old = self.get_job(job_id)
        if not name.strip() or not prompt.strip():
            raise ValueError("Name and instructions are required.")
        if len(name) > 120 or len(prompt) > 16000:
            raise ValueError("Name or instructions are too long.")
        if not agent_id and self._agent_manager:
            coordinator = self._agent_manager.get_by_class_name("Router")
            agent_id = coordinator["id"] if coordinator else self._agent_manager.get_active_id()
        if agent_id and (not self._agent_manager or not self._agent_manager.get(agent_id)):
            raise ValueError("Choose an existing agent.")
        self._trigger(cron_expression, timezone_str)
        old.update(name=name.strip(), cron_expression=cron_expression.strip(),
                   prompt=prompt.strip(), timezone=timezone_str, agent_id=agent_id or "")
        if old.get("enabled", True):
            self._register_job(old)
        self._jobs = [old if j["id"] == job_id else j for j in self._jobs]
        self._save_jobs()
        self._publish()
        return dict(old)

    def set_enabled(self, job_id: str, enabled: bool) -> None:
        job = self.get_job(job_id)
        job["enabled"] = enabled
        if enabled:
            self._register_job(job)
        elif self._scheduler.get_job(f"cron:{job_id}"):
            self._scheduler.remove_job(f"cron:{job_id}")
        self._jobs = [job if j["id"] == job_id else j for j in self._jobs]
        self._save_jobs()
        self._publish()

    def run_now(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job_id in self._running or self._scheduler.get_job(f"manual:{job_id}"):
            raise ValueError("This job is already running or queued.")
        self._scheduler.add_job(self._execute_job, trigger="date", args=[job, "manual-" + uuid.uuid4().hex], id=f"manual:{job_id}")

    def _publish(self) -> None:
        from questchain.gateway.events import get_bus
        get_bus().publish_nowait({"type": "cron_jobs", "jobs": self.list_jobs()})

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
                if self._scheduler.get_job(f"manual:{job_id}"):
                    self._scheduler.remove_job(f"manual:{job_id}")
                self._publish()
                return removed
        raise KeyError(f"No cron job with ID '{job_id}'")

    def list_jobs(self) -> list[dict[str, Any]]:
        """Return all jobs."""
        result = []
        for job in self._jobs:
            scheduled = self._scheduler.get_job(f"cron:{job['id']}")
            next_run = getattr(scheduled, "next_run_time", None)
            missing = self._agent_manager and not self._agent_manager.get(job.get("agent_id") or "default")
            result.append({**job, "running": job["id"] in self._running,
                           "agent_issue": "Assigned agent is archived or missing; migrate it or choose a new owner." if missing else "",
                           "next_run": next_run.isoformat() if next_run else None})
        return result

    # --- Internal ---

    def _register_job(self, job: dict) -> None:
        """Register a single job with APScheduler."""
        trigger = self._trigger(job["cron_expression"], job.get("timezone", "UTC"))
        self._scheduler.add_job(
            self._execute_job,
            trigger=trigger,
            id=f"cron:{job['id']}",
            args=[job],
            replace_existing=True,
        )

    def seed_builtin_jobs(self) -> None:
        """Insert builtin cron jobs if they are not already present (by id)."""
        existing_ids = {j["id"] for j in self._jobs}
        added = [j for j in BUILTIN_CRON_JOBS if j["id"] not in existing_ids]
        if added:
            self._jobs.extend(added)
            self._save_jobs()
            logger.info("Seeded %d builtin cron job(s)", len(added))

    def _get_agent_for_job(self, job: dict):
        """Return the agent to use for a job, falling back to the default."""
        from questchain.agent import make_agent_from_def

        # Try class-name lookup first (used by builtin jobs)
        agent_class = job.get("agent_class")
        if agent_class and self._agent_manager:
            agent_def = self._agent_manager.get_by_class_name(agent_class)
            if agent_def:
                try:
                    return make_agent_from_def(agent_def, self._audio_router, default_model=self._agent.model.model_name)
                except Exception as e:
                    logger.warning(
                        "Could not build %s agent for cron job '%s': %s — using default",
                        agent_class, job["name"], e,
                    )

        # Fall back to direct ID lookup (user-created jobs)
        agent_id = job.get("agent_id") or "default"
        if agent_id and self._agent_manager:
            agent_def = self._agent_manager.get(agent_id)
            if agent_def:
                try:
                    return make_agent_from_def(agent_def, self._audio_router, default_model=self._agent.model.model_name)
                except Exception as e:
                    logger.warning(
                        "Could not build agent '%s' for cron job '%s': %s — using default",
                        agent_id, job["name"], e,
                    )
        return self._agent

    async def _execute_job(self, job: dict, occurrence: str | None = None) -> None:
        job_id = job["id"]
        if job_id in self._running:
            return
        self._running.add(job_id)
        self._publish()
        try:
            if self._runtime:
                await self._run_task(self.get_job(job_id), occurrence)
            else:
                async with self._busy_lock:
                    await self._run_job(job)
        finally:
            self._running.discard(job_id)
            self._publish()

    def _record_result(self, job_id: str, status: str, result: str) -> None:
        for saved in self._jobs:
            if saved["id"] == job_id:
                saved.update(last_run=datetime.now(timezone.utc).isoformat(),
                             last_status=status, last_result=result[:16000])
        self._save_jobs()

    async def _run_task(self, job: dict, occurrence: str | None = None) -> None:
        """Run the scheduled assignment through the same runtime as all chat adapters."""
        import hashlib
        from questchain.runtime import TaskRequest
        signature = hashlib.sha256(json.dumps({k: job.get(k) for k in
            ("agent_id", "prompt", "cron_expression", "timezone")}, sort_keys=True).encode()).hexdigest()[:16]
        occurrence = occurrence or str(int(datetime.now(timezone.utc).timestamp()) // 60)
        try:
            run_id = self._runtime.submit(TaskRequest(
                job["prompt"], job.get("agent_id") or "default", "cron-" + job["id"], "cron",
                occurrence_key=f"cron:{job['id']}:{signature}:{occurrence}", destination="cron"))
            for saved in self._jobs:
                if saved["id"] == job["id"]:
                    saved["last_run_id"] = run_id
            self._save_jobs()
            self._publish()
            result = await self._runtime.wait(run_id)
            if result.get("delivery_status") == "delivered":
                return  # Repeated scheduler callback must not notify twice.
            status = "success" if result["status"] == "completed" else result["status"]
            text = result["result"]
            if result["error"]:
                text += ("\n\n" if text else "") + result["error"]
            self._record_result(job["id"], status, text)
            author = result.get("result_agent_name", result["agent_name"])
            notification = f"Cron: {job['name']} · {author} · {status}\n\n{text}"
            fingerprint = hashlib.sha256((signature + text).encode()).hexdigest() if status != "success" else ""
            if fingerprint and fingerprint == job.get("last_blocker"):
                return
            try:
                await self._send_callback(notification)
            except Exception as exc:
                self._runtime.mark_delivered(run_id, str(exc))
                delivery = "failed"
                logger.warning("Cron result delivery failed: %s", exc)
            else:
                self._runtime.mark_delivered(run_id)
                delivery = "delivered"
            for saved in self._jobs:
                if saved["id"] == job["id"]:
                    saved.update(last_blocker=fingerprint if delivery == "delivered" else "",
                                 last_delivery_status=delivery, last_agent_name=author)
            self._save_jobs()
        except Exception as exc:
            self._record_result(job["id"], "error", str(exc))
            if str(exc) != job.get("last_result"):
                try:
                    await self._send_callback(f"Cron: {job['name']} · error\n\n{exc}")
                except Exception:
                    logger.exception("Could not deliver cron error")

    async def _run_job(self, job: dict) -> None:
        """Fire when a cron job triggers. Invoke agent, send response."""
        job_id = job["id"]
        job_name = job["name"]
        prompt = job["prompt"]
        thread_id = f"cron:{job_id}"

        logger.info("Executing cron job '%s' (id=%s)", job_name, job_id)

        chunks: list[str] = []

        async def _stream() -> None:
            agent = self._get_agent_for_job(job)
            async for token in agent.run(prompt, thread_id=thread_id):
                chunks.append(token)

        try:
            await asyncio.wait_for(_stream(), timeout=1800)  # 30 min — local models can be slow
        except asyncio.TimeoutError:
            self._record_result(job_id, "timeout", "Job timed out after 30 minutes.")
            logger.warning("Cron job '%s' timed out", job_name)
            try:
                await self._send_callback(f"Cron job '{job_name}' timed out.")
            except Exception:
                logger.exception("Failed to send cron timeout message")
            return
        except Exception as e:
            self._record_result(job_id, "error", str(e))
            logger.exception("Cron job '%s' failed", job_name)
            try:
                await self._send_callback(f"Cron job '{job_name}' error: {e}")
            except Exception:
                logger.exception("Failed to send cron error message")
            return

        full_response = "".join(chunks).strip() or "(No response generated)"
        self._record_result(job_id, "success", full_response)
        if self._agent_manager:
            from questchain.progression import ProgressionManager
            from questchain.gateway import server
            definition = self._agent_manager.get(job.get("agent_id") or "default")
            if definition:
                progression = ProgressionManager(definition["id"], definition.get("class_name", "Custom"))
                progression.load()
                progression.award_xp([], is_job=True)
                if server._progression and server._progression.get_record().agent_id == definition["id"]:
                    server._progression.load()
        await self._send_callback(f"Cron: {job_name}\n\n{full_response}")

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
