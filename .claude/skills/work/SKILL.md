---
name: work
description: Full issue execution pipeline. Reads a GitHub issue, creates a correctly-named branch, works the issue, and opens a PR. References /commit for commits.
argument-hint: <issue-number>
---

# work

You are the issue execution pipeline for this repository. Your goal is to take a GitHub issue from open to a merged PR. You NEVER skip a step and you NEVER ask questions as plain text — every question uses `AskUserQuestion`.

Work through the steps in order. Do NOT proceed to the next step until the current one is complete.

---

## Step 1 — Identify the issue

If `$ARGUMENTS` contains an issue number, use it. Otherwise use `AskUserQuestion`:

> "Which GitHub issue do you want to work on? (Enter the issue number)"

Store as `{issue_number}`.

---

## Step 2 — Read the issue

Fetch the full issue:

```bash
gh issue view {issue_number} --json number,title,body,labels,milestone,comments
```

Extract and store:
- `{issue_title}` — full title
- `{issue_type}` — from the `type: *` label (bug / feat / refactor / ci / chore)
- `{issue_body}` — full body
- `{issue_scope}` — the scope from the title convention `type(scope): ...` if present

Read the entire issue body and comments carefully before continuing.

---

## Step 3 — Determine base branch

Check current branches:

```bash
git branch -a
```

Infer the correct base branch using these rules:
- `bug` on production → `main`
- `feat`, `refactor`, `ci`, `chore` → `main` unless there is an in-progress branch for a related issue
- If an in-progress branch for a direct dependency exists, use it as base

Use `AskUserQuestion` with the inferred base pre-selected:

> "Base branch for this work? (I suggest: `<branch>`)"
> Options: main / <list any active feature branches> / Other (specify)

Store as `{base_branch}`.

---

## Step 4 — Name the branch

Generate the branch name following this convention:

```
<type>/<issue-number>-<slug>
```

Where `<slug>` is the issue title lowercased, non-alphanumeric chars replaced with `-`, truncated at 50 chars.

Examples:
- `bug/42-token-not-stripped-from-git-remote`
- `feat/17-sse-reconnect-last-event-id`
- `refactor/28-split-providers-outbound-adapter`

Use `AskUserQuestion` to confirm:

> "Branch name: `<generated-name>` from `{base_branch}`. Confirm or edit?"
> Options: Confirm / Edit name

Store confirmed name as `{branch_name}`.

---

## Step 5 — Create the branch

```bash
git checkout -b {branch_name} {base_branch}
```

Confirm the branch was created:

```bash
git branch --show-current
```

---

## Step 6 — Plan the work

Based on the issue body and your understanding of the codebase, produce a concise execution plan:

- List 3–7 concrete steps (files to change, logic to add/remove/move)
- Note which acceptance criteria each step addresses
- Flag any ambiguity that could block implementation

Use `AskUserQuestion` to present the plan and get approval:

> "Execution plan:\n<plan>\n\nReady to start?"
> Options: Start / Adjust plan (specify) / Cancel

If "Adjust plan": collect the adjustment, revise, and re-present. Repeat until approved.

---

## Step 7 — Execute the work

Work the plan. Follow all hard rules in `CLAUDE.md`, especially:
- Hard rule 1 (infrastructure only — Mad launches agents, does not execute tools)
- Hard rule 3 (path traversal prevention)
- Hard rule 4 (package layout and hexagonal architecture)
- Hard rule 5 (no real `claude` CLI or GitHub in tests — use FakeLauncher)
- Hard rule 9 (HTTP I/O strongly typed — Pydantic body, declared response shape)
- Hard rule 10 (tests follow the eight heuristics in `docs/04-conventions/testing-heuristics.md`; the `write-test` skill is auto-invoked when modifying any file under `tests/`)

Work the **entire plan WITHOUT committing**. Every edit stays in the working tree until Step 7.7. The full commit plan is designed at the end with complete diff visibility, by the `commit-planner` subagent — this avoids phase-per-commit inflation (one `feat` per internal slice) and keeps internal scopes (`core`, `events`, `sessions`) out of user-facing commits. See CLAUDE.md hard rule 12 and `.claude/skills/commit/SKILL.md`.

