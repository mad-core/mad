---
service: mad
domain: backend
section: conventions
source_of_truth: repo
---

# Testing Strategy

Mad's test suite asserts *contracts* — the hard rules in `CLAUDE.md` and the
HTTP/MCP acceptance criteria — not the shape of the type system. This page
documents the test layers, the eight testing heuristics every test must pass,
the coverage thresholds CI enforces, and the convention that all fakes live in
`tests/support/`.

The two load-bearing references are:

- [ADR-0001](../adr/0001-testing-strategy.md) — the layered testing strategy
  and coverage thresholds (`docs/adr/0001-testing-strategy.md`).
- [`docs/testing-heuristics.md`](../testing-heuristics.md) — the eight
  operational rules for writing a test that actually tests something. This is
  the canonical source; the summary below is a pointer, not a replacement.

## Test layers

The `tests/` tree is split into the layers ADR-0001 defines. Each layer has an
unambiguous home, resolved by the placement rules below.

```text
tests/
  unit/          # src/mad/core/ only — pure logic, no I/O
    core/        # sessions, events, orchestration bounded contexts
    adapters/    # adapter-level unit tests
    orchestration/
  integration/   # adapters + end-to-end HTTP composition (real disk/subprocess/git)
    api/         # HTTP routes via TestClient (test_sessions_http.py, ...)
    adapters/
    cli/
    orchestration/
    packaging/
    persistence/ # JSONL repo + recovery/rehydrate
  e2e/           # reserved for Behave BDD — deferred, not yet activated
  support/       # shared test doubles (fakes) — never imported from src/
  conftest.py    # shared fixtures (fake_launcher, client, bare_repo, ...)
```

- **Unit tests (`tests/unit/`)** target `src/mad/core/` exclusively: pure
  domain logic, value objects, and use cases. No I/O, no FastAPI, no
  `subprocess`, no real disk, no real git (ADR-0001 rule 1). Highest signal per
  test. The three bounded contexts (`sessions`, `events`, `orchestration`) each
  get their own subtree.
- **Integration tests (`tests/integration/`)** target adapters and end-to-end
  HTTP composition with real disk, real subprocess, and real git — via
  `tmp_path`, fake binaries, and local bare repos (the `bare_repo` fixture).
  They never hit the real `claude` CLI or real GitHub (ADR-0001 rule 2; hard
  rule 5). `integration/api/` is the highest-value surface: it maps 1:1 to
  acceptance criteria and includes the HTTP↔MCP parity gate
  (`test_http_mcp_parity.py`, hard rule 13).
- **End-to-end (`tests/e2e/`)** is reserved for Behave BDD journeys but is
  **deferred** — see `tests/e2e/README.md`. The integration suite currently
  covers the key journeys at the HTTP level.
- **Ports are not tested directly** (ADR-0001 rule 3) — they are interfaces,
  exercised through use cases (inbound) or adapters (outbound).
- **Architectural guards live in linters, not pytest** (ADR-0001 rule 4): the
  hexagonal boundary (no `fastapi` / `subprocess` / `mad.adapters` inside
  `mad.core`) is enforced by import-linter, not a test (ADR-0002).
- **Invariants are tested once, at the layer where they live** (ADR-0001
  rule 5): e.g. `MountPath` is exhausted in the domain layer; HTTP gets one
  smoke test per security invariant; the use case gets one negative test that
  the domain exception propagates.

## The eight testing heuristics

Every test must satisfy the eight rules in `docs/testing-heuristics.md`. A test
that violates them is debt, not coverage; reviewers (human and the `test-critic`
agent) reject it. Summary of each:

1. **Every endpoint test has a negative twin.** Any `*_happy_path` requires a
   sibling `*_rejects_<malformed>` that exercises a real failure mode (4xx for
   HTTP, a raised exception for use cases) and asserts the contractual error
   shape — status code AND body structure.
2. **One contract per test.** No `assert ... in (200, 202)` and no
   `assert ... or ...`. An assertion that accepts two status codes or two body
   shapes documents two contracts and validates neither. Pin the actual
   contract; if the code legitimately returns two shapes, write two tests.
3. **Fakes live in `tests/support/`, never inline.** A `Fake*` redefined inside
   a test file is a parallel re-implementation of the port that drifts from
   production silently. Shared fakes belong in `tests/support/<port>.py` and
   should be *stricter* than production where ambiguity exists.
4. **Weak assertion → specific assertion beside it.** `assert "k" in d`,
   `isinstance(x, list)`, and `len(x) > 0` prove shape, not value. Pair every
   weak assertion with a value-level assertion in the same test.
5. **JSON-body endpoints need an OpenAPI contract test.** Every `POST`/`PUT`
   route gets a test that opens `/openapi.json` and asserts the request body is
   `required`, references a named component schema, and that each required
   field appears. This is the mechanical guard against the "Postman shows no
   body schema" class of bug (hard rule 9).
6. **Streaming endpoints test the route with a bounded source — never the live
   infinite stream.** Test the route, not just the parsing helper, but do not
   connect a client to a server-side generator that yields forever
   (`httpx.AsyncClient.stream(...)` over `ASGITransport` against an unbounded
   `StreamingResponse` hangs on close). Preferred pattern: inject a bounded
   fake bus that yields a finite sequence and completes.
7. **Polling waits on state, never on time.** `time.sleep(0.2)` then
   `assert len(calls) == 2` is flaky and wrong — it passes because time
   elapsed, not because the system reached the right state. Poll on a state
   predicate with a deadline, then assert the *outcome* (event in log, status
   terminal), not the call count.
