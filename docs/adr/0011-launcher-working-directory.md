# ADR-0011 — Launcher working directory aligns with the cloned repo

- Status: Accepted
- Date: 2026-05-17

## Context

Mad provisions a workspace at `/tmp/mad_<session>/`, then clones a `github_repository` resource into a sub-directory keyed by its `mount_path` (e.g. `/workspace/repo` → `/tmp/mad_<session>/repo`). Until this ADR, the `claude_cli` launcher spawned the agent with `cwd=<workspace_root>` — one level *above* the clone.

Two consequences flowed from that mismatch:

1. **Per-repo Claude scaffolding was invisible.** `CLAUDE.md`, `.claude/agents/`, `.claude/skills/`, project-scoped MCP config, the project's own `.claude/settings.local.json` — all live inside the cloned repo. Claude Code discovers them by scanning from the cwd. From the workspace root they are unreachable.
2. **The ADR-0008 hook channel did not actually fire.** The provisioner installs `forward.sh` and `settings.local.json` at `<repo>/.claude/...`, but claude-cli reads `<cwd>/.claude/settings.local.json` — and `<cwd>` was the workspace root. Mad's hook bootstrap was effectively a dead artifact for every real session.

Fixing cwd realigns both concerns in one move. The design choice is how to *pick* the directory when it isn't obvious: single-repo sessions want the repo path automatically, but multi-repo and file-only sessions need an explicit knob.

A secondary concern surfaces once cwd points at the repo: the provisioner today **overwrites** `<repo>/.claude/settings.local.json` with Mad's bootstrap. Until this ADR that overwrite was harmless (nothing read the file). After this ADR it would silently delete any project-shipped Claude scaffolding the moment Mad cloned the repo.

## Decision

### 1. Hybrid working-directory selection

`CreateSessionRequest` gains an optional `working_directory: str | None = None` field (same `/workspace/...` convention as `mount_path`). The resolution rule:

1. If `working_directory` is set → validate via `MountPath` (hard rule 3) and use `_resolve_mount(workspace, working_directory)`.
2. Else if exactly one resource has `type == "github_repository"` → derive from that resource's `mount_path`.
3. Else → fall back to the workspace root.

The resolved absolute path is persisted on the `Session` entity as `working_directory`, emitted in the `session.created` event payload, and rehydrated from the JSONL log on subsequent reads. Legacy logs (predating this ADR) fall back to the workspace root via the entity's `__post_init__` — existing on-disk sessions stay correct.

### 2. The `AgentLauncher.run` `workspace` parameter widens

The Protocol stays unchanged. `SendUserMessageUseCase` passes `Session.working_directory` (the effective cwd) through the existing `workspace: Path` parameter. Launchers continue to set `cwd=str(workspace)` on the subprocess. The parameter name describes "the context the agent runs in" — its meaning was always "the cwd we'll spawn at", and that is now what the use case computes.

This avoids touching every launcher implementation (production + test doubles) and avoids coordination with the unrelated `env_extra` kwarg proposed in #31.

### 3. Hook bootstrap merges instead of clobbers

`LocalWorkspaceProvisioner._install_claude_hooks` deep-merges Mad's bootstrap into any existing `<repo>/.claude/settings.local.json`:

- Top-level keys outside `hooks` (e.g. `permissions`, `mcpServers`) are preserved from the project.
- Inside `hooks`, the union of event keys is taken; Mad's matcher group is appended to each event's list unless an entry containing `/.claude/hooks/forward.sh` is already there (keeps re-runs idempotent).
- A malformed pre-existing JSON file raises a typed `MalformedSettingsLocalJson` (subclass of `ValueError`) — the existing HTTP handler surfaces it as a 400. The provisioner refuses to destroy what it cannot parse.

`forward.sh` itself is written unconditionally — it is a Mad-owned filename that no project would collide with.

## Consequences

**Wins:**

- Per-repo Claude scaffolding (CLAUDE.md, .claude/agents/, .claude/skills/, project MCP config) is discovered by the launched agent. This is the design goal Mad was built for: drive an external harness against a repo that ships its own per-project Claude setup.
- The ADR-0008 hook channel actually fires on real sessions. `agent.<provider>.hook.*` events flow on every materialized github mount.
- Multi-mount and file-only sessions retain the old behavior (workspace root) as the safe default; the explicit `working_directory` field is the escape hatch for atypical layouts.
- No `AgentLauncher` Protocol churn — launchers and test doubles stay byte-identical.

**Costs:**

- One more optional field on `CreateSessionRequest` (visible in OpenAPI). Existing callers that omit it inherit the auto-derive behavior, which matches the documented intent.
- The `_install_claude_hooks` path now opens and re-parses the file when it exists. Negligible cost; bounded to the small bootstrap.
- `session.created` event payload gains a `working_directory` key. Legacy logs (~600 on disk at the time of this ADR) lack it; rehydration handles the absence by falling back to the workspace root via the entity's `__post_init__`.

**Revisit if:**

- Repo-less sessions (file-only, or no mounts) start needing the Mad hook channel. Today they get no hook materialization at all; auto-installing at the workspace root for those cases is an obvious follow-up.
- The launcher parameter rename from `workspace` to `cwd` / `working_directory` becomes worth the API churn. The current name is now semantically a bit fuzzy ("workspace" sometimes means the root, sometimes the repo); the cost of renaming touches every launcher impl + the Protocol + tests. Deferred.

## Alternatives considered

- **Auto-derive only, no explicit field.** Smallest diff, but the silent heuristic surprises multi-mount callers and offers no escape hatch. Rejected.
- **Explicit field only, no heuristic.** Most predictable but pushes verbose ceremony onto the 95% case (one github mount). Rejected.
- **Add a second parameter to `AgentLauncher.run`.** More explicit at the Protocol level but requires updating every launcher impl + `ScriptedLauncher` + `RaisingLauncher` + `RecordingLauncher` and the factory. Same runtime behavior as reusing `workspace`. Rejected on diff-size grounds.
- **Skip-if-exists for `settings.local.json`.** Preserves project scaffolding but silently disables Mad's hook channel — a regression of ADR-0008. Rejected.
- **Move hooks to workspace root and keep `cwd=workspace_root`.** Fixes hooks but does NOT fix the agent's view of per-repo scaffolding (the user's primary complaint). Rejected.
- **Auto-install hooks at workspace root for repo-less sessions.** Out of scope; tracked as a follow-up. Today's behavior (no hooks for repo-less sessions) is unchanged.

## Cross-references

- [ADR-0003](0003-package-layout.md) — hexagonal layout; the use case decides the effective cwd and the adapter (launcher) consumes it.
- [ADR-0006](0006-multi-tenancy-deferred.md) — single-operator assumption; no per-tenant working-directory semantics needed.
- [ADR-0007](0007-single-write-gateway-event-emitter.md) — `session.created` continues to flow through `EventEmitter`; the new `working_directory` field rides on the same emit call.
- [ADR-0008](0008-internal-hook-adapter-and-vocabulary.md) — defines the hook bootstrap; this ADR completes its delivery by aligning cwd with the materialization location.
- Issue #40 — driving GitHub issue.
