# ppxai Debt Inventory — Open Items

**Status:** Rolling. This file holds the **currently open** deferred items
across all branches. When an item lands, it moves to "## Closed" with the
commit hash + date. New deferred work added during a branch lands here at
that branch's commit.

This is the canonical location replacing the per-version
`DEBT-INVENTORY-v1.18.2.md` / `DEBT-INVENTORY-v1.18.3.md` pattern (those
are now archived under [docs/archive/](archive/) as historical snapshots).

---

## How to use this file

- **Update on every release branch.** When an item lands, move it under
  "## Closed" with commit hash + date. When new debt surfaces, add it
  to the appropriate section with a `**Planned:**` tag.
- **Tag every open item with where it'll be addressed.** Either a target
  release (`v1.19.x`), a target branch (`feat/<name>`), or a trigger
  condition (`when k8s context`). Untagged items become invisible in
  release planning.
- **Don't mix in feature work.** Debt is bug-class follow-up. Roadmap
  features (Anthropic provider, multi-model routing, etc.) live in
  [ROADMAP.md](../ROADMAP.md).
- **Don't mix in TODOs scoped to a specific in-flight version.** Those
  describe in-flight planning (`TODO-v1.18.x-*.md`); debt describes
  work intentionally **not** in any version's plan yet.
- **Keep entries scannable.** Lead with one short paragraph + the
  `**Planned:**` and `**Trigger to revisit:**` lines + an effort
  estimate. Long context goes in linked docs / archive snapshots.

---

## Open

### Item 3 — k8s session-manager security tests [originally Critique #8 in v1.18.2]

**Affected files:** `deploy/images/session-manager/main.py` (~648 LOC),
`deploy/images/session-manager/ldap_auth.py` (~130 LOC).

**What's wrong:** untested high-risk functions in the multi-tenant
deployment service: `_list_sessions` (risk 0.85), `_teardown_session`
(risk 0.7), `create_session`, `delete_session`, `heartbeat`, `startup`,
`LDAPAuthenticator._hash_password`, `authenticate`. Recommended
scenarios: auth failure, timing-safe hash comparison, K8s resource
naming validation (escape via `..` / `/` in usernames), teardown
idempotency, stale heartbeat cleanup, permissions/secrets handling.

**Why deferred:** zero blast radius for single-user macOS / Windows
ppxai installs (the mainline use case). Only deployers running the
Helm chart in a multi-tenant K8s cluster touch this code.

**Planned:** trigger-deferred — no version target. Open until at least
one of the three triggers fires.

**Branch when ready:** `feat/k8s-session-manager-tests` (quick-pass
already landed there + merged; 29 tests in `tests/test_session_manager_auth.py`).

**Status (2026-06-15):** quick-pass DONE. **Full suite POSTPONED — do
after agent-platform Stage 2 is in place.** Rationale: the full suite's
real value is validating the sub-agent-in-a-pod k8s security boundary
end-to-end, which doesn't exist to test against until Stage 2 ships the
sub-agent + pod-sandbox tool-execution path. Writing 30-50 mocked tests
now would test the session-manager in isolation, not the thing we
actually need confidence in. Revisit once Stage 2 Phase 1-4 lands.

**Trigger to revisit:** when a third-party deploys ppxai multi-tenant,
OR when a security audit demands LDAP/RBAC test coverage, OR when CVE
disclosure procedures need this code to have minimum test coverage,
OR when agent-platform Stage 2 sub-agent pod sandbox lands (validate together).

**Effort:**
- Quick pass (~1 hour): 10 unit tests around `_hash_password`
  (timing-safe), `authenticate` (denial fail-closed), naming validation.
- Full pass (~half day): 30-50 tests with mocked `kubernetes.client`,
  covering all 8 functions.
- Defensive sweep (+ ~half day): LDAP injection patterns, secret-in-log
  scrubbing, kubeconfig path validation.

