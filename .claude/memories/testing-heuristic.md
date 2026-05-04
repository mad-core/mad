---
name: Testing heuristic — Mad
description: Pragmatic-but-complete heuristic for what to test (and what NOT to test) in this hexagonal Python repo. Anchors unit tests to the core, integration tests to the adapters, and rejects banal/redundant tests.
type: feedback
---

# Testing heuristic — Mad

This document is the **single source of truth** for test scope, placement, and coverage thresholds in this repo. Apply it on every new test, every PR review, and every refactor of the test suite.

## TL;DR

- **Unit tests target `src/mad/core/` exclusively.** No I/O, no FastAPI, no subprocess, no real disk, no real git. Required coverage: **≥ 94%** on `src/mad/core/`.
- **Integration tests target adapters and end-to-end composition.** Real disk, real subprocess, real git via tmp_path / fake binaries / bare repos — never the real `claude` CLI or real GitHub. Required combined coverage (unit + integration over the full `src/mad`): **≥ 90%**.
- **Ports are not tested directly.** They are interfaces; they are exercised through use cases (inbound) or adapters (outbound).
- If a test does not satisfy one of the rules below, **it should not exist**. Delete it.

## What to test, by layer

### Domain (`src/mad/core/domain/`) — entities, value objects, domain exceptions

- **Always with unit tests.** Pure logic, zero dependencies. Highest signal-to-cost ratio in the suite.
- Test invariants and rejection rules (e.g. `MountPath` rejecting `/etc/passwd`), state-transition rules **only when the entity actually enforces them** (not trivial setters), and serialization round-trips that protect security invariants (e.g. `to_dict` excluding tokens).
- **Do not** write a test per trivial setter or default value. Parametrize transitions instead.

### Use cases (`src/mad/core/use_cases/`) — application services

- **Unit tests with hand-rolled fakes/stubs of the ports.** Ports are contracts; fake them in-memory. Never reach for real implementations or HTTP from a use-case test.
- Test the orchestration: the use case calls the right ports in the right order, raises the right domain exceptions, emits the right events.
- **Do not** test that a fake was called with arguments the use case literally just received — that is testing the mock, not the behavior. Prefer asserting observable outcomes (events appended, session state, returned DTO).

### Ports (`src/mad/core/ports/`) — Protocol interfaces

- **Do NOT write tests for ports directly.** No `hasattr`, no `isinstance` against `Protocol`, no "typed variable assignment compiles" tests. Static typing (mypy/pyright) and the use-case + adapter tests already cover this.
- A test in `tests/unit/core/ports/` is a smell. If it exists, it likely belongs to the adapter or the use case.

### Adapters (`src/mad/adapters/`) — outbound infra and inbound HTTP

- **Integration tests, not unit tests.** Mocking the thing the adapter wraps (the DB, the subprocess, git) reduces the test to "verify we called the SDK we wrote a wrapper around" — low value.
- Drive real behavior with realistic stand-ins:
  - `JsonlSessionRepository`, `LocalWorkspaceProvisioner` → `tmp_path` and a local bare repo (`bare_repo` fixture).
  - `ClaudeCLIProvider` → fake executable scripts in `tmp_path` plus `MAD_CLAUDE_CLI_BIN`. Never the real `claude` CLI.
  - HTTP routes → FastAPI `TestClient` with `FakeLauncher` and bare repos (per CLAUDE.md hard rule 5).
- The HTTP suite should map 1:1 to acceptance criteria from the spec. Each endpoint deserves: happy path + the one or two error paths that exist in the spec (404, 400). No more.

## Decision tree — write the test, or don't?

Apply in order. Stop at the first hit.

1. **Does the test verify a CLAUDE.md hard rule or a spec acceptance criterion?**
   → Write it. These are the executable documentation of the project's contract.
2. **Does the test verify a domain invariant a human could plausibly break?**
   (security validation, redaction, state transitions with real rules, JSONL log shape)
   → Write it. **Once. At the lowest layer where the invariant actually lives.**
3. **Does the test verify an adapter's observable contract against a realistic stand-in?**
   (subprocess + tmp_path, real disk, real git on a bare repo)
   → Write it. One test per behavior, not per branch of the wrapped library.
4. **Does the test verify HTTP → use-case → ports composition end-to-end?**
   → Write it. Happy path per endpoint + a small handful of error edges.
5. **None of the above** → do not write the test.

## Reject these test patterns

- `hasattr(x, "method")`, `callable(x.method)`, `isinstance(x, SomeProtocol)`, `x: SomeProtocol = Impl()` — type-system noise.
- Tests that duplicate an invariant already covered at a lower layer (if `MountPath` rejects `/etc/passwd` in domain, you do **not** also test it in use case **and** in HTTP — keep domain exhaustive + one HTTP smoke).
- Tests of trivial getters/setters or default constructor values.
- Tests asserting that a mock was called with the literal arguments the SUT just received.
- N near-duplicate test functions that should be one `pytest.mark.parametrize`.
- "It imports without crashing" / "the protocol is a protocol" tests.

## Pencil-red rule

If you delete the production line a test covers and **another test already fails**, the first test is redundant — delete it.

## Placement rule

The invariant is tested at the layer where it **lives**, not at every layer it traverses.

- `MountPath` validation lives in domain → exhaustive tests in `tests/unit/core/domain/`.
- HTTP gets **one** smoke test per security invariant proving the 400 reaches the wire.
- Use cases get a single negative test confirming the domain exception propagates.

## Architectural guards live in the linter, not in pytest

The hexagonal boundary (CLAUDE.md hard rule 4 — `mad.core` cannot import FastAPI, adapters, `subprocess`, etc.) is enforced by **import-linter** via `[tool.importlinter]` in `pyproject.toml`. Run with `make lint`.

Do NOT re-implement this as a pytest test. Static structural rules are linter responsibility; mixing them into the test suite confuses concerns and inflates the test count without exercising any behavior.

If a new architectural rule appears (e.g. "use_cases cannot import each other"), express it as a new contract in `pyproject.toml`, not as a test.

## Coverage thresholds (enforced by CI / `make`)

- `make test-unit` → runs `tests/unit/`, measures coverage on `src/mad/core/`, fails under **94%**.
- `make test` → runs the full suite (unit + integration), measures coverage on `src/mad`, fails under **90%**.

If a number falls under threshold, the right move is almost always to delete dead code or write the missing **integration** test — not to pad the unit suite with shallow tests.

**Why:** mocked-DB unit tests on adapters were what we were trying to avoid. The thresholds reflect that: core is held to a high bar because it is pure and cheap to cover; the rest is held to a sane bar via integration tests that exercise real infrastructure.

**How to apply:** when adding a new file under `src/mad/core/`, add a unit test the same PR. When adding a new adapter, add an integration test the same PR. When a test would live in `tests/unit/core/ports/` or duplicate an HTTP-layer security check, push back and remove it before merge.
