# Release Notes — v1.19.0 (PREVIEW)

**Branch:** `feature/v1.19.0`
**Theme:** Agent platform Stage 2 (ADR 0003): the `/v1/agent/*` run registry
+ the tool-capable **`/task` command family** in web + VSCode, client bearer
auth, and the surrounding hardening.

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
  grant + tool allowlist + egress allowlist + budgets/cancel + sub-agent spawn),
  **default-off** (`tools.agent.task_tier_enabled`).

On top of the registry, the **`/task` command family** (T1–T8a) ships in the
**web and VSCode clients**: launch/list/show/watch/cancel plus the full run
lifecycle — consent parks (`respond`), held results (`ack`), and conditional
resume. See the new **[Task Agent User Guide](task-agent-guide.md)**.

## v1 gateway compatibility (ppxai-sre and other consumers)

The v1 gateway **shape** (`POST /v1/oneshot`, bearer auth, response shape) is
**preserved**. The `oneshot.py` changes are additive and default-off:
provider-agnostic construction, an opt-in grounding flag, and loopback
auth carve-outs. Existing bearer clients are unaffected. The `/v1/agent/*` +
`/v1/tokens` surface remains under an explicit in-development exemption
([api-gateway.md](api-gateway.md)).

## Highlights

### Platform (server)
- **Run registry** (`engine/agent_runs.py`): start/list/get, background
  execution, append-only `events.jsonl` + monitor SSE (`?live=1`, level/category
  filters), budgets (iterations/time/tokens), cooperative cancel, conditional
  resume checkpoint, restart-orphan sweep.
- **Sandbox seams:** AC-1 tool allowlist (`ScopedToolManager`), AC-2 egress
  allowlist (`engine/tools/network_policy.py`, fail-closed, https-only, superset
  rule, SSRF guard for private/loopback IPs), shell tools rejected (400),
  optional filesystem seal (`tools.agent.sandbox`, default-off, per-run jail +
  read-path scoping, `path_denied` events).
- **Run lifecycle (T5–T7):** consent parks (`waiting` + resume token +
  `POST /runs/{id}/respond`, TTL fail-closed deny), two-phase termination
  (`completed_pending_ack` + `POST /runs/{id}/ack` → `finalized`, lazy
  retention reaper), conditional resume (`POST /runs/{id}/resume` with a
  refusal decision matrix).
- **Spec files (T3):** `--spec <name>` under `tools.agent.sandbox.specs_dir`
  (`engine/agent_spec.py`; `.md` front-matter or `.json`), precedence
  request > spec > skill > `default_subagent`, ceiling-clamped (no shell,
  tier gate). Examples in `examples/task-specs/`.
- **Skills (T4):** `--skill <name>` under `sandbox.skills_dir`
  (`engine/agent_skill.py`): `SKILL.md` grant + the skill dir mounted into the
  run's read scope; skills compose. Examples in `examples/task-skills/`.
- **Sub-agents:** `spawn_subagent` (N=1, depth=1, child grant ⊆ parent, child
  egress ⊆ parent, consent-gated, owner- and workdir-inherited).
- **Per-run workdir intent:** `workdir` on `POST /v1/agent/task` — clients
  thread the session working dir (`--work-dir` overrides); unsealed default is
  `server.working_dir` → home (never the server process launch dir); sealed
  runs keep their jail and flag `workdir_ignored`.
- **Auth:** `/v1/tokens` registry (mint/list/revoke, salted-hash store,
  loopback bootstrap mint) + pluggable secret sources; per-run owner-scoped
  authorization; CORS `*` removed + Host-header validation.

### Clients (web + VSCode)
- **`/task` family UI (T1 + T8a):** run/ls/show/watch/cancel/respond/ack/resume;
  live event tail with poll fallback; consent card (web) / native QuickPick
  (VSCode); Collect + Resume affordances; status-aware run-id autocomplete.
- **`/token` bearer management (Item 40):** `status|set|mint|clear` in both
  clients — web `localStorage`, VSCode `SecretStorage` (shared with the
  "ppxai: Set API Token" palette entry); bearer scoped to `/v1/*` only; 401s
  from agent verbs point at the fix.
- **Per-client completion gating:** server-driven autocomplete no longer offers
  client-side commands to clients that don't implement them (TUIs stop seeing
  `/task`, `/token`, `/agentrun`).
- **Web `/agentrun` UX:** background oneshot runs render into right-panel panes
  (`AgentRunView`), fire-and-forget, chat stays usable.

