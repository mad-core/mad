# Mad claude-cli — Spec

This folder is the **spec-driven development** package for the `claude_cli` provider: the implementation that makes `agent.provider = "claude_cli"` fully functional by shelling out to the locally authenticated `claude` CLI, enabling Claude Pro/Max accounts to power Mad sessions without an `ANTHROPIC_API_KEY`.

## Why this spec exists

Mad v0.1 declared `claude_cli` and `anthropic_api` as two valid providers (see [`specs/v0.1/requirements.md` FR-10 and FR-11](../v0.1/requirements.md)). The `anthropic_api` path is complete. The `claude_cli` path exists only as an 8-line stub at `src/mad/providers/claude_cli.py` that raises `NotImplementedError`. This spec defines what a correct implementation looks like, how it must behave under failure, and how it must be tested — so the `/implement` workflow can drive it to production quality without ambiguity.

## How to read this spec

Read the files in order. Each one answers a different question.

| File | Question it answers |
|---|---|
| [`requirements.md`](requirements.md) | **What** must be true for this feature to be done? Nine functional requirements, three non-functional constraints, and six MVP acceptance criteria. |
| [`design.md`](design.md) | **How** does it work internally? ASCII diagram, stdin payload shape, stream-json parser state machine, subprocess lifecycle, and error taxonomy. |
| [`plan.md`](plan.md) | **How do we build it?** Stack, six implementation rules, and the items deliberately left out of scope. |

## No `api.md`

This spec does **not** include an `api.md`. The HTTP contract is unchanged: the existing `agent.provider` field in `POST /v1/sessions` already selects the provider. No new endpoints, no new request fields, no new response shapes. See [`specs/v0.1/api.md`](../v0.1/api.md) for the full HTTP contract.

## Related

- [`specs/v0.1/requirements.md`](../v0.1/requirements.md) — FR-10 and FR-11 that this spec elaborates.
- [`specs/v0.1/plan.md`](../v0.1/plan.md) — implementation rules 8 and 9 this spec supersedes for the `claude_cli` path.
- [`../../docs/backlog.md`](../../docs/backlog.md) — items deferred past this feature (resumable sessions, auto-login, etc.).
- [`../../CLAUDE.md`](../../CLAUDE.md) — project hard rules, especially rule 1 (native tool use) and rule 5 (no real CLI in tests).
