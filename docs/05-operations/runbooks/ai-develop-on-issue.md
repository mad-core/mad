---
service: mad
domain: backend
section: operations
source_of_truth: repo
---

# AI development on an issue (GitHub Action)

This guide walks an operator through enabling the **AI Develop on Issue** workflow
([`.github/workflows/ai-develop-on-issue.yml`](../../../.github/workflows/ai-develop-on-issue.yml)).
Once configured, applying a single label to an issue starts Claude-driven
development on that issue's branch and opens a pull request — no local session,
no manual `/work` invocation. See [`../ci-cd.md#ai-develop-on-issueyml`](../ci-cd.md#ai-develop-on-issueyml)
for how this workflow fits into the full pipeline.

The recipe is two gates and one principle:

- **Author gate** — the issue author must be listed in the `AI_DEVELOP_ALLOWLIST`
  repository variable.
- **Label gate** — the issue must carry the `ai:auto-develop` label.

The principle: **either gate failing makes the run a no-op.** Arbitrary
contributors and unlabeled issues never trigger automated execution.

## Threat model — read this first

When both gates pass, this workflow runs `claude` with broad tool access against
your repository and pushes commits with write permissions. **This is automated
code execution and code authorship triggered by a label.** Treat the allow-list
as a list of people you trust to spend your Claude credits and write to your
default-branch-adjacent branches.

- Keep `AI_DEVELOP_ALLOWLIST` tight. Every login on it can trigger a run by
  opening a labeled issue.
- Anyone who can add the `ai:auto-develop` label to an *eligible author's* issue
  can trigger a run. Restrict who can label issues if that matters to you.
- The workflow targets a branch and opens a PR toward `main`; it does not merge.
  Branch protection on `main` (required review) remains your last line of defense.

## What you must configure (GitHub-side, not committed)

These three pieces live in GitHub repository settings, never in the repo tree:

| Kind | Name | Value |
|---|---|---|
| Secret | `CLAUDE_CODE_OAUTH_TOKEN` | Output of `claude setup-token` |
| Variable | `AI_DEVELOP_ALLOWLIST` | Allowed logins, e.g. `cimode jlsaco` |
| Label | `ai:auto-develop` | The trigger label |

### 1. Generate the OAuth token

On a machine with the Claude CLI installed and logged in:

```bash
claude setup-token
```

Copy the printed token. **Do not paste it into a file, commit, or issue** — it is
a credential. Per [CLAUDE.md hard rule 2](../../../CLAUDE.md) the workflow references it
only as a secret expression and never echoes it to logs.

### 2. Store the secret

```bash
gh secret set CLAUDE_CODE_OAUTH_TOKEN
# paste the token at the prompt (stdin keeps it out of your shell history)
```

### 3. Set the allow-list variable

Comma- or space-separated GitHub logins:

```bash
gh variable set AI_DEVELOP_ALLOWLIST --body "cimode jlsaco"
```

### 4. Create the label

```bash
gh label create "ai:auto-develop" \
  --description "Trigger Claude-driven development via the AI Develop on Issue workflow" \
  --color 5319e7
```

## How it runs

1. **Trigger** — `issues: [labeled, opened]`. Adding the label to an existing
   issue, or opening an already-labeled issue, fires the workflow.
2. **Gate** — the label is checked by a workflow expression; the author is matched
   against `AI_DEVELOP_ALLOWLIST` in a shell step. Failing either gate skips the
   rest of the run.
3. **Branch** — the workflow derives `<type>/<issue-number>-<slug>` from the issue
   (the same convention as the `/work` skill): `<type>` from the `type:` label,
   `<slug>` from the title. An existing branch is reused; otherwise it is created.
4. **Develop** — `anthropics/claude-code-action@v1` runs Claude against the
   checked-out branch with the OAuth token.
5. **Commit / push / PR** — Claude finishes the whole git flow itself, from inside
   the action, while the checkout's auth is still live: it commits to the
   already-checked-out convention branch, pushes it, and opens a non-draft PR
   toward `main` (skipping PR creation if one already exists). Doing this inside
   the action — rather than in a later step — avoids the auth teardown that breaks
   a post-action `git push`. `GH_TOKEN` is exported to the action so `gh` works.

A `concurrency` group keyed by the issue number with `cancel-in-progress: true`
guarantees at most one run per issue: re-applying the label cancels any in-flight
run rather than duplicating it.

## Disabling

Remove the `ai:auto-develop` label from issues, delete the
`AI_DEVELOP_ALLOWLIST` variable (every author then fails the gate), or disable the
workflow from the repository's Actions tab.
