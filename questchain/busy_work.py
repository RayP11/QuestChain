"""QuestChain heartbeat — periodically checks HEARTBEAT.md and acts on it."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

HEARTBEAT_TIMEOUT = 1800  # 30 minutes — local models can be slow


class BusyWorkRunner:
    """Runs periodic heartbeat checks via the agent's heartbeat() method.

    The agent reads /workspace/HEARTBEAT.md and acts on anything listed there.
    Responses containing only HEARTBEAT_OK are silently suppressed.
    If HEARTBEAT.md is empty or missing the run is skipped entirely.
    """

    def __init__(
        self,
        agent,
        send_callback: Callable[[str], Awaitable[None]],
        interval_minutes: int = 60,
    ):
        self._agent = agent
        self._send_callback = send_callback
        self._interval_minutes = interval_minutes
        self._scheduler = AsyncIOScheduler()
        self._running = False

    @property
    def interval_minutes(self) -> int:
        return self._interval_minutes

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        self._scheduler.add_job(
            self._tick,
            trigger=IntervalTrigger(minutes=self._interval_minutes),
            id="heartbeat",
            replace_existing=True,
        )
        self._scheduler.start()
        self._running = True
        logger.info("Heartbeat started (every %d min)", self._interval_minutes)

    async def stop(self) -> None:
        if self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            logger.info("Heartbeat stopped")

    async def _tick(self) -> None:
        thread_id = f"heartbeat_{uuid.uuid4().hex}"
        logger.debug("Heartbeat tick — thread %s", thread_id)

        try:
            result = await asyncio.wait_for(
                self._agent.heartbeat(thread_id),
                timeout=HEARTBEAT_TIMEOUT,
            )
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
