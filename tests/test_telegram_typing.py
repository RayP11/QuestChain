import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from questchain import telegram


def delivery():
    message = SimpleNamespace(reply_chat_action=AsyncMock(), reply_text=AsyncMock())
    update = SimpleNamespace(message=message, effective_chat=SimpleNamespace(send_action=message.reply_chat_action))
    runtime = SimpleNamespace(wait=AsyncMock(return_value=dict(agent_name="Perseus", status="completed", result="Ready.", error="")),
                              mark_delivered=Mock())
    return runtime, update


async def test_typing_starts_before_even_an_immediate_response():
    runtime, update = delivery()

    async def reply(*args, **kwargs):
        assert update.message.reply_chat_action.await_count >= 1

    update.message.reply_text.side_effect = reply
    await telegram._deliver_runtime_result(runtime, "run", update)
    runtime.mark_delivered.assert_called_once_with("run")


async def test_typing_refreshes_while_working_then_stops(monkeypatch):
    monkeypatch.setattr(telegram, "_TYPING_INTERVAL", 0.01, raising=False)
    runtime, update = delivery()
    twice = asyncio.Event()

    async def action(*args, **kwargs):
        if update.message.reply_chat_action.await_count >= 2:
            twice.set()

    update.message.reply_chat_action.side_effect = action
    result = runtime.wait.return_value

    async def wait(run_id):
        await asyncio.wait_for(twice.wait(), 0.5)
        return result

    runtime.wait.side_effect = wait
    await telegram._deliver_runtime_result(runtime, "run", update)
    runtime.mark_delivered.assert_called_once_with("run")
    count = update.message.reply_chat_action.await_count
    await asyncio.sleep(0.03)
    assert update.message.reply_chat_action.await_count == count


async def test_typing_errors_are_visible_but_do_not_block_the_reply(caplog):
    runtime, update = delivery()
    update.message.reply_chat_action.side_effect = RuntimeError("a URL containing a credential")
    await telegram._deliver_runtime_result(runtime, "run", update)
    runtime.mark_delivered.assert_called_once_with("run")
    assert "typing" in caplog.text.lower() and "RuntimeError" in caplog.text
    assert "credential" not in caplog.text


async def test_typing_does_not_cancel_a_slow_successful_telegram_request(caplog):
    runtime, update = delivery()
    completed = asyncio.Event()

    async def slow_action(*args, **kwargs):
        await asyncio.sleep(1.7)
        completed.set()

    update.message.reply_chat_action.side_effect = slow_action
    result = runtime.wait.return_value

    async def wait(run_id):
        await asyncio.wait_for(completed.wait(), 2.5)
        return result

    runtime.wait.side_effect = wait
    await telegram._deliver_runtime_result(runtime, "run", update)
    assert completed.is_set(), "A healthy Telegram typing request was cancelled too soon"
    assert not caplog.records


async def test_slow_typing_never_delays_a_ready_response():
    runtime, update = delivery()
    stopped = asyncio.Event()

    async def stuck(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    update.message.reply_chat_action.side_effect = stuck
    await asyncio.wait_for(telegram._deliver_runtime_result(runtime, "run", update), 0.5)
    runtime.mark_delivered.assert_called_once_with("run")
    assert stopped.is_set()


async def test_repeated_typing_timeouts_log_once_and_recover(monkeypatch, caplog):
    monkeypatch.setattr(telegram, "_TYPING_TIMEOUT", 0.01)
    monkeypatch.setattr(telegram, "_TYPING_INTERVAL", 0.01)
    monkeypatch.setattr(telegram, "_TYPING_BACKOFF_MAX", 0.04, raising=False)
    caplog.set_level("INFO", logger=telegram.__name__)
    runtime, update = delivery()
    recovered = asyncio.Event()
    attempts = []

    async def action(*args, **kwargs):
        attempts.append(asyncio.get_running_loop().time())
        if len(attempts) <= 3:
            await asyncio.Event().wait()
        recovered.set()

    update.message.reply_chat_action.side_effect = action
    result = runtime.wait.return_value

    async def wait(run_id):
        await asyncio.wait_for(recovered.wait(), 1)
        return result

    runtime.wait.side_effect = wait
    await telegram._deliver_runtime_result(runtime, "run", update)
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "TimeoutError" in warnings[0].message
    assert "recovered" in caplog.text.lower()
    assert attempts[3] - attempts[2] >= 0.04  # Retry delay grows after repeated failures.
    runtime.mark_delivered.assert_called_once_with("run")


async def test_stuck_typing_request_times_out_and_response_is_delivered(monkeypatch):
    monkeypatch.setattr(telegram, "_TYPING_TIMEOUT", 0.01)
    runtime, update = delivery()
    timed_out = asyncio.Event()

    async def stuck(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            timed_out.set()
            raise

    update.message.reply_chat_action.side_effect = stuck
    result = runtime.wait.return_value

    async def wait(run_id):
        await timed_out.wait()
        return result

    runtime.wait.side_effect = wait
    await asyncio.wait_for(telegram._deliver_runtime_result(runtime, "run", update), 0.5)
    runtime.mark_delivered.assert_called_once_with("run")


async def test_cancellation_cleans_up_typing(monkeypatch):
    monkeypatch.setattr(telegram, "_TYPING_INTERVAL", 0.01)
    runtime, update = delivery()
    entered = asyncio.Event()

    async def wait(run_id):
        entered.set()
        await asyncio.Event().wait()

    runtime.wait.side_effect = wait
    task = asyncio.create_task(telegram._deliver_runtime_result(runtime, "run", update))
    await asyncio.wait_for(entered.wait(), 0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    count = update.message.reply_chat_action.await_count
    await asyncio.sleep(0.03)
    assert update.message.reply_chat_action.await_count == count


async def test_typing_uses_the_incoming_message_topic_and_business_connection():
    from datetime import datetime, timezone
    from telegram import Chat, Message
    message = Message(message_id=7, date=datetime.now(timezone.utc), chat=Chat(101, "private"),
                      message_thread_id=42, is_topic_message=True, business_connection_id="connection")
    bot = SimpleNamespace(send_chat_action=AsyncMock())
    message.set_bot(bot)
    async with telegram._typing(message):
        pass
    args = bot.send_chat_action.call_args.kwargs
    assert args["chat_id"] == 101
    assert args["message_thread_id"] == 42
    assert args["business_connection_id"] == "connection"
