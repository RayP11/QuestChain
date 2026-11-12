"""Aggregate limits through actual engine dispatch and inline runtime delegation."""
import asyncio
import os
import subprocess
import sys

import pytest

from questchain import config
from questchain.agents import AgentManager
from questchain.engine import context
from questchain.engine.agent import Agent
from questchain.engine.budget import ToolBudgetExceeded, ToolCallBudget
from questchain.engine.context import ContextManager
from questchain.engine.model import Chunk
from questchain.engine.tools import make_registry, tool
from questchain.runtime import TaskRequest, TaskRuntime


class Model:
    num_ctx = 1_000_000

    def __init__(self, *steps):
        self.steps = iter(steps)
        self.calls = 0

    async def chat_stream(self, messages, tools=None):
        self.calls += 1
        step = next(self.steps)
        if isinstance(step, list):
            yield Chunk(done=True, tool_calls=step)
        else:
            yield Chunk(done=True, text=step)


def call(name="write_file", **args):
    return {"name": name, "args": args}


def delegate(worker):
    return call("delegate_to_agent", agent_id=worker["id"], task="Do bounded work")


async def collect(agent, thread="test", **kwargs):
    return "".join([token async for token in agent.run("Work", thread, **kwargs)])


def saved_tools(thread):
    return [m["content"] for m in ContextManager(thread).messages if m["role"] == "tool"]


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "QUESTCHAIN_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(context, "QUESTCHAIN_DATA_DIR", tmp_path / "data")


@pytest.fixture
async def harness(tmp_path, monkeypatch):
    manager = AgentManager()
    manager.update(manager.get_active_id(), tools=["write_file"])
    worker = manager.add("Worker", None, "Work", ["write_file"],
                         when_to_call="Bounded work", routable=True)
    runtimes = []

    def build(limit, main_steps, worker_steps, fn):
        monkeypatch.setattr(config, "MAX_TOOL_CALLS", limit)
        models = []

        def factory(definition):
            model = Model(*(main_steps if definition["kind"] == "main" else worker_steps))
            models.append(model)
            return Agent(model, make_registry(fn), "Work")

        runtime = TaskRuntime(manager, default_model="fake", agent_factory=factory,
                              path=tmp_path / f"runs-{len(runtimes)}.sqlite3", event_sink=lambda e: None)
        runtimes.append(runtime)
        return runtime, models

    yield manager, worker, build
    for runtime in runtimes:
        await runtime.close()


@pytest.mark.parametrize("value", [0, -1, 10_001, True, False, 1.5, "10", None])
def test_invalid_budget_cannot_disable_limit(value):
    with pytest.raises(ValueError, match="1 to 10000"):
        ToolCallBudget(value)


@pytest.mark.parametrize("value", ["0", "-1", "10001", "", "no", "1.5"])
def test_invalid_environment_fails_startup(value, tmp_path):
    env = {**os.environ, "QUESTCHAIN_MAX_TOOL_CALLS": value,
           "QUESTCHAIN_DATA_DIR": str(tmp_path), "QUESTCHAIN_WORKSPACE_DIR": str(tmp_path)}
    result = subprocess.run([sys.executable, "-c", "import questchain.config"],
                            env=env, capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode != 0
    assert "QUESTCHAIN_MAX_TOOL_CALLS must be an integer from 1 to 10000" in result.stderr


async def test_batch_stops_before_side_effect_and_records_unstarted_calls():
    executed = []

    @tool
    async def write_file(number: int):
        executed.append(number)
        return f"saved {number}"

    agent = Agent(Model([call(number=n) for n in range(5)], "Done"), make_registry(write_file), "Work")
    budget = ToolCallBudget(2)
    callbacks = []

    async def on_tool(name, args):
        callbacks.append(args["number"])

    with pytest.raises(ToolBudgetExceeded):
        await collect(agent, tool_budget=budget, on_tool_call=on_tool)
    assert executed == callbacks == [0, 1]
    assert budget.used == 2
    results = saved_tools("test")
    assert results[:2] == ["saved 0", "saved 1"]
    assert len(results) == 5
    assert all("not started" in r and "budget exhausted" in r and "unknown" not in r for r in results[2:])
    assert agent.model.calls == 1


@pytest.mark.parametrize("count", [1, 128, 256])
async def test_exact_limit_and_configured_long_workload_can_finish(count, monkeypatch):
    executed = []

    @tool
    async def write_file():
        executed.append(True)
        return "saved"

    monkeypatch.setattr(config, "MAX_TOOL_CALLS", count)
    agent = Agent(Model([call() for _ in range(count)], "Final synthesis"), make_registry(write_file), "Work")
    assert await collect(agent) == "Final synthesis"
    assert len(executed) == count
    assert agent.model.calls == 2


async def test_failures_unknown_tools_and_bad_arguments_are_not_refunded():
    @tool
    async def write_file():
        raise TimeoutError("tool timed out")

    agent = Agent(Model([call(), call("missing"), call(bad=True), call()]), make_registry(write_file), "Work")
    budget = ToolCallBudget(3)
    with pytest.raises(ToolBudgetExceeded):
        await collect(agent, tool_budget=budget)
    results = saved_tools("test")
    assert "timed out" in results[0]
    assert "unknown tool" in results[1]
    assert "unexpected keyword" in results[2]
    assert "not started" in results[3]
    assert budget.used == 3


async def test_permission_rejection_is_not_budget_exhaustion_or_unknown():
    executed = []

    @tool
    async def write_file():
        executed.append(True)

    async def deny(name, args):
        raise PermissionError("disabled")

    budget = ToolCallBudget(3)
    agent = Agent(Model([call(), call()]), make_registry(write_file), "Work")
    with pytest.raises(PermissionError, match="disabled"):
        await collect(agent, tool_budget=budget, on_tool_call=deny)
    assert budget.used == 1 and not executed
    assert all("not started" in r and "unknown" not in r and "budget" not in r for r in saved_tools("test"))


async def test_nested_engine_calls_share_budget_and_propagate_through_tool_wrappers():
    budget = ToolCallBudget(3)
    executed = []

    @tool
    async def write_file():
        executed.append(True)
        return "saved"

    @tool
    async def inner():
        child = Agent(Model([call(), call()]), make_registry(write_file), "Child")
        return await collect(child, "inner", tool_budget=budget)

    @tool
    async def outer():
        child = Agent(Model([call("inner")]), make_registry(inner), "Child")
        return await collect(child, "outer", tool_budget=budget)

    agent = Agent(Model([call("outer"), call("outer")]), make_registry(outer), "Root")
    with pytest.raises(ToolBudgetExceeded):
        await collect(agent, tool_budget=budget)
    assert budget.used == 3 and executed == [True]
    assert "Delegated execution stopped" in saved_tools("test")[0]
    assert "not started" in saved_tools("test")[1]
    assert "not started" in saved_tools("inner")[1]


async def test_concurrent_children_cannot_oversubscribe_shared_budget():
    budget = ToolCallBudget(3)
    started = asyncio.Event()
    release = asyncio.Event()
    executed = []

    @tool
    async def write_file():
        executed.append(True)
        if len(executed) == 3:
            started.set()
        await release.wait()
        return "saved"

    async def child(index):
        agent = Agent(Model([call()], "Done"), make_registry(write_file), "Child")
        return await collect(agent, str(index), tool_budget=budget)

    tasks = [asyncio.create_task(child(i)) for i in range(10)]
    try:
        await asyncio.wait_for(started.wait(), 2)
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 2)
        assert results.count("Done") == 3
        assert sum(isinstance(r, ToolBudgetExceeded) for r in results) == 7
        assert len(executed) == budget.used == 3
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)