8. **Every test must terminate.** The repo enforces `pytest-timeout`
   (`timeout = 15`, `timeout_method = "thread"` in `pyproject.toml`) as a safety
   net; tests must be *designed* to finish well below the cap. Automatic FAIL:
   `while True:`, an unbounded `async for`, `c.stream(...)` against an
   unbounded generator, `time.sleep(...)` in a loop with no deadline, or
   `await some_future` with no `asyncio.wait_for` wrapper. A test that
   legitimately needs longer adds `@pytest.mark.timeout(N)` with a justifying
   comment; the global cap is never relaxed.

The full text — with bad/good examples and a pre-merge checklist — lives in
`docs/testing-heuristics.md`. Hard rule 10 in `CLAUDE.md` pins these rules at
the project level.

### The write-test ↔ test-critic loop

These heuristics are enforced mechanically, not just by convention (hard rule
10). The `/work` pipeline (Step 7.5) runs a generator/critic loop:

- The **`write-test`** agent writes or fixes tests under the heuristics.
- The **`test-critic`** agent — read-only — applies the eight rules to the test
  diff and returns a structured PASS/FAIL verdict with a per-finding
  `file:line` and rule number. It never edits and never runs pytest.
- The loop re-iterates up to 3 times; if it has not converged, the pipeline
  falls back to `AskUserQuestion`. Do not bypass it.

The `write-test` skill (`.claude/skills/write-test/SKILL.md`) is auto-loaded
whenever tests are written or modified.

## Coverage expectations

Coverage thresholds are enforced by the Makefile targets and by CI
(`.github/workflows/ci.yml`), not by `addopts`, so plain `pytest` stays cheap.
The thresholds actually enforced:

| Target | Scope | Source files | Fail-under |
|---|---|---|---|
| `make test-unit` | unit tests only | `src/mad/core/` | **94%** |
| `make test` | unit + integration | `src/mad/` | **90%** |

CI mirrors these exactly:

- `pytest -q tests/unit --cov=mad.core --cov-fail-under=94`
- `pytest -q --cov=mad --cov-fail-under=90`

`src/mad/entry_points/cli.py` is excluded from coverage (`[tool.coverage.run]`
`omit`) because it is a thin uvicorn launcher only exercised by `mad serve`.
Coverage runs with `branch = true`. (Note: an inline comment in
`pyproject.toml` mentions 95% / 92% targets — the binding numbers are the 94% /
90% in the Makefile and CI; the comment is stale.)

The thresholds intentionally differ by layer: `core/` is cheap to cover
thoroughly, so it carries the higher bar; adapters are integration-only and
expensive, so the full-suite bar is lower. The expected response to a coverage
gap is to delete dead code or write a test that *genuinely* exercises
orchestration — never a shallow mock-checking test that pads the number
(ADR-0001 Consequences).

## The fakes convention — fakes live in `tests/support/`

Test doubles live under `tests/support/` and are **never** imported from `src/`
(ADR-0003; testing heuristic 3). Production code carries no fixtures or fakes.
A fake redefined inline in a test file is a parallel re-implementation of the
port that stays green while production drifts (new `event_id`, timestamps,
redaction) — so fakes are centralized and shared, and should be *stricter* than
production where ambiguity exists, to fail loudly on contract drift.

Current shared doubles:

- `tests/support/launchers.py` — `AgentLauncher` test doubles that mock or
  script external agent behavior without spawning real processes (hard rule 5):
  - `ScriptedLauncher` — emits pre-scripted event sequences deterministically.
    Supports per-run conversation IDs and exception-raising runs for rate-limit
    retry tests.
  - `RecordingLauncher` — records every prompt and emits a single
    `session.status_idle` event per run; used when tests only care about
    *which prompts* the use case invokes.
  - `RaisingLauncher` — raises a fixed exception on every run; used to exercise
    dispatcher failure paths.
  - `GatedLauncher` — blocks until `release()` is called; used to assert that
    dependent workflow steps are held unqueued during predecessor execution.
- `tests/support/events.py` — `EventBus` / `EventLogQuery` doubles and an
  in-memory event store, so event-module tests share one implementation.
- `tests/support/sessions.py` — `FakeSessionRepository` (doubles as a
  `SessionRepository` and an `EventStore`) and `FakeProvisioner` (records
  workspace creation and resource materialization calls).
- `tests/support/orchestration.py` — orchestration-module doubles that script
  complex orchestration behavior without hitting real Git or network services:
  - `FakeGitInspector` — scripts baseline SHA and `GitResult` inspection; lets
    tests verify git-result events without touching a real repo.
  - `FakeModelCatalog` — scripts the model catalog discovery response; tests
    assert on `InvalidModelError` for unknown models without network calls.
  - `FakeTaskQueue` — scripts per-session queued and in-flight task state; used
    by workflow and rate-limit tests.
- `tests/support/clock.py` — a deterministic `FakeClock` double so scheduling
  tests advance time manually instead of wall-clock `time.sleep` (heuristic 7).

`tests/conftest.py` wires these into shared fixtures — `fake_launcher` (a
`ScriptedLauncher`), `client` (a `TestClient` built via
`create_app(launcher_factory=...)`), `bare_repo` (a local git bare repo used as
a clone source), `tmp_sessions_dir` (redirects the session log), and
`tmp_workspaces_dir` (redirects workspace paths to isolate tests). Tests inject
doubles through `create_app(...)`'s injectable defaults rather than
monkey-patching production modules.
