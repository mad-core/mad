from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

@dataclass
class ToolUse:
    id: str
    name: str
    input: dict


@dataclass
class ProviderResponse:
    text: str | None = None
    tool_uses: list[ToolUse] = field(default_factory=list)
    stop_reason: str = "end_turn"


class LLMProvider(Protocol):
    async def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
    ) -> ProviderResponse: ...


# ---------------------------------------------------------------------------
# LLM provider factory (monkey-patched in tests to return FakeProvider)
# ---------------------------------------------------------------------------

def get_provider(name: str) -> LLMProvider:
    if name == "claude_cli":
        return ClaudeCLIProvider()
    if name == "anthropic_api":
        return AnthropicAPIProvider()
    raise NotImplementedError(f"Unknown provider: {name!r}")


class ClaudeCLIProvider:
    async def complete(self, system: str, messages: list[dict], tools: list[dict]) -> ProviderResponse:
        raise NotImplementedError("ClaudeCLIProvider not implemented in MVP")


class AnthropicAPIProvider:
    async def complete(self, system: str, messages: list[dict], tools: list[dict]) -> ProviderResponse:
        raise NotImplementedError("AnthropicAPIProvider not implemented in MVP")


# ---------------------------------------------------------------------------
# Session log (source of truth)
# ---------------------------------------------------------------------------

SESSIONS_DIR = Path("sessions")


def _ensure_sessions_dir() -> None:
    SESSIONS_DIR.mkdir(exist_ok=True)


def _log_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.jsonl"


def _emit(session_id: str, event_type: str, data: dict[str, Any] | None = None) -> dict:
    event = {"type": event_type, "timestamp": datetime.now(timezone.utc).isoformat()}
    if data:
        event.update(data)
    line = json.dumps(event)
    print(line)
    with _log_path(session_id).open("a") as f:
        f.write(line + "\n")
    return event


def _get_events(session_id: str) -> list[dict]:
    p = _log_path(session_id)
    if not p.exists():
        return []
    lines = []
    for ln in p.read_text().splitlines():
        ln = ln.strip()
        if ln:
            lines.append(json.loads(ln))
    return lines


# ---------------------------------------------------------------------------
# In-memory session registry (rebuilt from logs on startup if needed)
# ---------------------------------------------------------------------------

# session_id -> session dict
_sessions: dict[str, dict] = {}
# idempotency_key -> session_id
_idempotency: dict[str, str] = {}

# session_id -> asyncio.Queue for SSE push
_sse_queues: dict[str, asyncio.Queue] = {}


def _get_or_create_queue(session_id: str) -> asyncio.Queue:
    if session_id not in _sse_queues:
        _sse_queues[session_id] = asyncio.Queue()
    return _sse_queues[session_id]


def _push_event(session_id: str, event: dict) -> None:
    """Push event to the SSE queue if there is one."""
    q = _sse_queues.get(session_id)
    if q is not None:
        q.put_nowait(event)


def _emit_and_push(session_id: str, event_type: str, data: dict | None = None) -> dict:
    event = _emit(session_id, event_type, data)
    _push_event(session_id, event)
    return event


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------

_WORKSPACE_PREFIX = "/workspace"


def _validate_mount_path(mount_path: str) -> None:
    """Reject any mount_path that doesn't resolve inside /workspace."""
    from pathlib import PurePosixPath
    if not mount_path.startswith("/"):
        raise HTTPException(status_code=400, detail=f"mount_path {mount_path!r} must be absolute")
    pure = PurePosixPath(mount_path)
    stack: list[str] = []
    for part in pure.parts[1:]:
        if part == "..":
            if not stack:
                raise HTTPException(status_code=400, detail=f"mount_path {mount_path!r} escapes workspace")
            stack.pop()
        elif part and part != ".":
            stack.append(part)
    logical = "/" + "/".join(stack)
    if not (logical == _WORKSPACE_PREFIX or logical.startswith(_WORKSPACE_PREFIX + "/")):
        raise HTTPException(status_code=400, detail=f"mount_path {mount_path!r} escapes workspace")


# ---------------------------------------------------------------------------
# Workspace management
# ---------------------------------------------------------------------------

def _workspace_path(session_id: str) -> Path:
    return Path(tempfile.gettempdir()) / f"mad_{session_id}"


def _local_path_for_mount(session_id: str, mount_path: str) -> Path:
    """Map a /workspace/... mount_path into the real temp workspace directory."""
    # strip /workspace prefix and join with the workspace root
    relative = mount_path.lstrip("/")
    # remove leading "workspace/"
    if relative.startswith("workspace/") or relative == "workspace":
        relative = relative[len("workspace"):]
    relative = relative.lstrip("/")
    base = _workspace_path(session_id)
    if relative:
        return base / relative
    return base