async def test_standalone_runs_get_fresh_independent_budgets(monkeypatch):
    monkeypatch.setattr(config, "MAX_TOOL_CALLS", 1)
    executed = []

    @tool
    async def write_file():
        executed.append(True)
        return "saved"

    agents = [Agent(Model([call()], "Done", [call()], "Done"), make_registry(write_file), "Work")
              for _ in range(2)]
    for _ in range(2):
        assert await asyncio.gather(*(collect(a, str(i)) for i, a in enumerate(agents))) == ["Done", "Done"]
    assert len(executed) == 4




async def test_exhaustion_does_not_cancel_already_admitted_concurrent_work():
    budget = ToolCallBudget(1)
    started, release, cleaned = asyncio.Event(), asyncio.Event(), asyncio.Event()

    @tool
    async def write_file():
        started.set()
        try:
            await release.wait()
            return "saved"
        finally:
            cleaned.set()

    first = Agent(Model([call()], "Done"), make_registry(write_file), "Worker")
    second = Agent(Model([call()]), make_registry(write_file), "Worker")
    task = asyncio.create_task(collect(first, "first", tool_budget=budget))
    try:
        await asyncio.wait_for(started.wait(), 2)
        with pytest.raises(ToolBudgetExceeded):
            await collect(second, "second", tool_budget=budget)
        assert not task.done() and not cleaned.is_set()
        release.set()
        assert await asyncio.wait_for(task, 2) == "Done"
        assert cleaned.is_set() and budget.used == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)




@pytest.mark.parametrize("source", ["cli", "cron"])
async def test_direct_owner_budget_and_retry_are_independent(harness, source):
    manager, worker, build = harness
    manager.set_active(worker["id"])
    executed = []
    @tool
    async def write_file():
        executed.append(True)
        return "saved"
    runtime, models = build(1, ["Main must not run"], [[call(), call()], "Done"], write_file)
    first = runtime.submit(TaskRequest("Work", worker["id"], "quest", source))
    result = await runtime.wait(first)
    assert result["status"] == "failed" and "budget exhausted" in result["error"]
    assert result["tool_calls_used"] == 1 and len(executed) == 1
    assert len(models) == 1 and len(runtime.store.runs()) == 1
    second = await runtime.wait(runtime.retry(first))
    assert second["status"] == "failed" and second["tool_calls_used"] == 1
    assert len(executed) == 2 and second["task_id"] == result["task_id"]
    assert not runtime.lock.locked()


async def test_scheduled_owner_exact_budget_needs_no_delegation_overhead(harness):
    _, worker, build = harness
    executed = []
    @tool
    async def write_file():
        executed.append(True)
        return "saved"
    runtime, models = build(1, ["Main must not run"], [[call()], "Owner done"], write_file)
    result = await runtime.wait(runtime.submit(TaskRequest("Work", worker["id"], "quest", "cron")))
    assert result["status"] == "completed" and result["result"] == "Owner done"
    assert result["tool_calls_used"] == 1 and len(executed) == 1
    assert len(models) == 1 and models[0].calls == 2


async def test_runtime_delegation_attempt_is_rejected_and_budgeted(harness):
    manager, worker, build = harness
    @tool
    async def write_file():
        return "must not run"
    runtime, models = build(3, [[delegate(worker)]], [], write_file)
    result = await runtime.wait(runtime.submit(TaskRequest("Work", manager.get_active_id(), "chat")))
    assert result["status"] == "failed"
    assert "delegation is disabled" in result["error"]
    assert result["tool_calls_used"] == 1
    assert len(models) == 1 and len(runtime.store.runs()) == 1
