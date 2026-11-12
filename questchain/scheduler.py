"""QuestChain quest scheduler."""

import asyncio
import json
import logging
import os
import stat
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from functools import wraps
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
            "Start QuestChain to manage quests."
        )
    return _scheduler_instance


def set_scheduler(scheduler: "CronScheduler | None") -> None:
    """Set or clear the singleton CronScheduler instance."""
    global _scheduler_instance
    _scheduler_instance = scheduler


def _serialized(method):
    """Serialize synchronous state transactions, including candidate construction."""
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._state_lock:
            return method(self, *args, **kwargs)
    return guarded


class CronScheduler:
    """Manages persistent quests for the QuestChain agent."""

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
        # Never hold this lock across await or wait for an event-loop callback.
        # APScheduler mutations are synchronous and only enqueue their wakeups.
        self._state_lock = threading.RLock()
        self._event_loop = None
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
        self._load_failed = False
        self._loaded = False

    async def start(self) -> None:
        """Load persisted jobs, seed builtins, register with APScheduler, start."""
        self._event_loop = asyncio.get_running_loop()
        self._start()

    @_serialized
    def _start(self) -> None:
        self._load_jobs()
        self.seed_builtin_jobs()
        if self._agent_manager:
            normalized = [
                {**job, "enabled": False,
                 "migration_pause": "Assigned agent is missing; choose an owner and explicitly resume."}
                if not self._agent_manager.get(job.get("agent_id") or "default") else job
                for job in self._jobs
            ]
            if normalized != self._jobs:
                self._save_jobs(normalized)
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

    @_serialized
    def add_job(
        self,
        name: str,
        cron_expression: str,
        prompt: str,
        timezone_str: str = "UTC",
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new quest, persist it, register with APScheduler.

        Raises ValueError if cron_expression is invalid.
        """
        name, prompt = name.strip(), prompt.strip()
        if not name or not prompt:
            raise ValueError("Name and instructions are required.")
        if len(name) > 120 or len(prompt) > 16000:
            raise ValueError("Use at most 120 characters for the name and 16000 for instructions.")
        if not agent_id and self._agent_manager:
            agent_id = self._agent_manager.get_active_id()
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
        self._save_jobs([*self._jobs, job])
        self._register_job(job)
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

    @_serialized
    def get_job(self, job_id: str) -> dict:
        for job in self._jobs:
            if job["id"] == job_id:
                return dict(job)
        raise ValueError("Quest not found.")

    @_serialized
    def update_job(self, job_id: str, *, name: str, cron_expression: str,
                   prompt: str, timezone_str: str = "UTC", agent_id: str | None = None) -> dict:
        old = self.get_job(job_id)
        if not name.strip() or not prompt.strip():
            raise ValueError("Name and instructions are required.")
        if len(name) > 120 or len(prompt) > 16000:
            raise ValueError("Name or instructions are too long.")
        if not agent_id and self._agent_manager:
            agent_id = self._agent_manager.get_active_id()
        if agent_id and (not self._agent_manager or not self._agent_manager.get(agent_id)):
            raise ValueError("Choose an existing agent.")
        self._trigger(cron_expression, timezone_str)
        old.update(name=name.strip(), cron_expression=cron_expression.strip(),
                   prompt=prompt.strip(), timezone=timezone_str, agent_id=agent_id or "")
        self._save_jobs([old if j["id"] == job_id else j for j in self._jobs])
        if old.get("enabled", True):
            self._register_job(old)
        self._publish()
        return dict(old)

    @_serialized
    def set_enabled(self, job_id: str, enabled: bool) -> None:
        job = self.get_job(job_id)
        job["enabled"] = enabled
        if enabled:
            if self._agent_manager and not self._agent_manager.get(job.get("agent_id") or "default"):
                raise ValueError("Import the assigned subagent or choose an existing owner before resuming.")
            job.pop("migration_pause", None)
        self._save_jobs([job if j["id"] == job_id else j for j in self._jobs])
        if enabled:
            self._register_job(job)
        elif self._scheduler.get_job(f"cron:{job_id}"):
            self._remove_registered(f"cron:{job_id}")
        self._publish()

    @_serialized
    def run_now(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job_id in self._running or self._scheduler.get_job(f"manual:{job_id}"):
            raise ValueError("This job is already running or queued.")
        self._scheduler.add_job(self._execute_job, trigger="date", args=[job, "manual-" + uuid.uuid4().hex], id=f"manual:{job_id}")

    @_serialized
    def _publish(self) -> None:
        from questchain.gateway.events import get_bus
        event = {"type": "cron_jobs", "jobs": self.list_jobs()}
        # asyncio queues must only be touched on their owning event loop. Enqueue
        # without waiting: the loop may itself be waiting for this transaction.
        if self._event_loop is not None:
            self._event_loop.call_soon_threadsafe(get_bus().publish_nowait, event)
        else:
            get_bus().publish_nowait(event)

    @_serialized
    def remove_job(self, job_id: str) -> dict[str, Any]:
        """Remove a job by ID. Raises KeyError if not found."""
        for job in self._jobs:
            if job["id"] == job_id:
                removed = job
                self._save_jobs([j for j in self._jobs if j["id"] != job_id])
                self._remove_registered(f"cron:{job_id}")
                if self._scheduler.get_job(f"manual:{job_id}"):
                    self._remove_registered(f"manual:{job_id}")
                self._publish()
                return removed
        raise KeyError(f"No quest with ID '{job_id}'")

    @_serialized
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
        if self._agent_manager and not self._agent_manager.get(job.get("agent_id") or "default"):
            raise ValueError("Assigned agent is missing; choose an owner and explicitly resume.")
        trigger = self._trigger(job["cron_expression"], job.get("timezone", "UTC"))
        try:
            self._scheduler.add_job(
                self._execute_job,
                trigger=trigger,
                id=f"cron:{job['id']}",
                args=[job],
                replace_existing=True,
            )
        except Exception as exc:
            self._registration_failed(exc)

    def _remove_registered(self, job_id: str) -> None:
        try:
            if self._scheduler.get_job(job_id):
                self._scheduler.remove_job(job_id)
        except Exception as exc:
            self._registration_failed(exc)

    def _registration_failed(self, exc: Exception) -> None:
        # Disk is already committed. Do not claim rollback or leave stale live
        # definitions firing after a failed register/remove operation.
        if self._scheduler.running:
            self._scheduler.pause()
        raise RuntimeError("Quest state was saved, but live scheduling failed. Scheduling is paused; repair the error and restart. " + str(exc)) from exc

    @_serialized
    def seed_builtin_jobs(self) -> None:
        """Insert builtin quests if they are not already present (by id)."""
        existing_ids = {j["id"] for j in self._jobs}
        added = [j for j in BUILTIN_CRON_JOBS if j["id"] not in existing_ids]
        if added:
            self._save_jobs([*self._jobs, *added])
            logger.info("Seeded %d builtin quest(s)", len(added))

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
                        "Could not build %s agent for quest '%s': %s — using default",
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
                        "Could not build agent '%s' for quest '%s': %s — using default",
                        agent_id, job["name"], e,
                    )
        return self._agent

    async def _execute_job(self, job: dict, occurrence: str | None = None) -> None:
        job_id = job["id"]
        with self._state_lock:
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
            with self._state_lock:
                self._running.discard(job_id)
                self._publish()

    def _record_result(self, job_id: str, status: str, result: str) -> None:
        self._update_saved(job_id, last_run=datetime.now(timezone.utc).isoformat(),
                           last_status=status, last_result=result[:16000])

    @_serialized
    def _update_saved(self, job_id: str, **changes) -> None:
        self._save_jobs([{**job, **changes} if job["id"] == job_id else job for job in self._jobs])

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
            self._update_saved(job["id"], last_run_id=run_id)
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
            notification = f"Quest: {job['name']} · {author} · {status}\n\n{text}"
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
            self._update_saved(job["id"], last_blocker=fingerprint if delivery == "delivered" else "",
                               last_delivery_status=delivery, last_agent_name=author)
        except Exception as exc:
            self._record_result(job["id"], "error", str(exc))
            if str(exc) != job.get("last_result"):
                try:
                    await self._send_callback(f"Quest: {job['name']} · error\n\n{exc}")
                except Exception:
                    logger.exception("Could not deliver cron error")

    async def _run_job(self, job: dict) -> None:
        """Fire when a quest triggers. Invoke agent, send response."""
        job_id = job["id"]
        job_name = job["name"]
        prompt = job["prompt"]
        thread_id = f"cron:{job_id}"

        logger.info("Executing quest '%s' (id=%s)", job_name, job_id)

        chunks: list[str] = []

        async def _stream() -> None:
            agent = self._get_agent_for_job(job)
            async for token in agent.run(prompt, thread_id=thread_id):
                chunks.append(token)

        try:
            await asyncio.wait_for(_stream(), timeout=1800)  # 30 min — local models can be slow
        except asyncio.TimeoutError:
            self._record_result(job_id, "timeout", "Job timed out after 30 minutes.")
            logger.warning("Quest '%s' timed out", job_name)
            try:
                await self._send_callback(f"Quest '{job_name}' timed out.")
            except Exception:
                logger.exception("Failed to send cron timeout message")
            return
        except Exception as e:
            self._record_result(job_id, "error", str(e))
            logger.exception("Quest '%s' failed", job_name)
            try:
                await self._send_callback(f"Quest '{job_name}' error: {e}")
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
        await self._send_callback(f"Quest: {job_name}\n\n{full_response}")

    @_serialized
    def _load_jobs(self) -> None:
        """Validate the whole file before enabling schedules; never reset corruption."""
        try:
            try:
                data = json.loads(self._jobs_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                data = []
            if not isinstance(data, list):
                raise ValueError("Expected a list of quests.")
            ids = set()
            for job in data:
                if not isinstance(job, dict) or any(
                    not isinstance(job.get(key), str) or not job[key].strip()
                    for key in ("id", "name", "prompt", "cron_expression")
                ):
                    raise ValueError("Invalid quest record.")
                if job["id"] in ids or not isinstance(job.get("enabled", True), bool):
                    raise ValueError("Duplicate quest ID or invalid enabled state.")
                if not isinstance(job.get("timezone", "UTC"), str):
                    raise ValueError("Invalid quest timezone.")
                ids.add(job["id"])
                self._trigger(job["cron_expression"], job.get("timezone", "UTC"))
        except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
            self._load_failed = True
            raise ValueError(f"Cannot load quests from {self._jobs_path}; file left unchanged. Repair or restore it before restarting the scheduler: {exc}") from exc
        self._jobs = data
        self._load_failed = False
        self._loaded = True

    @_serialized
    def _save_jobs(self, jobs: list[dict] | None = None) -> None:
        """Replace a complete snapshot before changing memory or live registrations.

        Replacement is the commit point. A later directory-fsync failure is an
        uncertain crash-durability warning, not a failed/rolled-back mutation.
        """
        if self._load_failed:
            raise ValueError("Cannot save quests after a failed load; repair or restore the file first.")
        if not self._loaded and self._jobs_path.exists():
            raise ValueError("Load quests before modifying an existing file.")
        candidate = self._jobs if jobs is None else jobs
        encoded = json.dumps(candidate, indent=2, ensure_ascii=False)
        self._jobs_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self._jobs_path.name}.", suffix=".tmp", dir=self._jobs_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                if os.name == "posix" and self._jobs_path.exists():
                    os.fchmod(handle.fileno(), stat.S_IMODE(self._jobs_path.stat().st_mode))
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._jobs_path)
            temporary = None
            self._jobs = candidate
            self._loaded = True
            if os.name == "posix":
                try:
                    directory = os.open(self._jobs_path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                except OSError as exc:
                    logger.warning("Quest state was replaced, but directory sync failed; crash durability is uncertain: %s", exc)
        finally:
            if temporary is not None:
                try:
                    Path(temporary).unlink(missing_ok=True)
                except OSError:
                    logger.warning("Could not remove uncommitted quest snapshot %s", temporary)
