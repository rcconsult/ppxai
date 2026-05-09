# Research note: OpenShell multi-agent coordination patterns and what (and what not) to lift into ppxai

**Date:** 2026-05-10
**Status:** Research / exploratory — not a decision
**Triggered by:** review of NVIDIA's OpenShell multi-agent-notepad
example (https://github.com/NVIDIA/OpenShell/tree/main/examples/multi-agent-notepad)
in the context of [ADR 0003 — Agent platform architecture](../decisions/0003-agent-platform-architecture.md)
**Author:** Captured from a research conversation; not vetted against a build.
**Not blocking:** v1.19.x agent-platform planning can proceed without
this. It exists so the patterns OpenShell got right (and the ones that
don't fit ppxai) are documented before Stage 2 sub-agent design starts.

This is a research note, not an architecture decision record. If the
patterns lifted from here actually inform a v1.19.x design choice,
amend ADR 0003 with a reference back to this note.

## TL;DR

| OpenShell pattern | Adopt? | Where in ppxai |
|---|---|---|
| Per-agent container sandboxing | ❌ No | ppxai is single-user, not a multi-tenant platform |
| Bash + external CLI agent (Codex) orchestration | ❌ No | ppxai's engine runs in-process Python, not shell-spawned agents |
| Provider-backed credential injection at network boundary | ❌ No | Conflicts with ppxai's `~/.ppxai/.env` single-user value prop |
| `gh + jq` host-side orchestration scripts | ❌ No | ppxai-server IS the orchestrator |
| Network policy as data (`policy.template.yaml`) | ⚠️ Partial | Could extend resource budgets to network egress in v1.19.x; not urgent |
| **SHA-conditional writes / 409-retry coordination** | ✅ Yes (already use this) | ppxai already does this with `cwd_anchor` 409 in state-sync; pattern generalizes to multi-agent file artifacts |
| **`runs/<run-id>/agent-<n>/` artifact namespace** | ✅ Yes | Solves four "what's missing" items from ADR 0003 in one shape (run_id, persistence, parent/child, scoped budgets) |
| **Map-reduce demo shape (N workers + 1 synthesizer)** | ✅ Yes | Tight, easy-to-explain canonical sub-agent example for ppxai docs |

## 1. What OpenShell's multi-agent-notepad actually does

A bash-script demonstration of N coding agents (NVIDIA's "Codex" agent)
running in **isolated containers**, coordinating only through a
**shared GitHub repo** with one note file per worker and one synthesis
file written by the parent.

File layout:

```
runs/<run-id>/notes/agent-1.md    ← worker 1 writes
runs/<run-id>/notes/agent-2.md    ← worker 2 writes
runs/<run-id>/notes/agent-N.md    ← worker N writes
runs/<run-id>/summary.md          ← synthesis agent writes
```

Coordination model: workers never share filesystems or containers.
Concurrency control comes from GitHub's "every PUT must include the
current file SHA" — concurrent writers get HTTP 409, retry.

Stack:
- `openshell` Go CLI
- Docker gateway
- `demo.sh` host orchestrator + `runner.sh` per-sandbox script
- `gh` + `jq` on the host
- Bash everywhere
- Codex preinstalled in the sandbox image
- `policy.template.yaml` declaring network egress allowlist per sandbox

## 2. Reframe: ppxai is single-user; OpenShell is a platform

OpenShell is solving the **multi-tenant cloud-platform** problem:
how do you let many agents from many users run in the same
infrastructure without leaking secrets, files, or network access
across tenants? The answer is "containers + network policies +
credential brokers + shared-storage coordination," and that's a
correct answer for that problem.

ppxai is solving a different problem: **a single user wants their
local agent to do useful parallel work.** No multi-tenancy. No
shared infrastructure. No external user supplying credentials. The
"tenant" is the human running ppxai locally; the "agents" are
sub-tasks of that human's intent. Per-agent containers would 100x
the install footprint for zero benefit.

The k8s session-manager (Item 3 in [DEBT-INVENTORY.md](../DEBT-INVENTORY.md))
is the **only** place ppxai uses containers, and that's for tenant
isolation in the multi-user deploy shape — orthogonal to per-agent
isolation.

So most of OpenShell's design surface is *correct for OpenShell* and
*wrong for ppxai*. The patterns that DO transplant are the ones that
solve coordination problems independent of the multi-tenant question.

## 3. The three patterns worth lifting

### 3.1 SHA-conditional writes / HTTP 409 retry

**OpenShell's use:** Workers write to GitHub. Every PUT carries the
expected current SHA; concurrent writers get HTTP 409; retry with
the new SHA.

**Why ppxai already does this:** the `cwd_anchor` 409 in v1.18.1's
state-sync determinism work uses the same pattern — client sends
expected anchor, server returns 409 if state moved, client re-anchors
from `GET /state`. See [docs/patterns/state-sync-determinism.md].

**What to take:** confirmation that the pattern scales to multi-agent
file artifacts. When sub-agents write to a shared workspace,
`POST /workspace/file/<path>` can carry the expected SHA and return
409 on conflict. No new infrastructure — generalize the existing
protocol from session-state to workspace-state. Cheap.

### 3.2 `runs/<run-id>/agent-<n>/` artifact namespace

**OpenShell's use:** Every multi-agent run gets a unique run-id;
each worker has its own slot under `runs/<run-id>/notes/agent-<n>.md`;
the synthesizer reads all slots and writes the summary in the
parent slot.

**Why ppxai needs this:** ADR 0003's "what's missing" list names
seven gaps. This namespace shape solves four of them at once:

| ADR 0003 gap | How the namespace solves it |
|---|---|
| **Run identity** ("No run_id. Can't address a running agent later") | The directory name IS the run_id |
| **Run persistence** ("Engine restart loses everything mid-run") | Sub-agents recover by re-reading their slot — slot is the persistence boundary |
| **Parent/child relationship** ("No model for sub-agents") | Slot ownership IS the relationship — `agent-1/` is owned by sub-agent 1, parent reads `agent-N/output.md` |
| **Resource budgets** ("Implicit max_iterations; no token/time caps") | `runs/<run-id>/meta.json` carries `{budget, started_at, status}` per run |

Concrete shape for ppxai (local filesystem, not GitHub):

```
~/.ppxai/runs/<run_id>/
  meta.json              # {parent_run, status, started_at, budget, model}
  agent-1/
    output.md            # what subagent 1 produced
    log.jsonl            # event stream (ANALOG of AGENT_BEAT/RUN_*)
    state.json           # checkpoint for resume
  agent-2/
    output.md
    log.jsonl
    state.json
  ...
  synthesis.md           # parent reads agent-N/output.md, writes here
```

This is the **artifact-isolation model**: "different files, same
workspace." It gets you OpenShell's coordination guarantees without
OpenShell's container infrastructure.

### 3.3 Map-reduce shape as the canonical sub-agent example

**OpenShell's framing:** "N worker agents fan out and write one note
each; one synthesis agent reads them and writes a summary."

**Why this is the right canonical example for ppxai:** the
fan-out/fan-in shape maps onto common dev tasks:

- **Research + summarize:** "Research these 5 frameworks; summarize trade-offs." Worker per framework, synthesizer writes the comparison.
- **Parallel benchmark + compare:** Worker per model/provider runs the benchmark; synthesizer writes the leaderboard. Already kind of how `tests/benchmarks/` is structured manually.
- **Fan-out search + consolidate:** "Search these 3 codebases for X; consolidate findings." One subagent per repo.
- **Per-file refactor + assemble:** "Refactor each of these 12 files to pattern Y; report a single PR description." Worker per file, synthesizer writes the PR body.

When ADR 0003 Stage 2 lands, the docs should ship with this canonical
example. It's tight, easy to explain, and demonstrates all the
sub-agent primitives (`spawn_subagent`, `await_subagent`, `read_subagent_output`).

## 4. What we don't take — and why

For each rejected pattern, the explicit "this is correct for OpenShell
but wrong for ppxai" reasoning, so future contributors don't
re-litigate it:

### 4.1 Per-agent containers

**OpenShell:** sandbox-per-agent for isolation across untrusted
tenants and untrusted agent code.

**ppxai:** the user's own machine, the user's own files, the user's
own agents. Containers would add 100s of MB to install footprint and
cold-start latency to every sub-agent spawn. No security benefit
because the threat model is "the user can already do everything the
agent does." Only place this changes is the k8s deployment shape
(Item 3 in DEBT-INVENTORY) where k8s already provides tenant
isolation per-session.

### 4.2 Bash host orchestration + external CLI agent

**OpenShell:** `demo.sh` on the host invokes `openshell` to spawn
sandboxes, each running `runner.sh` which invokes `codex` agent.
Multi-process, shell-glued.

**ppxai:** `chat_with_tools` runs in-process inside the engine.
Sub-agents will be **another in-process call** with scoped state,
not a spawned external process. Shell-glue would force serialization
through subprocess overhead, defeating most of the parallelism win.

### 4.3 Provider-backed credentials at network boundary

**OpenShell:** sandboxes start with placeholder credentials; real
ones are injected at the network gateway based on policy. Designed
so the agent code can never exfiltrate the real key.

**ppxai:** API keys live in `~/.ppxai/.env` because the user owns
both the keys and the agent. Adding a credential broker would
require a long-running daemon process, complicate the install, and
add an attack surface (the broker itself). The whole "single-user
local app" value prop dies if you bolt on tenant-isolation infra.

### 4.4 `gh` + `jq` on the host

**OpenShell:** uses the GitHub repo as the durable coordination
substrate, so the host needs `gh` for repo operations and `jq` for
parsing API responses.

**ppxai:** ppxai-server already has session storage, file storage,
event bus — those ARE the coordination substrate. Layering a GitHub
dependency on top would mean every sub-agent run requires GitHub
auth, which breaks offline use and adds a network round-trip per
write. The local filesystem is faster, simpler, and already there.

### 4.5 Network policy as YAML data

**OpenShell:** `policy.template.yaml` per sandbox declares allowed
hosts/paths/methods. Network gateway enforces.

**ppxai:** could be useful eventually as part of resource budgets
("agent X may only call api.openai.com, not arbitrary hosts"), but:

1. Tools layer already gates network access via the consent
   contract — see [docs/CONSENT-CONTRACT.md].
2. Sub-agents inherit the parent's tool consent, so policy lives at
   the tool level, not the network level.
3. Building a separate policy-enforcement layer is significant work
   for marginal benefit when the existing tool gates already cover
   the threat model.

If autonomous agents (long-running, client-disconnect-survivable)
ever need finer-grained egress control, revisit this. For now, ADR
0003's "implicit max_iterations" gap is more pressing than network
policy.

## 5. Specific recommendations for ADR 0003 Stage 2

When `spawn_subagent` is designed:

1. **Adopt the `runs/<run_id>/agent-<n>/` namespace as the
   coordination contract.** It collapses four "what's missing"
   items into one shape.
2. **Use SHA-conditional file writes** when sub-agents share write
   targets. Generalize the existing `cwd_anchor` 409 protocol from
   session-state to workspace-state.
3. **Ship the map-reduce example** in the v1.19.x sub-agent docs.
   `examples/sub-agents/research-and-summarize/` analogous to the
   OpenShell layout, but with a 50-line ppxai prompt instead of a
   500-line bash script.
4. **Don't import OpenShell as a dependency.** The architectural
   gap is too large; the patterns transplant, the code does not.

## 6. What's NOT in scope for this note

- Code-signing or verification of sub-agent prompts (no analog in
  OpenShell either)
- Multi-machine or distributed agent coordination (ppxai is
  single-machine; the deploy session-manager is a separate axis)
- Cross-agent message bus / pub-sub (the artifact-namespace pattern
  intentionally avoids needing one — workers don't talk to each
  other, only to their slot)

If those become real requirements, write follow-up notes; don't
try to retrofit them into this one.

## Related documents

- [docs/decisions/0003-agent-platform-architecture.md](../decisions/0003-agent-platform-architecture.md) — the active ADR this note feeds into
- [docs/patterns/state-sync-determinism.md](../patterns/state-sync-determinism.md) — the existing 409-retry pattern that generalizes
- [docs/CONSENT-CONTRACT.md](../CONSENT-CONTRACT.md) — current security boundary (per-tool, not per-network)
- [docs/research/2026-04-29-python-vs-go-for-agents.md](2026-04-29-python-vs-go-for-agents.md) — sibling research note on language choice for autonomous agents
- [DEBT-INVENTORY.md](../DEBT-INVENTORY.md) Item 3 — k8s session-manager (the only multi-tenant context in ppxai today)
- OpenShell upstream: https://github.com/NVIDIA/OpenShell
- multi-agent-notepad example: https://github.com/NVIDIA/OpenShell/tree/main/examples/multi-agent-notepad
