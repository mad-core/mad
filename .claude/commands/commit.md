---
description: Plan and execute commits for the current working tree, applying the package-centric scope policy in CLAUDE.md hard rule 12. Delegates to the `commit` skill (see `.claude/skills/commit/SKILL.md`).
argument-hint: [hint, full conventional message, --plan, --auto, or --dry-run]
---

Invoke the `commit` skill via the `Skill` tool, passing `$ARGUMENTS` through verbatim.

The skill at `.claude/skills/commit/SKILL.md` is the canonical implementation. It detects mode (`standalone` here), spawns the `commit-planner` subagent (`.claude/agents/commit-planner.md`), maps every changed path to a public scope per CLAUDE.md hard rule 12, consolidates phase-per-commit inflation, presents the plan via `AskUserQuestion`, and executes the commits.

Do NOT reimplement the planning logic in this command file. If the behaviour needs to change, edit the skill or the subagent — this command is a thin entry point.