# ---------------------------------------------------------------------------
# Resource provisioning
# ---------------------------------------------------------------------------

def _provision_github_repo(session_id: str, resource: dict) -> dict:
    url: str = resource["url"]
    mount_path: str = resource["mount_path"]
    token: str | None = resource.get("authorization_token")
    checkout: dict | None = resource.get("checkout")

    local_path = _local_path_for_mount(session_id, mount_path)
    local_path.mkdir(parents=True, exist_ok=True)

    # Build clone URL — inject token only for https:// URLs
    clone_url = url
    if token and url.startswith("https://"):
        # inject token into URL: https://token@github.com/...
        clone_url = url.replace("https://", f"https://{token}@", 1)
    # for file:// URLs the token is ignored (bare repo, no auth needed)

    cmd = ["git", "clone", "-q", clone_url, str(local_path)]
    if checkout and checkout.get("type") == "branch":
        cmd = ["git", "clone", "-q", "-b", checkout["name"], clone_url, str(local_path)]

    # remove and recreate because git clone requires empty dir
    shutil.rmtree(local_path)
    subprocess.run(cmd, check=True, capture_output=True)

    # Strip token from remote after clone (token hygiene rule)
    clean_url = url  # original URL without token
    subprocess.run(
        ["git", "-C", str(local_path), "remote", "set-url", "origin", clean_url],
        check=True,
        capture_output=True,
    )

    return {
        "type": "github_repository",
        "url": url,
        "mount_path": mount_path,
        "local_path": str(local_path),
        "status": "cloned",
    }


def _provision_file(session_id: str, resource: dict) -> dict:
    mount_path: str = resource["mount_path"]
    content: str = resource.get("content", "")
    local_path = _local_path_for_mount(session_id, mount_path)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(content)
    return {
        "type": "file",
        "mount_path": mount_path,
        "local_path": str(local_path),
        "status": "written",
    }


# ---------------------------------------------------------------------------
# Agent loop (harness)
# ---------------------------------------------------------------------------

