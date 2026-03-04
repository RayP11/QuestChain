"""QuestChain quest runner — periodically picks and completes quests from workspace/quests/."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

HEARTBEAT_TIMEOUT = 1800  # 30 minutes — local models can be slow
_FIRST_TICK_DELAY = 30    # seconds before the very first tick after startup


class QuestRunner:
    """Runs periodic quest ticks via the agent's run_quest() method.

    The agent picks the first quest from workspace/quests/ and completes it.
    If the quests directory is empty or missing, the tick is skipped silently.

    A shared *busy_lock* prevents quest ticks from running while the agent
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
        self._current_tick_task: asyncio.Task | None = None

    @property
    def interval_minutes(self) -> int:
        return self._interval_minutes

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="quest_runner")
        logger.info("Quest runner started (every %d min)", self._interval_minutes)

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
            logger.info("Quest runner stopped")

    async def interrupt(self) -> None:
        """Cancel the in-progress tick (if any) so the lock is released immediately.

        The tick will not be retried — the next scheduled interval picks up normally.
        Safe to call even when no tick is running.
        """
        task = self._current_tick_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

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
            logger.debug("Quest: skipping tick — agent is busy")
            return

        thread_id = f"quest_{uuid.uuid4().hex}"
        logger.debug("Quest tick — thread %s", thread_id)

        async def _run_quest() -> str | None:
            # Always look up the live agent from the holder so agent switches
            # are respected without needing to restart the runner.
            agent = self._agent_holder["agent"]
            if self._busy_lock is not None:
                async with self._busy_lock:
                    return await agent.run_quest(thread_id)
            return await agent.run_quest(thread_id)

        try:
            self._current_tick_task = asyncio.create_task(
                asyncio.wait_for(_run_quest(), timeout=HEARTBEAT_TIMEOUT),
                name="quest_tick",
            )
            result = await self._current_tick_task
        except asyncio.CancelledError:
            logger.debug("Quest tick interrupted by user input")
            return
        except asyncio.TimeoutError:
            logger.warning("Quest timed out after %ds", HEARTBEAT_TIMEOUT)
            try:
                await self._send_callback("Quest timed out — agent took too long.")
            except Exception:
                logger.exception("Failed to deliver quest timeout message")
            return
        except Exception as e:
            logger.exception("Quest tick failed")
            try:
                await self._send_callback(f"Quest error: {e}")
            except Exception:
                logger.exception("Failed to deliver quest error message")
            return
        finally:
            self._current_tick_task = None

        if result:
            await self._send_callback(result)
        else:
            logger.debug("Quest: nothing to do")
