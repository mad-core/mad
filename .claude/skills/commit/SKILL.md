---
name: commit
description: Plan and execute one or more commits for the current working tree, applying the package-centric scope policy in CLAUDE.md hard rule 12. Spawns the `commit-planner` subagent to produce a structured multi-commit plan, presents it via AskUserQuestion, and executes it. Runs in two modes — standalone (`/commit`) and invoked-from-`/work` (Step 7.7). Always uses AskUserQuestion for confirmation; never plain text.
argument-hint: [hint, full conventional message, --plan, --auto, or --dry-run]
---

# commit

You are the commit pipeline for this repository. You stage files and create commits. You NEVER bypass the planner. You NEVER ask questions as plain text — every decision uses `AskUserQuestion` (CLAUDE.md hard rule 7). Every commit you produce must be a valid Conventional Commit so `python-semantic-release` can parse it on push to `main`.

Work through the steps in order. Do NOT proceed to the next step until the current one is complete.

---

## Step 1 — Detect mode

Inspect the invocation context:

| Signal | Mode |
|---|---|
| Called by `/work` Step 7.7 with an `issue_number` argument | `from_work` |
| Called directly by the user as `/commit` | `standalone` |

In `from_work` mode, the parent (`/work`) has already verified the test suite via the write-test ↔ test-critic loop on the working tree. In `standalone` mode, the user invokes you ad-hoc.

Inspect `$ARGUMENTS`:

| `$ARGUMENTS` content | Sub-mode |
|---|---|
| empty, or vague text (e.g. `"avances"`, `"wip"`) | `plan` — present plan via `AskUserQuestion`, execute on approval |
| explicit `--plan` flag | `plan` |
| explicit `--auto` flag | `auto` — present plan via `AskUserQuestion` once, execute on approval (no per-commit confirmation) |
| explicit `--dry-run` flag | `dry-run` — print the plan and stop; do NOT stage or commit |
| a full Conventional Commits message (e.g. `fix(http): reject absolute mount_path`) | `single-shot` — bypass the planner, stage all changes, commit once with the provided message verbatim |

Note: even in `auto` and `single-shot` modes you MUST still confirm via `AskUserQuestion` before executing. Hard rule 7 has no escape hatch. The difference is the granularity of the question, not whether one is asked.

---

## Step 2 — Inspect the working tree

Run, in parallel:

```bash
git status --short
git diff --stat
git diff --name-only
```

If there are no changes, stop and report `Nothing to commit — working tree is clean.`

Untracked files are part of the diff for planning purposes — the planner sees them and decides whether they belong in a commit or should be skipped (e.g. local junk).

---

## Step 3 — Identify the issue number

For the `Closes #N` footer the planner needs an issue number.

- **`from_work` mode**: the parent passes `issue_number` directly. Use it.
- **`standalone` mode**: try to extract `\d+` from `git branch --show-current`. If a single match is found, use it as the inferred number. If zero or multiple matches, use `AskUserQuestion`:
  > "Which issue does this commit close? (Enter number, or 'none' if not closing one)"
  > Options: Use #<inferred> (Recommended) / Enter another / None

Store as `{issue_number}` (may be empty).

---

## Step 4 — Single-shot bypass (only if `single-shot` sub-mode)

If `$ARGUMENTS` is a full Conventional Commits message, skip the planner entirely:

1. Verify the message is well-formed: starts with `<type>(<scope>)?<!?>: <subject>`. Reject malformed input and fall back to `plan` sub-mode.
2. Verify the type/scope combination respects CLAUDE.md hard rule 12: `feat`/`fix`/`perf` MUST use a scope from `{http, sse, cli, config, agents, deps}`. If the user wrote `feat(core): ...`, refuse — use `AskUserQuestion`:
   > "`feat(<scope>)` is forbidden by hard rule 12 — only `{http, sse, cli, config, agents, deps}` are allowed in `feat`/`fix`/`perf`. How do you want to proceed?"
   > Options: Reclassify as `refactor(<scope>)` (Recommended) / Edit message / Cancel
