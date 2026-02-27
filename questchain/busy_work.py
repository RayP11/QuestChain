"""QuestChain heartbeat — periodically checks HEARTBEAT.md and acts on it."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

HEARTBEAT_TIMEOUT = 1800  # 30 minutes — local models can be slow
_FIRST_TICK_DELAY = 30    # seconds before the very first tick after startup


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
            # Clear HEARTBEAT.md so the same task isn't re-run on the next tick
            try:
                from questchain.config import WORKSPACE_DIR
                heartbeat_path = WORKSPACE_DIR / "workspace" / "HEARTBEAT.md"
                if heartbeat_path.exists():
                    heartbeat_path.write_text("", encoding="utf-8")
                    logger.debug("HEARTBEAT.md cleared after successful tick")
            except Exception:
                logger.warning("Could not clear HEARTBEAT.md after tick")
        else:
            logger.debug("Heartbeat: nothing to do")
