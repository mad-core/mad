# ADR-0001 — Testing strategy and coverage thresholds

- Status: Accepted
- Date: 2026-05-01

## Context

The test suite had grown to 108 tests against ~1.5k LOC of production code (ratio 1.5×) but the distribution was wrong: a non-trivial fraction of tests verified the type system (`hasattr`, `isinstance` against `Protocol`, "typed-variable assignment compiles") or duplicated the same invariant across three layers (domain → use case → HTTP). Adding new tests felt expensive without clear signal about which layer the new test belonged in.

Mad is a hexagonal Python project: pure domain in `src/mad/core/`, infrastructure in `src/mad/adapters/`. The forces in play:

- The domain is pure logic — easy to unit-test, very high signal per test.
- Adapters wrap subprocess, git, FastAPI, the local filesystem. Mocking them produces tests that verify "we called the SDK we wrote a wrapper around" — low value.
- CLAUDE.md hard rules (token hygiene, path traversal, log as source of truth) are the *contract* of the project and must remain executably enforced.
- The HTTP suite already maps 1:1 to acceptance criteria from the spec; that is the highest-value test surface and should not be diluted.

## Decision

Adopt an explicit, layered testing heuristic — codified in `.claude/memories/testing-heuristic.md` — with the following load-bearing rules:

1. **Unit tests target `src/mad/core/` exclusively.** No I/O, no FastAPI, no subprocess, no real disk, no real git.
2. **Integration tests target adapters and end-to-end HTTP composition.** Real disk, real subprocess, real git, via `tmp_path` / fake binaries / bare repos. Never the real `claude` CLI or real GitHub.
3. **Ports are not tested directly** — they are interfaces, exercised through use cases (inbound) or adapters (outbound).
4. **Architectural guards live in linters, not in pytest.** The hexagonal boundary (no `fastapi`/`subprocess`/`mad.adapters` inside `mad.core`) is enforced by `import-linter` (see ADR-0002).
5. **Invariants are tested at the layer where they live, once.** `MountPath` is exhaustively tested in domain; HTTP gets one smoke test per security invariant; the use case gets one negative test confirming the domain exception propagates.
6. **Coverage thresholds, enforced by `make`:**
   - `make test-unit` → ≥ 94% on `src/mad/core/` (unit tests only).
   - `make test`     → ≥ 90% on `src/mad/`     (unit + integration).
   - `src/mad/entry_points/cli.py` is excluded from coverage (uvicorn launcher, only exercised by `mad serve`).

## Consequences

**Wins:**

- Test count dropped from 108 to 95 while raising core unit coverage from 84% to 96.87% and full coverage to 94.51%. Higher signal per test.
- Each new test has an unambiguous home — the heuristic's decision tree resolves "where does this go?" in seconds.
- The test suite stops mirroring production code line-for-line and starts asserting *contracts* (hard rules + acceptance criteria).
- Type-system / structural assertions are off the table for pytest — they belong in mypy and import-linter.

**Costs:**

- The 94% / 90% thresholds will fight us when adding non-trivial async paths in core that are most naturally exercised through the HTTP layer. The expected response is to either delete dead code (preferred) or write a small async unit test that *genuinely* exercises orchestration — never a shallow mock-checking test that pads the number.
- Contributors must internalize the placement rule. The heuristic memory is the canonical reference; CLAUDE.md links to it.

**Revisit if:**

- We add a second deployment surface that runs without the FastAPI app (e.g. a CLI agent runner). The "integration tests use TestClient" assumption may need extension.
- The async machinery in `core/use_cases/sessions/` grows substantially. A dedicated async-orchestration test fixture may earn its keep.

## Alternatives considered

- **Keep the existing suite, write more tests to lift coverage to 90%.** Rejected: most of the gap was in async lifecycle paths and dead code; padding the suite with shallow tests would make the signal worse.
- **Single uniform threshold over `src/mad/` (e.g. 92%) with no layered rule.** Rejected: collapses the meaningful distinction between *core* (cheap to cover thoroughly) and *adapters* (expensive, integration-only).
- **Delete the architectural guard test entirely with no replacement.** Rejected: hard rule 4 needs an executable enforcement point. Moved to import-linter (ADR-0002), not removed.
- **Leave the architectural guard as a pytest test.** Rejected: it is a static structural rule, not a behavior assertion. Mixing them inflates the test count and confuses concerns.
