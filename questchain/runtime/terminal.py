"""Terminal rendering of the same attributed events consumed by the web UI."""
import asyncio

from rich.live import Live
from rich.markdown import Markdown

from questchain.gateway.events import get_bus
from questchain.runtime import TaskRequest


async def run_terminal_task(runtime, request: TaskRequest | None, console, *, run_id=None) -> dict:
    bus = get_bus()
    queue = bus.subscribe()
    run_id = run_id or runtime.submit(request)
    live = None
    response = ""
    current_message = None
    waiter = asyncio.create_task(runtime.wait(run_id))
    try:
        while not waiter.done() or not queue.empty():
            try:
                event = await asyncio.wait_for(queue.get(), .1)
            except asyncio.TimeoutError:
                continue
            if event.get("run_id") != run_id and event.get("parent_run_id") != run_id:
                continue
            if event["type"] == "routed":
                console.print(f"{event['agent_name']} → {event['destination_name']}", style="cyan", markup=False)
            elif event["type"] == "token":
                if current_message != event["message_id"]:
                    if live:
                        live.stop()
                    console.print(event["agent_name"], style="bold blue", markup=False)
                    response = ""
                    current_message = event["message_id"]
                    live = Live(Markdown(""), console=console, refresh_per_second=8)
                    live.start()
                response += event["content"]
                live.update(Markdown(response))
            elif event["type"] == "tool_call":
                console.print(f"{event['agent_name']} · Using {event['name']}", style="dim", markup=False)
        result = await waiter
        if live:
            live.update(Markdown(result["result"]))
        elif result["result"]:
            console.print(result.get("result_agent_name", result["agent_name"]), style="bold blue", markup=False)
            console.print(Markdown(result["result"]))
        if result["error"]:
            console.print(f"{result['status']}: {result['error']}", style="yellow", markup=False)
        runtime.mark_delivered(run_id)
        return result
    except (asyncio.CancelledError, KeyboardInterrupt):
        runtime.cancel(run_id)
        raise
    finally:
        if live:
            live.stop()
        bus.unsubscribe(queue)
        if not waiter.done():
            waiter.cancel()
