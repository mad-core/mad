---
description: Structured commit of modified files following project conventions, with automatic splitting into independent commits when appropriate.
argument-hint: [optional hint, full conventional message, or --plan / --auto]
---

Create one or more commits for the current working tree. Optional hint: $ARGUMENTS

The repo uses **python-semantic-release** (see `pyproject.toml [tool.semantic_release]`) on push to `main`. Only `feat`, `fix`, `perf` and breaking changes trigger a release; the others land without bumping the version. Every commit produced by this command MUST be a valid Conventional Commit so the parser can do its job.

Follow the steps in order. Do NOT skip any.

---

## Step 1 — Inspect changes

Run `git status` and `git diff` (staged + unstaged) to see every modified, added, and deleted file. Read enough of the diff to understand the nature of each change.

If there are no changes, stop and tell the user there is nothing to commit.

## Step 2 — Verify stability

Run `pytest -q`.

If tests fail, stop immediately. Do NOT commit. Report which tests failed and what blocks stability, then leave the working tree as-is. The user fixes the failures before re-invoking.

If tests pass, proceed.

## Step 3 — Decide mode (plan vs auto)

Inspect `$ARGUMENTS`:

| `$ARGUMENTS` content | Mode |
|---|---|
| empty, or vague text (e.g. `"avances"`, `"wip"`) | **plan** — propose split, wait for approval |
| explicit `--plan` flag | **plan** |
| explicit `--auto` flag | **auto** — execute the split directly |
| a full Conventional Commits message (e.g. `fix(core): reject absolute mount_path`) | **single-commit auto** — do NOT split, use the hint as the message verbatim, stage all changes, commit once |
| specific intent that names types/scopes (e.g. `"feat api + test + ci"`) | **auto** — split as instructed |

In **plan mode**, after Step 4 you present the plan and stop. Only continue to Step 5 after the user approves (e.g. "ok", "sí", "go"). In **auto mode**, continue straight through.

## Step 4 — Build the commit plan

Group the changed files into one or more commits using the rules below. Each group becomes one commit.

### 4.1 — Conventional Commits types

Use exactly these types. The "release" column shows what python-semantic-release does with them.

| Type | When | Release impact |
|---|---|---|
| `feat` | new user-visible functionality | minor (or major if breaking) |
| `fix` | bug fix | patch |
| `perf` | performance improvement, no behavior change | patch |
| `refactor` | internal restructure, no behavior change | none |
| `docs` | docs only (`docs/`, `*.md`, docstrings-only diffs) | none |
| `test` | tests only (see 4.4 — most test changes do NOT use this type) | none |
| `build` | packaging, deps, `pyproject.toml` build config | none |
| `ci` | `.github/workflows/`, CI scripts | none |
| `chore` | tooling, repo housekeeping, `.claude/`, linters config, Makefile chores | none |
| `style` | formatting only, no code change | none |
| `revert` | reverts a previous commit | matches reverted commit |

**Breaking changes:** mark with either form (or both):
- `!` after type/scope: `feat(api)!: drop create_app(positional_store)`
- Footer: `BREAKING CHANGE: <impact and migration note>`

While the project is in `0.x` (`major_on_zero = false`), breaking changes bump the minor, not the major.

### 4.2 — Scope (generic, derived from paths)

Derive the scope from the most-affected path:

- `src/mad/<area>/...` → scope = `<area>` (`api`, `core`, `providers`, …)
- `src/mad/providers/<name>.py` → scope = provider name (`claude-cli`, `fake`)
- `tests/...` for a `feat`/`fix` commit → scope = the area under test, NOT `tests`
- Root infra (`pyproject.toml` deps/build, `Makefile`, linter configs) → `build` or `chore` with no scope, or scope `repo`
- `.github/...` → type `ci`, no scope
- `.claude/...` → type `chore`, scope `claude`
- `docs/`, root `*.md` → type `docs`, no scope (or scope = section)
- Multiple unrelated areas in one logical change → omit scope

Scope is a free string. Do not invent scopes that don't reflect the actual paths touched.

### 4.3 — Splitting rules

Group files into separate commits whenever any of these apply:

1. **Different type.** A `feat` and a `chore` are always separate commits, even if touched in the same session.
2. **Mandatory-independent areas.** Each of these gets its own commit, regardless of what else changed:
   - `.github/` → `ci:`
   - `.claude/` → `chore(claude):`
   - `docs/` and root `*.md` → `docs:`
   - Linter / formatter / `pyproject.toml` config-only changes → `build:` or `chore:`
3. **Different `src/mad/` area only when the changes are independent.** If a single `feat` touches `api` + `core` + `providers` because they are coupled, keep it as ONE commit and omit the scope. Do not fragment a coherent change.

There is no upper bound on the number of commits per invocation.

### 4.4 — Tests: Option A (coupled by necessity)

Tests that **directly verify** a `feat` / `fix` / `perf` go in the **same commit** as the production code they verify. Heuristic: *if the new/changed test would fail without the `src/` change in this diff, it belongs with the `src/` change.*

A standalone `test:` commit is used ONLY when the test changes are independent of any production change in this diff:
- new fixtures or test helpers reused across suites
- refactor of existing tests with no behavior change
- adding coverage for code that already existed before this session
- test infrastructure (conftest, markers, CI test config — though CI config goes under `ci:`)

Rationale: every commit must pass `pytest -q` on its own, so `git bisect` works.

### 4.5 — Mixed concerns inside a single file

If one file mixes concerns across types (e.g. a `feat` change plus an unrelated `chore` cleanup in the same file), commit the **whole file** under the dominant type. Do NOT use `git add -p` or hunk-level staging. Mention the mix in the final summary so the next session aisles work better.

### 4.6 — Message format

```
<type>(<scope>)<!?>: <imperative one-line summary, ≤72 chars>

<optional body — what and why, wrapped at ~72 chars>

<optional footers>
Closes #123
Refs #45
BREAKING CHANGE: <impact + migration note>
Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

The `Co-Authored-By` trailer is mandatory on every commit.

If `$ARGUMENTS` references an issue (e.g. `"closes #12"`), include the corresponding `Closes #12` footer.

### 4.7 — Plan output (plan mode only)

Present the plan as a numbered list, one entry per proposed commit:

```
1. feat(providers): add claude-cli launcher with timeout
   files:
     - src/mad/providers/claude_cli.py
     - src/mad/providers/factory.py
     - tests/unit/providers/test_claude_cli.py
2. ci: bump setup-python to v5
   files:
     - .github/workflows/ci.yml
3. docs: document MAD_CLAUDE_CLI_TIMEOUT_S
   files:
     - CLAUDE.md
     - docs/backlog.md
```

Then stop and wait for explicit approval before Step 5.

## Step 5 — Execute commits

For each group in the plan, in order:

1. `git add <file1> <file2> ...` — list every file explicitly. Never `git add -A` or `git add .`.
2. `git commit` with the message from Step 4.6, passed via heredoc to preserve formatting:

   ```
   git commit -m "$(cat <<'EOF'
   feat(api): inject SessionStore into create_app

   Removes module-level globals from the FastAPI factory so each test
   builds its own isolated store.

   Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
   EOF
   )"
   ```

3. After the commit, run `pytest -q` again **only** if the split included a `test:` commit AFTER a `src/` commit (i.e. tests were separated under rule 4.4). This catches Option-A violations. If it fails, stop and report — do not attempt to fix automatically.

Hard constraints, never negotiable:
- Never `git push`.
- Never `git commit --amend`.
- Never `git commit --no-verify`.
- Never `git add -A` or `git add .`.

## Step 6 — Confirm

Show, in order, the hash and subject line of every commit created:

```
abc1234 feat(providers): add claude-cli launcher with timeout
def5678 ci: bump setup-python to v5
9012345 docs: document MAD_CLAUDE_CLI_TIMEOUT_S
```

If any file in the working tree was intentionally NOT committed (e.g. untracked junk, secrets, in-progress work), list it under "skipped" with a one-line reason.

If any committed file mixed concerns (rule 4.5), add a final note: `note: <path> mixed <type-A> and <type-B>; aisle work better next time`.
