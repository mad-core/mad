# CHANGELOG


## v0.3.0 (2026-05-04)

### Bug Fixes

- Include use_cases/sessions/ files missed by gitignore
  ([`c04c318`](https://github.com/jlsaco/mad/commit/c04c318c9d15399c5f277918ef683e0c0ea9d631))

The .gitignore had an unanchored 'sessions/' rule (intended for the runtime JSONL log directory at
  repo root), which silently matched src/mad/core/use_cases/sessions/ and excluded all six use case
  modules from the Phase 4 commit. Tests passed locally because the files existed on disk, but the
  previous commit (6995d5e) was missing them.

Anchor the rule to the repo root with '/sessions/' and add the use_cases/sessions/ directory.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

- **makefile**: Point serve target at the new adapters path
  ([`846274c`](https://github.com/jlsaco/mad/commit/846274ca2222a0dae2475aac676cd8923784666d))

The serve target still launched uvicorn against mad.api.app:create_app, which was removed in Phase 6
  of the hexagonal migration. Update it to mad.adapters.inbound.http.app:create_app so 'make serve'
  boots again.

Verified locally: GET /v1/sessions returns 200 against a fresh 'make serve PORT=...' instance.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

### Build System

- Configure ruff, mypy, import-linter, pytest-cov, pip-audit, pre-commit
  ([`4eebe83`](https://github.com/jlsaco/mad/commit/4eebe83af6d66f1f012449c96b043f69282b59f4))

Adds the full quality bundle described in .claude/memories/testing-heuristic.md:

- pytest-cov with two enforced thresholds: * make test-unit → ≥ 94% on src/mad/core (unit tests
  only) * make test → ≥ 90% on src/mad (unit + integration) Excludes src/mad/entry_points/cli.py
  from coverage (uvicorn launcher not exercised by the suite).

- ruff (check + format) replaces black, isort, flake8, bandit-lite. Rule set is deliberately scoped:
  E/F/W/I/UP/B/SIM/RUF/ASYNC plus S (security — matters since we run subprocess). Per-file ignores
  relax S, line-length, and unused-locals on tests/.

- mypy strict on src/mad/core only. Adapters wrap framework dynamic surfaces; --strict there
  produces noise that hides bugs in the domain.

- import-linter contract: mad.core is forbidden from importing fastapi, mad.adapters, subprocess,
  shutil, httpx, boto3, mad.api, mad.providers. Replaces the deleted
  tests/unit/core/test_no_framework_imports.py.

- pip-audit Make target for dependency vulnerability scanning.

- .pre-commit-config.yaml runs hygiene hooks (end-of-file-fixer, trailing-whitespace,
  check-yaml/toml, large-file/case-conflict guards), ruff (check + format), mypy on src/mad/core/,
  and gitleaks to block accidental secret commits (CLAUDE.md hard rule 2).

- New Make targets: lint, format, typecheck, audit, precommit, test-unit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

### Chores

- Remove spec-driven + TDD workflow tooling
  ([`4d22586`](https://github.com/jlsaco/mad/commit/4d22586d5629feab52dc49c3d7936747b809f6b1))

Drop the spec-author/spec-reviewer/test-author/implementer subagents and their /new-spec,
  /implement, /review-spec slash commands, and trim the matching workflow section from CLAUDE.md.
  The commit-stability criterion no longer references spec-reviewer.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Remove vestigial mad.agent module and anthropic_api stub
  ([`c420cdf`](https://github.com/jlsaco/mad/commit/c420cdfbed42dda75458fc931f25ee2a5b30076c))

Phase 0 of the hexagonal migration plan (docs/migration/phase-0-cleanup.md): drop unused vestigial
  code before restructuring. mad.agent was an empty package with no importers, and
  providers/anthropic_api.py was a NotImplementedError stub never wired into the factory. Adds a
  regression test that pins get_launcher rejection behavior.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

- **claude**: Add intake and work skills with search-issues agent
  ([`38600df`](https://github.com/jlsaco/mad/commit/38600df740fbbdb37f7b1741863e8c55f13e8685))

Introduces two project-level skills: - /intake: classify → search duplicates/blockers → fill
  template → create issue - /work: read issue → branch → plan → execute → commit → PR

Adds search-issues subagent (read-only GitHub issue search) used by /intake. Issue templates live in
  intake/resources/templates/ as canonical source.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **claude**: Add testing heuristic memory
  ([`618c7fd`](https://github.com/jlsaco/mad/commit/618c7fddf1597696f9779081c1ecbdf94f6dba31))

Documents the pragmatic testing rules for this hexagonal repo: unit tests target src/mad/core,
  integration tests cover adapters, ports are not tested directly, and architectural guards live in
  linters (not pytest). Establishes the coverage thresholds enforced by make test-unit (≥94% on
  core) and make test (≥90% on the full tree).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

- **claude**: Normalize skill frontmatter with name and argument-hint
  ([`a046478`](https://github.com/jlsaco/mad/commit/a04647855a4f3d4d19028a9da44d5ecf65586715))

Both intake and work now declare name, description, and argument-hint in consistent format (<arg>
  style).

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **claude**: Rewrite /commit with split rules and semantic-release awareness
  ([`5430305`](https://github.com/jlsaco/mad/commit/54303055809ae740613341df9c8057575e1e02d5))

Document conventional types and their release impact, generic scope derivation,
  mandatory-independent areas (.github/, .claude/, docs/, build config), Option A for tests (coupled
  with the code they verify), and plan-vs-auto mode driven by $ARGUMENTS.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **release**: 0.3.0 — finalize hexagonal layout (Phase 6)
  ([`505a59f`](https://github.com/jlsaco/mad/commit/505a59fb4e55a777df71111ac723fc4084d285fb))

Phase 6 of the hexagonal migration plan (docs/migration/phase-6-consolidation.md): close the
  residual debt from Phase 5 and bump the package to 0.3.0.

Composition root: - src/mad/adapters/inbound/http/dependencies.py exposes build_dependencies() and
  is now the single place that wires the in-memory SessionStore, the JsonlSessionRepository, and the
  LocalWorkspaceProvisioner. create_app() consumes it.

Decoupling: - SessionStore (mad.core.sessions) no longer imports mad.core.log; it is now a pure
  in-memory index of Session entities + SSE queues. The send_user_message use case owns the
  emit/persist flow via the injected SessionRepository port.

Removed shims and legacy packages: - src/mad/api/, src/mad/providers/ -
  src/mad/core/{log,resources,workspace,exceptions}.py

Tests: - conftest imports FakeLauncher from the canonical adapter location
  (mad.adapters.outbound.agents.fake) instead of redefining it. - tmp_sessions_dir patches only the
  adapter's SESSIONS_DIR. - test_session_recovery uses the new create_app import path. - The purity
  test forbids mad.adapters across the entire core/ tree now that no shim needs the exception.

Documentation: - CLAUDE.md sections "Package layout", "Key files", "Commands", and "AgentLauncher
  contract" rewritten to reflect the hexagonal tree. - tests/e2e/README.md updated with Behave
  activation notes.

108 passed, 0 xfailed. `pytest -m smoke` still 9 passed and the smoke files have not been
  functionally modified since Phase 1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

### Code Style

- Apply ruff format and pre-commit hygiene fixes across repo
  ([`8379730`](https://github.com/jlsaco/mad/commit/83797307102c8b1258230d5610fd79b8f83e4ba4))

First-time pass of the new tooling against existing files:

- ruff format normalizes whitespace, line continuations, and blank lines in src/ and tests/. -
  Trailing-whitespace and end-of-file-fixer hooks clean up markdown templates under .claude/ and
  .github/. - src/mad/entry_points/cli.py: rename loop variable token → arg to avoid bandit S105
  (the variable holds CLI args, not credentials), and add noqa S104 on the deliberate 0.0.0.0
  default for the uvicorn launcher. - src/mad/adapters/outbound/agents/claude_cli.py: split four
  over-length emit() calls onto multiple lines. - src/mad/core/security.py: drop the now-unused
  MountPath re-export. - tests/integration/api/test_sessions_http.py: replace try/except/pass with
  contextlib.suppress (ruff SIM105).

No behavior change.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

### Continuous Integration

- Add GitHub issue templates, PR template, and labels
  ([`83917bb`](https://github.com/jlsaco/mad/commit/83917bbfa66f28a282f4eca5691865c3a2950221))

Mirrors the canonical templates from .claude/skills/intake/resources/templates/ into
  .github/ISSUE_TEMPLATE/ for the GitHub web UI. Adds PR template and declarative labels.yml
  covering type/status/priority labels.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Extend workflow with lint, typecheck, coverage matrix, audit
  ([`dd8c5f2`](https://github.com/jlsaco/mad/commit/dd8c5f2b79b24d5932894614053b840e7d578c94))

Splits the previous single-job CI into four parallel jobs:

- quality: ruff check + format-check, mypy on mad.core, import-linter contracts, and the full
  pre-commit hook battery. - test: pytest matrix on Python 3.11 and 3.12, with coverage gates
  enforced in two passes (≥ 94% on mad.core via unit tests; ≥ 90% on mad via the full suite). -
  audit: pip-audit against the project's declared dependencies. - build: sdist + wheel + twine
  check, gated on quality + test.

Configures git user identity so the integration tests that clone bare repos do not fail on a clean
  runner.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

### Documentation

- Add AskUserQuestion hard rule and skills/agents section to CLAUDE.md
  ([`4b5766f`](https://github.com/jlsaco/mad/commit/4b5766f3e16243853664a16ce808fe0848229044))

Introduces hard rule 7 mandating AskUserQuestion for all user input, and documents the new
  skills/agents structure with the template sync rule.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Delegate commit policy to /commit slash command
  ([`d983a75`](https://github.com/jlsaco/mad/commit/d983a7564eeeb76d2dc58fe6ed5e862694f86fc3))

Replace the auto-commit policy section with a short pointer to .claude/commands/commit.md. Claude no
  longer commits on its own; commits happen only when the user invokes /commit.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Relax hard rules 4 and 5; record package layout in ADR-0003
  ([`ab93348`](https://github.com/jlsaco/mad/commit/ab9334810db50fd9c0c254cbe59f4223b8b84404))

Hard rule 4 previously inlined the entire `src/mad/` directory tree and hard rule 5 mandated a
  specific test fake (`FakeLauncher`). Both mixed genuine invariants (security, infrastructure-only
  stance) with conventions that evolve. Move the layout details and the test-doubles convention to
  ADR-0003; CLAUDE.md keeps only the load-bearing invariants (`mad.core` framework-free; tests never
  hit real `claude` CLI or GitHub).

Update the AgentLauncher contract section to reflect injection via
  `create_app(launcher_factory=...)` instead of monkey-patching, and add a Key files entry for
  `tests/support/`.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **adr**: Record testing strategy and quality tooling decisions
  ([`da4d7a9`](https://github.com/jlsaco/mad/commit/da4d7a94ad76b1f54cc187d3dfdd2c5b708dca41))

Adds docs/adr/ with the Michael Nygard format and the first two records:

- ADR-0001 captures the testing heuristic now codified in .claude/memories/testing-heuristic.md:
  unit tests on src/mad/core only, integration tests for adapters and HTTP, ports never tested
  directly, architectural guards in linters, and the 94% / 90% coverage gates.

- ADR-0002 captures the quality tooling bundle: ruff, mypy strict on mad.core, import-linter,
  pre-commit (with gitleaks), pip-audit, and the four-job CI layout. Lists alternatives explicitly
  rejected (pylint, bandit standalone, vulture, commitizen, mutation testing, markdown linting) so
  future contributors don't re-litigate them.

CLAUDE.md gains an "Architecture decisions" section pointing at the index, with the rule that
  disagreements become new ADRs rather than silent divergence.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

### Features

- **api**: Inject launcher_factory and relocate test doubles
  ([`3c4f322`](https://github.com/jlsaco/mad/commit/3c4f322a0f29e3b04da0c4e14997a0c81ad1d449))

Add a `launcher_factory` parameter to `create_app(...)` so tests inject scripted launchers via the
  composition root instead of monkey-patching `mad.adapters.outbound.agents.factory.get_launcher`.
  Production keeps the by-name extension point unchanged.

Other coupled changes folded into this commit:

- Move `FakeLauncher` from `src/mad/adapters/outbound/agents/fake.py` to
  `tests/support/launchers.py` as `ScriptedLauncher`. `src/` no longer ships test-only code. -
  Replace deprecated `@app.on_event("startup")` with a FastAPI lifespan context manager, eliminating
  76 DeprecationWarnings from the suite. - Drop the legacy `mad.core.security` shim;
  `MountPath._validate` is the canonical implementation and was already covered by
  `test_mount_path`. - Move adapter tests from `tests/unit/adapters/` to
  `tests/integration/adapters/` so the directory tree matches ADR-0001 (unit tests target `mad.core`
  only). - Add `tests` to `pythonpath` so `from support.launchers import ...` resolves under pytest,
  and treat `DeprecationWarning` originating in `mad.*` as errors to prevent silent deprecation
  drift.

BREAKING CHANGE: `mad.adapters.outbound.agents.fake.FakeLauncher` and
  `mad.core.security.validate_mount_path` are removed from the package. Tests should import
  `ScriptedLauncher` from `tests/support/launchers.py` and inject it via
  `create_app(launcher_factory=lambda name: launcher)`. Path validation should use
  `mad.core.domain.value_objects.MountPath`.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **core**: Introduce domain entities and use cases (Phase 4)
  ([`6995d5e`](https://github.com/jlsaco/mad/commit/6995d5e561ae2821e6e5f50673a21932f4597317))

Phase 4 of the hexagonal migration plan (docs/migration/phase-4-domain-and-usecases.md): the
  implicit dicts and strings that lived inside SessionStore and route handlers become explicit
  domain types, and each HTTP endpoint becomes a thin layer over a use case object that takes
  outbound ports by constructor injection.

Domain (src/mad/core/domain/): - entities/session.py — Session with mark_running/idle/error/deleted
  - value_objects/mount_path.py — frozen MountPath validated in __post_init__ -
  value_objects/agent_event.py — frozen AgentEvent - exceptions/base.py — DomainError,
  PathTraversalError, SessionNotFound (mad.core.exceptions kept as a DEPRECATED shim, removed in
  Phase 6)

Use cases (src/mad/core/use_cases/sessions/): - create_session, send_user_message, get_session,
  list_sessions, delete_session, stream_session_events

Hardening that closes the Phase 1 xfails: - send_user_message redacts known tokens from agent.output
  events before persisting / SSE — covers the "token not in stderr" gap. - get_session lazily
  rehydrates from the JSONL repository when the in-memory index is cold — covers the "session
  recovery after restart" gap. Both tests now pass without xfail.

Routes are now thin: src/mad/api/routes/sessions.py only parses HTTP in/out and delegates to use
  cases; SessionNotFound is mapped to 404 via an exception_handler in create_app.

107 passed, 0 xfailed. `pytest -m smoke` still 9 passed and the smoke files are unchanged (only the
  two xfail decorators were removed from non-smoke tests). Purity test extended to forbid framework
  imports under core/domain/ and core/use_cases/.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

- **core**: Introduce outbound ports (Phase 3)
  ([`199bb48`](https://github.com/jlsaco/mad/commit/199bb48a769fa3e35cd63d5a93cc82c048d7b8bb))

Phase 3 of the hexagonal migration plan (docs/migration/phase-3-extract-ports.md): define the
  contracts that the domain needs from the outside world, before moving any file. The
  implementations stay where they are; only the protocols are introduced and create_app accepts them
  by injection (with default factories), so behavior is unchanged.

New under src/mad/core/ports/outbound/: - agent_launcher.py — authoritative AgentLauncher Protocol -
  session_repository.py — append/read/exists for the JSONL log - workspace_provisioner.py —
  create/destroy/materialize_*

Adapters made structurally compliant (without moving): - mad.core.log.JsonlSessionRepository -
  mad.core.resources.LocalWorkspaceProvisioner - mad.providers.base now re-exports AgentLauncher
  from the canonical port (DEPRECATED shim, removed in Phase 5)

Tests: - tests/unit/core/ports/test_protocols.py — runtime_checkable conformance - purity test
  extended to forbid framework imports under core/ports/

65 passed, 2 xfailed. `pytest -m smoke` still 9 passed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

- **core**: Pin base_branch and run post-run auto-sync via second claude-cli invocation
  ([`d7f75f5`](https://github.com/jlsaco/mad/commit/d7f75f5d2322f0c85fca1c13427dfffeb3a297d4))

Closes #8

- Session entity carries an optional base_branch persisted across to_dict/from_dict. - CreateSession
  / HTTP route accept base_branch and forward it to the provisioner. - LocalWorkspaceProvisioner
  runs `git checkout <base_branch>` after clone and raises ValueError on unknown branch (mapped to
  HTTP 400). - SendUserMessage always launches a SECOND launcher.run after the primary run (success
  OR failure) with a fixed auto-sync instruction prompt; failures of the second run surface as
  session.error. - New auto_sync_prompt.build_auto_sync_prompt() renders the instruction with the
  session id and base_branch, instructing the agent to exclude .claude/settings.local.json and
  .claude/settings.json from any commit. - ScriptedLauncher records each call so tests can assert
  second-invocation prompt and workspace.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

### Refactoring

- Move physical layout to hexagonal adapters (Phase 5)
  ([`744dd7f`](https://github.com/jlsaco/mad/commit/744dd7f4533ade4aaa7d258b326f752abbbdbc6b))

Phase 5 of the hexagonal migration plan (docs/migration/phase-5-adapters-layout.md): physically
  relocate the HTTP transport, the JSONL persistence, the agent providers, and the CLI entry point
  into the target adapters/{inbound,outbound}/ tree defined by rules.md §2.

Moves (git mv where possible): - mad/api/app.py → mad/adapters/inbound/http/app.py -
  mad/api/routes/sessions.py → mad/adapters/inbound/http/routes/sessions.py -
  mad/providers/claude_cli → mad/adapters/outbound/agents/claude_cli.py - mad/providers/fake →
  mad/adapters/outbound/agents/fake.py - mad/providers/factory →
  mad/adapters/outbound/agents/factory.py - mad/cli.py → mad/entry_points/cli.py -
  subprocess/shutil/git logic from mad/core/resources.py and mad/core/workspace.py extracted into
  mad/adapters/outbound/persistence/local_workspace_provisioner.py - JSONL repository contract
  implementation extracted into mad/adapters/outbound/persistence/jsonl_session_repository.py

Console script in pyproject.toml now points at mad.entry_points.cli:main; create_app continues to be
  reachable as both `mad.adapters.inbound.http.create_app` and (via shim) `mad.api.app.create_app`
  for backwards compatibility during the remaining cleanup window.

Tests: 108 passed, 0 xfailed. `pytest -m smoke` still 9 passed and the smoke files were not
  modified. Purity tests continue to enforce that core/{domain,ports,use_cases}/ does not import
  frameworks or adapters.

Phase 6 will: extract a composition_root dependencies.py, break SessionStore's residual coupling to
  mad.core.log by injecting the SessionRepository port, and delete the remaining DEPRECATED shims
  (mad/api/, mad/providers/, mad/core/{log,resources,workspace}.py).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

- Remove dead code in core and persistence adapter
  ([`e5a23e9`](https://github.com/jlsaco/mad/commit/e5a23e9d44b80512eb8b216b0515690589bc85d0))

Drops three unused public surfaces flagged by the coverage audit: - AgentEvent value object —
  exported but never imported anywhere. - Module-level provision_github_repo / provision_file /
  local_path_for_mount in LocalWorkspaceProvisioner — superseded by the class methods used by the
  use case layer.

No behavior change. Keeps the canonical _resolve_mount helper and the class-based provisioner, which
  are the live paths.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

- **core**: Decouple FastAPI from domain (Phase 2)
  ([`aac70bc`](https://github.com/jlsaco/mad/commit/aac70bcd91acfaf4a4ef1e57dff8323f056c88c5))

Phase 2 of the hexagonal migration plan (docs/migration/phase-2-decouple-framework.md): the core no
  longer imports FastAPI. validate_mount_path now raises PathTraversalError, a pure DomainError
  subclass, and the HTTP adapter centralizes the translation to 400 via an exception_handler in
  create_app.

Adds: - src/mad/core/exceptions.py — DomainError + PathTraversalError -
  tests/unit/core/domain/test_security.py — domain-only unit coverage -
  tests/unit/core/test_no_framework_imports.py — purity test enforcing hard rule 4 (no framework
  imports under core/) at CI time

47 passed, 2 xfailed. `pytest -m smoke` still 9 passed; the smoke set files were not touched.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

- **core**: Tighten generic types for mypy strict mode
  ([`6793504`](https://github.com/jlsaco/mad/commit/679350470a173f1f92d4515362272902aaac2389))

Annotates the previously bare dict / asyncio.Queue parameters across ports, use cases, and
  SessionStore with their full element types (dict[str, Any], asyncio.Queue[Any]). Required to pass
  mypy --strict on src/mad/core/, which is now the enforced quality bar for the domain.

No runtime change — annotations only.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

### Testing

- Reorganize tests as hexagonal safety net (Phase 1)
  ([`b2c0d78`](https://github.com/jlsaco/mad/commit/b2c0d787117e5cb7ebb0e6e3441b0e973296ec66))

Phase 1 of the hexagonal migration plan (docs/migration/phase-1-tests-safety-net.md): restructure
  tests to mirror the target unit/integration/e2e layout from rules.md, register the 'smoke' marker
  for hard-rule invariants, and pre-emptively cover the gaps that Phase 4 will need (token redaction
  in launcher output, mount root rejection, JSONL session recovery — last two ship as xfail until
  the hardening lands).

Test layout: - tests/unit/adapters/providers/ (was tests/unit/providers/) - tests/integration/api/
  (sessions_http, security, native_tool_use) - tests/integration/persistence/ (jsonl_security,
  session_recovery) - tests/e2e/ (placeholder for Behave in Phase 6)

No src/ changes. 42 passed, 2 xfailed. `pytest -m smoke` runs the 9 canonical invariants covering
  hard rules 1, 2, 3, and 6.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

- **core**: Prune redundant unit tests and add async coverage
  ([`664aa37`](https://github.com/jlsaco/mad/commit/664aa37dcc5767559484fc98b6dbe128af482072))

Applies the heuristic in .claude/memories/testing-heuristic.md:

- Delete tests/unit/core/ports/ entirely. Protocol hasattr/isinstance tests verify the type system,
  not behavior; the real ports are exercised through use cases and adapters. - Delete
  tests/unit/core/test_no_framework_imports.py — moved to import-linter (added in the build commit)
  where architectural contracts belong. - Parametrize the five Session.mark_* transition tests; drop
  the trivial default-list test. - Drop empty-input and single-status list_sessions tests; one
  happy-path test covers both. - Collapse the three _redact_tokens duplicates into one parametrized
  test; add async tests for the SendUserMessage background task (lifecycle events + token redaction
  + error handling). - Add unit tests for SessionStore (queue creation, push noop) and
  StreamSessionEventsUseCase (queue rehydration, not-found). - Parametrize get_session
  lifecycle-event rehydration.

Net: 108 → 95 tests, with higher signal per test.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>


## v0.2.0 (2026-04-30)

### Continuous Integration

- **pypi**: Enable manual publishing via workflow dispatch
  ([`2e92c69`](https://github.com/jlsaco/mad/commit/2e92c692d88c35e3a483d6dd09c5c03166e997e6))

- **release**: Disable TestPyPI publishing and update dependencies
  ([`b261efb`](https://github.com/jlsaco/mad/commit/b261efb8bb876cd49e4344b1059a7bbfff66e450))

### Documentation

- **claude-cli**: Add comprehensive specification for provider implementation
  ([`4f2fb88`](https://github.com/jlsaco/mad/commit/4f2fb88435fcb3a8bacd2cad13078a66a88eb8dd))

Introduce detailed specs for the claude-cli provider feature, including README, requirements,
  design, and plan documents. These define the functional requirements, internal workings,
  subprocess lifecycle, error handling, and implementation guidelines to enable spec-driven
  development of the Claude CLI integration without modifying existing APIs or contracts. Covers
  authentication reuse, stream-json parsing, tool schema passthrough, and testing isolation
  constraints.

- **infra**: Rewrite spec to reflect infrastructure-only architecture
  ([`7eba26d`](https://github.com/jlsaco/mad/commit/7eba26dab64887a66017b1a849ecfb00e3a75c73))

- Remove FR-6 agent loop / FR-11 native tool use — Mad no longer manages conversation turns or
  executes tools on behalf of agents - FR-6 now describes launching an external agent process
  (Claude Code, etc.) that handles its own harness internally - FR-10 introduces the AgentLauncher
  protocol; claude_cli launches `claude --dangerously-skip-permissions -p "{prompt}"` in the
  workspace - design.md: replace Sandbox + Harness components with single Launcher; event vocabulary
  drops agent.message/tool_use/tool_result, adds agent.output - plan.md: Rule 8 documents
  AgentLauncher protocol; Rule 9 (native tool use) removed; out-of-scope section explicitly calls
  out task queue + scheduler as the next natural feature for Mad

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **specs**: Rename v0.1 to infra, revise claude-cli spec, add /commit command
  ([`1c42453`](https://github.com/jlsaco/mad/commit/1c42453421d9a994adffc06d17a593acd0316f44))

- Rename specs/v0.1/ → specs/infra/ and update all references in CLAUDE.md, README.md, agents, and
  commands - Revise specs/claude-cli/ design, requirements, and plan - Add
  .claude/commands/commit.md as a standalone /commit slash command

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Features

- **claude-cli**: Implement ClaudeCLI provider with timeout and cancellation
  ([`96ecfe3`](https://github.com/jlsaco/mad/commit/96ecfe31dbe98482cfbfe8730aee6bbe2c687ecf))

- Spawns `claude --dangerously-skip-permissions -p {prompt}` in workspace (FR-1 through FR-8) -
  Streams stdout line-by-line as agent.output events; scrubs sk-ant-* tokens from stderr on error -
  Separates TimeoutError (returns after emitting session.error) from CancelledError (re-raises per
  design spec)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **infra**: Realign codebase to infrastructure-only architecture
  ([`7471cb1`](https://github.com/jlsaco/mad/commit/7471cb13abebc182ad9d279944ad22ca3569a92c))

- Replace LLMProvider/ProviderResponse/ToolUse with AgentLauncher protocol - Implement
  ClaudeCLIProvider.run(): spawns claude --dangerously-skip-permissions, streams stdout as
  agent.output, handles timeout/error with token scrubbing - Replace FakeScriptedProvider with
  FakeLauncher for tests (scripted event sequences) - Replace run_agent_loop with _run_launcher in
  sessions route (background asyncio task) - Delete mad.agent.loop and mad.agent.tools (agent
  loop/tool execution removed from Mad) - Rewrite conftest, test_acceptance, test_security to use
  FakeLauncher - Add tests/unit/providers/test_claude_cli.py covering AC-1 through AC-5 - Update
  CLAUDE.md hard rules and AgentLauncher contract section

Covers FR-1 through FR-10 (specs/infra) and AC-1 through AC-5 (specs/claude-cli).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.1.0 (2026-04-15)

### Build System

- **pypi**: Rename package to mad-bros
  ([`fbb828c`](https://github.com/jlsaco/mad/commit/fbb828cc0e8501fa846725bb1d2d430cecc479e4))

Update PyPI project name from 'mad' to 'mad-bros' across release workflows, documentation, and
  project configuration. Modify build command to ensure build dependency installation. This rename
  aligns with the new project identity.

BREAKING CHANGE: Package name change requires users to install 'mad-bros' instead of 'mad'

### Chores

- Add Makefile with common targets
  ([`73e33d5`](https://github.com/jlsaco/mad/commit/73e33d585ba36dd59e2997cc97a2184d6487570e))

Wraps the day-to-day commands (install, test, serve, clean) behind `make` so operators and future
  Claude runs have a single entry point. Targets honor HOST=/PORT= overrides for `make serve`.
  CLAUDE.md and README now point at the Makefile as the source of truth for commands.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Continuous Integration

- Implement automated release pipeline with semantic versioning
  ([`f8eb874`](https://github.com/jlsaco/mad/commit/f8eb87491f1fa80e98f9db9d0f56d31b09a30803))

Add GitHub Actions workflows for CI builds, artifact verification, and automated releases using
  python-semantic-release. Configure pyproject.toml for packaging, dependencies, and release
  settings. Include Makefile targets for building and dry-run releases. Add CHANGELOG.md for version
  tracking and docs/releasing.md for release process documentation. Update .gitignore to exclude
  venv directories.

### Documentation

- Add initial project documentation and v0.1 specs
  ([`ee74d08`](https://github.com/jlsaco/mad/commit/ee74d082c04d2aec421a0abcf4c64f77aa726426))

Introduce comprehensive documentation for the Mad project, including an overview in README.md,
  future improvements in docs/backlog.md, sandbox hardening guide in docs/sandbox-bwrap.md, and a
  complete spec-driven development package for v0.1 in specs/v0.1/ covering requirements, design,
  API contract, and implementation plan. This establishes the project's foundation and guides
  development towards the first functional version.

- **v0.1**: Mandate src/mad/ package layout
  ([`92d5d17`](https://github.com/jlsaco/mad/commit/92d5d17f8460ec7215d86305105bd7cc14c93d36))

- Rewrite CLAUDE.md hard rule #4 from "Single-file MVP" to a package layout split by concern (api,
  core, agent, providers) with create_app(store=...) and no module-level globals; update Key files,
  Commands, and LLMProvider sections accordingly. - Update specs/v0.1 requirements NFR-1, plan rule
  2, and the design diagram so the spec no longer contradicts the new convention. - Update the 4
  subagents and /implement command to point at src/mad/ instead of app.py and to enforce the layout
  in reviews. - Extend README with an Install section (pip install -e .) and a project structure
  tree.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Features

- Initialize project infrastructure for Mad v0.1
  ([`1494569`](https://github.com/jlsaco/mad/commit/1494569f02344b9b0a923446f765801e37f728ec))

Add core components including Claude agent definitions, slash commands, CI pipeline, FastAPI app
  skeleton, test fixtures, and security tests. Establish spec-driven development workflow with TDD
  support, enforcing hard rules for token hygiene, path traversal prevention, and native tool use.

BREAKING CHANGE: Introduces new project structure requiring spec-first development process.

- **api**: Implement session management and provider interfaces
  ([`b232a75`](https://github.com/jlsaco/mad/commit/b232a756af10e05e32bfd8e635380bdb3f6c2aff))

Introduce core session lifecycle handling including creation, logging, and SSE streaming. Add stub
  implementations for ClaudeCLIProvider and AnthropicAPIProvider. Expand acceptance tests to cover
  MVP criteria such as repo cloning, event handling, and session resumption. Enhance security tests
  with comprehensive path traversal validations and token hygiene checks.

BREAKING CHANGE: Updates session response structure to include workspace and resources_mounted
  details. Requires client adjustments for new fields.

### Refactoring

- **v0.1**: Migrate app.py into src/mad/ package
  ([`c652791`](https://github.com/jlsaco/mad/commit/c652791e55f4f333ecaeb597b483eebcb7f65bf8))

Split the monolithic app.py into a pip-installable src/mad/ package: - mad.api: FastAPI app factory
  (create_app) + routes/sessions.py. No module-level globals; per-process state lives on a
  SessionStore held in app.state.store so every create_app() call is isolated. - mad.core: log,
  security (path validation), workspace, resources, sessions (SessionStore). - mad.agent: loop and
  tools (run_agent_loop takes the store as a parameter). - mad.providers: base (Protocol +
  ProviderResponse + ToolUse), factory, claude_cli, anthropic_api, fake (FakeScriptedProvider moved
  out of conftest so tests and production share one implementation). - mad.cli: `mad serve` console
  entry-point.

pyproject.toml gains build-system (hatchling), [project] metadata and dependencies, a `mad` console
  script, and pytest pythonpath=["src"]. Tests now import from mad.* and TestClient wraps
  create_app().

All 35 tests green. No functional changes — this is a pure refactor; FR-7 recovery, FR-10 provider
  stubs, and the sse-starlette gap are carried over from the previous state as pre-existing debt.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Breaking Changes

- **api**: Updates session response structure to include workspace and resources_mounted details.
  Requires client adjustments for new fields.

- **pypi**: Package name change requires users to install 'mad-bros' instead of 'mad'
