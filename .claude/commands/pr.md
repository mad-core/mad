---
description: Open a pull request for the current branch. Infers the related issue from branch name or asks. Always uses AskUserQuestion before creating.
argument-hint: [issue-number or --auto]
---

Create a pull request for the current branch. Follow the steps in order.

---

## Step 1 — Identify the related issue

If `$ARGUMENTS` contains an issue number, use it. Otherwise try to infer it from the branch name (pattern: `<type>/<number>-<slug>`).

If no issue number can be inferred and `--auto` is not set, use `AskUserQuestion`:

> "Which issue does this PR close? (Enter number, or 'none')"

Store as `{issue_number}` (may be empty).

---

## Step 2 — Collect context

```bash
git branch --show-current
git log main..HEAD --oneline
```

Store the current branch as `{branch}` and the commit list as `{commits}`.

If `{branch}` is `main` or the default branch, stop and report: "Cannot open a PR from the default branch."

---

## Step 3 — Determine base branch

Infer base from the branch name prefix or the commit log origin. Default to `main`.

Use `AskUserQuestion` to confirm:

> "Base branch: `main`. Confirm or change?"
> Options: Confirm / Other (specify)

Store as `{base_branch}`.

---

## Step 4 — Build PR title and body

Derive the PR title from the most significant commit subject, following Conventional Commits style (≤72 chars).

Build the body:

```markdown
## Summary
<1–3 bullet points: what changed and why, derived from {commits}>

## Related issue
Closes #{issue_number}
(omit this section if issue_number is empty)

## Type of change
- [ ] bug fix
- [ ] feature
- [ ] refactor
- [ ] ci / tooling
- [ ] chore / docs

## Test plan
- [ ] <key scenario>
- [ ] <edge case>

🤖 Generated with [Claude Code](https://claude.ai/claude-code)
```

Check the correct "Type of change" box based on the branch prefix or commit types.

---

## Step 5 — Confirm and create

Use `AskUserQuestion` to show the full draft:

> "Ready to open PR:\n\nTitle: <title>\nBase: {base_branch}\n\n<body>\n\nProceed?"
> Options: Create PR / Edit title / Edit body / Cancel

If "Edit title" or "Edit body": collect the correction via `AskUserQuestion`, apply it, re-present. Repeat until confirmed or cancelled.

Once confirmed:

```bash
gh pr create \
  --base {base_branch} \
  --title "<title>" \
  --body "<body>"
```

Report the PR URL to the user.
