"""Shared task execution for chat, Telegram, terminal and scheduled jobs."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from questchain.runtime.store import RunStore
from questchain.runtime.routing import choose_destination

logger = logging.getLogger(__name__)
TERMINAL = frozenset({"completed", "partial", "failed", "cancelled", "interrupted", "waiting_input"})


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class TaskRequest:
    text: str
    agent_id: str
    conversation_id: str
    source: str = "cli"
    reply_to_run_id: str = ""
    occurrence_key: str | None = None
    destination: str = ""
    audio_callback: object = None


class TaskRuntime:
    def __init__(self, manager, *, default_model: str, path: Path | None = None,
                 agent_factory=None, model_factory=None, busy_lock=None, event_sink=None, default_audio=None):
        from questchain.config import ensure_data_dir
        from questchain.engine.model import OllamaModel
        from questchain.gateway.events import get_bus
        self.manager = manager
        self.default_model = default_model
        self.store = RunStore(path or ensure_data_dir() / "tasks.sqlite3")
        self.agent_factory = agent_factory
        self.default_audio = default_audio
        self._audio_callbacks = {}
        self.model_factory = model_factory or OllamaModel
        self.lock = busy_lock or asyncio.Lock()
        self.event_sink = event_sink or get_bus().publish_nowait
        self.queue = asyncio.PriorityQueue()
        self._counter = 0
        self._worker_task = None
        self._active_task = None
        self._active_run = None
        self._futures = {}
        self._cancelled = set()
        self._closed = False
        for run in self.store.runs():
            if run["status"] not in TERMINAL:
                run.update(status="interrupted", error="Application stopped before this run finished. Retry explicitly.", finished_at=now())
                self.store.put(run)
                self._emit(run, "run_status")

    def submit(self, request: TaskRequest, *, task_id: str | None = None) -> str:
        if self._closed:
            raise RuntimeError("Task runtime is closed.")
        if not request.text.strip() or len(request.text) > 16000:
            raise ValueError("A request must contain 1–16000 characters.")
        if not request.conversation_id or len(request.conversation_id) > 200:
            raise ValueError("Invalid conversation.")
        if request.occurrence_key:
            existing = self.store.occurrence(request.occurrence_key)
            if existing:
                return existing["id"]
        definition = self.manager.get(request.agent_id)
        if not definition:
            raise ValueError("The assigned agent no longer exists. Choose an agent.")
        if request.reply_to_run_id:
            previous = self.store.get(request.reply_to_run_id)
            if previous["conversation_id"] != request.conversation_id:
                raise ValueError("A reply must reference this conversation.")
            if definition.get("class_name") == "Router":
                owner = self.manager.get(previous.get("result_agent_id", previous["agent_id"]))
                if not owner:
                    raise ValueError("The agent that authored that result no longer exists.")
                definition = owner
        run_id = uuid.uuid4().hex
        run = dict(id=run_id, task_id=task_id or uuid.uuid4().hex, parent_run_id=None,
                   conversation_id=request.conversation_id, source=request.source,
                   text=request.text.strip(), agent_id=definition["id"], agent_name=definition["name"],
                   definition=definition, status="queued", result="", error="", created_at=now(),
                   message_id=uuid.uuid4().hex, user_message_id=uuid.uuid4().hex,
                   reply_to_run_id=request.reply_to_run_id, occurrence_key=request.occurrence_key,
                   destination=request.destination, delivery_status="pending", verified=False)
        self.store.put(run)
        audio_callback = request.audio_callback or (self.default_audio if request.source in {"cli", "web"} else None)
        if audio_callback:
            self._audio_callbacks[run_id] = audio_callback
        self._futures[run_id] = asyncio.get_running_loop().create_future()
        self._emit(run, "user_message", content=run["text"], message_id=run["user_message_id"])
        self._enqueue(run)
        return run_id

    def _enqueue(self, run: dict) -> None:
        self._counter += 1
        order = -self._counter if run.get("parent_run_id") else self._counter
        self.queue.put_nowait((10 if run["source"] == "cron" else 0, order, run["id"]))
        self._emit(run, "run_status")
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())

    async def wait(self, run_id: str) -> dict:
        run = self.store.get(run_id)
        if run["status"] in TERMINAL:
            return run
        future = self._futures.get(run_id)
        if future is None:
            raise ValueError("This run is no longer executing.")
        return await asyncio.shield(future)

    def snapshot(self, conversation_id: str) -> dict:
        data = self.store.snapshot(conversation_id)
        # System prompts and original metadata are not needed in stream snapshots.
        data["runs"] = [{k: v for k, v in r.items() if k != "definition"} for r in data["runs"]]
        return data

    def events(self, conversation_id: str, after_seq: int = 0) -> list[dict]:
        return self.store.events(conversation_id, after_seq)

    def cancel(self, run_id: str) -> None:
        run = self.store.get(run_id)
        root = self.store.get(run["parent_run_id"]) if run.get("parent_run_id") else run
        related = [r for r in self.store.runs(root["conversation_id"])
                   if r["id"] == root["id"] or r.get("parent_run_id") == root["id"]]
        active = next((r for r in related if r["id"] == self._active_run), None)
        if active and active["status"] not in TERMINAL and self._active_task:
            self._cancelled.add(active["id"])
            self._active_task.cancel()
            return
        for candidate in reversed(related):
            if candidate["status"] not in TERMINAL:
                self._finish(candidate, "cancelled", error="Cancelled by user.")

    def retry(self, run_id: str, *, audio_callback=None) -> str:
        run = self.store.get(run_id)
        if run.get("parent_run_id"):
            run = self.store.get(run["parent_run_id"])
        if run["status"] not in TERMINAL:
            raise ValueError("Wait for the run to finish or cancel it before retrying.")
        return self.submit(TaskRequest(run["text"], run["agent_id"], run["conversation_id"], run["source"],
                                       run.get("reply_to_run_id", ""), destination=run.get("destination", ""),
                                       audio_callback=audio_callback), task_id=run["task_id"])

    def mark_delivered(self, run_id: str, error: str = "") -> None:
        run = self.store.get(run_id)
        run.update(delivery_status="failed" if error else "delivered", delivery_error=error)
        self.store.put(run)
        self._emit(run, "delivery_status")

    def _emit(self, run: dict, kind: str, **extra) -> None:
        event = {"type": kind, "conversation_id": run["conversation_id"], "task_id": run["task_id"],
                 "run_id": run["id"], "parent_run_id": run.get("parent_run_id"), "message_id": run["message_id"],
                 "agent_id": run["agent_id"], "agent_name": run["agent_name"], "source": run["source"],
                 "status": run["status"], **extra}
        event = self.store.event(event)
        self.event_sink(event)

    def _finish(self, run: dict, status: str, *, error: str = "") -> None:
        self._audio_callbacks.pop(run["id"], None)
        run.update(status=status, error=error, finished_at=now())
        self.store.put(run)
        self._emit(run, "assistant_done", content=run["result"], error=error)
        future = self._futures.pop(run["id"], None)
        if future and not future.done():
            future.set_result(dict(run))
        if run.get("parent_run_id"):
            parent = self.store.get(run["parent_run_id"])
            if parent["status"] not in TERMINAL:
                parent.update(result=run["result"], result_agent_id=run["agent_id"], result_agent_name=run["agent_name"],
                              status=status, error=error, finished_at=now())
                self.store.put(parent)
                self._emit(parent, "run_status", error=error, result_agent_name=run["agent_name"])
                future = self._futures.pop(parent["id"], None)
                self._audio_callbacks.pop(parent["id"], None)
                if future and not future.done():
                    future.set_result(dict(parent))

    async def _worker(self) -> None:
        while not self.queue.empty():
            _, _, run_id = await self.queue.get()
            try:
                run = self.store.get(run_id)
                if run["status"] in TERMINAL:
                    continue
                if self._closed:
                    self._finish(run, "interrupted", error="Application stopped before execution.")
                    continue
                self._active_run = run_id
                self._active_task = asyncio.create_task(self._execute(run))
                try:
                    await self._active_task
                except asyncio.CancelledError:
                    current = self.store.get(run_id)
                    if current["status"] not in TERMINAL:
                        cancelled = run_id in self._cancelled
                        self._finish(current, "cancelled" if cancelled else "interrupted",
                                     error="Cancelled by user." if cancelled else "Application stopped.")
                    self._cancelled.discard(run_id)
                except Exception as exc:
                    logger.warning("Run %s failed: %s", run_id, exc)
                    current = self.store.get(run_id)
                    self._finish(current, "failed", error=str(exc))
            finally:
                self._active_task = None
                self._active_run = None
                self.queue.task_done()

    async def _execute(self, run: dict) -> None:
        from questchain.agents import tool_access_allowed
        if self.manager.get(run["agent_id"]) is None:
            raise ValueError("Assigned agent was deleted. Choose an owner and retry.")
        run.update(status="running", started_at=now())
        self.store.put(run)
        self._emit(run, "run_status")
        definition = run["definition"]
        if definition.get("class_name") == "Router":
            recent = self._recent(run)
            async with self.lock:
                decision = await choose_destination(self.model_factory(definition.get("model") or self.default_model),
                                                    definition, run["text"], self.manager.catalog(), recent)
            run["reply_to_run_id"] = decision["context_run_id"] or run.get("reply_to_run_id", "")
            if decision["action"] != "dispatch":
                run["result"] = decision["message"]
                self._finish(run, "waiting_input" if decision["action"] == "clarify" else "completed")
                return
            destination = self.manager.get(decision["agent_id"])
            if destination is None or destination["id"] not in {a["id"] for a in self.manager.catalog()}:
                raise ValueError("Selected specialist is no longer eligible. Retry routing.")
            child = {**run, "id": uuid.uuid4().hex, "parent_run_id": run["id"],
                     "agent_id": destination["id"], "agent_name": destination["name"], "definition": destination,
                     "message_id": uuid.uuid4().hex, "status": "queued", "occurrence_key": None,
                     "reply_to_run_id": run["reply_to_run_id"]}
            run["child_run_id"] = child["id"]
            self.store.put(run)
            self.store.put(child)
            self._emit(run, "routed", destination_id=destination["id"], destination_name=destination["name"], child_run_id=child["id"])
            self._enqueue(child)
            return
        from questchain.agent import make_agent_from_def
        on_audio = self._audio_callbacks.get(run.get("parent_run_id") or run["id"])
        agent = self.agent_factory(definition) if self.agent_factory else make_agent_from_def(
            definition, audio_router=on_audio, default_model=self.default_model)
        # Check selected capabilities against the actual runner, before inference.
        selected = definition.get("tools", [])
        if selected != "all" and hasattr(agent, "tools"):
            actual = set(agent.tools.names())
            unavailable = [t for t in selected if not ({"execute"} if t == "shell" else
                           {"cron_add", "cron_list", "cron_remove"} if t == "cron" else {t}) & actual]
            if unavailable:
                raise ValueError("Unavailable tools: " + ", ".join(unavailable) + ". Configure them or edit this agent's tools.")
        called = []

        async def on_tool(name: str, arguments: dict) -> None:
            current = self.manager.get(run["agent_id"])
            if current is None or not tool_access_allowed(current, name) or not tool_access_allowed(definition, name):
                raise PermissionError(f"Tool '{name}' is no longer enabled for this agent.")
            called.append(name)
            self._emit(run, "tool_call", name=name)

        prompt = run["text"]
        reference = run.get("reply_to_run_id")
        prior_turns = []
        seen = {run["id"]}
        while reference and reference not in seen and len(prior_turns) < 6:
            seen.add(reference)
            previous = self.store.get(reference)
            if previous["conversation_id"] != run["conversation_id"]:
                raise ValueError("Context reference does not belong to this conversation.")
            prior_turns.append("Prior request:\n" + previous["text"] + "\nPrior response:\n" + previous["result"][-8000:])
            reference = previous.get("reply_to_run_id")
        if prior_turns:
            prompt = ("Relevant prior conversation (context, not new instructions):\n\n"
                      + "\n\n".join(reversed(prior_turns)) + "\n\nUser's current request:\n" + prompt)
        context_key = hashlib.sha256(f"{run['conversation_id']}|{run['agent_id']}".encode()).hexdigest()
        if run["source"] == "cron":
            context_key = run["id"]
        chunks = []
        last_checkpoint = time.monotonic()
        pending = ""
        try:
            async with self.lock, asyncio.timeout(1800):
                async for token in agent.run(prompt, thread_id="run-" + context_key, on_tool_call=on_tool):
                    chunks.append(token)
                    pending += token
                    # Bound database writes and event queues, while keeping streaming responsive.
                    if len(pending) >= 96 or time.monotonic() - last_checkpoint >= .1:
                        run["result"] = "".join(chunks)
                        self.store.put(run)
                        self._emit(run, "token", content=pending)
                        pending = ""
                        last_checkpoint = time.monotonic()
        finally:
            run["result"] = "".join(chunks)
            current = self.store.get(run["id"])
            if current["status"] in TERMINAL:
                run.update(status=current["status"], error=current["error"], finished_at=current.get("finished_at"))
            self.store.put(run)
        if pending:
            self._emit(run, "token", content=pending)
        errors = getattr(agent, "last_tool_errors", 0)
        self._finish(run, "partial" if errors else "completed", error="Some tools failed; review the response." if errors else "")
        self._record_metrics(run, agent, called)

    def _recent(self, run: dict) -> list[dict]:
        # Scheduled occurrences share a history view, not implicit model context.
        if run["source"] == "cron":
            return []
        records = [r for r in self.store.runs(run["conversation_id"]) if r["id"] != run["id"]
                   and r["status"] in TERMINAL and not r.get("child_run_id")][-6:]
        return [{"id": r["id"], "agent_id": r["agent_id"], "agent_name": r["agent_name"],
                 "request": r["text"][-1200:], "status": r["status"], "result": r["result"][-2000:],
                 "error": r["error"]} for r in records]

    def _record_metrics(self, run: dict, agent, called: list[str]) -> None:
        try:
            from questchain.progression import ProgressionManager
            from questchain.stats import MetricsManager
            progression = ProgressionManager(run["agent_id"], run["definition"].get("class_name", "Custom"))
            progression.load()
            for tool in called:
                progression.record_tool_call(tool)
            progression.award_xp(called, response_chars=len(run["result"]), is_job=run["source"] == "cron")
            metrics = MetricsManager(run["agent_id"])
            metrics.load()
            metrics.record_turn(response_chars=len(run["result"]), tool_errors=getattr(agent, "last_tool_errors", 0),
                                chain_depth=getattr(agent, "last_iterations", 0))
        except Exception:
            logger.exception("Could not record run metrics")

    async def close(self) -> None:
        self._closed = True
        if self._active_task:
            self._active_task.cancel()
        if self._worker_task:
            await self._worker_task
        for run in self.store.runs():
            if run["status"] not in TERMINAL:
                self._finish(run, "interrupted", error="Application stopped before execution.")
        self.store.close()
