# Release Notes — v1.19.0 (PREVIEW)

**Branch:** `feature/v1.19.0`
**Theme:** Agent platform Stage 2 (ADR 0003) + web `/agentrun` UX.

> ⚠️ **This is a PREVIEW / EXPERIMENTAL release.** The agent platform is
> functional and live-trial-verified, but ships with deliberate, documented
> deferrals. Read the [Preview caveats](#preview-caveats) before deploying it
> anywhere it could receive untrusted input.

---

## What this is

v1.19.0 lands the **agent platform Stage 2** (ADR 0003): a durable, addressable
`/v1/agent/*` background-run registry with two tiers locked at the URL level:

- **`POST /v1/agent/run`** — the **tool-free oneshot tier** (safe *because* it
  has no tools; same class as `/v1/oneshot`).
- **`POST /v1/agent/task`** — the **tool-capable, sandboxed tier** (capability
  grant + tool allowlist + egress allowlist + budgets/cancel + sub-agent spawn).

Plus a **web-client UX** for the oneshot tier: `/agentrun` renders a background
run into a right-panel pane while the chat stays interactive, and `/agentruns`
lists/navigates runs.

## v1 gateway compatibility (ppxai-sre and other consumers)

The v1 gateway **shape** (`POST /v1/oneshot`, bearer auth, response shape) is
**preserved**. The `oneshot.py` changes are additive and default-off:
provider-agnostic construction, an opt-in grounding flag, and loopback
auth carve-outs. Existing bearer clients are unaffected.

## Highlights

- **Run registry** (`engine/agent_runs.py`): start/list/get, background
  execution, append-only `events.jsonl` + monitor SSE (`?live=1`, level/category
  filters), budgets (iterations/time/tokens), cooperative cancel, conditional
  resume checkpoint.
- **Sandbox seams:** AC-1 tool allowlist (`ScopedToolManager`), AC-2 egress
  allowlist (`engine/tools/network_policy.py`, fail-closed, https-only, superset
  rule, SSRF guard for private/loopback IPs), shell tools rejected (400).
- **Sub-agents:** `spawn_subagent` (N=1, depth=1, child grant ⊆ parent, child
  egress ⊆ parent, consent-gated, owner-inherited).
- **Auth:** `/v1/tokens` CRUD + pluggable secret sources; per-run owner-scoped
  authorization on monitor channels.
- **Web UX:** `AgentRunView` (one pane per `run_id`), clickable breadcrumbs +
  `/agentruns` rows that focus/reopen panes, pinned running panes. Logic in
  `web/shared/agent-run-controller.js`. The detached watcher polls to terminal
  on stream loss, breaks on all terminal run-events (incl. cancelled /
  interrupted), and mirrors the result to chat if the pane was closed/evicted.
- **Oneshot grounding** (opt-in, `tools.web_search.oneshot_grounding`,
  default off).
- **Dev ergonomics:** `PPXAI_WEB_DIR` to serve the web UI from a checkout.
- **Model:** vLLM `Qwen3.6-27B-FP8-agent` config provider (self-hosted
  llm-eval champion, 93.6%).

See [docs/plan-v1.19.0-sequencing.md](plan-v1.19.0-sequencing.md) for the
increment plan and [docs/agent-platform-call-graphs.md](agent-platform-call-graphs.md)
for per-increment route→event call graphs (including the post-Inc-9 §A–§K fixes).

## Preview caveats

These are intentional Stage-2 deferrals. They are **safe to ship labeled**, not
safe to ship silently:

1. **The `/v1/agent/task` sandbox is in-process only.** OS-level isolation
   (ADR 0003 tier-d) is deferred. The tool allowlist and egress firewall are
   enforced at a single Python chokepoint (`ScopedToolManager.execute_tool`).
2. **Egress defense is application-layer.** `NetworkPolicy.check()` blocks
   allowlisted hosts that resolve to private/loopback IPs and enforces
   https-only, but **DNS-rebinding / TOCTOU is not defended** (needs
   network-layer enforcement, lands with tier-d). **Treat `allow_outbound`
   allowlists as trusted operator input, not a boundary against a hostile
   agent.** Do not expose `/v1/agent/task` to untrusted input in this release.
3. **Sub-agent spawning over the API requires `tools.agent.spawn_consent="auto"`**
   (no interactive consent channel); the subset rules are then the only
   boundary. The proper `AGENT_WAITING`/respond flow (ADR §8) is deferred.
4. **Cancel is cooperative.** A cancel issued during a provider HTTP call waits
   for that call to return.
5. **Web `/agentrun` UX is experimental.** The tool-capable `/task` UI is **not
   built** (its own design iteration), and TUI/VSCode parity is not done — this
   release's agent UX is web + oneshot only.

Tracked in [docs/debt-inventory.md](debt-inventory.md) Item 37 (agent-platform
watchlist) and Item 21 (`chat_with_tools` decomposition).

## Tests

Full suite green on Unix with `uv sync --all-extras`. (See the README badge for
the canonical count.)

## Upgrade notes

- No migration required. New `/v1/agent/*` surface is additive.
- Optional config: `tools.web_search.oneshot_grounding` (default off),
  `tools.agent.spawn_consent` (default `deny`).
- For web development, `PPXAI_WEB_DIR=$PWD/ppxai/web` serves a checkout directly
  (see [docs/dev-setup.md](dev-setup.md)).