### Providers & misc
- **Gemini:** google-genai unfrozen 1.56.0 → **2.11.0** (`<2.12.0`), KI-001
  resolved; tool-schema sanitizer (oneOf→anyOf etc.) fixes spawn-tool
  validation crashes.
- **Gemini native tool loop (Item 41):** `_parse_function_call` threads a
  `tool_call_id` (synthesized when the SDK omits it) and `_convert_messages`
  maps the engine's native transcript onto Gemini's
  `function_call`/`function_response` parts (paired by function name) —
  activating the native tool-pairing branch for Gemini instead of the
  synthetic "I'll use the X tool" text flattening. Dead `_filter_empty_parts`
  deleted. Benchmark gate 3× gemini-2.5-flash on 2.11.0: code editing
  100/100/100, overall 80.7/72.6/73.8.
- **`gateway-smoke.py`** (`scripts/gateway-smoke.py`) — stdlib-only v1-surface
  acceptance for an installed binary (`/status`, `/v1/agent/runs`,
  `POST /v1/oneshot` shape, the `/v1/agent/run`→`completed` and
  `/v1/agent/task`→ack→`finalized` lifecycles); refuses to spawn over a held
  port. Wired into the build-install skill's step-8 acceptance.
- **Oneshot grounding** (opt-in, `tools.web_search.oneshot_grounding`,
  default off).
- **Desktop:** the web-UI installer is version-gated (`.installed-by` marker) —
  local web syncs survive relaunches.
- **Dev ergonomics:** `PPXAI_WEB_DIR` to serve the web UI from a checkout.
- **Model:** vLLM `Qwen3.6-27B-FP8-agent` config provider (self-hosted
  llm-eval champion, 93.6%).

See [docs/plan-v1.19.0-sequencing.md](plan-v1.19.0-sequencing.md) +
[docs/plan-task-command-sequencing.md](plan-task-command-sequencing.md) for the
increment plans and
[docs/agent-platform-call-graphs.md](agent-platform-call-graphs.md) for
route→event call graphs (post-Inc-9 hardening §A–§N).

## Preview caveats

These are intentional Stage-2 deferrals. They are **safe to ship labeled**, not
safe to ship silently:

1. **The `/v1/agent/task` sandbox is in-process only.** OS-level isolation
   (ADR 0003 tier-d) is deferred. The tool allowlist, egress firewall, and
   filesystem seal are enforced at a single Python chokepoint
   (`ScopedToolManager`).
2. **Egress defense is application-layer.** `NetworkPolicy.check()` blocks
   allowlisted hosts that resolve to private/loopback IPs and enforces
   https-only, but **DNS-rebinding / TOCTOU is not defended** (needs
   network-layer enforcement, lands with tier-d). **Treat `allow_outbound`
   allowlists as trusted operator input, not a boundary against a hostile
   agent.** Do not expose `/v1/agent/task` to untrusted input in this release.
3. **Headless spawn consent.** Interactive consent parks (T5) need a client to
   answer them; unattended API callers must either answer parks via
   `POST /runs/{id}/respond` or set `tools.agent.spawn_consent="auto"` (the
   subset rules are then the boundary). Unanswered parks deny at TTL.
4. **Cancel is cooperative.** A cancel issued during a provider HTTP call waits
   for that call to return.
5. **Client coverage:** `/task` ships in **web + VSCode**. The TUI port (T8b)
   is parked pending a transport decision; the container tier (T9) is
   deferred. `/agentrun` remains web-only.

Tracked in [docs/debt-inventory.md](debt-inventory.md) Item 37 (agent-platform
watchlist) and Item 21 (`chat_with_tools` decomposition). (Item 41 — Gemini
text-flattened tool loops — is **resolved** in this release; see Providers.)

## Tests

Full suite green on Unix with `uv sync --all-extras`. (See the README badge for
the canonical count.)

## Upgrade notes

- No migration required. The `/v1/agent/*` surface is additive.
- New optional config (all default-off/safe):
  `tools.agent.task_tier_enabled`, `tools.agent.default_subagent`,
  `tools.agent.sandbox.{enforcement,workdir,read_paths,specs_dir,skills_dir,allow_skill_scripts}`,
  `tools.agent.{spawn_consent,consent_ttl_s,result_retention_s}`,
  `tools.web_search.oneshot_grounding`, `server.working_dir`,
  `server.secrets.providers` (file provider ⇒ auth enforced + `/v1/tokens`).
- Gemini users: google-genai now resolves to 2.11.x (`<2.12.0`).
- For web development, `PPXAI_WEB_DIR=$PWD/ppxai/web` serves a checkout directly
  (see [docs/dev-setup.md](dev-setup.md)).