The single exception: if execution stretches across multiple sessions and you need to checkpoint progress to disk, use `/commit --plan` ad-hoc — the planner will still consolidate phases on the next pass because it operates on the full diff range.

---

## Step 7.5 — Test review loop (write-test ↔ test-critic)

Tests written during Step 7 MUST pass through the generator/critic loop before the suite is run. This loop enforces `docs/04-conventions/testing-heuristics.md` mechanically; without it, tautological tests, weak assertions, and missing OpenAPI / SSE contract tests slip through (this happened in May 2026 — see the audit referenced in the doc).

Run iterations 1, 2, and up to 3 in order. Stop as soon as `test-critic` returns `Verdict: PASS`.

### Iteration N (N = 1, 2, 3)

**N.a — Run `test-critic`.**

Spawn the `test-critic` agent (foreground) with:
- `target` = the diff range from Step 7 (e.g. `git diff --name-only main...HEAD -- 'tests/**'`)
- `iteration` = N

Wait for the structured verdict.

**N.b — If `Verdict: PASS`**, exit the loop and proceed to Step 8.

**N.c — If `Verdict: FAIL`**, spawn the `write-test` agent (foreground) with:
- `mode` = `from_critic`
- the full critic verdict markdown as input
- `iteration` = N

When `write-test` returns, continue to iteration N+1.

### Escape hatch

If after iteration 3 the critic still returns FAIL, do NOT proceed silently. Use `AskUserQuestion`:

> "Test critic still flags issues after 3 iterations:\n<must-fix findings>\n\nHow do you want to proceed?"
> Options:
> - "Show me the findings and let me fix manually"
> - "Accept current state and proceed (I'll address in a follow-up issue)"
> - "Cancel /work — I want to rethink the approach"

If the user picks "Accept", record in the PR body under a "Known test debt" section: list each unresolved finding with `file:line`, the rule it violates, and "tracked in #?".

### Why this loop exists

Cada bug que escapa a la suite y aparece recién al interactuar con la API en producción (Postman, cliente real) cuesta un orden de magnitud más caro de arreglar que uno detectado por el critic acá. La iteración no es burocracia — es la red que evita escribir tests que defienden un bug en lugar de un contrato.

---

## Step 7.7 — Plan and execute commits

The working tree at this point holds the entire issue's worth of changes. Tests already passed inside the test-critic loop on the working tree, so the suite is green. Now design the commit history.

Invoke the `/commit` skill (`.claude/skills/commit/SKILL.md`) in `from_work` mode, passing:
- `issue_number` = `{issue_number}`
- `issue_title` = `{issue_title}`
- `issue_type` = `{issue_type}`

The skill spawns the `commit-planner` subagent (`.claude/agents/commit-planner.md`), which reads the entire diff with full visibility, maps every path to a public scope per CLAUDE.md hard rule 12, consolidates internal phases, and produces a structured plan. The skill then presents the plan via `AskUserQuestion`, applies any adjustments, and executes the staged-and-committed sequence.

Expected shape: 0–N internal commits (`refactor`/`chore`/`test` with internal scopes) followed by exactly ONE user-visible commit (`feat`/`fix`/`perf` with a scope from `{http, sse, cli, config, agents, deps}`) carrying `Closes #{issue_number}` in the body. If the issue is purely internal (no public surface change), the sequence is N internal commits, the last one carrying `Closes #{issue_number}`.

NEVER hand-type commits at this step. The planner enforces hard rule 12 mechanically; bypassing it is exactly the regression #24 was filed to prevent.

---

## Step 8 — Verify

Run the test suite after the commits land — this catches Option-A violations where a `test:` commit was split out from its production change and now fails alone (`git bisect` correctness check):

```bash
make test
```

If tests fail, fix them in a NEW commit (do NOT amend). Do not skip this step.

---

## Step 9 — Open the PR

Invoke `/pr {issue_number}` to create the pull request.

The `/pr` command handles title derivation, body structure, base branch confirmation, and the `gh pr create` call. Pass `{issue_number}` as the argument so it pre-fills `Closes #{issue_number}` without asking.
