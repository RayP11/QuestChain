"""Genie busy work — periodically checks /workspace/BUSY_WORK.md."""

import asyncio
import logging
import uuid
from typing import Awaitable, Callable

from genie.agent import build_input

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

# Max seconds a single busy work run may take before it is cancelled.
BUSY_WORK_TIMEOUT = 600  # 10 minutes

BUSY_WORK_PROMPT = """\
AUTONOMOUS MODE. Do useful work for the user right now.

1. Run: ls /workspace/
2. If /workspace/TASKS.md exists: read it, pick the FIRST incomplete task [ ], \
complete it using all your tools. IMPORTANT: you MUST then edit TASKS.md and \
change that task's [ ] to [x] — this is required, not optional. \
Do exactly one task — no more.
3. If no tasks: do something genuinely useful based on what you know about the \
user from your memory.
   Ideas: research a topic they care about, prepare something they'll need, \
run a helpful automation.
4. Use as many tool calls as needed to complete the one task. Don't stop early.
5. When done: write one short paragraph summarizing exactly what you did.
   If you truly found nothing to do: reply with only the word NO_WORK.\
"""


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
        thread_id = f"busy_work_{uuid.uuid4().hex}"
        config = {"configurable": {"thread_id": thread_id}}

        chunks: list[str] = []

        async def _stream() -> None:
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
                        chunks.append(chunk.content)

        try:
            await asyncio.wait_for(_stream(), timeout=BUSY_WORK_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("Busy work timed out after %ds", BUSY_WORK_TIMEOUT)
            try:
                await self._send_callback("Busy work timed out — the agent took too long.")
            except Exception:
                logger.exception("Failed to send busy work timeout message")
            return
        except Exception as e:
            logger.exception("Busy work tick failed")
            try:
                await self._send_callback(f"Error: {e}")
            except Exception:
                logger.exception("Failed to send busy work error message")
            return

        full_response = "".join(chunks).strip()

        # Silently drop "all clear" responses
        if "NO_WORK" in full_response and len(full_response) < 200:
            logger.debug("No work — nothing to report")
            return

        if not full_response:
            logger.debug("Busy work returned empty response — skipping")
            return

        await self._send_callback(full_response)