3. On approval, stage all changes (`git add -A` is forbidden — list files explicitly) and commit with the message via heredoc plus the mandatory co-author trailer.
4. Skip Steps 5–7 and go to Step 8.

---

## Step 5 — Spawn the commit-planner subagent

Spawn the `commit-planner` agent (foreground, defined at `.claude/agents/commit-planner.md`) with this input:

```
diff_range: HEAD..   # working tree
issue_number: {issue_number or empty}
issue_title: {issue_title from /work, or empty in standalone}
issue_type: {issue_type from /work, or empty in standalone}
mode: {from_work | standalone}
```

Wait for the structured `## commit-planner result` markdown. Do not edit it.

If the planner returns `Commits planned: 0`, stop and report `Nothing to plan — diff is empty.`

---

## Step 6 — Present plan and collect adjustments

Use `AskUserQuestion` to present the plan summary:

> "Commit plan ({N} commits):\n\n1. `<subject 1>`\n2. `<subject 2>`\n...\n\nProceed?"
> Options:
> - Execute the plan (Recommended)
> - Adjust plan (specify)
> - Show full plan (paths + bodies)
> - Cancel

Adjustment routing (free-text reply guidance — apply this when the user picks "Adjust plan"):

| User intent | Action |
|---|---|
| "merge 2 with 3" / "split commit 1" / change subject wording / reorder | apply in-place to the planner output, re-present |
| "switch type to refactor" / "use scope X" / "this is breaking" | re-spawn `commit-planner` with a `## Adjustment` block appended to its input — type/scope changes can cascade to grouping |
| "drop file X from the plan" | apply in-place, list `X` under `skipped` in Step 8 |

Repeat Step 6 until approved or cancelled. If the user picks `Show full plan`, dump the full markdown returned by the planner and re-ask.

If sub-mode is `dry-run`: stop here regardless of choice and print the plan. Do NOT execute.

---

## Step 7 — Execute the plan

For each commit in plan order:

1. Stage exactly the listed paths:
   ```bash
   git add <path1> <path2> ...
   ```
   NEVER `git add -A` or `git add .`. NEVER hunk-level staging.

2. Commit with the planner's message, passed via heredoc to preserve formatting:
   ```bash
   git commit -m "$(cat <<'EOF'
   <type>(<scope>): <subject>

   <body>

   Closes #<N>
   Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
   EOF
   )"
   ```

3. Verify the commit landed:
   ```bash
   git log -1 --pretty=oneline
   ```

Hard constraints, never negotiable:
- Never `git push`.
- Never `git commit --amend`.
- Never `git commit --no-verify`.
- Never `git add -A` or `git add .`.
- Never re-run the planner mid-execution to "regroup" — if a commit fails, stop and report; the user decides.

If a commit fails (pre-commit hook, hook lint failure, etc.):
- Report the failure with the hook output verbatim.
- Do NOT attempt to fix automatically.
- Use `AskUserQuestion`:
  > "Commit `<subject>` failed during pre-commit hook. How do you want to proceed?"
  > Options: Show me the failure / Skip this commit / Cancel remaining commits

---

## Step 8 — Confirm and report

Show, in order, the hash and subject line of every commit created:

```
abc1234 refactor(core): prep ports for emitter
def5678 feat(http): expose /v1/sessions filters
9012345 chore(claude): document the new commit skill
```

If any file in the working tree was intentionally NOT committed (skipped by the user during Step 6, or planner-flagged as junk), list it under `skipped:` with a one-line reason.

If the planner flagged a mixed-concern file (rule 4.5 in its procedure), surface the note: `note: <path> mixes <type-A> and <type-B>`.

In `from_work` mode, return control to the parent (which proceeds to Step 8 of `/work` — `make test`). In `standalone` mode, you are done.
