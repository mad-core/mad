---
service: mad
domain: backend
section: Operations
source_of_truth: repo
---

# CI/CD

How Mad is built, tested, and shipped. All pipelines live as GitHub Actions
workflows under [`.github/workflows/`](../../.github/workflows/). There is no
server "deploy" step: Mad is distributed as the `mad-bros` PyPI package that
operators self-host, so for Mad **"deploy" means "publish a release to PyPI."**
The artifact is the deliverable.

Two authoring patterns appear below:

- **Self-contained workflows** — `ci.yml`, `release.yml`, `testpypi-preview.yml`,
  `ai-develop-on-issue.yml` carry their own jobs and steps.
- **Thin callers** — `docs-validate.yml` and `docs-sync.yml` only declare a
  trigger and delegate to a reusable workflow in the central
  `mad-core/.github` repository. That is why their job bodies look empty (a
  single `uses:` line); the steps live in the reusable workflow, not here.

Publishing never stores a long-lived PyPI token. Every publish job uses
`pypa/gh-action-pypi-publish` with `permissions: id-token: write` and a GitHub
**Environment** (`pypi` or `testpypi`); PyPI's Trusted Publishing mints a
short-lived token from the repository's own OIDC identity at publish time.

Per-job step lists below omit the universal boilerplate — `actions/checkout`,
`actions/setup-python` (Python 3.11 unless noted, pip cache on), and
`pip install -e '.[dev]'` — and describe only the steps that gate or do work.

---

## Pull-request and push gates — `ci.yml`

**Trigger:** every `push` to `main` and every `pull_request` targeting `main`.
This is the gate that guards the branch. Four jobs run in parallel; `build`
waits on two of them.

### Job `quality` (Python 3.11)

The lint / type / architecture / secrets gate. Each step is an independent
tripwire (rationale in [ADR-0002](../adr/0002-quality-tooling-bundle.md)):

| Step | Command | What it enforces |
|---|---|---|
| ruff check + format | `ruff check .` then `ruff format --check .` | Lint and formatting. The active rule set is `E,F,W,I,UP,B,SIM,RUF,ASYNC,S` at line length 100 (`[tool.ruff]`). `S` is the Bandit security subset — it matters because Mad spawns subprocesses. `--check` fails on any unformatted file rather than rewriting it. |
| mypy (strict on `mad.core`) | `mypy` | Static types. Config (`[tool.mypy]`) sets `files = ["src/mad/core"]` with `strict = true`. The framework-free core is fully typed; adapters that wrap FastAPI/stdlib dynamic surfaces are deliberately left to tests + import-linter. |
| import-linter | `lint-imports` | The hexagonal boundary (CLAUDE.md hard rule 4). The `forbidden` contract in `[tool.importlinter]` fails the build if `mad.core` imports `fastapi`, `mad.adapters`, `mad.api`, `mad.providers`, `subprocess`, `shutil`, `httpx`, or `boto3`. This is the executable form of "core is framework-free and adapter-free." |
| pre-commit | `pre-commit run --all-files` | The full hook battery, including checks the steps above do **not** cover: file hygiene (end-of-file, trailing whitespace, YAML/TOML validity, merge-conflict markers, large files >500 KB, case conflicts) and **gitleaks** secret scanning — the CI-side enforcement of token hygiene (hard rule 2). It re-runs ruff and mypy too, so a local `--no-verify` bypass is caught here. |

### Job `test` (Python 3.11 and 3.12 matrix)

Behavior and coverage, on both supported interpreters.

- **Configure git identity** — the workspace-provisioning tests perform real
  `git clone`/`git` operations, which refuse to run without a configured
  `user.name`/`user.email`.
- **Unit tests + coverage on `mad.core`** —
  `pytest -q tests/unit --cov=mad.core --cov-fail-under=94`. The framework-free
  core must hold **≥ 94 %** line+branch coverage on its own.
