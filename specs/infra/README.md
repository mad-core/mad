# Mad infra — Spec

This folder is the **spec-driven development** package for the first functional version of **Mad**: a self-hosted system that replicates the core of Anthropic Managed Agents on your own hardware.

Mad receives a JSON request that defines an agent and a set of resources (GitHub repositories, inline files), provisions a local workspace, clones the repos, and runs an autonomous session where Claude (via headless CLI or API) works against them.

## How to read this spec

Read the files in order. Each one answers a different question.

| File | Question it answers |
|---|---|
| [`requirements.md`](requirements.md) | **What** must be true for infra to be considered done? Functional requirements, constraints, and the MVP acceptance criteria. |
| [`design.md`](design.md) | **How** does it work internally? Architecture, components, end-to-end request flow. |
| [`api.md`](api.md) | **What does the outside see?** HTTP contract: endpoints, request/response schemas, headers, events. |
| [`plan.md`](plan.md) | **How do we build it?** Implementation rules, stack, conventions, out-of-scope items. |

## Related

- [`../../docs/backlog.md`](../../docs/backlog.md) — improvements deliberately deferred past this spec.
- [`../../docs/sandbox-bwrap.md`](../../docs/sandbox-bwrap.md) — hardening guide for the execution sandbox.
