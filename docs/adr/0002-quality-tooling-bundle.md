# ADR-0002 — Quality tooling bundle

- Status: Accepted
- Date: 2026-05-01

## Context

Mad needed a defensible answer to "what kinds of human errors does our automation catch before they reach `main`?" The repo handles GitHub tokens (CLAUDE.md hard rule 2), spawns external processes, and depends on a strict hexagonal boundary (hard rule 4). Without enforced gates, drift is a matter of when, not if.

Before this ADR there was: `pytest -q` + `git diff` review. Nothing that would catch a stray `subprocess` import inside `mad.core`, an accidentally committed `ghp_*` token, an unused-arg defect, a CVE in a dependency, or a regression in formatting.

The Python OSS ecosystem (FastAPI, Pydantic, httpx, Starlette, Anthropic SDK, Polars, uv, Litestar) has converged on a small set of tools. Picking from that set is cheap; picking outside it is expensive in maintenance and onboarding cost.

## Decision

Adopt the following bundle, all configured in `pyproject.toml` and wired through `Makefile` + `.pre-commit-config.yaml` + `.github/workflows/ci.yml`:

1. **ruff** (`ruff check` + `ruff format`) — single replacement for black, isort, flake8, bandit-lite, pyupgrade. Rule set: `E`, `F`, `W`, `I`, `UP`, `B`, `SIM`, `RUF`, `ASYNC`, `S`. The `S` (bandit) rules matter here because we run `subprocess`.
2. **mypy strict on `src/mad/core/` only.** Adapters and HTTP wrap framework dynamic surfaces; `--strict` there produces noise that hides bugs in the domain.
3. **import-linter** with one contract: `mad.core` may not import `fastapi`, `mad.adapters`, `mad.api`, `mad.providers`, `subprocess`, `shutil`, `httpx`, `boto3`. This is the executable form of CLAUDE.md hard rule 4.
4. **pytest-cov** with two thresholds (`make test-unit` ≥ 94% on core, `make test` ≥ 90% on the full tree). See ADR-0001.
5. **pre-commit** running: hygiene hooks (`end-of-file-fixer`, `trailing-whitespace`, `check-yaml/toml`, `check-added-large-files`, `check-case-conflict`, `check-merge-conflict`), ruff (check + format), mypy, and **gitleaks**.
6. **gitleaks** in pre-commit + CI to block accidental secret commits. Directly reinforces hard rule 2 ("tokens never persisted").
7. **pip-audit** as `make audit` and a CI job, scanning the project's declared dependencies against the PyPA Advisory Database.
8. **GitHub Actions** workflow split into four parallel jobs: `quality` (ruff + mypy + import-linter + pre-commit), `test` (matrix on Python 3.11/3.12 with both coverage gates), `audit` (pip-audit), `build` (sdist + wheel + twine check, gated on `quality` + `test`).

## Consequences

**Wins:**

- Every category of mistake the team realistically makes now has at least one automated tripwire: style/lint (ruff), types (mypy), architecture (import-linter), secrets (gitleaks), supply chain (pip-audit), behavior (pytest), coverage (pytest-cov).
- Reproducible locally (`make lint && make typecheck && make test && make audit`) and in CI from the same configuration source.
- Onboarding cost is low — the bundle is conventional. A contributor familiar with FastAPI / Pydantic / httpx will recognize every tool here.
- Tooling cost is small: ruff is <10× faster than the chain it replaces, pre-commit runs the hot path on changed files only.

**Costs:**

- One more tool list to keep updated (`pyproject.toml` `dev` extras, `.pre-commit-config.yaml` rev pins). When ruff or mypy releases a major, expect an afternoon of triage.
- mypy strict on `mad.core` constrains the domain to fully typed dicts and `asyncio.Queue[X]` annotations. New domain code must follow.
- pre-commit on every commit is friction; can be bypassed with `--no-verify`, but CI re-runs the same hooks so the bypass only postpones the bill.

**Explicitly rejected from the bundle:**

- `pylint` — redundant with ruff, slow, false positives.
- `bandit` standalone — its useful rules are already in ruff `S`.
- `vulture` — useful one-shot (we did one manually as part of this work) but low value as recurring CI.
- `black` / `isort` standalone — `ruff format` and `ruff check --select I` cover them.
- `commitizen` / `commitlint` — `python-semantic-release` already parses Conventional Commits; we accept the risk of a malformed message slipping through and being caught in code review.
- Markdown linting / link checking — the repo has minimal external docs; the value is too low for the toil.
- Mutation testing (`mutmut`, `cosmic-ray`) — devastatingly slow, marginal value at this size.

**Revisit if:**

- A token leak ever reaches `main` despite gitleaks. Either tune the rules or add a second-line scanner.
- pip-audit produces frequent false positives or misses real CVEs. Consider `safety` or GitHub's native Dependabot alerts as a complement.
- The pre-commit run time exceeds ~5s on a typical change. Profile and prune the hot hook.

## Alternatives considered

- **Keep `pytest -q` + manual review only.** Rejected: hard rules 2 and 4 deserve enforced gates, not vigilance.
- **Pyright/Pyrefly instead of mypy.** Pyright is faster but produces diff-noisy output when mixed with an editor running Pylance. Mypy is also better integrated with `import-linter` and the rest of the Python OSS toolchain. No reason to switch today.
- **TruffleHog instead of gitleaks.** TruffleHog has more entropy-based detection but heavier setup. Gitleaks's regex baseline + git-staged-only mode is a better fit for a single-user pre-commit hook.
- **Run all checks in a single CI job sequentially.** Rejected: parallelization keeps PR feedback under a couple of minutes, and the four jobs have genuinely different failure modes — collapsing them obscures which gate broke.
