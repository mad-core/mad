---
service: mad
domain: backend
section: conventions
source_of_truth: repo
---

# Testing heuristics — `mad`

These are the rules every test in this repo must satisfy. They were derived from a critical audit (May 2026) that found ~50 tests across the suite suffering from one or more of the patterns below — including a test that **codified a real bug as the contract** (`test_stream_route_rejects_invalid_last_event_id`, since rewritten).

A test that violates these heuristics is debt, not coverage. PR reviewers (human and Claude) MUST reject tests that fail any rule below. The `test-critic` agent applies these rules mechanically.

ADR-0001 covers the high-level testing strategy (unit / integration / e2e split). This document is the operational complement: how to write a test that actually tests something.

---

## The eight rules

### 1. Every endpoint test has a negative twin

Any `test_endpoint_X_happy_path` requires a sibling `test_endpoint_X_rejects_<malformed>` that exercises a real failure mode (4xx for HTTP, raised exception for use cases) and asserts the *contractual* error shape — status code AND body structure.

**Why.** Happy-path-only tests pass for any implementation that returns `200 {}`. They never catch validation regressions, never document the failure contract, and leave the client guessing.

**Bad** (illustrative — not drawn from a current file):
```python
def test_send_message_happy(...):
    r = client.post(f"/v1/sessions/{sid}/messages", json={"content": "hi"})
    assert r.status_code in (200, 202)  # also bad — see rule 2
```

**Good** (real negative twin — `tests/integration/api/test_sessions_http.py:605`, `test_openapi_post_messages_rejects_missing_content`):
```python
def test_openapi_post_messages_rejects_missing_content(client, fake_launcher, session_payload):
    fake_launcher.script([[{"type": "session.status_idle", "stop_reason": "end_turn"}]])
    session_id = client.post("/v1/sessions", json=session_payload).json()["session_id"]
    r = client.post(f"/v1/sessions/{session_id}/messages", json={})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert any(d.get("loc") == ["body", "content"] for d in detail)
```

### 2. One contract per test — no `or`, no `in (200, 202)`

If your assertion accepts two status codes or two body shapes, you are documenting two contracts and validating neither. Pin the actual contract; if the code legitimately returns two things in different contexts, write two tests.

**Bad** (illustrative — not drawn from a current file):
```python
assert isinstance(body, list) or "sessions" in body
```

**Bad** (illustrative — not drawn from a current file):
```python
assert data["session_id"].startswith("sesn_") or len(data["session_id"]) > 0
# the `or` clause makes the first one redundant; any non-empty string passes
```

**Good** (real — `tests/integration/api/test_sessions_http.py:58-66`, `test_mvp_01_create_session_response_shape`):
```python
assert isinstance(data["session_id"], str) and len(data["session_id"]) > 0
assert data["session_id"].startswith("sesn_")
```

### 3. Fakes live in `tests/support/`, never inline in a test file

A `FakeRepo` redefined inside `test_create_session.py` with `events.append({"type": ..., **data})` is a parallel re-implementation of the port. When the production adapter changes (event_id, timestamps, redaction), the fake doesn't; the test stays green while production breaks.

If you need a fake, put it in `tests/support/<port>.py` and share it across all tests that depend on the port. The fake should be **stricter** than production where ambiguity exists (reject unknown keys, validate timestamps), so a test with the fake will fail loudly if the production contract drifts.

