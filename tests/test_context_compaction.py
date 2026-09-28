"""Context summaries stay durable and preserve valid tool conversations."""
import copy

import pytest

from questchain.engine.agent import Agent
from questchain.engine.context import ContextManager
from questchain.engine.model import Chunk
from questchain.engine.tools import make_registry, tool


@pytest.fixture(autouse=True)
def isolated_context(monkeypatch, tmp_path):
    from questchain.engine import context
    monkeypatch.setattr(context, "QUESTCHAIN_DATA_DIR", tmp_path)


async def test_compaction_keeps_tool_calls_with_all_results():
    context = ContextManager("paired")
    context.extend([
        {"role": "user", "content": "Earlier request"},
        {"role": "assistant", "content": "Earlier answer"},
        {"role": "assistant", "content": "Reading files", "tool_calls": [
            {"function": {"name": "read_file", "arguments": {"path": "/notes.md"}}}]},
        {"role": "tool", "name": "read_file", "content": "Notes"},
        {"role": "assistant", "content": "Notes read"},
        {"role": "user", "content": "Follow-up"},
        {"role": "assistant", "content": "Follow-up answer"},
        {"role": "user", "content": "Latest request"},
        {"role": "assistant", "content": "Latest answer"},
    ])
    preserved = context.messages[2:]

    class Model:
        async def summarize(self, text):
            assert "Earlier request" in text
            assert "Notes" not in text
            return "Earlier request answered."

    await context.compact(Model())
    assert context.messages[1:] == preserved
    assert ContextManager("paired").messages == context.messages


async def test_empty_summary_does_not_replace_existing_history():
    context = ContextManager("empty-summary")
    context.extend([{"role": "user", "content": f"Message {i}"} for i in range(10)])
    context.save()
    original = context.messages

    class Model:
        async def summarize(self, text):
            return "  "

    with pytest.raises(RuntimeError, match="empty history summary"):
        await context.compact(Model())
    assert context.messages == original
    assert ContextManager("empty-summary").messages == original


async def test_tool_loop_compacts_before_the_next_model_call():
    @tool
    async def read_notes():
        """Read notes."""
        return "A note about the project. " * 60

    class Model:
        num_ctx = 2048

        def __init__(self):
            self.calls = []
            self.summaries = []

        async def chat_stream(self, messages, tools=None):
            self.calls.append(copy.deepcopy(messages))
            if len(self.calls) <= 6:
                yield Chunk(done=True, tool_calls=[{"name": "read_notes", "args": {}}])
            else:
                yield Chunk(text="Finished reading the notes.", done=True)

        async def summarize(self, text):
            self.summaries.append(text)
            return "The user requested a review of the project notes; several notes were read."

    model = Model()
    agent = Agent(model, make_registry(read_notes), "Review project notes.")
    response = "".join([token async for token in agent.run("Review the project notes", "tool-loop")])
    assert response == "Finished reading the notes."
    assert model.summaries
    assert any("[Earlier conversation" in str(call) for call in model.calls)
    for messages in model.calls:
        for index, message in enumerate(messages):
            if message["role"] == "tool":
                assert messages[index - 1].get("tool_calls") or messages[index - 1]["role"] == "tool"
