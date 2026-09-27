"""FastAPI WebSocket gateway server for the QuestChain web UI."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, Response

from questchain.gateway.events import get_bus

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from questchain.agents import AgentManager
    from questchain.progression import ProgressionManager
    from questchain.stats import MetricsManager

app = FastAPI(docs_url=None, redoc_url=None)

_MAX_WS_MSG_BYTES = 512_000  # 512 KB per WebSocket message
_MAX_CHAT_CHARS   = 16_000   # max characters in a single chat message
_MAX_SYSTEM_PROMPT = 4_000   # max characters in a system prompt
_RATE_LIMIT_MSGS  = 30       # max messages per window
_RATE_LIMIT_SECS  = 10.0     # rate limit window in seconds

_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "   # unsafe-inline needed for <style> block
    "img-src 'self' data:; "
    "connect-src 'self' ws: wss:;"
)

# Optional shared secret loaded at startup (set QUESTCHAIN_WS_TOKEN in .env).
_ws_token: str = ""

# Set by start_gateway_server() so validators know what the server is bound to.
_LOCALHOST_NAMES: frozenset[str] = frozenset(("127.0.0.1", "localhost", "::1"))
_bound_host: str = "127.0.0.1"
_bound_port: int = 8765


def _is_loopback_bind() -> bool:
    return _bound_host in _LOCALHOST_NAMES


def _host_allowed(hostname: str) -> bool:
    """Return True if a Host/Origin hostname is permitted to reach this server."""
    hostname = hostname.lower().strip("[]")  # normalise IPv6 brackets
    if _is_loopback_bind():
        return hostname in _LOCALHOST_NAMES
    if _bound_host == "0.0.0.0":
        return True  # user explicitly exposed the server on all interfaces
    return hostname in (*_LOCALHOST_NAMES, _bound_host)


@app.middleware("http")
async def _security_headers(request: Request, call_next) -> Response:
    # DNS rebinding protection: reject requests whose Host header doesn't match
    # the address this server is bound to.
    host_header = request.headers.get("host", "")
    hostname = host_header.split(":")[0]
    if not _host_allowed(hostname):
        return Response("Misdirected Request", status_code=421)

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = _CSP
    response.headers["Referrer-Policy"] = "no-referrer"
    return response

# Shared state — set by CLI at startup via setup()
_agent_manager: "AgentManager | None" = None
_progression: "ProgressionManager | None" = None
_metrics: "MetricsManager | None" = None
_web_queue: asyncio.Queue | None = None
_model_name: str = ""
_thread_id: str = ""
_runtime = None
_clients: dict[int, dict] = {}


def update_thread_id(tid: str) -> None:
    global _thread_id
    _thread_id = tid
    get_bus().publish_nowait({"type": "settings", **_settings_payload()})


def setup(
    agent_manager: "AgentManager",
    progression: "ProgressionManager | None",
    metrics: "MetricsManager | None",
    web_queue: asyncio.Queue,
    model_name: str = "",
    runtime=None,
) -> None:
    global _agent_manager, _progression, _metrics, _web_queue, _model_name, _runtime
    _agent_manager = agent_manager
    _progression = progression
    _metrics = metrics
    _web_queue = web_queue
    _model_name = model_name
    _runtime = runtime


def update_progression(progression: "ProgressionManager | None") -> None:
    global _progression
    _progression = progression


def update_metrics(metrics: "MetricsManager | None") -> None:
    global _metrics
    _metrics = metrics


# ── HTML serving ──────────────────────────────────────────────────────────────

def _get_html() -> str:
    # Bundled static (installed package)
    bundled = Path(__file__).parent.parent / "static" / "index.html"
    if bundled.exists():
        return bundled.read_text(encoding="utf-8")
    # Dev fallback: repo root / web / index.html
    dev = Path(__file__).parent.parent.parent / "web" / "index.html"
    if dev.exists():
        return dev.read_text(encoding="utf-8")
    return "<h1>QuestChain UI — index.html not found</h1>"


def _get_app_js() -> str:
    p = Path(__file__).parent.parent / "static" / "app.js"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


@app.get("/")
async def serve_ui() -> HTMLResponse:
    html = _get_html()
    # Inject WS token into the meta tag so app.js can pick it up
    if _ws_token:
        html = html.replace(
            '<meta name="ws-token" content="">',
            f'<meta name="ws-token" content="{_ws_token}">',
        )
    return HTMLResponse(html)


@app.get("/app.js")
async def serve_app_js() -> Response:
    return Response(_get_app_js(), media_type="application/javascript")


@app.get("/markdown-it.min.js")
async def serve_markdown_parser() -> FileResponse:
    return FileResponse(Path(__file__).parent.parent / "static" / "markdown-it.min.js", media_type="application/javascript")


@app.get("/chat-markdown.js")
async def serve_chat_markdown() -> FileResponse:
    return FileResponse(Path(__file__).parent.parent / "static" / "chat-markdown.js", media_type="application/javascript")


_CLASS_IMAGES: dict[str, list[str]] = {
    "Router":    ["Pixel_idle.png", "evolve2.png", "draft-evolve-3.png"],
    "Custom":    ["Pixel_idle.png",                        "evolve2.png",                           "draft-evolve-3.png"],
    "Keeper":    ["Sage1.png",                             "Sage2.png",                             "Sage3.png"],
    "Explorer":  ["Explorer1-jukebox-bg-removed.png",      "Explorer2-jukebox-bg-removed.png",      "Explorer3-jukebox-bg-removed.png"],
    "Builder":   ["Arch1-jukebox-bg-removed.png",          "Arch2-jukebox-bg-removed.png",          "Arch3-jukebox-bg-removed.png"],
    "Planner":   ["Oracle1-jukebox-bg-removed.png",        "Oracle2-jukebox-bg-removed.png",        "Oracle3-jukebox-bg-removed.png"],
    "Scheduler": ["Scheduler1-jukebox-bg-removed.png",     "Scheduler2-jukebox-bg-removed.png",     "Scheduler3-jukebox-bg-removed.png"],
}


@app.get("/agent-image")
async def serve_agent_image(agent_id: str = Query(default="")) -> Response:
    """Serve the evolution image for an agent, resolved from live server data."""
    agent_def = None
    if _agent_manager:
        agent_def = _agent_manager.get(agent_id) if agent_id else _agent_manager.get_active()
    if not agent_def:
        return Response(status_code=404)

    class_name = agent_def.get("class_name", "Custom")
    from questchain.progression import ProgressionManager
    rec = ProgressionManager(agent_def["id"], class_name).load()
    level = rec.level

    stage = 0 if level <= 5 else (1 if level <= 10 else 2)
    images = _CLASS_IMAGES.get(class_name, _CLASS_IMAGES["Custom"])
    name = images[stage]
    static_dir = Path(__file__).resolve().parent.parent / "static"
    p = static_dir / name
    if p.exists():
        return FileResponse(str(p), media_type="image/png")
    return Response(status_code=404)


# ── WebSocket endpoint ─────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    # Block cross-site WebSocket hijacking: browsers always send Origin.
    # Non-browser clients (CLI tools) omit it — those are allowed through.
    origin = ws.headers.get("origin")
    if origin is not None:
        hostname = urlparse(origin).hostname or ""
        if not _host_allowed(hostname):
            await ws.close(code=1008)
            return

    # Optional token auth — enforced when QUESTCHAIN_WS_TOKEN is set.
    if _ws_token:
        provided = ws.query_params.get("token", "")
        if provided != _ws_token:
            await ws.close(code=1008)
            return

    await ws.accept()
    conversation = ws.query_params.get("conversation", "")
    if not re.fullmatch(r"web-[a-zA-Z0-9-]{1,100}", conversation):
        conversation = "web-" + uuid.uuid4().hex
    _clients[id(ws)] = {"conversation_id": conversation, "agent_id": _agent_manager.get_active_id() if _agent_manager else "default"}
    bus = get_bus()
    event_q = bus.subscribe()

    async def _send_loop() -> None:
        while True:
            event = await event_q.get()
            state = _clients[id(ws)]
            if event.get("conversation_id") and event["conversation_id"] != state["conversation_id"]:
                if state.get("cron_id") and event["conversation_id"] == "cron-" + state["cron_id"]:
                    await _send_cron_history(ws)
                continue
            if event["type"] == "resync_required" and _runtime:
                await _send_conversation(ws)
                await _send_cron_history(ws)
                continue
            try:
                await ws.send_json(event)
            except Exception:
                break

    async def _recv_loop() -> None:
        msg_count = 0
        window_start = asyncio.get_event_loop().time()
        while True:
            try:
                raw = await ws.receive_text()
            except (WebSocketDisconnect, RuntimeError):
                break
            if len(raw) > _MAX_WS_MSG_BYTES:
                continue
            # Rate limiting
            now = asyncio.get_event_loop().time()
            if now - window_start > _RATE_LIMIT_SECS:
                msg_count = 0
                window_start = now
            msg_count += 1
            if msg_count > _RATE_LIMIT_MSGS:
                logger.warning("WebSocket rate limit exceeded — dropping message")
                continue
            try:
                msg = json.loads(raw)
                await _handle_inbound(ws, msg)
            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                logger.debug("WebSocket: invalid JSON from client")
            except Exception as exc:
                logger.warning("WebSocket: error handling inbound message", exc_info=True)
                try:
                    await ws.send_json({"type": "error", "error": str(exc)})
                except (WebSocketDisconnect, RuntimeError):
                    break

    # Push current state to the new client immediately
    await _push_initial_state(ws)

    send_task = asyncio.create_task(_send_loop())
    recv_task = asyncio.create_task(_recv_loop())
    try:
        done, pending = await asyncio.wait(
            [send_task, recv_task], return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            try:
                await task
            except (WebSocketDisconnect, RuntimeError):
                pass
        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
    except (asyncio.CancelledError, Exception):
        pass
    finally:
        for t in [send_task, recv_task]:
            if not t.done():
                t.cancel()
        bus.unsubscribe(event_q)
        _clients.pop(id(ws), None)


# ── Initial state push ────────────────────────────────────────────────────────

async def _push_initial_state(ws: WebSocket) -> None:
    try:
        await ws.send_json({"type": "agents", **_agents_payload()})
        await ws.send_json({"type": "stats", **_stats_payload()})
        await ws.send_json({"type": "cron_jobs", "jobs": _list_cron_jobs()})
        await ws.send_json({"type": "settings", **_settings_payload()})
        if _runtime:
            await _send_conversation(ws)
    except Exception:
        logger.debug("Failed to push initial state to WebSocket client", exc_info=True)


# ── Input helpers ─────────────────────────────────────────────────────────────

def _sanitize_prompt(raw: str | None) -> str | None:
    """Truncate and strip control characters from a system prompt."""
    if not raw:
        return None
    cleaned = raw[:_MAX_SYSTEM_PROMPT]
    return cleaned if cleaned.strip() else None


# ── Inbound message handlers ──────────────────────────────────────────────────

async def _handle_inbound(ws: WebSocket, msg: dict) -> None:
    t = msg.get("type")

    if _runtime and t == "get_cron_history":
        state = _clients.get(id(ws))
        if state:
            cron_id = msg.get("cron_id", "")
            if cron_id and cron_id not in {job["id"] for job in _list_cron_jobs()}:
                raise ValueError("Cron job not found.")
            state["cron_id"] = cron_id
            await _send_cron_history(ws)
        return

    if _runtime and t in {"chat", "switch_agent", "new_thread", "get_conversation", "cancel_run", "retry_run"}:
        from questchain.runtime import TaskRequest
        state = _clients.setdefault(id(ws), {"conversation_id": "web-" + uuid.uuid4().hex,
                                              "agent_id": _agent_manager.get_active_id()})
        try:
            if t == "chat":
                agent_id = msg.get("agent_id") or state["agent_id"]
                run_id = _runtime.submit(TaskRequest(
                    text=msg.get("message", ""), agent_id=agent_id, conversation_id=state["conversation_id"],
                    source="web", reply_to_run_id=msg.get("reply_to_run_id", ""), destination=state["conversation_id"],
                    occurrence_key=(f"web:{state['conversation_id']}:{msg['request_id']}" if msg.get("request_id") else None)))
                await ws.send_json({"type": "run_accepted", "run_id": run_id, "conversation_id": state["conversation_id"]})
            elif t == "switch_agent":
                agent_id = msg.get("agent_id", "")
                if not _agent_manager.get(agent_id):
                    raise ValueError("Agent not found.")
                state["agent_id"] = agent_id
                await ws.send_json({"type": "agent_selected", "agent_id": agent_id})
            elif t == "new_thread":
                state["conversation_id"] = "web-" + uuid.uuid4().hex
                await _send_conversation(ws)
            elif t == "get_conversation":
                await _send_conversation(ws)
            else:
                run_id = msg.get("run_id", "")
                if _runtime.store.get(run_id)["conversation_id"] != state["conversation_id"]:
                    raise ValueError("Run does not belong to this conversation.")
                if t == "cancel_run":
                    _runtime.cancel(run_id)
                else:
                    _runtime.retry(run_id)
        except (ValueError, TypeError, AttributeError) as exc:
            await ws.send_json({"type": "error", "action": t, "error": str(exc)})
        return

    if t == "chat":
        text = (msg.get("message") or "").strip()[:_MAX_CHAT_CHARS]
        if text and _web_queue is not None:
            fut: asyncio.Future = asyncio.get_event_loop().create_future()
            await _web_queue.put((text, fut))

    elif t == "get_agents":
        await ws.send_json({"type": "agents", **_agents_payload()})

    elif t == "switch_agent":
        if _agent_manager:
            agent_id = msg.get("agent_id", "")
            _agent_manager.set_active(agent_id)
            get_bus().publish_nowait({"type": "agents", **_agents_payload()})
            if _web_queue is not None:
                fut: asyncio.Future = asyncio.get_event_loop().create_future()
                await _web_queue.put((f"__switch_agent__:{agent_id}", fut))

    elif t == "get_stats":
        await ws.send_json({"type": "stats", **_stats_payload(msg.get("agent_id"))})

    elif t == "get_cron_jobs":
        await ws.send_json({"type": "cron_jobs", "jobs": _list_cron_jobs()})

    elif t in ("save_cron", "delete_cron", "toggle_cron", "run_cron"):
        from questchain.scheduler import get_scheduler
        try:
            scheduler = get_scheduler()
            job_id = msg.get("cron_id", "")
            if t == "save_cron":
                values = dict(name=msg.get("name", ""), prompt=msg.get("prompt", ""),
                              cron_expression=msg.get("cron_expression", ""),
                              timezone_str=msg.get("timezone", "UTC"), agent_id=msg.get("agent_id") or None)
                if not all(isinstance(v, str) for k, v in values.items() if k != "agent_id"):
                    raise ValueError("Job fields must be text.")
                job = scheduler.update_job(job_id, **values) if job_id else scheduler.add_job(**values)
                job_id = job["id"]
            elif t == "delete_cron":
                scheduler.remove_job(job_id)
            elif t == "toggle_cron":
                job = scheduler.get_job(job_id)
                scheduler.set_enabled(job_id, not job.get("enabled", True))
            else:
                scheduler.run_now(job_id)
            await ws.send_json({"type": "cron_saved", "cron_id": job_id, "action": t})
        except (ValueError, KeyError, RuntimeError, TypeError) as exc:
            await ws.send_json({"type": "cron_error", "message": str(exc)})

    elif t == "get_settings":
        await ws.send_json({"type": "settings", **_settings_payload()})

    elif t == "new_thread":
        if _web_queue is not None:
            fut: asyncio.Future = asyncio.get_event_loop().create_future()
            await _web_queue.put(("__new_thread__", fut))

    elif t == "delete_legacy_agent":
        if _agent_manager:
            try:
                removed = _agent_manager.delete_legacy(msg.get("agent_id", ""))
                await ws.send_json({"type": "legacy_deleted", "agent_id": removed["id"], "name": removed["name"]})
                get_bus().publish_nowait({"type": "settings", **_settings_payload()})
            except (ValueError, TypeError, OSError) as exc:
                await ws.send_json({"type": "legacy_error", "error": str(exc)})

    elif t == "migrate_legacy_agent":
        if _agent_manager:
            try:
                saved = _agent_manager.migrate_legacy(msg.get("agent_id", ""))
                await ws.send_json({"type": "legacy_migrated", "agent_id": saved["id"], "name": saved["name"]})
                get_bus().publish_nowait({"type": "agents", **_agents_payload()})
                get_bus().publish_nowait({"type": "settings", **_settings_payload()})
            except (ValueError, TypeError) as exc:
                await ws.send_json({"type": "legacy_error", "error": str(exc)})

    elif t == "create_agent":
        if _agent_manager:
            try:
                from questchain.agents import CLASS_TOOL_PRESETS, CLASS_GUIDANCE
                class_name = msg.get("class_name") or "Custom"
                saved = _agent_manager.add(
                    name=msg.get("name", ""),
                    model=msg.get("model") or None,
                    system_prompt=msg.get("system_prompt"),
                    tools=msg.get("tools", CLASS_TOOL_PRESETS.get(class_name) or []),
                    class_name=class_name,
                    when_to_call=msg.get("when_to_call", CLASS_GUIDANCE.get(class_name, "")),
                    when_not_to_call=msg.get("when_not_to_call", ""),
                    routing_examples=msg.get("routing_examples", []),
                    routable=msg.get("routable", True),
                )
                await ws.send_json({"type": "agent_saved", "agent_id": saved["id"]})
                get_bus().publish_nowait({"type": "agents", **_agents_payload()})
                get_bus().publish_nowait({"type": "settings", **_settings_payload()})
            except (ValueError, TypeError) as exc:
                await ws.send_json({"type": "agent_error", "error": str(exc)})

    elif t == "update_agent":
        if _agent_manager:
            agent_id = msg.get("agent_id", "")
            allowed = {"name", "model", "system_prompt", "class_name", "tools", "when_to_call",
                       "when_not_to_call", "routing_examples", "routable"}
            kwargs = {k: v for k, v in msg.items() if k in allowed}
            if agent_id and kwargs:
                try:
                    _agent_manager.update(agent_id, **kwargs)
                    await ws.send_json({"type": "agent_saved", "agent_id": agent_id})
                    get_bus().publish_nowait({"type": "agents", **_agents_payload()})
                    get_bus().publish_nowait({"type": "settings", **_settings_payload()})
                except (ValueError, TypeError) as exc:
                    await ws.send_json({"type": "agent_error", "error": str(exc)})

    elif t == "delete_agent":
        if _agent_manager:
            agent_id = msg.get("agent_id", "")
            if agent_id:
                try:
                    _agent_manager.remove(agent_id)
                    get_bus().publish_nowait({"type": "agents", **_agents_payload()})
                    get_bus().publish_nowait({"type": "settings", **_settings_payload()})
                except Exception:
                    logger.warning("delete_agent failed for %s", agent_id, exc_info=True)

    elif t == "set_model":
        model = (msg.get("model") or "").strip()
        apply_all = bool(msg.get("apply_all", True))
        if model:
            try:
                from questchain.onboarding import _save_env_key
                _save_env_key("OLLAMA_MODEL", model)
                if apply_all and _agent_manager:
                    for a in _agent_manager.all_agents():
                        if not a.get("built_in"):
                            try:
                                _agent_manager.update(a["id"], model=None)
                            except Exception:
                                pass
                get_bus().publish_nowait({"type": "settings", **_settings_payload()})
            except Exception:
                logger.warning("set_model failed", exc_info=True)


# ── Payload builders ──────────────────────────────────────────────────────────

async def _send_cron_history(ws) -> None:
    state = _clients.get(id(ws), {})
    if _runtime and state.get("cron_id"):
        records = _runtime.snapshot("cron-" + state["cron_id"])["runs"]
        await ws.send_json({"type": "cron_history", "cron_id": state["cron_id"], "runs": records[-40:]})


async def _send_conversation(ws) -> None:
    state = _clients.get(id(ws))
    if state and _runtime:
        await ws.send_json({"type": "conversation", **_runtime.snapshot(state["conversation_id"]),
                            "selected_agent_id": state["agent_id"]})

def _agents_payload() -> dict:
    if _agent_manager is None:
        return {"agents": [], "active_id": ""}
    agents = _agent_manager.all_agents()
    active = _agent_manager.get_active()
    active_id = active.get("id", "") if active else ""

    # Enrich each agent with full progression + metrics so the UI can render
    # the agent page entirely from this payload without a separate get_stats call.
    from questchain.progression import ProgressionManager
    from questchain.stats import MetricsManager
    enriched = []
    from questchain.agents import ROLE_LABELS, tool_issues
    for agent in agents:
        a = dict(agent)
        a["role_label"] = ROLE_LABELS.get(a.get("class_name"), "Custom")
        a["availability_issues"] = tool_issues(a)
        agent_id = agent["id"]
        class_name = agent.get("class_name", "Custom")
        # Progression
        try:
            pm = ProgressionManager(agent_id, class_name)
            rec = pm.load()
            a["progression"] = {
                "level": rec.level,
                "xp_this_level": rec.xp_this_level,
                "xp_next_level": rec.xp_next_level,
                "class_name": rec.class_name,
                "achievements": [
                    {"id": ach.id, "name": ach.name, "description": ach.description, "earned_at": ach.earned_at}
                    for ach in rec.achievements
                ],
                "prestige": rec.prestige,
            }
            a["level"] = rec.level  # keep top-level for roster display
        except Exception:
            a["progression"] = {"level": 1, "xp_this_level": 0, "xp_next_level": 100, "class_name": class_name, "achievements": [], "prestige": 0}
            a["level"] = 1
        # Metrics — use in-memory manager if it matches this agent, else disk
        metrics_src = None
        if (
            _metrics is not None
            and getattr(_metrics, "_agent_id", None) == agent_id
            and agent_id == active_id
        ):
            _metrics.load()
            metrics_src = _metrics.get_record()
        else:
            try:
                mm = MetricsManager(agent_id)
                metrics_src = mm.load()
            except Exception:
                pass
        if metrics_src:
            a["metrics"] = {
                "agent_id": agent_id,
                "agent_name": agent.get("name", "QuestChain"),
                "model_name": metrics_src.model_name or (agent.get("model") or _model_name),
                "num_tools": metrics_src.num_tools,
                "prompt_count": metrics_src.prompt_count,
                "tokens_used": metrics_src.tokens_used,
                "total_errors": metrics_src.total_errors,
                "highest_chain": metrics_src.highest_chain,
            }
        else:
            a["metrics"] = {
                "agent_id": agent_id,
                "agent_name": agent.get("name", "QuestChain"),
                "model_name": agent.get("model") or _model_name,
                "tokens_used": 0, "total_errors": 0, "highest_chain": 0,
            }
        enriched.append(a)

    return {"agents": enriched, "active_id": active_id}


def _stats_payload(agent_id: str | None = None) -> dict:
    prog_data: dict = {}
    metrics_data: dict = {}

    # Resolve which agent we're looking at
    if agent_id and _agent_manager is not None:
        agent_def = _agent_manager.get(agent_id)
    else:
        agent_def = _agent_manager.get_active() if _agent_manager else None
        if agent_id is None and _agent_manager is not None:
            agent_id = _agent_manager.get_active_id()

    effective_agent_id = agent_def["id"] if agent_def else None
    active_id = _agent_manager.get_active_id() if _agent_manager else None

    # Always load progression fresh from disk — it's the source of truth
    if agent_def is not None:
        from questchain.progression import ProgressionManager
        pm = ProgressionManager(agent_def["id"], agent_def.get("class_name", "Custom"))
        rec = pm.load()
        prog_data = {
            "level": rec.level,
            "xp_this_level": rec.xp_this_level,
            "xp_next_level": rec.xp_next_level,
            "class_name": rec.class_name,
            "achievements": [
                {"id": a.id, "name": a.name, "description": a.description, "earned_at": a.earned_at}
                for a in rec.achievements
            ],
            "prestige": rec.prestige,
            "turns_completed": rec.turns_completed,
        }

    # Metrics: use in-memory manager only when it's tracking the same agent
    # that is both active AND the one being queried.  After a web switch_agent
    # the server's _metrics still points to the previous agent's manager, so we
    # must guard against returning stale data for the wrong agent.
    metrics_agent_matches = (
        _metrics is not None
        and effective_agent_id == active_id
        and getattr(_metrics, "_agent_id", None) == effective_agent_id
    )
    if metrics_agent_matches:
        _metrics.load()
        m = _metrics.get_record()
        metrics_data = {
            "prompt_count": m.prompt_count,
            "tokens_used": m.tokens_used,
            "total_errors": m.total_errors,
            "highest_chain": m.highest_chain,
            "num_tools": m.num_tools,
            "model_name": m.model_name or _model_name,
        }
    elif effective_agent_id:
        from questchain.stats import MetricsManager
        mm = MetricsManager(effective_agent_id)
        m = mm.load()
        metrics_data = {
            "prompt_count": m.prompt_count,
            "tokens_used": m.tokens_used,
            "total_errors": m.total_errors,
            "highest_chain": m.highest_chain,
            "num_tools": m.num_tools,
            "model_name": m.model_name or (agent_def.get("model") or _model_name if agent_def else _model_name),
        }
    else:
        metrics_data["model_name"] = _model_name

    metrics_data["agent_name"] = agent_def.get("name", "QuestChain") if agent_def else "QuestChain"
    metrics_data["agent_id"] = effective_agent_id or ""

    return {"progression": prog_data, "metrics": metrics_data}


# ── Settings payload ──────────────────────────────────────────────────────────

def _get_speak_available() -> bool:
    try:
        from questchain.tools.speak import is_speak_available
        return is_speak_available()
    except Exception:
        return False


def _settings_payload() -> dict:
    import json as _json
    from questchain.config import (
        TAVILY_API_KEY, TELEGRAM_BOT_TOKEN, MODEL_PRESETS, get_cron_jobs_path,
    )
    from questchain.tools import is_claude_code_available
    from questchain.agents import AGENT_CLASSES, SELECTABLE_TOOLS, CLASS_GUIDANCE, CLASS_TOOL_PRESETS, preset_prompt, ROLE_LABELS, tool_issues
    from questchain.config import WORKSPACE_DIR as _ws_dir
    from questchain.engine.workspace_tools import get_tool_entries as _ws_tool_entries

    try:
        from questchain.models import list_available_models
        available_models = list_available_models()
    except Exception:
        available_models = []

    cron_jobs = _list_cron_jobs()

    agents: list[dict] = []
    if _agent_manager:
        for a in _agent_manager.all_agents():
            agents.append({
                "id": a["id"],
                "name": a.get("name", ""),
                "class_name": a.get("class_name", "Custom"),
                "model": a.get("model") or "",
                "system_prompt": a.get("system_prompt") or "",
                "tools": a.get("tools", "all"),
                "when_to_call": a.get("when_to_call", ""),
                "when_not_to_call": a.get("when_not_to_call", ""),
                "routing_examples": a.get("routing_examples", []),
                "routable": a.get("routable", False),
                "availability_issues": tool_issues(a),
            })

    agent_classes = [{"name": c[0], "icon": c[1], "description": c[2]} for c in AGENT_CLASSES]

    selectable_tools = (
        [{"name": t[0], "description": t[1], "workspace": False} for t in SELECTABLE_TOOLS]
        + [{"name": t[0], "description": t[1], "workspace": True} for t in _ws_tool_entries(_ws_dir)]
    )

    return {
        "thread_id": _thread_id,
        "model_name": _metrics.get_record().model_name if _metrics else _model_name,
        "available_models": available_models,
        "model_presets": list(MODEL_PRESETS.keys()),
        "agents": agents,
        "legacy_agents": [{k: a.get(k) for k in ("id", "name", "class_name", "model", "tools")}
                          for a in _agent_manager.legacy_agents()] if _agent_manager else [],
        "agent_classes": agent_classes,
        "role_labels": ROLE_LABELS,
        "agent_presets": {c[0]: {"tools": CLASS_TOOL_PRESETS.get(c[0]) or [],
                                 "system_prompt": preset_prompt(c[0]), "when_to_call": CLASS_GUIDANCE.get(c[0], "")}
                          for c in AGENT_CLASSES},
        "selectable_tools": selectable_tools,
        "cron_jobs": cron_jobs,
        "integrations": {
            "tavily": bool(TAVILY_API_KEY),
            "claude_code": is_claude_code_available(),
            "telegram": bool(TELEGRAM_BOT_TOKEN),
            "speak": _get_speak_available(),
        },
    }


# ── Cron job helpers ──────────────────────────────────────────────────────────

def _list_cron_jobs() -> list[dict]:
    from questchain.scheduler import get_scheduler
    try:
        return get_scheduler().list_jobs()
    except RuntimeError:
        return []


# ── Uvicorn launcher ──────────────────────────────────────────────────────────

def _handle_loop_error(loop, context, previous=None) -> None:
    # Windows can report a reset while disposing an already-disconnected socket.
    # This is a client lifecycle event, not an error in the running task.
    if (isinstance(context.get("exception"), ConnectionResetError)
            and "_ProactorBasePipeTransport._call_connection_lost" in context.get("message", "")):
        logger.debug("Browser connection closed during transport cleanup")
        return
    if previous:
        previous(loop, context)
    else:
        loop.default_exception_handler(context)


def install_connection_error_handler() -> None:
    from functools import partial
    loop = asyncio.get_running_loop()
    current = loop.get_exception_handler()
    if getattr(current, "func", None) is not _handle_loop_error:
        loop.set_exception_handler(partial(_handle_loop_error, previous=current))


async def start_gateway_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Start uvicorn in the current event loop as a background task."""
    global _bound_host, _bound_port, _ws_token
    _bound_host = host
    _bound_port = port
    from questchain.config import QUESTCHAIN_WS_TOKEN
    _ws_token = QUESTCHAIN_WS_TOKEN

    import uvicorn
    install_connection_error_handler()

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        loop="none",
        log_level="critical",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # don't steal SIGINT from CLI
    asyncio.create_task(server.serve())