- **Full suite + coverage on `mad`** —
  `pytest -q --cov=mad --cov-fail-under=90`. The whole tree (unit +
  integration) must hold **≥ 90 %**.

Coverage behavior comes from `[tool.coverage]`: `branch = true` (branch
coverage, not just line), `source = ["mad"]`, the thin uvicorn launcher
`src/mad/entry_points/cli.py` is `omit`ted (it is only exercised by `mad serve`,
never the suite), and `exclude_also` drops `...`, `if TYPE_CHECKING:`,
`raise NotImplementedError`, and `pragma: no cover` lines from the denominator.
The fail-under thresholds themselves live in the CLI flags (mirrored by
`make test-unit` / `make test`), not in `[tool.coverage]`. A hard 15 s
per-test `pytest-timeout` cap (`[tool.pytest.ini_options]`) makes a hung test
fail instead of stalling the job, and `filterwarnings` turns Mad's own
`DeprecationWarning`s into errors.

### Job `audit` (Python 3.11)

`pip-audit --strict --skip-editable .` — scans the project's declared
dependencies against the PyPA Advisory Database and fails on any known CVE.
`--skip-editable` skips the local editable install of Mad itself (only third-
party deps are audited). This job runs independently and is a required check,
but it does **not** gate `build`.

### Job `build` (Python 3.11, `needs: [quality, test]`)

Runs only after `quality` and `test` are green. Installs `build` + `twine`,
runs `python -m build` to produce the sdist and wheel (hatchling backend), then
`twine check dist/*` to validate metadata and the long-description rendering.
This is a build-integrity check — it proves the package assembles and is
publishable, but `ci.yml` does **not** upload or publish anything. (See
`testpypi-preview.yml` for the faithful build→publish→install round-trip.)

---

## Preview publishing — `testpypi-preview.yml`

**Trigger:** every `pull_request` to `main`, plus manual `workflow_dispatch`.
**Concurrency:** one in-flight preview per PR (`cancel-in-progress: true`) — a
new push supersedes the previous build instead of burning a TestPyPI version
number.

