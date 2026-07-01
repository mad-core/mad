---
service: mad
domain: backend
section: conventions
source_of_truth: repo
---

# Code Quality

Mad's quality bar is enforced mechanically, not by vigilance. Linters / formatters
and the quality gates: ruff, mypy (strict on `mad.core`), import-linter
(architecture contracts), pre-commit, gitleaks, pip-audit (ADR-0002). Every gate is
configured once in `pyproject.toml` and run from three places that share that
configuration: the `Makefile` (local), `.pre-commit-config.yaml` (commit-time), and
`.github/workflows/ci.yml` (CI). The rationale, the rejected alternatives, and the
"what human error does each gate catch?" framing live in
[ADR-0002](../adr/0002-quality-tooling-bundle.md).

## The bundle at a glance

| Gate | Tool | What it enforces | Config |
|---|---|---|---|
| Lint + format | ruff | Style, imports, bug patterns, security subset | `[tool.ruff]`, `[tool.ruff.lint]` |
| Types | mypy | Strict typing on `src/mad/core` only | `[tool.mypy]` |
| Architecture | import-linter | Hexagonal boundary (`mad.core` is framework-free) | `[tool.importlinter]` |
| Commit hygiene | pre-commit | File invariants + ruff + mypy + gitleaks | `.pre-commit-config.yaml` |
| Secrets | gitleaks | No tokens / credentials committed | `.pre-commit-config.yaml` |
| Supply chain | pip-audit | No known CVEs in declared deps | CI `audit` job, `make audit` |
| Behavior + coverage | pytest / pytest-cov | Tests pass; coverage thresholds met | `[tool.pytest.ini_options]`, `[tool.coverage.*]` |

Run the whole local sweep with `make lint && make typecheck && make test && make audit`.

## ruff — lint and format

ruff replaces black, isort, flake8, bandit-lite, and pyupgrade with one fast tool.
It runs in two modes: `ruff check` (lint) and `ruff format` (formatter). Settings
(`[tool.ruff]`): `target-version = "py311"`, `line-length = 100`, `src = ["src",
"tests"]`, with `sessions/`, `venv/`, `build/`, `dist/`, and the bats temp dirs
excluded.

Selected rule families (`[tool.ruff.lint]`):

| Code | Family | Why |
|---|---|---|
| `E`, `F`, `W` | pycodestyle / pyflakes | Baseline correctness and style |
| `I` | isort | Import ordering (`known-first-party = ["mad"]`) |
| `UP` | pyupgrade | 3.11+ syntax |
| `B` | bugbear | Mutable defaults, bad except blocks |
| `SIM` | simplifications | Redundant constructs |
| `RUF` | ruff-specific | Misc ruff rules |
| `ASYNC` | asyncio bugs | We are heavily async |
| `S` | bandit security subset | Matters here — we spawn `subprocess` |

Project-wide ignores (`ignore`): `S101` (asserts are intentional), `S603`
(`subprocess.run` with an arg list is the safe form Mad uses), `S607` (partial paths
like `git` / `claude` resolved via `PATH` are fine).

Per-file ignores for `tests/**` (`[tool.ruff.lint.per-file-ignores]`): the whole `S`
family, `B011`, `E501` (tests inline JSON / URLs), `F841` (intentional `_ = ...`),
`RUF059` (tuple destructuring in fixtures), and `ASYNC110` (polling test state with
`while ...: await asyncio.sleep` is acceptable in tests).

CI runs `ruff check .` and `ruff format --check .` in the `quality` job; pre-commit
runs `ruff-check --fix` and `ruff-format` on changed files.

## mypy — strict on the core only

mypy runs with `strict = true` but scoped to `files = ["src/mad/core"]`
(`[tool.mypy]`, `python_version = "3.11"`, `ignore_missing_imports = true`,
`warn_redundant_casts`, `warn_unused_ignores`). The deliberate choice (ADR-0002 §2):
adapters and HTTP wrap FastAPI / stdlib dynamic surfaces where `--strict` produces
noise that hides real domain bugs, so the framework-free core is fully typed while
adapters lean on tests plus import-linter. CI invokes a bare `mypy` (picks up the
`pyproject.toml` config); pre-commit runs the `mirrors-mypy` hook constrained to
`^src/mad/core/`.

## import-linter — architecture contracts