**Bad** (illustrative — not drawn from a current file; this repo's suite no longer has any inline `class Fake*` outside `tests/support/`):
```python
# tests/unit/core/sessions/use_cases/test_create_session.py
class FakeRepo:
    def __init__(self):
        self.events = []
    def append_event(self, session_id, type, data):
        self.events.append({"type": type, **data})
```

**Good** (real — every use-case test imports the shared doubles instead of redefining them):
```python
# tests/unit/core/sessions/use_cases/test_create_session.py:18-19
from support.events import FakeEventBus
from support.sessions import FakeProvisioner, FakeSessionRepository
```

`tests/support/sessions.py` defines `FakeSessionRepository` / `FakeProvisioner` once; `tests/support/events.py` defines `FakeEventStore` / `FakeEventBus` / `FakeEventLogQuery` once. Every session and event test imports these instead of redefining its own.

### 4. Weak assertion → pair it with a specific second assertion

`assert "key" in dict`, `assert isinstance(x, list)`, `assert len(x) > 0` are *necessary* but never *sufficient*. They prove the response has shape, not value. Pair every weak assertion with a value-level assertion in the same test.

**Bad** (real — `tests/integration/persistence/test_session_recovery.py:39-44`; this test still only checks that the recovered event *type* is present, never a specific field value on the recovered event):
```python
events = r2.json().get("events", [])
assert len(events) > 0, "Recovered session must have at least one event from the JSONL log"
event_types = {e.get("type") for e in events}
assert "session.created" in event_types, (
    f"Expected session.created in recovered events, got: {event_types}"
)
```

**Good:**
```python
assert len(events) > 0
created = next(e for e in events if e["type"] == "session.created")
assert created["agent"]["provider"] == "claude_cli"
assert UUID(created["event_id"])  # valid UUIDv7
assert datetime.fromisoformat(created["timestamp"])
```

### 5. Endpoints with a JSON body need an OpenAPI contract test

Every `POST` / `PUT` route MUST have a test that opens `/openapi.json` and asserts:

- `paths[<route>][<method>].requestBody.required is True`
- `paths[<route>][<method>].requestBody.content."application/json".schema` exists and references a named component
- Each required field of the body model appears in the schema

This is the test that would have caught the original "Postman shows no body schema" bug. Three lines, mechanical.

**Reference test** (real — `tests/integration/api/test_sessions_http.py:566-585`, `test_openapi_post_sessions_declares_body_schema`):
```python
def test_openapi_post_sessions_declares_body_schema(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    op = spec["paths"]["/v1/sessions"]["post"]
    body = op["requestBody"]
    assert body["required"] is True

    schema = body["content"]["application/json"]["schema"]
    component = _resolve_ref(spec, schema["$ref"])
    required = set(component.get("required", []))
    assert "agent" in required, (
        f"CreateSessionRequest must mark 'agent' required; got required={required}"
    )
```

### 6. SSE / streaming endpoints — never test only the helper, never hit the live infinite stream

If a route does `StreamingResponse`, test the route, not just the parsing helper. But **do not connect a test client to a server-side generator that yields forever** — `httpx.AsyncClient.stream(...)` against an unbounded `StreamingResponse` over `ASGITransport` will hang on close, even with `timeout=`, because the ASGI app does not honor the disconnect promptly. We have already burned a CI run on this.

The acceptable patterns, in order of preference:

1. **Inject a bounded source.** Replace the route's event bus / iterator with a fake that yields a finite sequence and then completes. Connect, read all frames, assert. The route exits naturally.
2. **Read one frame, then close, with a hard `@pytest.mark.timeout`.** Only use this if the route emits at least one frame immediately. Set `@pytest.mark.timeout(5)` so a regression in the close path fails fast instead of hanging.
3. **Helper-only test, *plus* a route smoke test that does not stream.** If the route opens a long-lived stream by design and you cannot bound it from the test, keep the helper unit test for parsing logic AND add a route-level test that asserts wiring (e.g., `app.routes` contains the path, or call the route function directly with a scoped fake) — never `c.stream(...)` against the live infinite generator.

**Pattern 1 — bounded source (real, trimmed from `tests/integration/api/test_events_http.py:305-330`, `test_stream_does_not_emit_heartbeat_when_events_flow_under_interval`):**
```python
bus = FakeEventBus()
log = FakeEventLogQuery()

async def publisher() -> None:
    await _wait_for_subscription(bus)
    for i in range(3):
        await bus.publish(_make_event("sesn_a", "agent.output", {"line": f"frame-{i}"}))
        await asyncio.sleep(0.05)
    await bus.close_subscriber()  # <- lets the route's generator complete

pub_task = asyncio.create_task(publisher())
try:
    response = await _stream_with_injected_bus(bus, log)
finally:
    if not pub_task.done():
        pub_task.cancel()

assert response.status_code == 200
assert response.text.count("data:") == 3
```

`bus.close_subscriber()` is what makes this a *bounded* source — the fake event bus's generator terminates on its own once closed, instead of the test relying on `stream(...)` to abort an infinite one.

### 7. Polling waits on state, never on time

`time.sleep(0.2)` followed by `assert len(calls) == 2` is flaky AND wrong: the test passes because *time elapsed*, not because the system reached the right state. Poll on a state predicate (event in log, status terminal) with a deadline, and after the loop assert the **outcome**, not the call count.

**Bad** (illustrative — not drawn from a current file; this repo's suite has no remaining bare-`sleep`-then-assert pattern):
```python
client.post(...)
time.sleep(0.2)
assert "agent.output" in [e["type"] for e in events]
```

**Good** (real — `tests/integration/api/test_native_tool_use.py:60-73`, `test_launcher_output_lines_emitted_as_agent_output`):
```python
# Poll on state, not time (rule 7): wait until the launcher completes
# and session.status_idle is appended to the log.
log_path = tmp_sessions_dir / f"{session_id}.jsonl"
deadline = time.monotonic() + 5.0
lines: list[dict] = []
while time.monotonic() < deadline:
    if log_path.exists():
        lines = [json.loads(ln) for ln in log_path.read_text().splitlines() if ln.strip()]
        if any(e.get("type") == "session.status_idle" for e in lines):
            break
    time.sleep(0.05)
assert any(e.get("type") == "session.status_idle" for e in lines), (
    f"expected session.status_idle within deadline; got types={[e.get('type') for e in lines]}"
)
```

The `else: pytest.fail(...)` after a `while` — or asserting outcome explicitly with a descriptive message — is what turns flakes into actionable failures.

### 8. Every test MUST terminate — no infinite waits, no unbounded loops

A test that hangs is worse than a test that fails: it freezes the suite, blocks CI, and burns developer time. The repo enforces this with `pytest-timeout` (`timeout = 15`, `timeout_method = "thread"` in `pyproject.toml`) — any test that exceeds 15 s real time is killed and reported as a failure.

This is the safety net, not the strategy. A test author MUST design every test to terminate well below the cap:

- Polling loops have a `deadline = time.monotonic() + N` and exit on the predicate or on the deadline (rule 7). Never `while True:`.
- Streaming tests bound the generator (rule 6 pattern 1) or read one frame and close with `@pytest.mark.timeout(5)` (rule 6 pattern 2). Never connect to an unbounded SSE generator and rely on `c.stream(...)` close to abort it.
- Subprocess / launcher tests use `ScriptedLauncher` from `tests/support/launchers.py`, which completes deterministically. Never spawn a real `claude` CLI.
- `asyncio` tests must not `await` on an `Event`/`Future` that no other task sets. If you cannot prove the awaited object will be resolved, use `asyncio.wait_for(..., timeout=N)` and make the timeout an assertion (`pytest.fail` on timeout, not silent retry).
- A test legitimately needing more than 15 s adds `@pytest.mark.timeout(N)` with a one-line justification comment. Global config is never relaxed.

The reviewer (and the `test-critic` agent) treats any of the following as automatic FAIL:

- `while True:` in a test
- `async for` over an iterator with no termination condition
- `c.stream(...)` against a route whose generator is unbounded by the test setup
- `time.sleep(...)` inside a loop with no deadline check
- `await some_future` with no `asyncio.wait_for` wrapper

If a hang reaches CI, root-cause it the same day; do not bump the global timeout to mask it.

---

## Pre-merge checklist

Before marking a PR with new tests as ready:

- [ ] Every new endpoint test has a negative twin (rule 1)
- [ ] No `assert x in (a, b)` or `assert ... or ...` in any new test (rule 2)
- [ ] No `Fake*` class defined inline in a test file (rule 3)
- [ ] Every `assert "k" in d` / `len(...) > 0` / `isinstance` has a value-level partner (rule 4)
- [ ] If the PR adds a `POST` / `PUT` endpoint with a JSON body, it has an OpenAPI contract test (rule 5)
- [ ] If the PR adds a streaming endpoint, it has an `httpx.AsyncClient` test (rule 6)
- [ ] No bare `time.sleep` followed by an assertion (rule 7)
- [ ] No `while True:`, no unbounded `async for`, no `c.stream(...)` against an infinite generator; every loop has a deadline; streaming tests use a bounded source or `@pytest.mark.timeout` (rule 8)
- [ ] If any hard rule from `CLAUDE.md` is touched, the test verifies the *property* (e.g., "token never appears in any log line") not the *implementation* (e.g., "the redact function was called")

If any box is unchecked, the test is debt. Fix it or document why this case is exempt in the PR body.

---

## How this is enforced

1. **`CLAUDE.md` hard rule 10** — points to this doc and forbids the worst patterns.
2. **`.claude/skills/write-test/SKILL.md`** — auto-loaded when Claude writes or modifies tests; embeds this checklist.
3. **`.claude/agents/test-critic.md`** — reviewer agent applied at `/work` step 7.5; mechanically checks each rule against the diff.
4. **`/work` step 7.5** — generator/critic loop: `write-test` agent → `test-critic` agent → re-iterate up to 3 times → AskUserQuestion if still not converged.