Purpose: publish a real, installable pre-release of the PR's exact built
artifact to TestPyPI so it can be `pip install`ed before it ever reaches the
real index. This exists because a past packaging bug (#50) only manifested in
the **built** sdist/wheel; an editable or `git+https` install rebuilds from the
source tree and silently masks it. The only faithful check is
build → publish → install-from-index → import.

- **Job `build`** — runs for same-repo branches and manual dispatch, but is
  **skipped for fork PRs** (forks never receive the OIDC identity Trusted
  Publishing needs, and publish rights should never be handed to fork-authored
  code). It derives a unique PEP 440 dev version `<base>.dev<run_id>` (run IDs
  are globally unique and monotonic, so re-runs and concurrent PRs never collide
  on TestPyPI's immutable namespace), patches `pyproject.toml` and
  `src/mad/__init__.py` ephemerally (never committed), builds, runs
  `twine check`, and uploads the `dist/` artifact. The version is exported as a
  job output.
- **Job `publish`** (`needs: build`) — gated on the operator opt-in variable
  `vars.TESTPYPI_ENABLED == 'true'`, so the workflow stays green before the
  TestPyPI publisher is configured. Publishes the artifact to TestPyPI via
  Trusted Publishing (Environment `testpypi`, OIDC).
- **Job `verify`** (`needs: [build, publish]`, same opt-in gate) — the real
  test. In a clean venv it resolves the exact wheel URL from TestPyPI's JSON API
  (retrying up to 12×15 s because TestPyPI indexing lags the upload), installs
  **that wheel** while letting every dependency resolve from real PyPI (pointing
  pip wholly at TestPyPI is unsafe — it hosts junk squats that shadow real deps),
  then runs the smoke import that #50 broke:
  `from mad.core.sessions import SessionStore; from mad.adapters.inbound.http.app import create_app; create_app()`.
  Finally it upserts a single PR comment with copy-paste install instructions
  (updating its previous comment rather than spamming new ones).

---

## Release and publish — `release.yml`

**Trigger:**

- `push` to `main`, **path-gated** to `src/mad/**`, `pyproject.toml`,
  `README.md`, and `LICENSE`. Bytes that never reach a PyPI consumer (skills,
  docs, tests, the CI workflows themselves, the `Makefile`, `CLAUDE.md`) do not
  match the gate, so a merge that touches only those paths **never even starts a
  release** — the cleanest enforcement of the package-centric versioning policy
  (CLAUDE.md hard rule 12; see next section).
- `workflow_dispatch` with two inputs: `manual_publish` (boolean) and
  `release_kind` (`auto` | `minor` | `major`).

**Concurrency:** grouped per workflow+ref with `cancel-in-progress: false` — a
release in flight is never cancelled.

### Job `release`

Runs on every qualifying `push`, and on `workflow_dispatch` when
`manual_publish` is **not** chosen. Checks out full history (`fetch-depth: 0`,
required by semantic-release to read the commit log), then:

1. **`pytest -q`** — the full suite runs one last time as the final gate before
   anything is tagged or published.
2. **python-semantic-release** — parses Conventional Commits since the last tag,
   computes the next version, writes the bump into `pyproject.toml` and
   `src/mad/__init__.py`, updates `CHANGELOG.md`, commits, tags `v{version}`,
   and creates the GitHub release (`contents: write`). On `workflow_dispatch` the
   `release_kind` value is passed through as semantic-release's `force` (an
   explicit `minor`/`major`); on `push`, and when `release_kind` is `auto`, that
   expression is empty and the version is derived from commits.
3. **Upload `dist/`** — only `if released == 'true'`. The job exposes
   `released`, `version`, and `tag` as outputs.

### Job `publish-pypi`

`needs: release`, runs only `if needs.release.outputs.released == 'true'`.
Downloads the `dist/` artifact and publishes to PyPI via Trusted Publishing
(Environment `pypi`, `id-token: write`). (A `publish-testpypi` twin exists in
the file but is commented out.)

### Job `manual-publish-pypi`

The escape hatch: runs only on `workflow_dispatch` with `manual_publish: true`.
Skips semantic-release entirely — builds the current tree as-is and publishes it
to PyPI. Used to recover from a release that built correctly but failed only at
the publish step.

---

## Versioning and release policy (hard rule 12)

Versioning describes the **package** a `mad-bros` consumer installs, not the
repo's internal churn. The pipeline enforces this at several layers so that
internal work never inflates the version or pollutes the changelog, and so that
minor/major bumps are always deliberate.

**1. Every eligible commit is a patch; minor/major are opt-in.**
`[tool.semantic_release.commit_parser_options]` sets `minor_tags = []` and
`patch_tags = ["feat", "fix", "perf"]`. With no type mapped to a minor bump,
`feat` is demoted to a patch — so on the current `0.x` line every public commit
auto-publishes a patch. A **minor or major** bump requires an explicit signal:
a `BREAKING CHANGE:` footer / `feat!:` style commit, or a `workflow_dispatch`
run with `release_kind: minor|major`. `major_on_zero = false` further means that
while the package is on `0.x`, even a breaking change produces a minor bump — it
will not silently jump to `1.0`.

**2. The release trigger is path-gated.** As above, only changes under
`src/mad/**`, `pyproject.toml`, `README.md`, or `LICENSE` start `release.yml`.
Internal-only merges produce no release at all.

**3. The changelog is consumer-facing only.**
`[tool.semantic_release.changelog]` `exclude_commit_patterns` drops
`chore`, `style`, `docs`, `test`, `refactor`, `ci`, `build`, and `revert`
commits from `CHANGELOG.md`. Those types still bump the patch version (they are
in `allowed_tags`) but never appear in release notes. To put an externally
visible refactor back into the changelog, author it as `feat!:` / `fix!:` so the
`!` reclassifies it.

**4. `feat`/`fix`/`perf` are restricted to public scopes.** Only the closed set
`{http, sse, cli, config, agents, deps}` may carry these types. Internal
bounded contexts (`core`, `events`, `sessions`, `domain`, `ports`) ship as
`refactor:` / `chore:` / `test:`. This is authored by the `/commit` flow and the
`commit-planner` agent, not by CI — but it is the convention the rules above
assume.

Other relevant `[tool.semantic_release]` settings: `branch = "main"`,
`tag_format = "v{version}"`, `upload_to_vcs_release = true`, a custom
`commit_message` of `chore(release): {version}`, the Conventional Commits
parser, and a `templates/` directory that renders changelog entries as a bare
`- <subject> ([hash](link))` (no body, no co-authors, no issue refs). Preview
the next computed version locally with `make release-dry`.

---

## Documentation gates — `docs-validate.yml` and `docs-sync.yml`

Both are **thin callers** to reusable workflows in the central
`mad-core/.github` repository, parameterized with `service_slug: mad`. The
trigger lives here; the steps live in the reusable workflow (hence the empty job
body in the skeleton).

- **`docs-validate.yml`** — on `pull_request` to `main`, calls
  `docs-validate.reusable.yml`. A **lint-only** gate: it validates the `/docs`
  structure but does **not** generate docs in CI. Documentation is authored and
  regenerated **locally** via the living-docs skill/commands, then committed —
  CI only checks the result.
- **`docs-sync.yml`** — on `push` to `main` (i.e. after merge), calls
  `docs-sync.reusable.yml` with the `DOCS_SYNC_TOKEN` and `ANTHROPIC_API_KEY`
  secrets. It mirrors this repo's `/docs` tree verbatim into the central
  `mad-core/mad-docs` repository under `raw/<service_slug>/`, via a correlated
  PR. This is how per-service docs are aggregated into the shared docs site.

---

## AI development on issues — `ai-develop-on-issue.yml`

**Trigger:** an issue being `labeled` or `opened`. **Concurrency:** one run per
issue (`cancel-in-progress: true`), so re-applying the label cancels any
in-flight run rather than duplicating work. Two gates must both pass or the run
is a no-op:

- **Job `gate`** — runs only `if` the issue carries the `ai:auto-develop` label
  (the cheap label gate first). It then checks the issue **author** against the
  `AI_DEVELOP_ALLOWLIST` repository variable, so arbitrary contributors cannot
  trigger automated execution. If eligible, it derives the branch name using the
  `/work` convention `<type>/<issue-number>-<slug>` (type taken from a
  `type: …` label, default `feat`) and exposes `eligible` + `branch` as outputs.
- **Job `develop`** (`needs: gate`, `if eligible == 'true'`) — checks out full
  history, configures a git identity, resolves the issue branch (reusing the
  remote branch if it exists, else creating and pushing it), then runs
  `anthropics/claude-code-action@v1` with `--dangerously-skip-permissions`. The
  agent owns the entire git flow inside the action (commit, push, open a
  non-draft PR closing the issue) — deliberately, because auth configured by
  `checkout` is only live during the action, and a later step would run after it
  was torn down. Per token hygiene (hard rule 2), the `CLAUDE_CODE_OAUTH_TOKEN`
  is referenced only as a secret expression and never echoed or written to the
  workspace.

---

## Reproducing the gates locally

The CI gates are reproducible from the same configuration source via the
`Makefile`, so failures can be triaged before pushing:

| CI gate | Local equivalent |
|---|---|
| `quality` (ruff + import-linter) | `make lint` |
| `quality` (mypy) | `make typecheck` |
| `quality` (pre-commit + gitleaks) | `make precommit` |
| `test` (core, ≥ 94 %) | `make test-unit` |
| `test` (full tree, ≥ 90 %) | `make test` |
| `audit` | `make audit` |
| `build` | `make build` |
| next release version | `make release-dry` |
