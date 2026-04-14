---
description: Run the full spec-driven implementation loop against an existing spec folder.
argument-hint: <spec-path>
---

Implement the spec at: $ARGUMENTS

Run this three-step loop in order. Do NOT skip steps and do NOT merge them.

**Step 1 — Red tests.**
Invoke the `test-author` subagent. Pass it the spec path. Its job is to write failing pytest tests in `tests/` that map 1:1 to the MVP acceptance criteria in the spec's `requirements.md`. After it finishes, run `pytest -q` and confirm the new tests are discovered and failing (red). If any are unexpectedly green, stop and ask the user.

**Step 2 — Green code.**
Invoke the `implementer` subagent. Pass it the spec path and the list of failing tests. Its job is to edit `app.py` (and only `app.py`, unless the spec says otherwise) until all tests pass. After it finishes, run `pytest -q` and confirm everything is green.

**Step 3 — Review.**
Invoke the `spec-reviewer` subagent. Pass it the spec path. Its job is to produce a short markdown report covering FR coverage, NFR compliance, hard-rule audit, and risks.

**Step 4 — Commit the stable version.**
Surface the reviewer's report to the user verbatim. Then decide whether the current state qualifies as "apparently stable":
- All tests green (`pytest -q` exits 0).
- Reviewer reports no ❌ on FR coverage, no hard-rule violations, and no critical risks.

If stable, create a commit automatically WITHOUT asking for approval:
1. `git status` and `git diff` to inspect what will be committed.
2. `git add` the specific files touched by this loop (spec files, tests, `app.py`, any new modules). Never use `git add -A` or `git add .`.
3. `git commit` with a Conventional Commits message. Format:
   - `feat(<spec-name>): <one-line summary>` for new features.
   - `fix(<spec-name>): <one-line summary>` for bug fixes.
   - Body (optional): 1-2 bullets covering what changed and which FR-* were covered.
   - Trailer: `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`.
4. Do NOT push. Pushing is always the user's explicit call.

If NOT stable, skip the commit, leave the working tree as-is, and tell the user exactly what blocks stability (failed tests, reviewer ❌, etc.).