AGENT_TOOLS = [
    {
        "name": "bash",
        "description": "Execute a bash command in the workspace sandbox.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a file from the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file in the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
]


def _execute_tool(session_id: str, tool_use: ToolUse) -> str:
    """Execute a structured tool call in the session workspace."""
    workspace = _workspace_path(session_id)
    if tool_use.name == "bash":
        command = tool_use.input.get("command", "")
        result = subprocess.run(
            command, shell=True, cwd=str(workspace),
            capture_output=True, text=True, timeout=60,
        )
        return result.stdout + (("\n" + result.stderr) if result.stderr else "")
    if tool_use.name == "read_file":
        path = workspace / tool_use.input.get("path", "").lstrip("/")
        try:
            return path.read_text()
        except Exception as exc:
            return f"error: {exc}"
    if tool_use.name == "write_file":
        path = workspace / tool_use.input.get("path", "").lstrip("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tool_use.input.get("content", ""))
        return "ok"
    return f"unknown tool: {tool_use.name}"


async def _run_agent_loop(session_id: str, session: dict, user_message: str) -> None:
    """Run the agent loop for one user message, appending all events to the session log."""
    _emit_and_push(session_id, "session.status_running")
    session["status"] = "running"

    provider = get_provider(session["agent"]["provider"])
    system = session["agent"].get("system", "")

    messages: list[dict] = []
    # Replay prior turns from the log so Claude has context on resume
    for event in _get_events(session_id):
        if event["type"] == "user.message":
            messages.append({"role": "user", "content": event["content"]})
        elif event["type"] == "agent.message" and event.get("content"):
            messages.append({"role": "assistant", "content": event["content"]})

    # Append the current user message if it is not already last
    if not messages or messages[-1] != {"role": "user", "content": user_message}:
        messages.append({"role": "user", "content": user_message})

    stop_reason = "end_turn"
    try:
        while True:
            response = await provider.complete(system=system, messages=messages, tools=AGENT_TOOLS)
            stop_reason = response.stop_reason

            if response.text:
                _emit_and_push(session_id, "agent.message", {"content": response.text})
                messages.append({"role": "assistant", "content": response.text})

            if not response.tool_uses:
                break

            # Process structured tool_use blocks only (hard rule: no free-text parsing)
            tool_results = []
            for tu in response.tool_uses:
                _emit_and_push(session_id, "agent.tool_use", {
                    "tool": tu.name,
                    "input": tu.input,
                    "tool_use_id": tu.id,
                })
                result = _execute_tool(session_id, tu)
                _emit_and_push(session_id, "agent.tool_result", {
                    "tool": tu.name,
                    "result": result,
                    "tool_use_id": tu.id,
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result,
                })

            messages.append({"role": "user", "content": tool_results})

            if stop_reason != "tool_use":
                break

    except Exception as exc:
        _emit_and_push(session_id, "session.error", {"error": str(exc)})
        stop_reason = "error"

    _emit_and_push(session_id, "session.status_idle", {"stop_reason": stop_reason})
    session["status"] = "idle"

    # Signal SSE stream that we are done
    q = _sse_queues.get(session_id)
    if q is not None:
        await q.put(None)  # sentinel


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(title="Mad", version="0.1.0")


@app.on_event("startup")
async def _startup() -> None:
    _ensure_sessions_dir()


# ---------------------------------------------------------------------------
# POST /v1/sessions
# ---------------------------------------------------------------------------

@app.post("/v1/sessions")
async def create_session(
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    _ensure_sessions_dir()

    # Idempotency check
    if idempotency_key and idempotency_key in _idempotency:
        existing_id = _idempotency[idempotency_key]
        return _sessions[existing_id]["response"]

    body = await request.json()
    agent = body["agent"]
    resources = body.get("resources", [])

    # Validate all mount_paths before doing anything
    for res in resources:
        _validate_mount_path(res["mount_path"])

    session_id = "sesn_" + uuid.uuid4().hex[:12]
    workspace = _workspace_path(session_id)
    workspace.mkdir(parents=True, exist_ok=True)

    _emit(session_id, "session.created", {"agent": agent["name"]})

    resources_mounted = []
    for res in resources:
        if res["type"] == "github_repository":
            mounted = _provision_github_repo(session_id, res)
        elif res["type"] == "file":
            mounted = _provision_file(session_id, res)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown resource type: {res['type']!r}")
        resources_mounted.append(mounted)

    response = {
        "session_id": session_id,
        "status": "created",
        "workspace": str(workspace),
        "resources_mounted": resources_mounted,
    }

    _sessions[session_id] = {
        "session_id": session_id,
        "agent": agent,
        "workspace": str(workspace),
        "status": "created",
        "response": response,
    }
    _get_or_create_queue(session_id)

    if idempotency_key:
        _idempotency[idempotency_key] = session_id

    return response


# ---------------------------------------------------------------------------
# POST /v1/sessions/{id}/events
# ---------------------------------------------------------------------------

@app.post("/v1/sessions/{session_id}/events")
async def send_events(session_id: str, request: Request) -> dict:
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    body = await request.json()
    events = body.get("events", [])
    session = _sessions[session_id]

    for event in events:
        event_type = event.get("type")
        if event_type == "user.message":
            content = event.get("content", "")
            _emit(session_id, "user.message", {"content": content})
            # Fire and forget — non-blocking
            asyncio.create_task(_run_agent_loop(session_id, session, content))

    return {"status": "accepted"}


# ---------------------------------------------------------------------------
# GET /v1/sessions/{id}/stream  (SSE)
# ---------------------------------------------------------------------------

@app.get("/v1/sessions/{session_id}/stream")
async def stream_session(session_id: str) -> StreamingResponse:
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    queue = _get_or_create_queue(session_id)

    async def event_generator():
        while True:
            event = await queue.get()
            if event is None:
                # sentinel: agent loop finished
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# GET /v1/sessions/{id}
# ---------------------------------------------------------------------------

@app.get("/v1/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    session = _sessions[session_id]
    events = _get_events(session_id)
    return {
        "session_id": session_id,
        "status": session["status"],
        "workspace": session["workspace"],
        "events": events,
    }


# ---------------------------------------------------------------------------
# GET /v1/sessions
# ---------------------------------------------------------------------------

@app.get("/v1/sessions")
async def list_sessions() -> list:
    return [
        {"session_id": sid, "status": s["status"]}
        for sid, s in _sessions.items()
    ]


# ---------------------------------------------------------------------------
# DELETE /v1/sessions/{id}
# ---------------------------------------------------------------------------

@app.delete("/v1/sessions/{session_id}")
async def delete_session(session_id: str) -> dict:
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = _sessions[session_id]
    workspace = Path(session["workspace"])

    if workspace.exists():
        shutil.rmtree(workspace)

    session["status"] = "deleted"
    # Remove from the SSE registry but keep session entry so GET returns deleted status
    _sse_queues.pop(session_id, None)

    return {"status": "deleted", "session_id": session_id}
