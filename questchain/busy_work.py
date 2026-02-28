"""QuestChain heartbeat — periodically checks HEARTBEAT.md and acts on it."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

HEARTBEAT_TIMEOUT = 1800  # 30 minutes — local models can be slow
_FIRST_TICK_DELAY = 30    # seconds before the very first tick after startup

_OVERNIGHT_PROMPT = (
    "Check /workspace/overnight.md for your tasks. Complete all Standing Tasks "
    "and any items in Tonight's Queue. Mark queue items [x] when done and move "
    "them to the Completed Archive section. Append a brief timestamped LOG entry "
    "at the bottom. Reply OVERNIGHT_DONE when all work is complete."
)


class BusyWorkRunner:
    """Runs periodic heartbeat checks via the agent's heartbeat() method.

    The agent reads /workspace/HEARTBEAT.md and acts on anything listed there.
    Responses containing only HEARTBEAT_OK are silently suppressed.
    If HEARTBEAT.md is empty or missing the run is skipped entirely.

    A shared *busy_lock* prevents heartbeat ticks from running while the agent
    is already processing a user or Telegram message.
    """

    def __init__(
        self,
        agent_holder: dict,
        send_callback: Callable[[str], Awaitable[None]],
        interval_minutes: int = 60,
        busy_lock: asyncio.Lock | None = None,
    ):
        self._agent_holder = agent_holder
        self._send_callback = send_callback
        self._interval_minutes = interval_minutes
        self._busy_lock = busy_lock
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def interval_minutes(self) -> int:
        return self._interval_minutes

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="heartbeat")
        logger.info("Heartbeat started (every %d min)", self._interval_minutes)

    async def stop(self) -> None:
        if self._running:
            self._running = False
            if self._task:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                self._task = None
            logger.info("Heartbeat stopped")

    async def _run_loop(self) -> None:
        """Short initial delay, then tick at the configured interval forever."""
        try:
            await asyncio.sleep(_FIRST_TICK_DELAY)
            while self._running:
                await self._tick()
                if not self._running:
                    break
                await asyncio.sleep(self._interval_minutes * 60)
        except asyncio.CancelledError:
            pass

    async def _tick(self) -> None:
        # Skip this tick if the agent is already handling a user or Telegram turn.
        # In asyncio (single-threaded) there is no TOCTOU between locked() and
        # acquire() because no await separates them.
        if self._busy_lock is not None and self._busy_lock.locked():
            logger.debug("Heartbeat: skipping tick — agent is busy")
            return

        thread_id = f"heartbeat_{uuid.uuid4().hex}"
        logger.debug("Heartbeat tick — thread %s", thread_id)

        async def _run_heartbeat() -> str | None:
            # Always look up the live agent from the holder so agent switches
            # are respected without needing to restart the runner.
            agent = self._agent_holder["agent"]
            if self._busy_lock is not None:
                async with self._busy_lock:
                    return await agent.heartbeat(thread_id)
            return await agent.heartbeat(thread_id)

        try:
            result = await asyncio.wait_for(_run_heartbeat(), timeout=HEARTBEAT_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("Heartbeat timed out after %ds", HEARTBEAT_TIMEOUT)
            try:
                await self._send_callback("Heartbeat timed out — agent took too long.")
            except Exception:
                logger.exception("Failed to deliver heartbeat timeout message")
            return
        except Exception as e:
            logger.exception("Heartbeat tick failed")
            try:
                await self._send_callback(f"Heartbeat error: {e}")
            except Exception:
                logger.exception("Failed to deliver heartbeat error message")
            return

        if result:
            await self._send_callback(result)
        else:
            logger.debug("Heartbeat: nothing to do")


class OvernightRunner:
    """Runs the Night Owl agent every 30 min during overnight hours (12 AM – 6 AM).

    Uses /workspace/overnight.md as its task source — never touches HEARTBEAT.md.
    Maintains a per-date thread (overnight:YYYY-MM-DD) so the agent remembers
    earlier work from the same night.
    Shares *busy_lock* with BusyWorkRunner to prevent concurrent runs.
    """

    START_HOUR = 0   # midnight
    END_HOUR   = 6   # 6 AM exclusive

    def __init__(
        self,
        agent_manager,
        send_callback: Callable[[str], Awaitable[None]],
        busy_lock: asyncio.Lock | None = None,
        interval_minutes: int = 30,
    ):
        self._agent_manager = agent_manager
        self._send_callback = send_callback
        self._busy_lock = busy_lock
        self._interval_minutes = interval_minutes
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="overnight")
        logger.info("OvernightRunner started (every %d min, 00–06h)", self._interval_minutes)

    async def stop(self) -> None:
        if self._running:
            self._running = False
            if self._task:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
                self._task = None
            logger.info("OvernightRunner stopped")

    async def _run_loop(self) -> None:
        try:
            await asyncio.sleep(_FIRST_TICK_DELAY)
            while self._running:
                await self._tick()
                if not self._running:
                    break
                await asyncio.sleep(self._interval_minutes * 60)
        except asyncio.CancelledError:
            pass

    def _is_overnight_hour(self, hour: int) -> bool:
        return self.START_HOUR <= hour < self.END_HOUR

    async def _tick(self) -> None:
        from datetime import datetime
        now = datetime.now()
        if not self._is_overnight_hour(now.hour):
            logger.debug("OvernightRunner: outside overnight window (%02d:xx) — skipping", now.hour)
            return

        if self._busy_lock is not None and self._busy_lock.locked():
            logger.debug("OvernightRunner: skipping tick — agent is busy")
            return

        # Check that overnight.md exists — if not, nothing to do
        from questchain.config import WORKSPACE_DIR
        overnight_path = WORKSPACE_DIR / "workspace" / "overnight.md"
        if not overnight_path.exists():
            logger.debug("OvernightRunner: overnight.md not found — skipping")
            return

        # Find the Night Owl agent by class name
        overnight_def = self._agent_manager.get_by_class_name("NightOwl")
        if overnight_def is None:
            logger.warning("OvernightRunner: no NightOwl agent found — skipping")
            return

        from questchain.agent import make_agent_from_def
        agent = make_agent_from_def(overnight_def)

        thread_id = f"overnight:{now.strftime('%Y-%m-%d')}"
        logger.info("OvernightRunner tick — thread %s", thread_id)

        async def _run() -> str:
            chunks: list[str] = []
            async for token in agent.run(_OVERNIGHT_PROMPT, thread_id=thread_id):
                chunks.append(token)
            return "".join(chunks).strip()

        try:
            if self._busy_lock:
                async with self._busy_lock:
                    result = await asyncio.wait_for(_run(), timeout=HEARTBEAT_TIMEOUT)
            else:
                result = await asyncio.wait_for(_run(), timeout=HEARTBEAT_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("OvernightRunner timed out after %ds", HEARTBEAT_TIMEOUT)
            try:
                await self._send_callback("Night Owl timed out — agent took too long.")
            except Exception:
                logger.exception("Failed to deliver overnight timeout message")
            return
        except Exception as e:
            logger.exception("OvernightRunner tick failed")
            try:
                await self._send_callback(f"Night Owl error: {e}")
            except Exception:
                logger.exception("Failed to deliver overnight error message")
            return

        if result and "OVERNIGHT_DONE" not in result:
            await self._send_callback(result)
        else:
            logger.debug("OvernightRunner: OVERNIGHT_DONE or empty response — nothing to send")
