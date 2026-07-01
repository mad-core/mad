---
service: mad
domain: backend
section: user-manuals
source_of_truth: repo
---

# Mad — User Manuals

Mad runs coding agents against your repositories and reports back what they
did: you send it a prompt, it works inside a private copy of your code, and
you watch the results stream in. Mad is not the agent itself — it never
writes code, reviews a diff, or makes a decision. It rents the workspace,
starts your chosen agent inside it, and hands you every line of output as an
update you can read live or look up later. There is no login and no built-in
user accounts: anyone who can reach Mad's address can use it, so who is
allowed to reach that address is something you control around Mad (a private
network, a tunnel with an access gate), not a setting inside it.

Everything below works two ways — plain HTTP calls, or tool calls from an
MCP-speaking client such as Claude Code. Every manual shows both side by
side, so pick whichever fits how you already work.

## Which manual do I want?

| I want to… | Read |
|---|---|
| Install Mad and run my first end-to-end round trip | [`getting-started.md`](getting-started.md) |
| Run an agent on my repo, message it, and check on it | [`sessions.md`](sessions.md) |
| Watch what an agent is doing — live, or after the fact | [`events.md`](events.md) |
| Line up several prompts and control when they run | [`queue-and-scheduling.md`](queue-and-scheduling.md) |
| Chain several sessions into one multi-step pipeline | [`workflows.md`](workflows.md) |
| Pick which agent, which model, and how hard it thinks | [`choosing-agent-and-model.md`](choosing-agent-and-model.md) |
| Drive Mad from Claude Code or another MCP client | [`connecting-your-tools.md`](connecting-your-tools.md) |

If you are new here, start with `getting-started.md` — it walks through the
whole loop once before the other manuals go deep on one piece of it each.