**Original entry (full design rationale):**
[docs/archive/DEBT-INVENTORY-v1.18.2.md](archive/DEBT-INVENTORY-v1.18.2.md#item-3--k8s-session-manager-security-tests-critique-8).

---

### Item 21 — `chat_with_tools` decomposition

**Affected file:** `ppxai/engine/chat.py:475-1147` (single function,
673 LoC, fan-out 169 — the largest function in the codebase).

**What's wrong:** the engine's core tool loop is one monolithic
function with no direct unit-test coverage. The only existing test is
`tests/test_chat_profile_routing.py` which exercises it through a
"Minimal mock provider" — integration paths only, no isolated
coverage of the inner-loop state transitions (tool call → tool result
→ continuation, abort handling, budget enforcement, AGENT_BEAT
emission, retry semantics).

**Why deferred:** the function IS the engine's hot path. Refactoring
it without a comprehensive unit-test scaffold first risks behavioral
regressions across every provider + every tool. Decomposition needs
to be ADR-backed (proposed split: outer-loop / inner-loop / state
machine), with a per-stage test sweep before any code moves.

**Planned:** v1.19.x or later. Likely shares ADR space with the
agent-platform Stage 2 work (ADR 0003) since `chat_with_tools` is
where the run-namespace, budget enforcement, and sub-agent spawn all
intersect.

**Status (2026-06-15): POSTPONED for the `feature/v1.19.0` iteration.**
Not in this iteration's active set. The decomposition is best done
*alongside or after* Stage 2 lands its run-state machine — Stage 2 will
add run-namespace / budget / sub-agent code into this exact function, so
decomposing first would just be re-touched. Let Stage 2 settle the shape,
then split. See [docs/archive/plan-v1.19.0-sequencing.md](archive/plan-v1.19.0-sequencing.md).

**Branch when ready:** `feat/chat-with-tools-decomp` (ADR + tests
first commit; code split as a follow-on).

**Trigger to revisit:** when ADR 0003 Stage 2 implementation opens
(the run-state machine refactor is the natural companion), OR when
the function grows beyond 800 LoC.

**Effort:**
- ADR + behavior-pinning test scaffold (~half day to ~1 day): map
  every distinct control-flow path, write assertions for each.
- Split into outer-loop / inner-loop / state machine (~2-3 days).
- Per-provider regression sweep (~1 day across OpenAI-compat, Gemini,
  Perplexity, native OpenAI).

**Surfaced by:** CRG `find_large_functions` + `get_hub_nodes` on
bugfix/v1.18.7 (graphify hyperedge "chat_with_tools dispatcher"
captured the same shape).

---

### Item 22 — `PpxaiApp` (web/app.js) further decomposition

**Affected file:** `ppxai/web/app.js` — `PpxaiApp` class, 3,749 LoC
(down from 3,679 before the v1.18.7 `_previewAttachment` extract —
extract added 71 lines of method boilerplate; the dispatcher itself
shrank 8x).

**What's wrong:** still the single biggest god class in the codebase
even after the v1.18.7 split. Other long methods inside it (e.g.
`setupEventListeners` at degree 103, `cacheElements` at degree 64)
remain candidates. The class also still owns SSE handling, AppState
sync, slash-command dispatch, the markdown renderer wrappers, and
the right-panel orchestration — five distinct responsibilities.

**Why deferred:** decomposing a god class in non-bundled JS without
introducing a build step is painful (`AttachmentView` was extractable
because it had no state; most other methods touch `this.state`,
`this.apiClient`, `this.eventBus`, and DOM elements all at once). The
right shape is probably a "responsibilities-as-mixins" refactor or
the introduction of esbuild on the web side (mirror of the
vscode-extension bundler from v1.18.2). Neither fits a bugfix branch.

**Planned:** trigger-deferred — no version target. Revisit when (a)
web client gets a build step, OR (b) a specific responsibility (e.g.
SSE handling) needs to be reused by ppxai-desktop / another consumer.

**Branch when ready:** `feat/web-client-decomp` (with explicit
sub-step plan in the branch's first commit).

**Trigger to revisit:** when ppxai-desktop or another client wants to
share part of `PpxaiApp`'s logic, OR when adding a build step to the
web client is on the table for other reasons.

**Effort:** unknown until shape is chosen. Likely 3-5 days for a
mixin-based split; longer if introducing esbuild.

**Recent progress (v1.18.7):** `_previewAttachment` (347 LoC) split
into 6 per-format renderers + dispatcher — file +71 LoC net but each
branch individually browseable. See commit on bugfix/v1.18.7.

---

### Item 23 — `SessionManager` growth drift (flag-only, not action)

**Affected file:** `ppxai/engine/session.py` — `SessionManager`
class, 2,091 LoC (was 1,648 at v1.18.2 baseline — grew +443 LoC, +27%,
in 3 weeks).

**What's wrong:** noted as a drift signal during bugfix/v1.18.7
analysis. After verification per the CLAUDE.md "verify before
flagging" rule, the growth is **fully explained by intentional
recent feature work** — every commit accounting for the +443 LoC is
ADR 0006 wiring:
- `02ef33ab` Step 5: v1→v2 session migration on first load (+224)
- `21dd226d` Step 7c: producer drops in-block keys (+174/-50, +124 net)
- `b20cb1b0` fix: trailing-tool strip cascade (+132/-51, +81 net)
- `af63e482` Step 4: `schema_version: 2` + ArtifactRegistry (+81/-11)
- `b07bd0fa` Phase 1: AttachmentRef + Message.attachments (+11/-1)
- `70a0457f` fix: per-turn delta for context baseline (+11/-2)

Channel ratio (`event_bus.emit/subscribe`, `state.on/set/get`) = 0:
all coupling is direct. Production-only inbound = 47 textual
references across 13 files — above the 30-ref threshold but
proportionate to the type-spine role.

**Why "flag-only":** the growth is not architectural decay. It's
load-bearing v1.18.6 release work that landed on this file.

**Planned:** no action required. **If** decomposition is ever needed,
the natural carve-out is the schema-migration block (lines covering
`migrate_v1_to_v2`, the `.v1.backup/` sibling-folder logic, and the
schema_version dispatch) — that's where the recent growth
concentrated, and it's a self-contained sub-responsibility.

**Trigger to revisit:** when SessionManager crosses 2,500 LoC, OR when
schema_version: 3 is proposed (the migration block becomes a natural
extract at that point).

**Surfaced by:** CRG analysis on bugfix/v1.18.7.

---

### Item 29 — `engine.completion` imports `commands.factory` and reads its internals [layer inversion]

**Affected files:** `ppxai/engine/completion.py` (import at line **48**).
Shared entrypoint `complete()` is called from `ppxai/tui/completer.py:25`,
`ppxai/rich/main.py:34`, and `ppxai/server/routes/completion.py:17`.

> **Re-verified 2026-08-15 — half of this item is already closed.** The
> private-registry access is **gone**: completion now reads the public
> `iter_completion_specs()` snapshot and `CommandFactory.get()` for alias
> resolution, so the "reads privates, brittle to factory refactors" half no
> longer applies. What remains is the **layer inversion alone** — one
> import, the only `engine → commands` edge in the whole engine package.
>
> **It is not currently blocking the SDK use case.** Measured: importing
> `ppxai.engine.task_runner` + `ppxai.engine.client` — the path ppxai-sre
> embeds — pulls in **zero** `ppxai.commands` modules and never imports
> `engine.completion`. The edge is dormant unless a caller imports
> completion explicitly, which only the three client glue layers do.
>
> **Reclassified:** architectural cleanup, no current correctness defect.
> Keep open, not release-blocking. The conditions that would make it hard-
> blocking are enumerated in
> [ADR 0007](decisions/0007-completion-first-class-service.md) "Triggers to
> revisit"; the planned fix (a top-level `CompletionService` behind narrow
> protocols, roster published via AppState) is unchanged and still right.

**What's wrong:** `engine/completion.py` is documented as engine /
client-agnostic, but it imports **upward** into the `commands` layer and
reaches into `CommandFactory`'s private `_registry`/`_aliases` to enumerate
slash-command names for autocomplete. Engine depending on `commands` is a
layer inversion; reading privates makes it brittle to factory refactors.

**Why deferred:** the coupling is **intrinsic and harmless at runtime** —
command-name completion inherently needs the command registry, and there's
no correctness bug. Surfaced by the v1.18.7 post-release code review
(finding 1); the "real" fix is an architecture change, not bug-class.

**Review-gate outcome (2026-06-14):** the gate reframed completion as a
*capability* over `(command-space × live-context)` that belongs to no single
layer — not engine-owned data. Decision recorded in
[ADR 0007](decisions/0007-completion-first-class-service.md):
- **Seed landed in v1.18.8** (`bugfix/v1.18.8`): added public
  `CommandFactory.iter_completion_specs()` + `CompletionCommandInfo`;
  `engine.completion._complete_commands` now consumes that snapshot instead
  of `_registry`/`_aliases`. **The privates-reach is closed**, behaviour
  byte-identical (61 completion tests + 3 new accessor tests green). The
  `engine → commands` *import* deliberately remains — removing it is the
  v1.19.x work below.
- **v1.19.x (ADR 0007):** lift `complete()` into a first-class
  `ppxai/completion/CompletionService` behind `CommandRegistryProtocol` +
  `CompletionContextProtocol` (leaf), injected at each composition root
  (preloaded at startup); publish the command **roster** through AppState
  `state_sync` for palettes/help/menus. This is what removes the import.

**Planned:** seed **done** in v1.18.8; first-class service + AppState roster
**→ v1.19.x** per ADR 0007.

**Branch when ready:** v1.19.x (new branch — pairs with any "ship engine
standalone" goal).

**Trigger to revisit:** see ADR 0007 triggers (engine-as-standalone-library
goal; a second client surface needing the live roster; a second cross-layer
capability of the same shape).

**Effort (remaining, v1.19.x):** ~1–1.5 d — two Protocols, the service
package, composition-root wiring at 3 entry points, AppState roster field +
4-mirror DTO update, cross-client completion tests.

---

### Item 33 — command-layer `console.print` sweep (agent/utility/handler) [envelope-pattern hygiene]

**Affected files:** `commands/agent.py` (~43 `console.print`),
`commands/utility.py` (~39), `commands/handler.py` (~29).

**What's wrong:** these handlers write user-facing text directly to the Rich
console instead of returning typed results / side-effects, so anything they
print is invisible to web/VSCode (server-side stdout). The cross-client
gap on the coding commands was the acute case — fixed as Item 30 (closed).

**Why deferred (verify-before-fixing):** the bulk of these are genuinely
**interactive TUI-only flows** (`input()`-driven rollback / confirm prompts
in `/agent`, `/undo`) that cannot run under `ServerCommandContext` anyway, so
they are *not* a cross-client bug. The remainder must be audited
case-by-case: only the ones on a cross-client command path (reachable via
`POST /command/{name}` and emitting information not already in the returned
result) need routing through `content`/`message`/side-effects. Bulk
conversion is UI-purity refactor, not bug-class.

**Planned:** v1.19.x — audit each site; fix only the cross-client-reachable
ones; leave interactive TUI prompts as-is. Pairs naturally with ADR 0002
(CommandContext) work if the contexts gain a "can prompt interactively" flag.

**Branch when ready:** v1.19.x.

**Trigger to revisit:** a web/VSCode user reports missing output from a
non-coding command, or the v1.19.x command-context work opens the file set.

**Effort:** ~0.5 d audit + targeted fixes (most sites confirmed TUI-only).

---

### Item 34 — office-preview deps must be bundled in binaries; build/CI must use `--all-extras` [packaging]

**Affected:** `.claude/skills/build-install/SKILL.md`, the release CI build
step, `pyproject.toml [data]` extra (`pypdfium2`, `openpyxl`, `python-pptx`;
NB **no `python-docx`** → Word *text* fallback can't extract).

**What's wrong:** the office-preview pipeline needs `pypdfium2` (PDF→PNG) and
`python-pptx`, which live in the `[data]` optional extra. The `/build-install`
skill builds with `uv run --no-sync pyinstaller`, so if the venv lacks
`[data]` the binaries ship **without** office support — LibreOffice is detected
but `render_pptx_slides` returns `[]` ("No slides rendered"). Found live on a
2026-06-14 local build. Also: `python-docx` is absent from `[data]`, and the
frozen binary can't use a `pip install 'ppxai[data]'` hint.

**Release CI verified SAFE (2026-06-14) — NOT a release blocker.**
`.github/workflows/build.yml` runs `uv sync --frozen --all-extras` before
**every** PyInstaller job (ppxai / ppxai-server / ppxaide / ppxai-desktop,
lines 95/155/209/264); the server-job comment documents exactly this trap
("Without `--all-extras`, PyInstaller silently drops … pypdfium2 … python-pptx
… missing PDF rasterization"). So **released binaries bundle the office deps**.
The gap is local-only: the `/build-install` SKILL uses `--no-sync`. (Local
v1.18.8 build re-run WITH `[data]` synced renders previews correctly — verified
HTTP 200 image/png.)

**Release-script test step fixed (2026-06-14):** `scripts/release.py::run_tests`
ran `uv run pytest` (no `--all-extras`), which synced to default deps and
stripped the `[data]` extras → office/upload suites skipped → ~150-short count
written into the README `tests-NNNN` badge (it had regressed to 3844). Now
`uv run --all-extras pytest` so the count matches the all-extras suite (3989).

**Build-install skill fixed (2026-06-14):** `.claude/skills/build-install/SKILL.md`
Step 1 now runs `uv sync --all-extras` before PyInstaller (the per-build
`--no-sync` reuses that env), with a precondition note and a Step-8
office-preview acceptance check (curl `/files/preview` → expect `image/png`).

**Remaining (v1.19.x, non-blocking):** add `python-docx` to the `[data]` extra
so the Word *text* fallback can extract without LibreOffice. (Word *raster*
preview already works via LibreOffice.)

**Branch when ready:** `bugfix/v1.18.8` (skill) / v1.19.x (docx dep).

**Trigger to revisit:** active for the skill edit; docx is v1.19.x.

**Effort:** ~1 h (skill `uv sync --all-extras` + docx dep).

---

### Item 35 — pluggable memory/log/knowledge persistence channel abstraction [architecture]

**Affected (future):** a new `ppxai/persistence/` (or `ppxai/memory/`)
package; first consumers would be ADR 0003's `AgentRunRegistry`
(`events.jsonl` / `state.json` / `transcript.md`), `engine/session.py` +
`session_store.py`, and the checkpoint machinery — each currently rolls
its own filesystem persistence.

**What's needed:** a ppxai service/component that abstracts **recording
of memory / logs / session knowledge behind a pluggable *channel*
interface**, so the backing technology is swappable without touching
callers. Backends to support over time: append-only **JSONL** (today's
default), **markdown** (human-readable transcript), **SQLite** (indexed
queries), **mem0** and **vector stores** (semantic recall / curated
long-term memory), and others. The same abstraction is the substrate
for two capabilities ppxai doesn't have yet: (1) **resume context** —
reconstructing an agent or session's working state from its recorded
channel, and (2) **knowledge curation** — summarizing / compacting /
promoting durable facts out of raw event logs (the mem0-style layer).

**Why this generalizes existing seams:** ADR 0003 Question B already asks
"filesystem vs SQLite for the registry" and answers "put the read/write
API behind a single class so the migration is mechanical." This item is
that idea promoted to a **first-class protocol** shared across agent
runs, sessions, and checkpoints, with the backend chosen by config — not
a per-subsystem decision. Fits the project's leaf-`Protocol`
dependency-inversion pattern (define `MemoryChannelProtocol` /
`PersistenceChannelProtocol` in a leaf module; concrete backends as
plug-in implementations, mirroring `rendering/base.py::Renderer` and the
`ArtifactRegistry`/`ArtifactProjector` framework from ADR 0006).

**Why deferred:** this is foundational infra that should crystallize
**after** the `AgentRunRegistry` exists (so the registry is its first
concrete consumer and the protocol is shaped by a real second caller),
not before — abstracting on one consumer is premature. mem0/vector
backends also add dependency + operational surface (embeddings, store
lifecycle) that wants its own design pass.

**Planned:** v1.19.x+ — likely its own ADR (e.g. ADR 0008 "pluggable
persistence/memory channels"); sequence it alongside or just after
ADR 0003 Stage 2 so agent-runs and sessions become the two consumers
that validate the protocol shape.

**Branch when ready:** new branch (pairs with ADR 0003 Stage 2 work).

**Trigger to revisit:** a second persistence consumer wants a swappable
backend (agent-runs **and** sessions both asking), OR resume-context /
knowledge-curation becomes a feature ask, OR a mem0 / vector-recall
requirement lands from a consumer (e.g. ppxai-sre long-lived agents
needing cross-run memory).

**Effort:** ~2–3 d for the protocol + JSONL/markdown/SQLite backends
behind it (the file backends already exist as code to wrap); mem0 /
vector backends are separate, larger, dependency-bearing add-ons.

**Surfaced by:** agent-platform MVP design discussion 2026-06-15 (while
resolving ADR 0003 — the registry's hardcoded filesystem layout made the
missing abstraction visible).

---

### Item 38 — model-catalog watch list (verified live 2026-07-11)

Full live sweep 2026-07-11 (method: `set -a; . ~/.ppxai/.env; set +a` + curl
each provider's `/models` with bearer; Perplexity has no `/models` — verified
via docs + changelog). **Result: every configured model on all four providers
is still live — no dead models, no config change required now.** OpenAI 7/7
(incl. `gpt-5.3-codex`, still the newest codex line), Gemini 5/5 (incl. both
`gemma-4-*`), NVIDIA 9/9 (unusually, zero NIM retirements this round),
Perplexity 4/4 Sonar models unchanged. `model_deprecations.py` verification
date bumped to 2026-07-11; no new table entries needed.

**Watch items (act on trigger, not now):**

1. **OpenAI gpt-5.6 "Sol / Terra / Luna"** — ⚠️ **TRIGGER FIRED 2026-08-01:
   GA, plus 2026-07-30 price cuts (Luna −80% to $0.20/$1.20, Terra −20% to
   $2/$12 — the $2.50/$15 / $1/$6 figures below-generation are stale).
   Superseded by Item 55**, which carries the verified pricing/benchmark/
   hazard detail and the fix order.

2. **Perplexity Agent API** — 🔴 **ESCALATED 2026-08-30: the Sonar
   chat-completions endpoint has a RETIREMENT DATE — 2026-09-27** (forum
   announcement "Sonar is moving to the Agent API",
   community.perplexity.ai/t/5802, + changelog; endpoint now labelled
   *legacy* with a migration guide). It is the only wire
   `PerplexityProvider` — and `web_premium.py`'s separate web_search
   client — speak. Migration is planned as
   [plan-adr-0012-implementation.md](plan-adr-0012-implementation.md)
   W0–W3, target complete **2026-09-20** (forum precedent: Gemini
   endpoints have died early). Prior state (TRIGGER FIRED 2026-08-13):
   docs stabilized, "Sonar Chat Completions is now Agent API" (changelog,
   July 2026; GA February 2026); chat completions still works — the
   Item 43 live runs all went through it.

   **Verified roster** (`docs.perplexity.ai/docs/agent-api/models.md`,
   fetched 2026-08-13) — far wider than the 2026-07 changelog sample:
   - Anthropic: `claude-opus-5`, `claude-opus-4-8`, `claude-opus-4-7`,
     `claude-opus-4-6`, `claude-opus-4-5`, `claude-sonnet-5`,
     `claude-fable-5`, `claude-sonnet-4-6`, `claude-sonnet-4-5`,
     `claude-haiku-4-5`
   - OpenAI: `gpt-5.6-{sol,terra,luna}`, `gpt-5.5`, `gpt-5.4`,
     `gpt-5.4-mini`, `gpt-5.4-nano`, `gpt-5.2`, `gpt-5.1`, `gpt-5`,
     `gpt-5-mini`
   - Google: `gemini-3.1-pro-preview`, `gemini-3.1-flash-lite`,
     `gemini-3.5-flash`, `gemini-3.5-flash-lite`, `gemini-3.6-flash`,
     `gemini-3-flash-preview`
   - xAI: `grok-4.6`, `grok-4.5`, `grok-4.3`, `grok-4.20-reasoning`,
     `grok-4.20-non-reasoning`, `grok-4.20-multi-agent`
   - Other: `perplexity/deepseek-v4-flash-0731`, `perplexity/glm-5.2`,
     `perplexity/kimi-k3`, `perplexity/kimi-k2.7-code`,
     `perplexity/nemotron-3.5-lightning-30b-a3b`,
     `perplexity/nemotron-3-ultra-550b-a55b`, `perplexity/sonar`

   **Wire shape — CORRECTED 2026-08-15, measured live.** The paragraph
   here previously read *"NOT OpenAI-compatible for tools … would need a
   translation layer"*. That was derived from the docs and is **wrong**.
   The Agent API **is the OpenAI Responses API**: `POST /v1/agent` and
   `POST /v1/responses` are both live, accept the new model IDs, and return
   the Responses envelope. It does return `function_call` items rather than
   `tool_calls` — but that *is* the Responses shape, and ppxai already
   implements it at `openai_native.py:610` (`_chat_responses_api`), which
   already handles `function_call`. The stock OpenAI SDK
   (`OpenAI(base_url=...).responses.create`) drives it unchanged.

   So this is a **routing** problem, not a protocol problem — per-model
   `api_path`, which is exactly what `ToolCallingProfile` already carries.
   Tracked as I4b in [plan-per-model-capabilities.md](plan-per-model-capabilities.md).
   Note `anthropic/*` **requires `max_output_tokens`** (400 without) — more
   table data, not a code branch.

   Built-in tools: `web_search`, `sandbox` (code execution), `fetch_url`,
   `finance_search`, `people_search`, plus MCP server support.

   **Bearing on Item 43:** the Sonar chat-completions endpoint *does* now
   emit native `tool_calls` for `sonar-pro` / `sonar-reasoning-pro`
   (verified live), so fixing Item 43 does **not** require adopting the
   Agent API. These are independent decisions.

   **Still open:** (a) reaching the Agent-API fleet — no translation layer
   needed (see the correction above), only `api_path` routing; the open
   question is whether these are new models on the existing `perplexity`
   provider or a second provider entry, deliberately reserved for the owner
   at I4b — (b) Search API as a `web_search` backend, or (c) out of scope.
   `anthropic/*` here intersects the
   roadmap's native Anthropic-provider item — going direct is likely
   preferable to proxying through Perplexity. Pricing unverified.

3. **`gemini-3.1-pro-preview` succession** — still live, no announced
   shutdown, but it is the only *preview*-class model left in our catalog and
   Google retires previews on ~2–3-month cycles once a successor lands
   (precedents: `gemini-3-pro-preview` → shutdown 2026-03-09,
   `gemini-3.1-flash-lite-preview` → shutdown 2026-05-25, both bit us before).
   **Trigger:** a GA `gemini-3.1-pro`/`gemini-3.5-pro` appears → migrate + add
   the preview to the deprecations table. New Gemini families seen 2026-07-11
   worth a look at next refresh: `gemini-omni-flash-preview`,
   `deep-research-*`, `antigravity-preview-05-2026`.

4. **NVIDIA next-refresh candidates** (no action now): `z-ai/glm-5.2`,
   `minimaxai/minimax-m3`, `mistralai/mistral-small-4-119b-2603`,
   `mistralai/mistral-medium-3.5-128b`, `google/gemma-4-31b-it`,
   `moonshotai/kimi-k2.6` (already configured). NVIDIA publishes no
   deprecation calendar — the live-catalog diff IS the check; re-run the
   sweep at the next release prep.

**Trigger:** gpt-5.6 GA announcement, Perplexity Agent API docs stabilizing,
or the next release prep — whichever comes first. **Two of the three have
now fired** (watch item 1 → Item 55, 2026-08-01; watch item 2 → 2026-08-13);
only the release-prep sweep remains outstanding.

**Perplexity capability correction (2026-08-13).** The 2026-07-11 sweep
recorded "Perplexity 4/4 Sonar models unchanged", which is true of the
*model list* but missed a **capability** change: `sonar-pro` and
`sonar-reasoning-pro` gained native tool calling. A `/models`-style
existence sweep cannot see this. **Method note for the next refresh:**
probe capabilities, not just liveness — send a one-message request with a
`tools=[...]` array per model and record whether it 400s, returns prose,
or returns `tool_calls`. That single probe is what overturned Item 43.

**That method is now a script (2026-08-24, plan I4):**
`scripts/probe-perplexity-capabilities.py` runs the probe against the
shipped roster and exits non-zero on drift, so the next refresh does not
have to re-derive the method. Run it as part of the sweep:

    python3 scripts/probe-perplexity-capabilities.py --check-models-endpoint

Result 2026-08-24 — **no drift**: `sonar` REJECTS, `sonar-pro` NATIVE
(emitted a real tool call), `sonar-reasoning-pro` NATIVE; all three match
the shipped table. `/models` still 404, so enumeration remains impossible
and this probe stays the only check that can see a capability change.
`sonar-deep-research` (dropped from the roster at I3) still returns its
distinct parameter-SHAPE 400, unchanged.

---

### Item 39 — `rtk discover` false-negatives under hook rewriting; `rtk gain` is ground truth [tooling]

**What's wrong:** the 2026-07-11 `rtk discover` run reported "2.2% rtk
adoption, 489 commands / ~118K tokens of missed savings" — a false alarm.
`discover` scans Claude Code transcripts, which record the **model-emitted**
command; the global `rtk hook claude` PreToolUse[Bash] hook rewrites eligible
commands via `updatedInput` *after* the transcript records them, so every
hook-rewritten execution is miscounted as "missed". Verified live 2026-07-11:
a plain `grep -c` incremented `rtk gain`'s executed-command counter
(2517→2518) while `rtk gain` itself does not self-count; `gain` shows 1.1M
tokens actually saved (50.1% of 2.2M input) — an order of magnitude above
discover's claimed 118K "missed". Cross-check: discover claims 238 missed
`grep -n`; gain shows 266 executed `rtk grep`.

**What's real in the discover output:** the "TOP UNHANDLED" list ($UV run
35×, jq 26×, stat 7×, git rev-parse 5×) — rtk has no handlers for these.
Upstream feature-request material (github.com/rtk-ai/rtk/issues), not ppxai
debt. The residual genuine miss rate inside the "missed savings" table is
unknown but small (some entries may predate the 2026-05-10 hook install or
be compound/piped forms the hook skips).

**Why recorded here:** `rtk discover` is in the standing toolkit
(`~/.claude/RTK.md` → "Analyze Claude Code history for missed
opportunities"); without this note, the next discover run re-triggers a
false "the hook is broken" investigation.

**Planned:** no action. Use `rtk gain` / `rtk gain --history` as the
adoption ground truth; ignore discover's "missed savings" percentages on
hook-enabled hosts.

**Trigger to revisit:** an rtk release notes fix for discover counting
hook-rewritten commands, OR `rtk gain` totals plateau across sessions
(would indicate the hook actually stopped rewriting).

**Effort:** none (documentation-only entry).

---

### Item 43 — Perplexity `/task` never calls granted tools → ✅ **FIXED 2026-08-24** (plan I3) [providers / perplexity / agent platform]

> **CLOSED.** The cause was ours, not the model's. Fixed in three parts,
> because two of them were separately load-bearing:
>
> 1. **Per-model capability table** — `PERPLEXITY_NATIVE_TOOL_MODELS` in
>    `providers/perplexity.py`. `sonar-pro` and `sonar-reasoning-pro`
>    resolve `native_tool_calling=True`; everything else stays False, so an
>    unmeasured model degrades rather than 400ing.
> 2. **Model profiles** — `sonar-pro*` and `sonar-reasoning-pro*` were
>    pinned `mode="prompt_based"` in `model_profiles.py`. `chat.py:693`
>    checks the mode FIRST and short-circuits without consulting provider
>    capabilities, so **the table alone would have been decorative** —
>    measured: `profile.mode=prompt_based, caps.native=True → use_native=
>    False`. Both are now `"auto"`, which defers to the table. Same
>    "override exists but nothing reads it" shape as plan finding F1.
> 3. **Admission guard** — `_reject_tool_incapable_model` in
>    `task_authorizer.py`. `sonar` and `sonar-deep-research` answer a tools
>    array with HTTP 400 rather than degrading, and the engine's fallback
>    for a non-capable model is the prompt-based path that produced this
>    item's confabulations. A tool-carrying run on such a model is now
>    refused before it is minted, naming the capable models. Fails OPEN on
>    any unresolved lookup — it converts a KNOWN-bad combination into a
>    clear error, it is not a security boundary.
>
> `sonar-deep-research` **dropped from the shipped catalog** (owner
> decision) — example config, `install.sh`, `scripts/install.ps1`,
> `vscode-extension/src/config.ts`, and their pricing tables. Note its 400
> is not a schema quirk: the example config's own comment records that it
> "uses Jobs API with reasoning_effort … not chat completions", so it was
> never reachable on the endpoint we call. Its `model_profiles.py` entry
> stays as a behavioural fallback for anyone who configures it by hand.
>
> Tests: `tests/test_perplexity_model_capabilities.py` (31), including an
> end-to-end mode-resolution check that replicates `chat.py`'s logic so the
> profile/table coupling cannot silently break again. Five mutations killed.
>
> Framework context: `docs/plan-per-model-capabilities.md` (I1 send-path
> wiring, I2 config layers, I3 this). Remaining: I4 roster probe, I4b the
> new Agent-API fleet, I5 other providers.

---

**Historical (superseded) — the diagnosis arc, kept for the evidence.**

### Item 43 — original entry [providers / perplexity / agent platform] — ⚠️ **PREMISE OVERTURNED 2026-08-13**

> **2026-08-13 — the diagnosis below is superseded; the fix is now a
> one-line capability correction, not a routing gate.**
>
> Perplexity **added native tool calling**. Verified live against
> `api.perplexity.ai` through our own provider client:
>
> | Model | Native `tool_calls` |
> |---|---|
> | `sonar` | ❌ HTTP 400 `Tool calling is not supported for this model` |
> | **`sonar-pro`** | ✅ **emits `tool_calls`** |
> | **`sonar-reasoning-pro`** | ✅ **emits `tool_calls`** |
> | `sonar-deep-research` | ❌ HTTP 400 `Tool parameters must be a JSON object` |
>
> Full round-trip confirmed on `sonar-pro`: emits
> `read_file{"path": ...}` → accepts the `tool` result message → answers
> from it (unguessable canary content returned verbatim, so a real loop,
> not inference).
>
> **So the failures below were caused by our own config.**
> `ppxai/engine/providers/perplexity.py:63` hardcodes
> `native_tool_calling=False` on `default_capabilities` with the comment
> "Sonar models don't support native API tool_calls" — true when written,
> false now. That flag forces `profile.mode=prompt_based` and every
> symptom below follows from the prompt-based fallback, not from the API.
>
> A same-day direct-provider re-run (5 trials × `sonar`, `sonar-pro`,
> `sonar-reasoning-pro`) scored **0/15 tool calls** — but that measured
> the *prompt-based path*, i.e. the consequence of the flag. The earlier
> "1 success in 6" was the agent loop's text-extraction fallback getting
> lucky, not the model emitting a call.
>
> **Revised fix.** Make the capability **per-model**, not per-provider —
> `openai_native.py:368` already implements exactly this via
> `get_capabilities_for_model`, so it is the established shape:
> `sonar-pro` / `sonar-reasoning-pro` → `True`; `sonar` /
> `sonar-deep-research` → `False` **and** reject tool-capable `/task`
> up front, since the API 400s rather than degrading.
> Options (a)/(b)/(c) below are moot — (a) and (b) would now *block or
> reroute working functionality*, and (c) was already low-confidence.
>
> **Open sub-question.** `sonar-deep-research`'s 400 is a *schema-shape*
> complaint ("Tool parameters must be a JSON object"), not a flat refusal,
> so it may be usable with a stricter schema. Not chased.
>
> **API-surface note.** Perplexity announced *"Sonar Chat Completions is
> now Agent API"* (July 2026). Chat completions still works — all the
> above ran through it — but the Agent API is the forward surface and uses
> `function_call` / `function_call_output` rather than OpenAI-style
> `tool_calls`. Official `perplexityai` SDK is at **0.43.3**; ppxai does
> not use it (we go through the OpenAI SDK), so no SDK bump is implied.
> The Agent API also fronts third-party models — see Item 38.

**Historical diagnosis (2026-07-13, 8-run web-app trial) — kept for the
symptom record; the root cause attribution is wrong, see above.**

**Planned:** `v1.19.x`. Originally filed 2026-07-12 from one run
(`run_07c2f15936d3`, "summarize docs/README.md", perplexity/sonar-pro) that
cited `https://www.paxerp.com/...` instead of the local file. A **2026-07-13
web-app trial (8 runs across 3 providers, same task)** confirmed and
widened the root cause — the wire evidence lives in `~/.ppxai/runs/<id>/agent-0/`
(`meta.json` = finalized `result`, `events.jsonl` = tool-call trace) and
`~/.ppxai/logs/{chat,engine,validator}-debug.log`.

**Root cause (wire-verified).** Perplexity config has
`capabilities.native_tool_calling: false`, so every `/task` sonar-pro run
resolves to `profile.mode=prompt_based, use_native=False` (chat-debug.log).
sonar-pro **does not honor the injected prompt-based tool contract** —
across **6 perplexity runs, zero produced a real `read_file` call**
(no `tool_call` event in `events.jsonl`, no `Recorded tool call` in
validator-debug.log, ~2–4s wall). The failure is **nondeterministic** —
same task, three different wrong outcomes:
- **Refusal** — "I do not have direct filesystem access… I cannot
  summarize its contents" (the exact output `manager.py:457` instructs
  against). Runs `run_315575932bc0`, `run_63374fabab34`.
- **Confabulation** — "A child agent has been spawned, it read
  docs/README.md…" then a *hallucinated* summary (release notes / roadmap /
  debt-inventory — none of which are in the real file, a docs index).
  Run `run_7984ebf09bba`.
- **External mis-grounding (the original Item 43 symptom)** — a native
  web search substitutes for the file, summarizing the unrelated
  `github.com/steipete/summarize` repo (Chrome extension, cache/daemon)
  and **citing that external URL**. Reproduced twice: `run_5ecb1da71dfb`,
  `run_7c0fd9a357dd`.

**Provider-isolation control (same task, native-tool providers).** The bug
is specific to Perplexity's prompt-based path, not the `/task` platform:
- `nvidia/deepseek-ai/deepseek-v4-pro` → `profile.mode=native`, real
  `tool_call read_file` (`Recorded tool call: read_file success=True`),
  **faithful** summary of the actual file. Direct (`run_76f07756de42`) AND
  full subagent chain (parent `run_f07d4f8c3209` → child `run_055a6b79d51e`)
  both correct.
- `gemini-3.1-pro-preview` → native, real tool call — but 400s (see Item 45).

**The existing guard is insufficient.** `chat.py:455–467` already suppresses
the "Native Web Search Capability" prompt block when a `/task`
`system_prompt_override` is active (and it *is* active — `agent_v1.py:915`
sets `compose_agent_system_prompt`). sonar-pro web-searches anyway.

**Fix direction (not yet built).** This is a model-capability limitation of
sonar-pro under prompt-based tools, not a ppxai logic bug. Options: (a) gate
at run creation — warn/reject a tool-capable `/task` targeting a
`native_tool_calling:false` provider; (b) auto-route tool-capable `/task` to
a native-tool provider (deepseek/nvidia proven; Gemini once Item 45 lands);
(c) stronger system-prompt guard (low confidence — `manager.py:457` already
emphatically forbids the observed refusal and was ignored). Related to
Item 37's `oneshot_grounding` Option-A work.

**Caveat.** "No tool call" is inferred from validator/event **absence** +
duration (consistent across all 6 perplexity runs), not a captured HTTP
response body. The native-provider tool executions ARE directly evidenced
(both a `tool_call` event and a `Recorded tool call … success=True` line).

### Item 46 — `/task` `read_file` (and non-`spawn_subagent` tools) are consent-free AND path-unconfined by default [agent platform / security posture]

**Planned:** `v1.19.x` (posture decision, not a spec violation). Surfaced by
the 2026-07-13 trial observation that the nvidia/deepseek direct run read the
file with **no consent prompt**. Confirmed by source + live config:

- The `/task` interactive consent gate is wired **only** for `spawn_subagent`
  (`agent_v1.py:923–952`, `consent_policy = spawn_consent or "deny"`,
  deny-by-default → parks `waiting{consent}` + card). Proven live: subagent
  run `run_f07d4f8c3209` fired `agent_waiting kind=consent` → `agent_resumed
  approved:true`.
- **`read_file` and every non-spawn tool have no consent tier** — they are
  gated *solely* by the `--tools` allowlist. Granting the tool IS the consent.
- The **T2 filesystem seal** (path jail) is the intended confinement, but it
  is **off by default** (`execution.task.sandbox` — moved from
  `tools.agent.sandbox` in v1.19.1, ADR 0010 — engages only when
  `enforcement == "in_process"`; live config has `sandbox: null`). With it
  off, a `/task … --tools read_file` can silently read **any file the process
  can reach** (e.g. `~/.ppxai/.env`), unconfined and unprompted.

**Why it matters (defense-in-depth).** Combined with Item 43's mis-grounding
class, a `/task` run can silently read arbitrary local files and fold them
into a result with no prompt and no jail. Not a spec violation — the
confinement mechanism exists and ships intentionally-off — but the default
posture is worth an explicit decision.

**Fix direction (posture, not yet decided):** either default the T2 seal on
for tool-capable runs, add a read-consent tier for filesystem tools outside
the workdir, or document the posture prominently so operators opt into the
seal. Owner decision required before code.

### Item 47 — VSCode `/task` lacks the web split-pane; run/sub-agent dynamics collapse into flat chat lines [agent platform / clients / vscode / UX]

**Planned:** `v1.19.x` (UX parity follow-up to T8a). Observed live 2026-07-13:
in the VSCode client a `/task` run is far less legible than in the web app —
the user misses the "major part of the dynamics" (per-tool progress, meta,
sub-agent activity).

**What web has that VSCode doesn't (source-verified).** The web client renders
a run into a **stateful `RightPanelFrame` split-pane** —
`ppxai/web/components/views/task-run-view.js` (`TaskRunView`, 378 LoC) atop
`agent-run-view.js` + `shared/task-controller.js`. Per its own header it shows,
**live**: a meta bar (provider/model, tool-grant chips, egress chips, budget),
a **scoped events log** (`tool_call` / `tool_denied` / `network_*` /
`spawn_*`), a Cancel button, and an inline consent card — all held on the
instance and rebuilt on re-mount.

**What VSCode does instead (by deliberate T8a design).**
`vscode-extension/src/taskController.ts` header line ~21: *"No right-panel pane
stack: runs render into the chat transcript (ui.system lines + ui.result)."*
Its watcher (`runWatch`, ~L598) **does tail the same SSE stream**
(`agentRunEvents`) — so it is not blind to events — but renders each as **one
throwaway line** `this.ui.system("  " + eventText(ev))` (L602), interleaved
with the user's commands and any concurrent run's events. Consequences:
no persistent per-run surface, no live meta bar, no scoped events log,
result body competes with chat, and **sub-agent dynamics collapse** — a
parent→child spawn (e.g. `run_f07d4f8c3209` → `run_055a6b79d51e`) shows as two
`subagent_spawned`/`subagent_finished` lines with no tree and no way to watch
the child's own tool activity.

**Feasibility (not a rewrite).** The extension already has the needed
infrastructure: `previewPanel.ts` uses `vscode.window.createWebviewPanel(…,
vscode.ViewColumn.Beside)` — the idiomatic VSCode analog of the web split-pane.
A "Task Run" Beside-panel webview reusing the events `runWatch` already tails,
mirroring `TaskRunView`'s meta+events+result regions (and rendering the
sub-agent tree), is a bounded feature. The consent QuickPick idiom stays.

**Design decision (owner steer, 2026-07-13): reuse VSCode-native surfaces to
the maximum; a "reveal/preview to the side" mechanism is acceptable; a bespoke
webview is the last resort.** Prefer delegating to a built-in or already-present
extension preview over hand-building/maintaining a webview UI.

**Precedent already in the codebase — the exact ladder to follow.**
`previewPanel.ts` already implements a "native-first, webview-fallback" chain
for HTML preview:
  1. `vscode.commands.executeCommand('livePreview.start.preview.atFile', Uri.file(path))`
     — delegate to MS **Live Preview** (its own side preview). (~L104)
  2. `extension.liveServer.goOnline` — delegate to **Live Server** if present. (~L125)
  3. `openWebviewFallback` → `createWebviewPanel(…, ViewColumn.Beside)` — our
     own webview only when neither delegate exists. (~L148)
The Task-Run pane should mirror this preference order.

**MIME / preview-plugin-selection caveat (the open question, now scoped).**
Auto-selecting a preview plugin by MIME type is **not a clean hook here**: those
`livePreview`/`liveServer` delegations trigger off a **real file** (`Uri.file(path)`),
and VSCode picks the renderer by file/language *association*, not by an
in-memory MIME type. A `/task` run's live SSE event stream is not a file, so
there is no MIME to hand a preview plugin. To reuse a native side-preview you
would have to **materialize** the run as a file — write a live-updating
HTML/markdown artifact to a temp path (reusing the `previewPanel.ts` file
watcher, which already re-renders on saved-file change) and point Live Preview
at it. That's the reuse-max path; whether the refresh cadence/flicker is
acceptable for a fast event stream is unverified and is the thing to prototype
first.

**Fix direction (not yet built), in reuse-preference order:**
  1. **Reuse-max:** materialize the run as a live-updated HTML/MD file under a
     temp dir and drive it through the existing `previewPanel.ts`
     Live-Preview→Live-Server→webview ladder. Native rendering, minimal new UI
     code; risk = refresh cadence for streaming events (prototype to confirm).
  2. **Fallback:** a dedicated Task-Run `createWebviewPanel(ViewColumn.Beside)`
     fed directly by the SSE tail `runWatch` already consumes — full control
     over the meta bar / events log / sub-agent tree, but bespoke UI to
     maintain.
Keep the chat-line rendering as the no-panel fallback either way. Verb/status
parity sentinel (`tests/test_vscode_task_controller.py`) is unaffected — this
is presentation, not protocol.

### Item 49 — cross-tier cost + shared-resource accounting: `/cost` under-reports true provider spend; KV-cache contention unmodeled [engine / gateway / agent platform / cost] → ADR 0008

**Planned:** `v1.19.x`+ (**needs an architecture decision, not a patch** —
design in [decisions/0008-cross-tier-cost-and-resource-accounting.md](decisions/0008-cross-tier-cost-and-resource-accounting.md),
Status: Proposed). Surfaced 2026-07-15 while reviewing Item 48's engine
isolation.

**Gap #1 (verified) — local cost view under-reports true spend.**
`save_usage_to_persistent_storage` (sole writer of `usage.json`, backing
`/cost`) is called **only from interactive paths** (`commands/handler.py:441`,
`rich/main.py:623`, `tui/stream_handler.py:310`, `server/session_manager.py`,
`server/streaming.py`). **Neither `oneshot.py` nor `agent_v1.py` calls it.**
So for a user running chat + `/v1/oneshot` + `/v1/agent/task` on the **same
provider account**: the provider bills for all three, but `/cost`/`usage.json`
reflect **only the interactive session**. Oneshot usage is returned then
dropped (stateless, no `EngineClient` by ADR 0004); task usage lives in the
run's own per-run engine (ADR 0003 D1 isolation) and never aggregates.
`/cost` silently under-reports whenever background runs are active. (Distinct
from Item 48's `Ctx:` badge, which is *correctly* per-engine display-scoping —
this is about the shared **money**.)

**Gap #2 (verified absent) — no model of shared KV-cache contention.** On a
self-hosted vLLM/NIM endpoint the KV cache is a finite GPU resource shared
across all concurrent requests (client-side `EngineClient` isolation has no
effect — the cache is server-side). The three tiers send different system
prompts → no prefix-cache reuse, only contention → preemption/recompute raises
cost + latency for all three incl. interactive chat. ppxai models none of it
(no cache-occupancy metric anywhere — correct, since hosted cache is invisible,
but the cost model should at least acknowledge it for self-hosted users).

**What exists:** per-run task token budget caps an *individual* run
(`agent_v1.py` ~L1045, `control.tokens_used = session.live_run_tokens`) — NOT
account-wide, NOT fed into `usage.json`.

**Fix direction:** owner-signoff on ADR 0008. Recommended = Option A (a
usage-recording sink keyed by `(provider, model, tier, owner)`; `/cost` becomes
a tier/provider-filterable query over an append log — one truth without
un-isolating the tiers; composes with Item 35). Naive "one global counter" is
wrong: different providers = different pricing, cross-process concurrency, and
legitimately separate per-tenant vs. operator views. KV-cache = acknowledge in
docs (+ optional vLLM `/metrics` operator read), don't try to account
per-request. **Until decided, disclose:** `/cost` = interactive session only.

### Item 54 — Gemini fleet migration: 2.5-line sunset (earliest 2026-10-16), google-genai SDK behind, Gemini-3 `thought_signature` chain rules untested [providers / gemini / SDK]

**Planned:** `v1.19.x` — deadline-driven, the only fleet item with a date on
it. Filed 2026-08-01 from the provider-fleet web sweep (official
[deprecations page](https://ai.google.dev/gemini-api/docs/deprecations)).

**Facts (verified on ai.google.dev 2026-08-01):**
1. **2.5-line shutdown, earliest 2026-10-16:** `gemini-2.5-flash` →
   `gemini-3.6-flash` ($1.50/$7.50, **GA**); `gemini-2.5-pro` →
   `gemini-3.1-pro-preview` ($2/$12 ≤200K, $4/$18 above — replacement still
   **preview**, see Item 38 watch 3); `gemini-2.5-flash-lite` →
   `gemini-3.1-flash-lite` (itself already sunset-dated 2027-05-07 →
   `gemini-3.5-flash-lite` $0.30/$2.50). Dates are "earliest possible" with
   ≥6-months notice promised after Gemini 3 GA, BUT a forum report of
   2.5-flash going unavailable *early* for some users argues against waiting.
2. **Not just user config — code defaults:** `tools.web_search.gemini_model`
   defaults to `"gemini-2.5-flash"` (`web_premium.py:206`) → the web_search
   fallback-chain backend itself dies on sunset. `model_deprecations.py`
   needs the four 2.5→3.x rows (that table is the `/doctor` shipping vehicle).
3. **SDK:** pinned `google-genai==2.11.0`; latest 2.16.0 (2026-07-30;
   2.12–2.16 all landed 07-16→07-30). Changelog delta NOT reviewed — do not
   bump blind. Google says pin `<3.0.0` (breaking major announced).
4. **Gemini 3 makes `thought_signature` MANDATORY on function-call turns**
   (400 on missing), with rules our Items-45/50/51 round-trip has not been
   tested against: every call in a *sequential* chain needs its own
   signature; in a *parallel* batch only the FIRST part does. Extend
   `test_gemini_thought_signature.py` with both cases before pointing the
   native loop (Item 41 work) at any 3.x model.
5. `gemini-3.1-pro-preview-customtools` (benched 81.5% per AGENTS hints) is a
   separate model id biasing toward registered tools over shell — relevant to
   Item 43's class of problem; pricing parity with the base preview is
   aggregator-claimed, not officially confirmed.

**Fix order:** (a) `/doctor` deprecation rows + `web_premium.py` default bump
→ ships independently, small; (b) SDK changelog review → bump + full Gemini
suite; (c) signature chain tests; (d) bench `gemini-3.6-flash` vs 2.5-flash
(+ 3.1-pro-preview vs 2.5-pro) per AGENTS.md before config/model_hints move.
**Trigger to act NOW is (a);** (b)–(d) before the October window closes.
Effort: (a) ~1h; (b)+(c) ~half day; (d) benchmark session.

### Item 55 — OpenAI fleet refresh: gpt-5.6 Sol/Terra/Luna GA + price cuts obsolete configured 5.5/5.5-pro; chat-completions tool+reasoning hazard unverified [providers / openai]

**Planned:** benchmark session (cost-driven, no deadline — no confirmed
sunset for `gpt-5.5`/`gpt-5.5-pro`/`gpt-5.4-mini`; legacy dated `gpt-5-*`
snapshots shut down 2026-12-11, none configured). Filed 2026-08-01 from the
provider-fleet web sweep (developers.openai.com model pages fetched directly).
Supersedes Item 38 watch 1 (trigger FIRED).

**Facts (verified 2026-08-01, post the 2026-07-30 price cuts — Luna −80%,
Terra −20%; Item 38's Terra $2.50/$15 figure is stale):**
| Model | $/M in/out | Context | Cutoff | vs configured |
|---|---|---|---|---|
| `gpt-5.6-sol` | $5/$30 | 1.05M/128K | 2026-02-16 | = `gpt-5.5` price, beats it (SWE-Pro 64.6 vs 59.4); makes `gpt-5.5-pro` ($30/$180) look like poor value outside its Responses-only/multi-minute niche |
| `gpt-5.6-terra` | $2/$12 | 1.05M/128K | 2026-02-16 | beats `gpt-5.5` at 40% of its price — clearest swap |
| `gpt-5.6-luna` | $0.20/$1.20 | 1.05M/128K | 2026-02-16 | vs champion `gpt-5.4-mini` $0.75/$4.50 400K: 73% cheaper, 2.6× context, **BUT MRCR long-context recall 41.3%** (Sol/Terra ~90) — cheap context it can't reliably recall over |

**Hazards to clear before any switch:**
1. **Community-reported (NOT officially confirmed):** `gpt-5.6-sol` rejects
   function tools combined with `reasoning_effort` on `/v1/chat/completions`
   — and ppxai is chat-completions-shaped for ALL providers. Probe
   empirically; mitigation fits existing per-model `tool_calling` /
   `extra_body` config; worst case pin `reasoning_effort: none` for sol.
2. New reasoning surface (7-level `effort`, `mode: standard|pro`,
   `context: all_turns`) is Responses-API-centric — catalog note only, no
   client work identified.
3. Bare `gpt-5.6` id aliases to sol — don't configure the alias.
4. Cache-write billing reportedly 1.25× input for 5.6+ (secondary source,
   unconfirmed — official pricing page 403s scrapers).

**Fix order:** (a) sol tool+reasoning probe (one live curl session); (b)
benchmark Luna vs `gpt-5.4-mini` + Terra vs `gpt-5.5` per AGENTS.md
(model_hints locked to bench — standing rule); (c) config + our own
deprecation-table rows for 5.5/5.5-pro if bench confirms. Effort: (a) ~30min;
(b) benchmark session; (c) ~1h.

---

### Item 64 — ⏰ re-probe Perplexity's pro line on the Responses wire BEFORE 2026-09-27 [providers / deadline]

**Filed 2026-08-31.** Deadline-carrying, and the shortest item here that can
still break users.

`PERPLEXITY_DEPRECATIONS` tells every `sonar-pro` / `sonar-reasoning-pro`
operator to migrate to **`perplexity/sonar`** — the *lighter* model — because
that is the only Sonar id measured live on the Responses wire on 2026-08-31.
Both pro ids answered `400 validation failed: model "..." is not supported`
there, in bare and namespaced form (probe + a plain SDK call, no framing).

That hint is correct only while it stays true. If Perplexity ships the pro
line on Responses before the cutover, ppxai will be actively advising a
downgrade nobody needs — a wrong migration hint the user *will* follow.

**Action, ~2 minutes:**

```bash
uv run python scripts/probe-perplexity-capabilities.py --api-path responses   --model "perplexity/sonar-pro" --model "perplexity/sonar-reasoning-pro"   --model "sonar-pro"
```

If any answers, update `replacement` in
[`ppxai/engine/model_deprecations.py`](../ppxai/engine/model_deprecations.py)
and re-add the entries to `ppxai-config.example.json` (with a pricing row and
the migration fence's `RETIRED` set trimmed to match).

**Why this is an inventory item and not just a code comment.** It was one: a
`Re-probe before the date` line in `model_deprecations.py` and a line in an
untracked audit-notes file. Neither is a commitment anyone will find — the
comment is only read by someone already editing that table, which is the
person who least needs telling. A dated obligation belongs where dated
obligations are tracked.

---

### Item 65 — `BUILTIN_PROFILES` is still the seed vocabulary; the bridge needs a scheduled death [providers / config]

**Filed 2026-08-31.** ADR 0012 refactor (b), second half. Not deadline-bound,
but time-sensitive in a different way: an adapter with no scheduled removal
becomes permanent, which is the whole concern that prompted the refactor.

`ModelFacts` is the record every consumer reads. `BUILTIN_PROFILES` (65 rows
of `ModelProfile` / `ToolCallingProfile`) survives as its **seed**, flattened
once at import via `facts_from_profile`. Two vocabularies for one set of
facts is the two-systems problem ADR 0012 exists to remove — the same shape
as the `capabilities` / `tool_calling` split W1 collapsed, just one level
down.

**What already landed (d1fe2912):** `supports_vision()` reads `ModelFacts`,
so no behaviour-bearing reader consults the profile table; the dead
`BaseProvider.get_model_profile()` accessor is deleted.

**What remains:** re-author the 65 rows as native `ModelFacts` literals, then
retire `ModelProfile`, `ToolCallingProfile`, `facts_from_profile`,
`_seed_row`, `_wire_for` and `_API_PATH_TO_WIRE`.

**Deliberately deferred rather than rushed:** that is a data migration, and
mixing its diff with a behaviour change is what makes such a diff
unreviewable — the same reason this was kept out of W4, where it would have
blinded the byte-identical converter check.

**The fence is already in place**, which is what makes the migration
checkable whenever it is scheduled:
`tests/test_model_facts_are_the_source.py` asserts every profile row
flattens to its facts row, field for field, with the mapping written out
rather than inferred, plus a row-count canary that trips the moment the
re-authoring starts.

---

### Item 63 — benchmark conclusions are hand-typed into code, unlinked and unchecked [benchmarks / providers]

**Filed 2026-08-30** from ADR 0012 Q0h. Design decided there; this is the
tracking entry. Not on the 2026-09-27 deadline path — sequenced after W3.

`BenchmarkResult` (`benchmarks/llm-eval/results.py`) captures
`overall_score`, `category_scores`, `test_results` — the **measurements**.
It has no field for what they *mean*, so behavioural conclusions reach the
code by a human retyping them:

    #   o4-mini: 10.9% native → 62.5% prompt-based (native returns empty responses)
    #   gpt-4.1-mini: 60.9% native → 71.9% prompt-based (hybrid tool_json_in_content)
    PROMPT_BASED_MODEL_PREFIXES = ("o4-mini", "gpt-4.1-mini")

(`openai_native.py:53-55`.) A measured conclusion as a comment above a
hardcoded tuple: nothing links it to the run, nothing rechecks it, nothing
fails when it rots. **Same shape as Item 61**, which is the defect ADR 0012
exists to remove — a fact declared in one place and verified by nobody.

**Fix (Q0h):** benchmark runs append
`benchmarks/tuning/<provider>_<model>.json` carrying `recommended_facts`
(in `ModelFacts` shape) + `rationale` keyed by field, referenced by run id.
Separate from `BenchmarkResult` on purpose: a score is a measurement, a
recommendation is an interpretation, and they have different lifetimes — a
re-run replaces the former while the latter may be reviewed or superseded.
One format then serves a maintainer promoting it into the shipped table, an
operator dropping it into config, and `/doctor` scaffolding from it.

**Depends on:** ADR 0012 W1 (defines `ModelFacts`). **Blocks:** nothing.

---

## Recently moved out of debt scope

These items left the debt inventory because they're not bug-fix-class
follow-up — they're feature work belonging on the roadmap, or they
shipped already.

- **Item 14 — Anthropic provider** → moved to roadmap 2026-05-05.
  See [ROADMAP.md §"v1.19.x - Anthropic Provider (planned)"](../ROADMAP.md#v119x---anthropic-provider-planned).
  Original v1.18.2 entry preserved at
  [docs/archive/DEBT-INVENTORY-v1.18.2.md](archive/DEBT-INVENTORY-v1.18.2.md#item-14--add-anthropic-provider-with-explicit-tos-aware-auth-fallback)
  for full design rationale (TOS warning text, OAuth fallback caveats).

---

### Item 36 — per-session sub-agent config + `/subagent` command, persisted in checkpoint [agent platform]

**Context:** v1.19.0 Inc 2 fixed sub-agent provider/model resolution to
be **per-run injected intent** (ADR 0003 §9), NOT inherited from the
interactive chat session. Resolution today: request value →
`execution.default_subagent` (global JSON config; moved from
`tools.agent.default_subagent` in v1.19.1, ADR 0010) → 400. The
interactive session's *active chat provider* is deliberately not consulted
(that was the bug: `/agentrun` resolved a stale global default and ignored
the run's intended model).

**What's missing (the middle layer):** a **per-session sub-agent default**
between the request and the global JSON config. User decision 2026-06-15:

- A `/subagent` slash command to configure, per session, the default
  provider/model (and later budget/tool-grant) for sub-agents spawned
  from that session — e.g. "in this session, sub-agents default to a
  cheap fast model."
- **Persist it in the session checkpoint/status file** so a session
  restart revives the per-session sub-agent config (and it can be
  re-adjusted live).

**Target resolution chain once this lands:**
`request value → per-session sub-agent config → execution.default_subagent (global) → 400`.

**Why deferred (not Inc 2):** touches the session checkpoint format + a new
slash command surface across clients — too big for the Inc 2 provider-fix.
Natural fit alongside the session/spawn machinery (≈ Inc 6-7, when
checkpoint state and `spawn_subagent` land). The Inc 2 fix already
established the correct *contract* (per-run intent, never chat-session
inheritance); this adds the convenience layer.

**Branch when ready:** part of `feat/agent-platform-stage-2` (Inc 6/7) or
its own `feat/subagent-session-config`.

---

### Item 37 — agent-platform (v1.19.0) watchlist [agent platform]

Low-severity, correctness-neutral items from the Inc 5–7 codex/copilot
reviews. None block the MVP; grouped here so they're discoverable when the
relevant follow-on work is scheduled.

**a. sub-agent wait: disk-poll fallback.** `SpawnSubagentTool._await_child`
awaits the child's background `asyncio.Task` directly via
`registry.get_run_task(run_id)` (no 20×/sec `meta.json` polling on the happy
path; on wait-cap timeout it CANCELS the child, not orphan; cap = child
`time_s` budget else `_DEFAULT_CHILD_WAIT_S=300`). A **bounded disk-poll
fallback** remains for the no-task-handle case (child already finished, or a
test seam bypassing `run_in_background`). Unify once every spawn path
guarantees a task handle.

**b. N=1 concurrency only.** Parent awaits one child to terminal before its
tool call returns (ADR 0003 `max_concurrent_subagents=1`). N>1 fan-out + the
backpressure cap is deliberately out of MVP scope.

**c. `tool_targets()` fixed backend list (copilot 2026-06-16) — MITIGATED.**
The egress target enumeration for `web_search`/`get_weather` in
`engine/tools/network_policy.py::_NETWORK_TOOLS` is a hard-coded list of every
backend host a tool could reach (the AC-2 superset-rule fix). **Maintenance
hazard:** if a new `web_search` backend is added and `_NETWORK_TOOLS` is NOT
updated, a run could reach an un-allowlisted host with no
`network_policy_denied` event — a silent AC-2 regression. **Mitigation
landed:** `tests/test_network_policy.py::TestBackendCoverage` (commit
`a8e7247d`, Item 37 g/c/f wave) source-scans the web tool modules for URL
literals and fails on any host missing from `_NETWORK_TOOLS`, plus pins the
known backends against deletion. Extended 2026-07-12: the scan now also
covers `web.py` (free-tier search/weather) and catches f-string scheme
placeholders (`f"{scheme}://wttr.in/…"`) that a bare `https?://` regex
misses. Residual (acceptable): a backend whose host arrives purely from
config/data (no source literal) would still evade the scan — deriving the
set from a single source remains the structural fix if one is ever added.

**d. `_ppxai_overflowed` private queue flag (copilot 2026-06-16).** The Inc 3
SSE slow-consumer self-heal sets a private attribute on the asyncio.Queue to
signal "resync from disk." Works, but it's a brittle convention (relies on an
ad-hoc attribute). Acceptable for MVP; consider a typed wrapper if the event
fan-out grows.

**e. Cancel latency: cooperative polling vs blocking calls (secondary review
2026-06-16).** `RunControl.check()` is evaluated only at `chat_with_tools`
tool-loop boundaries, so a `POST /runs/<id>/cancel` issued while the engine is
inside a long blocking call does NOT halt the run until that call returns. Two
such calls: `provider.oneshot` / the LLM HTTP request (bounded by the provider
timeout), and `SpawnSubagentTool._await_child` (up to the child `time_s` budget
else `_DEFAULT_CHILD_WAIT_S=300`). **Verified:** cancel is *safe* (stops at a
clean checkpoint, never mid-tool-call → no truncated `events.jsonl`/artifacts)
but *not immediate*. `cancelling → cancelled` can lag by the in-flight call's
duration. Acceptable for MVP; a future increment could race `check()` against
the blocking await (e.g. `asyncio.wait` with a cancel event) for snappier
cancellation. Document the latency in the API guide; no code change for MVP.

**f. Egress is application-layer; no DNS-rebinding / private-IP defense
(secondary review 2026-06-16).** `NetworkPolicy.check()`
(`engine/tools/network_policy.py:222`) matches `urlparse(url).hostname` against
the allowlist *strings* — an application-layer check performed before
`urllib`/`httpx` opens the TCP connection. **Gaps verified in code:** (1) an
allowlisted host whose DNS an attacker controls can rebind to `127.0.0.1`/a
link-local address between the check and the connect → SSRF against localhost
services (classic TOCTOU/DNS-rebinding); (2) no rejection of allowlist entries
that *themselves* resolve to private/loopback/link-local IPs; (3) `scheme ""`
is accepted (line 228) alongside `https`. For the MVP — read-only tools, no
shell, trusted operator-authored allowlists — string-matching is standard and
sufficient. **For an untrusted-code production tier**, egress needs
network-layer enforcement (egress proxy, `iptables`/NetworkPolicy, or a custom
resolver that rejects private/loopback IPs and pins the resolved address
through to connect). This aligns with — and should land alongside — the
deferred **tier-d OS-isolation** work (ADR 0003 §3), which the shell-tool
rejection already defers to. Until then, treat `allow_outbound` as "trusted
operator input," not "safe against a hostile agent."

**g. `_strip_section` couples the AC-1 prompt filter to markdown formatting
(secondary review 2026-06-16).** `agent_scoped_tools.py:42` strips off-grant
shell guidance by locating the section end via `prompt.find("\n## ", ...)` and
matching the literal header `"## Shell wrapper context"` (line 220). **Verified
brittleness:** if the base prompt renderer later changes that section's
heading level (`### `), wraps it in XML/`<details>`, or renames it, the strip
silently no-ops and shell instructions leak into the prompt of a run with NO
shell grant. **Severity: token-waste, not a security breach** — the
`ScopedToolManager.execute_tool` chokepoint still hard-denies the shell call
(AC-1 holds); the LLM just wastes tokens attempting it. **Better design:** the
prompt generator should build the shell block conditionally from a
`has_shell_grant` flag passed down, rather than always-concatenating and
parsing it back out by substring slicing. Worth a covering test now (assert no
shell guidance survives `_strip_section` for a no-shell grant) even before the
modular-prompt refactor.

**Status (updated 2026-06-16, commits `a8e7247d` g/c/f + the e follow-up):**

- **(c) DONE** — `tests/test_network_policy.py::TestBackendCoverage` asserts
  every https host literal in `web_premium.py` is covered by `_NETWORK_TOOLS`,
  plus a pin on the five known backends. Drift now fails CI.
- **(g) DONE** — the shell-wrapper block is gated at the source via
  `ToolManager.get_tools_prompt(include_wrapper_context=)`;
  `_strip_section` deleted. No more markdown-format coupling.
- **(f) PARTIAL** — `NetworkPolicy.check` now denies an allowlisted host that
  resolves to a loopback/private/link-local/reserved IP, and rejects
  bare/empty scheme. **Still deferred:** DNS-rebinding (TOCTOU between check
  and connect) needs network-layer enforcement (pinned-IP connect / egress
  proxy) and lands with **tier-d OS-isolation**. Must NOT ship to an
  untrusted-code tier on the app-layer check alone.
- **(e) PARTIAL** — two layers now stop an awaited child when its parent is
  cancelled: (1) `AgentRunRegistry.cancel_run` CASCADES — it cancels any
  in-flight run whose `parent_run_id == run_id` (recursion-safe, cycle-guarded)
  so a parent cancel never orphans a sub-agent regardless of who's polling;
  (2) `_await_child` polls the parent's cancel flag on a ~100ms tick for prompt
  latency (was: up to the 300s wait cap). **Still deferred:** a cancel issued
  *during the provider HTTP call* (`engine.chat` → `provider.oneshot`) still
  waits for that call to return — racing `control` against the provider await
  is a deep change to the core chat path with real regression risk, out of
  MVP scope.
- **(h) DONE — audit fidelity for multi-backend tools (secondary review
  2026-06-16).** `NetworkPolicy.authorize` previously reported only
  `targets[0]` in the `network_policy_allowed` event, so a `web_search` that
  actually hit Perplexity would log DuckDuckGo. `ToolDecision` now carries
  `approved_targets` (the full superset of allowlisted hosts), surfaced in the
  audit payload (`approved_targets`). `target_host`/`target_path` keep the
  first target for back-compat; the new key is additive. Tests:
  `test_approved_targets_lists_all_backends_not_just_first` /
  `_empty_on_deny`.
- **(i) MOSTLY DONE — agent-tier system-prompt framing (root-cause fix for
  the Perplexity substitution; review 2026-06-16).** Original framing was
  "weak tool-caller → just warn the operator." Re-examination found the real
  cause: `/v1/agent/task` sent the provider's CHAT `system_prompt` (which for
  Perplexity actively encourages native web search) with NO agent framing,
  AND `chat.py` appended a "you have native search, you do NOT need a tool"
  block. So the substitution was a PROMPT problem, not a model ceiling.
  **Fixed:** (1) per-engine `system_prompt_override` (honored by both
  prompt-based + native assembly paths in `chat.py`); (2) `/v1/agent/task`
  sets it to `compose_agent_system_prompt(req.system)` =
  `DEFAULT_AGENT_SYSTEM_PROMPT` ("use ONLY granted tools, no native
  fallback") + the caller's `system` (e.g. ppxai-sre's rendered AGENT.md);
  (3) the native-search-encouragement block is SUPPRESSED when an agent
  override is active. Ownership boundary preserved: the SOUL.md/AGENT.md
  persona artifact stays in the CONSUMER (ppxai-sre); ppxai provides the
  seam (`system` field, already on the request model) + a sane default.
  Tests: `test_agent_system_prompt.py`. **VERIFIED LIVE (2026-06-16):** the
  `benchmarks/agent-behavior/` cross-provider run confirms all four
  providers (perplexity/sonar-pro, gemini-3.1-pro-preview, gpt-5.4-mini,
  nvidia/qwen3.5) use the granted tool with correct results under the
  framing — Perplexity included, no native-search substitution. So 37i is
  **DONE**. **Still optional (low value now):** a `weak_tool_calling`
  warning event when a `/task` targets `native_tool_calling:false` — the
  framing fix addresses the actual behavior, so this is just SRE audit
  nicety; leave unbuilt unless asked.

- **(j) DONE — non-streaming provider call blocked the event loop
  (surfaced by the agent-behavior benchmark, 2026-06-16).** Every
  provider's `chat` non-streaming branch (+ openai responses API) called
  the SYNCHRONOUS SDK inside `async def` with no offload; `/v1/agent/task`
  uses `stream=False`, so one agent run starved the whole asyncio loop
  (server unresponsive to all other requests until the LLM call returned).
  This is the concurrency half of the branch-start "threading/subprocess
  for sub-agents" question. **Fixed:** wrapped the non-streaming calls in
  `asyncio.to_thread` (openai_compat / openai_native completions+responses
  / gemini / perplexity); LLM calls are I/O-bound so the GIL is released
  during the socket wait → real interleaving. PROVEN: independent request
  returns in 0.46s while an agent run is in flight (was: timeout).
  **Deferred (separate axis):** the streaming `/chat` path still starves
  the loop in small bursts (sync chunk iterator); offloading a generator
  is bigger — track if interactive concurrency becomes a problem.
  Subprocess/OS-isolation (tier-d) remains the CPU/security-isolation
  answer, NOT needed for I/O concurrency.
- **(k) DONE — opt-in native web search for the tool-free oneshot tiers
  (Option A, 2026-06-17).** `/v1/oneshot` + `/v1/agent/run` answer from model
  weights only, which made search-native providers (Perplexity, Gemini) near
  useless on those tiers. Resolution: a single config flag
  `tools.web_search.oneshot_grounding` (default **off**) that, when on, switches
  *search-capable* providers into the PROVIDER'S OWN web search at construction
  (Gemini `enable_grounding=True`; Perplexity sonar* searches intrinsically).
  **Option A, not B:** retrieval stays inside the provider API call — no
  `web_search`/`fetch_url` tool is exposed to the model, so the egress perimeter
  is unchanged and `NetworkPolicy` (the `/task`-only egress firewall) is NOT
  involved. Capability-gated: no-op for OpenAI/NVIDIA (`web_search:false`), so
  the flag can never reach for a tool a provider lacks. Wired once in
  `routes/oneshot.py::_build_provider` (the shared construction site —
  `agent_v1._v1_provider_or_400` delegates here, so both oneshot tiers pick it
  up). Tests: `test_oneshot_grounding.py` (flag plumbing, capability gate,
  build-wiring, + a **perimeter-lock AST test** that fails if a web-tool symbol
  is ever referenced in oneshot CODE — guards against drift to Option B). Docs:
  `docs/api-gateway.md` Notes, `docs/archive/plan-oneshot-grounding.md`. **Deferred
  (out of scope, low value):** Perplexity model-substitution when a non-sonar
  model is requested under the flag — risks downgrading a deliberately chosen
  reasoning model, so left to the caller to pass a sonar model.
- **(l) DONE — `/v1/agent/run` loopback carve-out (refines §H, 2026-06-17).**
  §H (commit aa989cef) protected the WHOLE `/v1/agent` prefix on loopback,
  which broke the web `/agentrun` command: its only agent verb POSTs the
  tool-free `/v1/agent/run` and the browser carries no bearer → 401 under a
  file token store. Fix: two scoped, fail-closed loopback exemptions UNDER the
  protected prefix — (1) exact path `/v1/agent/run` (tool-free oneshot tier,
  same class as the already-exempt `/v1/oneshot`); (2) `GET /v1/agent/runs/<id>`
  + `/events` ONLY when the run is UNOWNED (`owner=None` — the kind a token-less
  local client creates), via `_is_loopback_unowned_run_read`. OWNED runs (every
  `/task` run, every bearer-created run), list, cancel, and unknown-run reads
  stay 401 even on loopback; remote never exempt. Closes the confidentiality
  gap a naive "exempt all of /v1/agent on loopback" would open (other owners'
  transcripts + tool output). Tests: 14 in `test_tokens_v1_route.py`. Verified
  live on the rebuilt server (web launch→tail→read token-less OK; protected
  surface 401).
- **(m) DONE — web `/agentrun` fire-and-forget (2026-06-17).** `/agentrun`
  AWAITED its own SSE tail inline, blocking the chat prompt until the run
  finished — defeating the background run registry the whole platform is built
  on. `_dispatchAgentRun` now launches, frees the prompt, and tails+posts the
  result detached (`_watchAgentRunDetached`, not awaited); the result appends
  out-of-band and the Inc-9 background_agents badge shows it running meanwhile.
  Web-client-only. **Deployment lesson (cost a debugging round):** web JS is
  bundled into the `ppxai-desktop` binary and the launcher RESTORES it to
  `~/.ppxai/web/` on every start, so a web-asset change needs a `ppxai-desktop`
  REBUILD — copying into `~/.ppxai/web/` is reverted on next launch. Tests:
  `test_web_command_dispatcher_v18_1.py::TestAgentRunFireAndForget` + size fence
  300→340 (documented). Verified live: `ls`/`/pwd` ran while a run was active;
  `✅ completed` posted out-of-band. **Deferred (design iteration, not started):**
  the full interactive sub-agent UX (tool-capable `/task` launch surface,
  monitor/cancel controls, reattach) across web + VSCode — `/agentrun` only
  covers the tool-free tier today.
- **(n) DONE — Gemini review fixes (2026-06-17).** Four issues, each verified
  against the code before fixing (one proposed fix was empirically worse and
  replaced). **#4 (regression from §J):** the loopback auth exemptions returned
  early without resolving a PRESENT bearer, stamping authenticated local runs
  `owner=None` — fixed by gating the exemptions on `has_bearer` (present-but-
  invalid → 401, never silently exempted). **#1:** the SSRF-guard sync DNS ran
  inline on the event loop per network tool call; the obvious offload was
  measured ~4× slower (2.4s vs ms) and broke the egress test, so replaced with a
  30s TTL memo (`_resolve_cache`) — repeated checks do zero DNS. **#2:**
  `active_summary()` scanned `list_runs()` (disk) on every lifecycle event;
  replaced with an in-memory `_active` index maintained at each transition
  (O(active), no disk). **#3:** `_await_child` summed `waited += tick` (drifts
  under load); switched to `time.monotonic()`. Tests: +3 in test_tokens_v1_route
  (`TestLoopbackHonorsProvidedBearer`), +4 in test_network_policy (cache), +2 in
  test_background_agents_mirror (no-disk / cancelling). Call-graph §L. **Lesson:**
  the theoretically-correct async-DNS fix was empirically slower in this env —
  verified-then-replaced rather than shipped on plausibility.
- **(o) DONE — second review round (2026-06-17).** Two more, both verified
  against the committed tree first. **Cancel-cascade disk reads:**
  `_cancel_run_cascade` did `store.load_meta(child_id)` per in-flight control to
  read `parent_run_id` (O(C·D) disk on the loop during cancel); now carried in
  the in-memory `_active` index and read from memory (zero disk).
  `active_summary()` still projects badge fields only. **Fixed-name temp files
  (defense-in-depth, NOT a live bug):** `persist_meta` + token-store `_save`
  wrote to hardcoded `*.tmp` names; harmless in our single-process async model
  (per-run slot dirs make meta tmps distinct; no await between write+replace),
  but a multi-worker `uvicorn --workers N` deployment WOULD race — switched both
  to `tempfile.mkstemp` + temp-cleanup-on-failure. Tests: +1 cascade-no-disk,
  +2 persist tmp. Call-graph §L. **Severity honesty:** the temp-file race was
  filed/fixed as future-proofing with the model caveat stated, not dressed up as
  a current corruption bug.
- **(p) — external review round (Gemini/antigravity + Codex, 2026-07-02/03).**
  Two independent reviews of the branch (during the `/task` T1–T2 work).
  **Fixed + tested:** (1) loopback `X-Forwarded-For` spoofing — `_is_loopback`
  now rejects any request carrying a forwarding header, AND uvicorn defaults
  `forwarded_allow_ips=""` (trust no proxy) via `_forwarded_allow_ips()`,
  overridable with `PPXAI_FORWARDED_ALLOW_IPS`; (2) filesystem-seal deny globs
  now match a bare name anywhere (`.env`/`secrets`, not only `**/.env`);
  (3) **HIGH — filesystem-seal bypass via arg aliases** — `ScopedToolManager`
  now normalizes aliases (`file`→`filepath`, `path`→`directory`) BEFORE the
  egress/filesystem checks, so `read_file(file=…)`/`search_files(path=…)` can't
  slip the jail via the base manager's *post*-check normalization; (4) **HIGH —
  spawn wildcard egress subset** — `_check_egress_subset` probes TWO unguessable
  labels, so a child `*.suffix` glob is approved only if the parent holds a
  covering glob, not one exact subdomain. Commits `ccf9c1fc` (1,2), `5b987fd0`
  (3,4). **Still open (deferred):**
    - **Sync DNS in the SSRF guard blocks the loop on a COLD lookup** (Gemini).
      Distinct from (f)'s rebinding gap: `_host_resolves_to_blocked_ip` calls
      `socket.getaddrinfo` synchronously — TTL-cached (one block per host per
      window) and only on the opt-in tool-capable tier, but a slow/timing-out
      DNS stalls the loop. The async fix needs the whole `execute_tool`
      chokepoint to go async (event-emit callback must stay on the loop thread).
      **Planned:** with tier-d / an egress-proxy rework.
    - **O(N) token verification** (Gemini). `secrets/file.py` hashes every stored
      token per auth (no public id prefix). SHA-256 is µs-fast and the file
      store holds small operator token sets → low DoS risk, but poor scaling.
      **Planned:** `token_id.material` bearer format → O(1) lookup + one compare.
      Land with Inc 8b RBAC.
    - **No role-subset check on mint** (Gemini). `tokens_v1.mint_token` lets a
      scoped caller request arbitrary `roles`. Inert today — roles are NOT authz
      gates (owner is; the F6 owner-scoping was chosen precisely to avoid a
      mint-your-own-role escalation) — but a seam once RBAC lands. **Planned:**
      require `roles ⊆ caller.roles` with Inc 8b RBAC.
    - **`get_weather` http fallback un-allowlistable** (Codex). Its plain-http
      target is always denied under the https-only policy — already documented
      at `network_policy.py:143-144`; drop the http target (or the tool) when
      convenient. Relates to (c).
    - **Filesystem-jail alias completeness — ✅ DONE** (commit `15534784`). The
      alias fix already caught every alias the tool CONSUMES; this closes the
      remaining completeness gap where a cross-group name the tool does NOT accept
      (e.g. `read_file(path=…)`) reached the base past the jail before erroring
      (not a leak — the tool failed on the missing required arg — but a gap).
      `_PATH_TOOLS` now carries `path_required`; `FilesystemPolicy.authorize`
      fails CLOSED for a required-path tool (and any write) whose canonical kwarg
      is absent after normalization. `list_directory`/`search_files` keep the
      workdir "." default. Tests: `test_filesystem_policy.py` (required-missing
      denied, optional-missing allowed, unrecognized-alias denied at jail).
  **Confirmed duplicates (still-known, not re-filed):** Gemini's "50ms disk-poll
  fallback" = (a); "100ms cancel poll" ≈ (e). **Meta:** the alias-normalization
  ordering bug is a general class — any kwarg-inspecting policy must run AFTER
  normalization; the fix hoists it before all checks. Lesson
  `docs/lessons/loopback-ui-auth-exemption.md` corrected (the earlier "gate
  ignores forwarded headers" note was imprecise — uvicorn DOES rewrite
  `client.host`).
- **(a)/(b)** unchanged — promote with the N>1 sub-agent work.
- **(d)** unchanged — only matters if the SSE layer is reworked.

**ppxai-sre integration gaps (filed 2026-06-24 from the code-verified
reconciliation — see [docs/research/2026-06-24-ppxai-sre-integration-reconciliation.md](research/2026-06-24-ppxai-sre-integration-reconciliation.md)
and [docs/research/2026-06-24-ppxai-sdk-mutation-tools-for-sre-agents.md](research/2026-06-24-ppxai-sdk-mutation-tools-for-sre-agents.md);
contract of record is `ppxai-sre/docs/PPXAI-INTEGRATION-V1.19.md`). The written
contract C1–C4 + A3 is effectively MET on `feature/v1.19.0`; these are the
genuine open set. (Lettered q–t; upstream owns p = external review round.)**

- **(q) OPEN — C5 agent-served services routing (entirely unbuilt).** No
  `services` field on `POST /v1/agent/run`, no reverse-proxy route
  `…/services/<name>/...` → bound port, no `EventType.AGENT_SERVICE_DOWN`, no
  inbound network policy (`allow_inbound`), no restart_policy/drain/terminate
  API, no `X-Forwarded-Prefix` semantics (C5.0–C5.5 all absent — verified). **Not
  a regression:** C5 post-dates the `42ed8f00` written agreement and was never
  folded upstream; outlook-monitor ships the documented workaround (FastAPI
  binds ports directly). **Entangled with (b)/(a) and the `agent_n` decision:**
  C5's bound-service inspection path is `runs/<run_id>/agent-<n>/services/<name>/`,
  which needs a REAL multi-slot `agent_n` (today always 0 — sub-agents are
  sibling top-level runs linked by `parent_run_id`, never `agent-1/`). The proper
  `/task` design IS the C5 + `agent_n`-nesting design — they cannot be decided
  separately. **Planned:** v1.19.x `/task` design iteration (debt 37m follow-on)
  or v1.20.x. **Trigger to revisit:** when `/task` proper design opens, or when a
  long-lived ppxai-sre service agent (incident-responder / cost-optimizer /
  cert-monitor / log-analyst) needs bound-port routing.

- **(r) RETIRED (2026-07-07, landed across T5–T7) — `state.json` now persisted
  (Inspection Triplet complete on the flat `agent-0/` slot).**
  `AgentRunStore.persist_state/load_state` + the `FilesystemAgentRunStore`
  implementation landed with T5; producers: T5 `waiting` park (+ resume
  `last_response`), T6 `completed_pending_ack` hold + `finalized`
  (`result_ready_at`/`result_chars`, `via`/`acked_at`), T7 resumable-stop
  checkpoint, restart-sweep (`via:"restart_sweep"`), and resume
  (`resumed_from`). Consumer: T7 `POST /runs/{id}/resume` + the
  `resume_refusal` decision matrix. Original context: the run slot wrote `meta.json` + `events.jsonl`
  but NOT `state.json` (`agent_runs.py` comments said "Inc 2-3"); a consumer
  expecting the full ADR-0005 Triplet (e.g. ppxai-sre `heartbeat.py` reconstructing
  `AgentBeatState`) found no file. **No longer a standalone item** — folded into the
  `/task` lifecycle plan ([plan-task-command-sequencing.md](plan-task-command-sequencing.md));
  each piece lands with the increment that uses it (vertical-slice contract).
  Stays flat `agent-0/`; the multi-slot/service-state Triplet is still (q)/`agent_n`
  nesting.

- **(s) OPEN — A3 `run_id`/`parent_run_id` form-vs-substance.** The info A3 needs
  is fully available — `run_id` is the event partition key + `GET /v1/agent/runs/<id>`,
  `parent_run_id` is on `RunMetaResponse` — but NOT literally inside the
  `AGENT_RUN_START.data` dict as the doc's "additive fields on the event" wording
  implies. **Resolution is a coin-flip:** either fold the two fields into the
  event payload for literal compliance, or amend the integration doc to state the
  structural form. **Severity: cosmetic/contract-wording**; no consumer is blocked
  (read from the meta projection). **Planned:** resolve during the
  `MIGRATION-V1.19.md` rewrite. **Trigger to revisit:** migration-doc pass.

- **(t) OPEN — embeddable sandboxed-run SDK API (`build_task_runner` welded to the
  HTTP route).** For the SDK model (ppxai-sre embeds ppxai; its long-running
  agents spawn ppxai sub-agent runs as the safe execution unit for AGENT.md-steered
  MUTATION tools), the run-assembly — `ScopedToolManager` + `NetworkPolicy` +
  budget/cancel + spawn + AGENT.md framing onto an `EngineClient` — currently lives
  at `server/routes/agent_v1.py::build_task_runner`, importing route/FastAPI state.
  A library consumer must import a server-route module or re-implement the security
  wiring. **Ask:** lift it into the engine as a FastAPI-free `build_sandboxed_run(...)`
  API; the HTTP route becomes a thin caller. **Structural precondition** for
  ppxai-sre mutation tools. Pairs with promoting integration asks **A2**
  (deterministic pre-mutation policy hook — the real write-tool unblocker) and
  **A1** (policy-decision audit events) from v1.20.x. See
  [docs/research/2026-06-24-ppxai-sdk-mutation-tools-for-sre-agents.md](research/2026-06-24-ppxai-sdk-mutation-tools-for-sre-agents.md).
  **NOTE — partially overtaken by upstream `/task` T1–T2 (2026-07-02/03):** the
  filesystem-seal (`tools.agent.sandbox` at the time, `filesystem_policy.py`) +
  alias-normalization hardening landed after this was filed; re-verify (t)
  against the current tree before acting — the sandbox surface has moved
  again since (now `execution.task.sandbox`, v1.19.1 ADR 0010). **Planned:**
  v1.19.x `/task` design iteration or v1.20.x.

- **(u) FIXED (2026-07-06) — CORS wildcard + no Host-header validation on the HTTP
  server [SECURITY].** **STATUS:** shipped + tested (16 tests in
  `tests/test_host_cors_security.py`; auth/tokens suites still green). Implemented
  in `server/http.py`: (1) CORS default is now a **loopback-origin regex**
  (`^https?://(127\.0\.0\.1|localhost)(:\d+)?$`) instead of `["*"]`, overridable via
  `PPXAI_ALLOWED_ORIGINS`; (2) a **Host-validation middleware** (outermost) rejects a
  non-loopback `Host` with 400 `invalid_host`, exempting `/health`+`/healthz` (kubelet
  probes send Host=<pod IP>) and OPTIONS (let CORS decide). **Bind-conditional +
  non-breaking:** `_BIND_HOST` set by `run_server`/`run_desktop`; loopback bind →
  strict loopback allowlist (desktop default, no env); wide bind + `PPXAI_TRUSTED_HOSTS`
  → loopback + those hosts (gateway/coder); wide bind + no env → permissive + one-time
  warn (so a server-image-only upgrade never 400s an existing gateway). k8s wiring:
  `deploy/images/session-manager/main.py` threads `PPXAI_TRUSTED_HOSTS`/
  `PPXAI_ALLOWED_ORIGINS` from `INGRESS_HOST` into each per-user pod;
  `deploy/examples/microk8s/session-manager-deployment.yaml` documents it. **Verified
  via TestClient (full ASGI stack)**; live-socket subprocess suite (`test_server_smoke_e2e`)
  is environmentally skipped on this Windows host (pre-existing, CI-Linux/macOS only) —
  NOT run here. **Original analysis retained below.**

  Full analysis:
  [docs/research/2026-07-05-http-server-attack-surface-and-transport-options.md](research/2026-07-05-http-server-attack-surface-and-transport-options.md)
  §"Point 1". **The bug (verified `6add04f6`):** `server/http.py:194-201` sets
  `CORSMiddleware(allow_origins=["*"], allow_credentials=True, allow_methods=["*"],
  allow_headers=["*"])`. Starlette's CORS, given `*` + credentials, **reflects the
  request Origin** back with `Allow-Credentials:true` (it can't legally send literal
  `*` with credentials) — so it behaves as "trust EVERY specific origin, with
  credentials." Combined with **default-OFF auth** (`auth.py:4-8`,
  `PPXAI_API_TOKEN` unset ⇒ unauthenticated) this means **any website the user
  visits can script credentialed requests to `127.0.0.1:54320`** — spend the user's
  provider $, read `/sessions`, drive `/v1/agent/task` if the tier is on, hit
  `/v1/tokens`. Zero user interaction. Also **no `Host`-header validation**, so
  **DNS-rebinding** (rebind `evil.com`→`127.0.0.1`) bypasses CORS entirely (browser
  sees same-origin; TCP lands on ppxai).

  **The fix (two parts, ~15 LoC, no architecture change):**
  1. Replace wildcard CORS with an explicit loopback-origin allowlist. Because the
     port may become random (see A.2 in the research doc) prefer
     `allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$"` so any loopback
     port passes, no external host does. **Also add the VSCode webview origin** if
     the extension's browser context (not the extension host) makes the call —
     verify which; extension-host `httpx`/`fetch` is not subject to CORS.
  2. Add `TrustedHostMiddleware(allowed_hosts=[loopback names])` as the OUTERMOST
     middleware (add it LAST — Starlette runs last-added first) so a rebinding
     request with `Host: evil.com` is 400'd before any route. Order target:
     `TrustedHost → CORS → auth → activity → routes`.

  **⚠️ DO NOT ship a hardcoded loopback-only `allowed_hosts` — it breaks the k8s
  coder/gateway deployment.** VERIFIED: `deploy/images/session-manager/main.py:428`
  spawns per-user server pods with `python -m ppxai.server.http --host 0.0.0.0
  --port 54320` (bound WIDE, not loopback), fronted by ingress-nginx with a signed
  **cookie** session (`coder_session`, LDAP `auth_request` — NOT the
  `PPXAI_API_TOKEN` bearer; `COOKIE_NAME`/`AUTH_MODE` in the same file). A
  loopback-only Host check would 400 every ingress-forwarded request (Host =
  `ppxai.local`). **So Host-validation + CORS-origin allowlist MUST be conditional
  on bind address / an explicit `PPXAI_TRUSTED_HOSTS` + `PPXAI_ALLOWED_ORIGINS`
  env override**: loopback-only when bound to `127.0.0.1` (desktop default);
  operator-supplied host(s) when bound `0.0.0.0` (gateway/coder). This is the exact
  "local transport locked to loopback; gateway transport is the explicit
  authenticated exception" thesis of the research doc — the fix ENCODES it.

  **Trap for the resume:** CORS/Host changes break clients SILENTLY. Before
  shipping, exercise EACH client against the patched server — (a) web app loads +
  SSE streams, (b) `X-Session-Id` round-trips, (c) VSCode extension works, (d) a
  cross-origin `fetch` from a foreign origin is now BLOCKED (positive test), (e)
  a `helm`-deployed coder pod behind ingress still serves (Host=ingress host
  passes). TUIs are `httpx`/`urllib`, NOT browsers — unaffected by CORS, but still
  hit by TrustedHost, so include them in the loopback allowlist. **Planned:**
  actionable now, independent of the transport-model decision (Options A–D in the
  research doc). **Trigger:** do the CORS+Host fix immediately; the random-port /
  loopback-token / UDS follow-ons (A.2–A.4) can wait.

- **(v) NETWORK-LAYER FIXED (2026-07-06) — cross-tenant pod reachability: per-user
  coder pods are `0.0.0.0`-bound + app-layer-unauthenticated, with NO ingress
  NetworkPolicy [SECURITY, multi-tenant isolation; HIGHER severity than (u);
  distinct layer].** **(u) does NOT resolve this** — (u) is browser-layer
  (CORS/Host) defense-in-depth; this is network/app-layer tenant isolation. Filed
  separately on purpose.

  **STATUS 2026-07-06:** the **network-layer fix (ingress NetworkPolicy) is shipped
  + live-verified.** The per-user egress policy gained `policyTypes:[Ingress]` with
  inbound restricted to exactly (1) the ingress-controller namespace
  (`namespaceSelector`) and (2) the node/kubelet-probe source CIDR (`ipBlock` — the
  probe comes from the NODE, not a pod; omitting it silently breaks readiness).
  Live-verified END TO END: the cross-tenant exploit that returned HTTP 200 on
  `/status,/sessions,/state,/v1/agent/runs` now **times out** from a neighbour pod;
  a real pod still reaches `Ready` (probe path intact, 0 restarts); ingress-nginx →
  pod still HTTP 200 (north-south intact). Live site config
  `deploy/microk8s/networkpolicy.yaml` + a generic opt-in
  `networkPolicy.ingressIsolation` in the Helm chart (`ingressNamespace` +
  `probeSourceCIDRs`; `fail`s if enabled with empty CIDRs). **STILL DEFERRED
  (defense-in-depth):** the app-layer per-session `PPXAI_API_TOKEN` between ingress
  and pod (fix option 2) — the NetworkPolicy is the correct primary layer and
  closes the exploit; the bearer is belt-and-suspenders for a CNI-less deployment
  or a same-namespace-but-authorized caller. Track with Item 3.

  **VERIFIED (`6add04f6`):**
  - Per-user server pods bind `--host 0.0.0.0 --port 54320`
    (`deploy/images/session-manager/main.py:428`).
  - App-layer auth is OFF on those pods; the ONLY gate is the north-south ingress
    path (ingress-nginx `auth_request` → LDAP → signed `coder_session` cookie).
  - `deploy/helm/ppxai/templates/networkpolicy.yaml` declares `policyTypes:
    [Egress]` ONLY (H2 egress hardening — stops a COMPROMISED pod calling out) and
    is **`networkPolicy.enabled: false` by default** (`values.yaml:92`) + needs a
    policy-enforcing CNI (Calico/Cilium). **There is NO ingress NetworkPolicy
    anywhere in the chart.**

  **The gap:** nothing at the network layer restricts WHO may open a TCP connection
  to `:54320` on a per-user pod. So any pod in the namespace (a neighbor user's
  pod, a benchmark job, a compromised sidecar) — or anyone with `kubectl
  port-forward` — can hit `http://<other-user-pod-ip>:54320` directly and drive
  that user's engine, **bypassing the ingress, LDAP, and the cookie entirely.**
  Cross-tenant, unauthenticated, east-west. The ingress-cookie model protects
  north-south only.

  **Why (u) doesn't cover it:** CORS is browser-enforced — a non-browser client
  (`curl`/`httpx`) ignores it. Host validation only helps if the attacker doesn't
  spoof `Host`, which is trivial on a raw request. So a deliberate in-cluster
  attacker sending `Host: <ingress-host>` + the right path still reaches an
  unauthenticated engine after (u) lands.

  **Fix (any of, best = both):**
  1. **Ingress NetworkPolicy (the missing half of H2).** Add `policyTypes:
     [Ingress]` on the per-user pods: `ingress.from` = only the ingress-nginx
     pod/namespace (+ probe source). Correct layer for tenant isolation; pods
     physically can't reach each other. Same CNI dependency + default-off caveat as
     the egress sibling.
  2. **App-layer bearer between ingress and pod.** Session-manager mints a
     per-user/per-session `PPXAI_API_TOKEN`, ingress-nginx injects it; a direct
     pod-to-pod call then 401s. CNI-independent; closes the gap even with no
     NetworkPolicy. Cost: token mint + inject plumbing in the session-manager.
  3. **Both** — proper multi-tenant posture (network isolation + defense-in-depth).

  **Ties to Item 3** (k8s session-manager security tests, still open) — same
  subsystem; "cross-tenant pod reachability" belongs in that hardening scope + its
  test suite. **Planned:** with Item 3 / a coder-deployment hardening pass.
  **Trigger:** before any real multi-tenant coder deployment; higher priority than
  (u) if coder is shipping to more than one user.

- **(w) CLOSED (2026-07-11) — external review round (Antigravity, of T3–T8a).**
  8 findings on the agent architecture; each verified against the code before
  acting (verify-don't-assume). **Fixed + tested (landed with this entry):**
  (1) CORS: a literal `*` in `PPXAI_ALLOWED_ORIGINS` is dropped with a warning
  instead of reaching Starlette next to `allow_credentials=True`
  (`http.py::_cors_kwargs`; wildcard-with-credentials would reflect ANY origin);
  (2) VSCode `/task` black-box UX: `httpClient.agentRunEvents()` now tails
  `GET /runs/{id}/events?live=1` (same wire parsing as web `_tailEvents`) and
  `taskController.runWatch` is tail→poll (web `_runWatch` parity) — action
  events render as one-line transcript entries, heartbeat/lifecycle filtered;
  (3) unbounded watcher fetches: all 7 agent REST calls carry
  `AbortSignal.timeout(15s)` so a hung connection counts as a poll failure and
  the `pollMaxFailures` tripwire actually fires (the long-lived events stream
  is exempt by design); (4) consent-park latency: an `agent_waiting` stream
  event raises the QuickPick immediately (shared, token-deduped
  `maybeAskConsent` across tail + poll paths) instead of waiting out a poll
  backoff of up to 30s against `consent_ttl`. Sentinels extended:
  `/events?live=1` endpoint parity, `agentRunEvents` in the backend-interface
  check, new `TERMINAL_EVENTS` set-parity test. **Reviewed + REJECTED (the
  reviewer's updated pass re-asserts these without new evidence — recorded here
  so future rounds don't re-litigate):**
    - *"Brittle IPv6 Host parsing / `[evil.com]` bypass or ValueError"* — false.
      `http.py` guards `.index("]")` with `and "]" in host` (no ValueError
      path), `[evil.com]` extracts `evil.com` which still hits the allowlist
      (rejected), and every malformed shape (unclosed bracket, multi-colon)
      falls through to the allowlist check — all paths fail closed. `urlsplit`
      would be cosmetic (and raises on invalid ports, needing its own guard).
    - *"sweep_orphans() in get_agent_run_registry() risks concurrent races"* —
      false in this process model. Every caller is an `async def`
      route/middleware (verified: all 9 agent_v1 routes, `/state`, auth
      helper); the getter has no `await` between check and set, so it cannot
      interleave on the event loop. Separate uvicorn workers each sweeping once
      is the CORRECT T7 semantic (fresh process = orphaned futures). A lifespan
      hook would lose the laziness (touch `~/.ppxai/runs/` even with the agent
      tier off). Invariant now pinned in a comment at the getter — add a lock
      IF a sync-def/threadpool caller ever appears.
    - *"`task = req.task or spec.task` is dead code"* — deliberate; the inline
      comment at the site already documents it as forward-compat for relaxing
      `AgentTaskRequest.task` to optional.
    - *"naive quote-strip in respondCmd"* — byte-identical to the web client's
      strip (verb-for-verb parity is the T8a contract); an escaped quote in a
      consent free-text answer rides harmlessly as literal text.

**Branch when ready:** (f)-rebinding + (e)-provider-call + (p)-sync-DNS land with
tier-d OS-isolation; (p)-token-O(N)/role-mint with Inc 8b RBAC; (a)/(b)/(q) with
N>1 sub-agents + the `agent_n`-nesting / `/task` design; **(r) RETIRED
(landed across `/task` T5–T7, 2026-07-07)**; (s) with the
v1.19.x→migration-doc rewrite; **(t) RETIRED** (2026-08-08, `eeb82076`) — T8b was the forcing function
and it resolved in favour of embedding: `build_task_runner` was extracted to
`ppxai/engine/task_runner.py`, so the TUIs drive the registry in-process and
no client grew an HTTP transport. The SDK-embedding question (t) tracked is
answered by that extraction; **(u) DONE** (CORS+Host fix, bind-conditional, shipped `b1e5b3a4`); **(v) ingress
NetworkPolicy + optional app-layer bearer for cross-tenant coder isolation, with
Item 3**; (d) with an SSE rework; (i) with a per-model capability-hint pass (cheap,
anytime).

---


## Closed (recent)

One-liners only — full bodies + evidence trails in
[docs/archive/DEBT-INVENTORY-CLOSED.md](archive/DEBT-INVENTORY-CLOSED.md);
older per-version detail in the v1.18.2/v1.18.3 snapshots.

- **Item 24** — non-vision image attach fail-loud + shell-CLI route — closed 2026-06-23, `feature/v1.19.0`
- **Item 40** — web + VSCode bearer-token support for `/task` — closed 2026-07-11 (web live-trialed 2026-07-12)
- **Item 41** — Gemini native tool-loop `tool_call_id` threading — closed 2026-07-12
- **Item 42** — orphan `assistant.tool_calls` ate user prompts — closed 2026-07-13, `46599e8f`
- **Item 44** — empty-content assistant persisted → Perplexity 400 — closed 2026-07-13
- **Item 45** — Gemini 3.x `thought_signature` round-trip — closed 2026-07-22, `edb74500`
- **Item 50** — `/task` grant naming a nonexistent tool — closed 2026-07-22, `edb74500`
- **Item 60** — refusal messages and API field docs named pre-ADR-0010 config keys — closed 2026-08-10; filed and fixed the same day. Scoped as 3 error strings, was **12** across 8 files: two were `AgentTaskRequest` field descriptions (so the stale path was in the published OpenAPI schema) and four were web/VSCode help text. The `spec` field description already said `execution.task.enabled` one line below `tools.agent.sandbox.specs_dir` — a half-migrated docstring is how a stale hint survives review.
- **Item 51** — Gemini `oneshot()` returned reasoning as answer — closed 2026-07-22, `edb74500`
- **Item 48** — `/clear` left the status-bar `Ctx:` percentage stale — closed 2026-08-03 (step 1 `e7b8f273` engine+Rich, step 2 `112bc0a9` Textual, step 3 Web+VSCode)
- **Item 52** — local `/task` egress gate denied `get_weather` wholesale (scheme-poison superset gap) — closed 2026-08-02, ADR 0009 step ②
- **Item 53** — task execution profiles: config-driven named grants + web_search enrichment — closed 2026-08-03, ADR 0009 (all four steps)
- **Item 56** — shell-wrapper (rtk) availability cache went permanently stale if the binary wasn't on PATH at first check — closed 2026-08-11. Fix (a): `WrapperBase.is_available()` no longer caches a NEGATIVE result — only a positive hit is memoized, so a late-arriving binary is picked up on the next call (`base.py`). Repro tests reframed to the fixed behavior (`test_wrapper_framework.py`, +1 test).
- **Item 57** — `/task` with no grant surfaced a raw HTTP 422 read as an outage — closed 2026-08-11. Web + VSCode clients (`task-controller.js`, `taskController.ts`) short-circuit an empty grant client-side with actionable guidance; server 422 message names the `--tools`/`--spec`/`--skill`/`--profile` flags.
- **Item 58** — user-configurable default `/task` grant (`execution.task.default_grant`) — closed 2026-08-11. New precedence layer below request/spec/skill/profile, above the built-in empty default; gated by operator `execution.task.allow_user_default` (default true, fail-closed when off); resolved grant faces every unchanged clamp (shell-reject, egress-ceiling, kill-switches). `config/execution.py` accessors, `task_authorizer.merge_task_fields` insertion, 422-defer in `agent_v1.py`, schema in `ppxai-config.example.json`, 11 clamp/no-escalation tests in `test_execution_profiles.py`.
- **Item 59** — coder `/task web_search` egress-denied: soft `preferred` let the chain fall to DuckDuckGo while the task egress allowed only perplexity — code closed 2026-08-11. `resolve_web_search_backend()` takes the run's egress predicate and narrows candidates + egress together; `authorize()` threads it in, `web_premium` reads it off a per-call `ContextVar` set by `ScopedToolManager` — selection and egress can't diverge under a narrowed task allowlist (`search_backends.py`, `network_policy.py`, `web_premium.py`, `agent_scoped_tools.py`; +3 tests). ⏳ **Coder ConfigMap** `strict:true`/`default_grant` still to apply on the live cluster (deployment step, not repo). **Seam strengthened 2026-08-31 (ADR 0012 W3 part 2):** the chain became configurable (`tools.web_search.order`), and the non-strict egress set is now **derived from the resolved order** rather than the static `ALL_HOSTS` list — so a configured order cannot enumerate a host the chain will never try, nor omit one it will. Same set as before for the default order (asserted), but no longer two independent sources. This does not reopen or re-close 59; it removes the way a *new* config key could have re-created its divergence.
- **Item 61** — `api_path` declared, config-overridable, `/provider`-displayed and **never routed on** — closed 2026-08-31, ADR 0012 W2 (`1bf93de7`). Routing reads `get_facts_for_model(model).wire_protocol` through ONE reader consumed by all four dispatch sites; the prefix tuple is seed data. Three measured drifts resolved per row on evidence (the two pro models in the router's favour — commit `5e1ace2f` added them after a live *"not a chat model"* 404; `gpt-5.3-codex` in the profile's favour), plus a **fourth found while fencing** (`gpt-5.5-pro`, reached by neither mechanism — probed 2026-08-31, same 404). Fences: declared-vs-routed across every built-in profile, and an operator override proven to change the **outgoing request** in both directions, asserted at the client spy rather than the resolver.
- **Item 62** — ADR 0006's wire validator covered ONE of three protocols; `_convert_messages` was one protocol's emitter in the shared base — closed 2026-08-31, ADR 0012 W2+W4 (`1bf93de7`, `476fce89`). **(a)** `assert_wire_blocks_clean` now runs inside each handler's converter, 3 of 3 wires; the fence parametrises over the handler **registry** (so a fourth wire inherits the requirement) and greps each handler's source, because 62 (a) was precisely a validator that existed and was not called. **(b)** `GeminiProvider._convert_messages` **deleted** with its three helpers — it returned `tuple` against a base annotated `List[Dict[str, Any]]`, a Liskov violation invisible to the type checker because the base's annotation was one wire's shape imposed on all. Each wire declares its own return type; `BaseProvider._convert_messages` survives as a delegation, not an emitter. Extracted converter diffed byte-for-byte across all four role paths before removal.
- Pre-v1.19 closes (v1.18.8 files-parity wave, LibreOffice discovery, session
  save/load security findings, and earlier): see the archive file.
## Related documents

- [ROADMAP.md](../ROADMAP.md) — feature work + future direction (multi-model
  routing, Anthropic provider, prompt analyzer, etc.)
- [CHANGELOG.md](../CHANGELOG.md) — what shipped per release
- [docs/archive/](archive/) — frozen historical snapshots, including the
  per-version debt inventories
- `docs/TODO-*.md` — in-flight planning for the current branch (kept
  separate from debt — those are not "deferred", they're "planned now")
