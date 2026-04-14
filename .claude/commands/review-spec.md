---
description: Run the spec-reviewer agent against the current diff and a given spec.
argument-hint: <spec-path>
---

Invoke the `spec-reviewer` subagent against the spec at: $ARGUMENTS

The reviewer is read-only. It will:
1. Read the full spec and `CLAUDE.md`.
2. Inspect the current code and `git diff` (against `main` if on a branch, otherwise the working tree).
3. Produce a markdown report with FR coverage, NFR compliance, hard-rule audit, and risks.

Surface the report to the user verbatim. Do not edit any file.