import-linter is the executable form of CLAUDE.md hard rule 4 ("`mad.core` is
framework-free and adapter-free"). Configuration `[tool.importlinter]`:
`root_package = "mad"`, `include_external_packages = true`. There is one contract:

- **Name:** "mad.core is framework-free and adapter-free"
- **Type:** `forbidden`
- **Source modules:** `mad.core`
- **Forbidden imports:** `fastapi`, `mad.adapters`, `mad.api`, `mad.providers`,
  `subprocess`, `shutil`, `httpx`, `boto3`

This keeps the domain from reaching into frameworks, adapters, or I/O-heavy stdlib
that would betray the hexagonal boundary. Run with `make lint` (wraps `lint-imports`);
CI runs `lint-imports` directly in the `quality` job.

## pre-commit — the commit-time hook battery

`.pre-commit-config.yaml` pins three hook repos. Install once with `pre-commit
install`; run the full set with `make precommit`. CI re-runs the entire battery
(`pre-commit run --all-files`) so a local `--no-verify` bypass only postpones the
bill.

Hygiene hooks (`pre-commit/pre-commit-hooks` v5.0.0):

- `end-of-file-fixer` — exactly one trailing newline
- `trailing-whitespace` — no trailing whitespace
- `check-yaml`, `check-toml` — parse-validate config files
- `check-merge-conflict` — no leftover conflict markers
- `check-added-large-files` — `--maxkb=500`
- `check-case-conflict` — no case-only filename clashes

ruff hooks (`astral-sh/ruff-pre-commit` v0.15.12): `ruff-check --fix` and
`ruff-format`.

mypy hook (`pre-commit/mirrors-mypy` v1.13.0): `id: mypy`, scoped to
`files: ^src/mad/core/`.

gitleaks hook (`gitleaks/gitleaks` v8.21.2): `id: gitleaks`.

## gitleaks — secret detection

gitleaks blocks accidental secret commits and directly reinforces CLAUDE.md hard
rule 2 ("GitHub tokens never persisted"). It runs as a pre-commit hook on staged
changes and again in CI via the full pre-commit battery. ADR-0002 chose gitleaks over
TruffleHog for its lighter setup and git-staged-only mode.

## pip-audit — dependency vulnerabilities

pip-audit scans the project's declared dependencies against the PyPA Advisory
Database. Run locally with `make audit`; CI runs it as a dedicated `audit` job. The
exact invocation is `pip-audit --strict --skip-editable .` — `--strict` fails on any
finding, `--skip-editable` skips the editable in-tree package itself.

## Coverage thresholds

Coverage is collected by pytest-cov with branch coverage on (`[tool.coverage.run]`:
`branch = true`, `source = ["mad"]`). The thin uvicorn launcher
`src/mad/entry_points/cli.py` is omitted from coverage because it is only exercised by
`mad serve` / `make serve`, not the suite. Reporting (`[tool.coverage.report]`)
excludes `raise NotImplementedError`, `if TYPE_CHECKING:`, `...`, and
`pragma: no cover`.

Two thresholds are **actually enforced** — both the `Makefile` and
`.github/workflows/ci.yml` agree:

| Target | Scope | `--cov-fail-under` |
|---|---|---|
| `make test-unit` / CI "Unit tests" | `mad.core` (unit tests only) | 94 |
| `make test` / CI "Full suite" | `mad` (unit + integration) | 90 |

Coverage flags are passed via the Makefile / CI command lines, not `addopts`, so plain
`pytest` stays cheap and each threshold is explicit per target.

**Documentation drift — flag.** The comment block in `pyproject.toml`
(`[tool.pytest.ini_options]`, lines 120–124) claims `make test-unit` enforces ≥ 95%
on core and `make test` enforces ≥ 92% on `src/mad/`. Both the `Makefile`
(`--cov-fail-under=94` / `--cov-fail-under=90`) and CI enforce **94 / 90**, not
95 / 92. ADR-0002 §4 also states 94 / 90. The pyproject comment is stale; the
enforced numbers are 94 (core) and 90 (full). See ADR-0001 for the coverage rationale.

## Other test-suite invariants

Defined in `[tool.pytest.ini_options]` and reinforced by the testing heuristics
(CLAUDE.md hard rule 10, `docs/04-conventions/testing-heuristics.md`):

- `timeout = 15` (`timeout_method = "thread"`) — a hard per-test wall-clock cap so a
  hung SSE / polling / subprocess test fails instead of stalling the suite.
- `asyncio_mode = "auto"` — async tests need no explicit marker.
- `filterwarnings` — `DeprecationWarning` from `mad.*` is an error (fix, don't
  accumulate); third-party deprecations are tolerated until a deliberate upgrade.

## CI job layout

`.github/workflows/ci.yml` splits the gates into four parallel jobs so a failure
points at the broken gate:

- **quality** — `ruff check` + `ruff format --check`, `mypy`, `lint-imports`,
  `pre-commit run --all-files`.
- **test** — matrix on Python 3.11 and 3.12, running both coverage gates.
- **audit** — `pip-audit --strict --skip-editable .`.
- **build** — `python -m build` + `twine check dist/*`, gated on `quality` + `test`.

## See also

- [ADR-0002 — Quality tooling bundle](../adr/0002-quality-tooling-bundle.md) — the
  full decision, costs, rejected tools, and revisit triggers.
- [ADR-0001 — Testing strategy](../adr/0001-testing-strategy.md) — coverage rationale
  and heuristics.
- `docs/04-conventions/testing-heuristics.md` — the eight test heuristics (CLAUDE.md hard rule 10).
