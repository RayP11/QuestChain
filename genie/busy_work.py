"""Genie busy work — periodically checks /workspace/BUSY_WORK.md."""

import logging
from typing import Awaitable, Callable

from genie.agent import build_input

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

BUSY_WORK_PROMPT = (
    "Read /workspace/BUSY_WORK.md and check if any items need your attention. "
    "If everything is clear or the file doesn't exist, respond with exactly "
    "NO_WORK and nothing else. Otherwise, act on the items that need "
    "attention and report what you did."
)


class BusyWorkRunner:
    """Periodically invokes the agent to check a busy work checklist."""

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
        """Start the busy work scheduler."""
        self._scheduler.add_job(
            self._tick,
            trigger=IntervalTrigger(minutes=self._interval_minutes),
            id="busy_work",
            replace_existing=True,
        )
        self._scheduler.start()
        self._running = True
        logger.info(
            "Busy work started (every %d min)", self._interval_minutes
        )

    async def stop(self) -> None:
        """Stop the busy work scheduler."""
        if self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            logger.info("Busy work stopped")

    async def _tick(self) -> None:
        """Single busy work tick: invoke agent and deliver if needed."""
        logger.debug("Busy work tick")
        thread_id = "busy_work"
        config = {"configurable": {"thread_id": thread_id}}

        try:
            full_response = ""
            async for event in self._agent.astream_events(
                build_input(BUSY_WORK_PROMPT),
                config=config,
                version="v2",
            ):
                if event["event"] == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if hasattr(chunk, "content") and isinstance(
                        chunk.content, str
                    ):
                        full_response += chunk.content

            stripped = full_response.strip()

            # Silently drop "all clear" responses
            if "NO_WORK" in stripped and len(stripped) < 200:
                logger.debug("No work — nothing to report")
                return

            if not stripped:
                logger.debug("Busy work returned empty response — skipping")
                return

            header = "[Busy Work]\n\n"
            await self._send_callback(header + full_response)

        except Exception as e:
            logger.exception("Busy work tick failed")
            try:
                await self._send_callback(f"[Busy Work] Error: {e}")
            except Exception:
                logger.exception("Failed to send busy work error message")
