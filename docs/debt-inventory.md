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
then split. See [docs/plan-v1.19.0-sequencing.md](plan-v1.19.0-sequencing.md).

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

### Item 24 — VL sidecar `auto_caption` fallback silently no-ops on non-vision models

**Affected files:** `ppxai/engine/multimodal_ops.py` (`auto_caption_image` and the
`get_vision_model_config()` consumers around L575–640), `ppxai/engine/file_preprocessing.py`
(L235–290, the `supports_vision(model)` routing branch), the chat-attachment path that
delivers the "It was sent as a text placeholder" warning to the web UI.

**What's wrong:** when the active model is text-only AND `tools.vision_model.auto_caption: true`
is configured with an enabled, reachable VL sidecar (the documented "Qwen3-VL caption
gateway" pattern used by the coder cluster — `Qwen/Qwen3-VL-8B-Instruct` at
`vllm-qwen3-vl-8b-fp8-lmcache-mig.vllm.svc`), the image-attach pipeline is
**expected** to call the sidecar, get a caption back, and inline it into the user
message so the text-only model receives describable content. Dogfooded on
coder.trad.int 2026-06-08 with the Qwen/Qwen3.5-27B-FP8 vllm-qwen35 provider: an
attached `.drawio.png` network diagram surfaced the `vision_unsupported` warning
("sent as a text placeholder") and the model then **hallucinated a fully
fabricated description of "empty 35mm film reels"** — the worst of both worlds.
Detection was correct (`supports_vision('Qwen/Qwen3.5-27B-FP8') = False`,
conservative default — no Qwen3.5-base profile entry); the auto-caption fallback
just never fired. Why is unconfirmed — candidates: sidecar unreachable from this
namespace, 30s timeout silently swallowed, the drag-drop UI path taking a
branch that bypasses `multimodal_ops.auto_caption_image`, or `enabled: true`
but the actual call erroring with no surfaced message.

**Why deferred:** detection logic is correct and the warning fires; the user
sees "sent as a text placeholder", so the failure isn't silent at the UI layer.
The downstream model hallucination is a model-quality issue, not a ppxai bug.
Workaround: switch to a true VL provider (gemini-2.5-flash, gpt-5.5, dgx-cluster
once the model swap lands), or check the VL sidecar health from the pod and
attach again. The class of bug — "fallback that's wired but doesn't run" —
deserves a sentinel; not a release blocker.

**Planned:** `bugfix/v1.18.8` or whichever v1.18.x branch follows. Trigger an
investigation pass that probes the actual auto_caption code path end-to-end on
the coder cluster (image attach → does the sidecar receive the POST?), surfaces
the failure mode in the user warning (currently "sent as a text placeholder" is
indistinguishable from "tried sidecar and it failed"), and adds an integration
test that mocks a text-only active model + a reachable VL sidecar and asserts
the caption is inlined into the message rather than the placeholder.

**Branch when ready:** `bugfix/v1.18.8` (open-items follow-up) or
`fix/vl-sidecar-fallback` (focused).

**Trigger to revisit:** any second report of "I attached an image and the
model made up a description" on the coder cluster, OR before the dgx-cluster
model swap to confirm we're not stacking another fallback gap, OR if anyone
adds a new modality (audio/video) — same pattern likely lurks for those too.

**Effort:**
- Diagnose root cause (~1 hour): tail pod debug log on next image attach;
  grep for `vision_model` / `caption` / `Qwen3-VL`; in-pod `curl` to the
  sidecar to confirm reachability; check `multimodal_ops.auto_caption_image`
  for swallowed exceptions.
- Fix + surface (~half day): if cause is timeout or unreachability, distinguish
  the warning text ("VL sidecar timed out (30s) — re-attach to retry" vs
  "sent as text placeholder, active model is not vision-capable"); if cause
  is a code-path bypass, route the drag-drop path through the same handler
  as `/attach`.
- Integration test (~1 hour): mock active=text-only model + mock vision_model
  endpoint; assert caption inlined into user message.

**Surfaced by:** coder.trad.int dogfooding 2026-06-08, drawio.png attach to
the vllm-qwen35 provider.

> **Update 2026-06-08 (same day):** the user pushed back that they're sure
> they tested these 27B models and they support VL. Cross-repo search found
> two artifacts that prove the user was right and reframe this item:
>
> 1. `/home/itadmin/ai/git/trad-ai-chat/scripts/test-vl-capabilities.sh`
>    (commit `916772c`, 2026-04-23) — 9-test VL probe (Test 0 image accept,
>    Test 1 OCR, Test 2 tables, Test 3 charts). Baseline run against
>    `https://codeai.trad.int/qwen35/v1` model `Qwen/Qwen3.5-27B-FP8`
>    scored **8/9 PASS**. The one fail (Test 2b) was arithmetic-over-OCR'd-data
>    reasoning — NOT vision.
> 2. `/home/itadmin/ai/git/trad-ai-chat/doc/research/qwen35-vs-qwen36-27b-comparison.md`
>    (2026-04-30) — confirms Qwen3.6-27B-FP8 has an **explicit vision
>    encoder** added in the architecture ("Text + image + video"); Qwen3.5
>    is labeled "Text-only" on the HF card but empirically handles
>    `image_url` content through vLLM. Comparison doc recommends the
>    `test-vl-capabilities.sh` script as Gate A for the Qwen3-VL
>    decommission (CR-v4.0.0 Part 2 Phase 6).
>
> **Reframed root cause:** ppxai's `model_profiles.py` has no entry for
> `Qwen/Qwen3.5-27B-FP8` or `Qwen/Qwen3.6-27B-FP8` (`supports_vision()`
> falls through to default `False`). The HF card "Text-only" label on 3.5
> is wrong for the model's behavior through vLLM, and 3.6's vision encoder
> is real. **The detection is wrong; the model would have shown the diagram
> correctly if ppxai had sent the `image_url` block.**
>
> **Revised fix path (priority bump — Item 24 jumps above 21–23):**
>
> 1. Add `model_profiles.py` entries with `supports_vision=True` for both
>    `Qwen/Qwen3.5-27B-FP8` and `Qwen/Qwen3.6-27B-FP8` (or a glob
>    `Qwen/Qwen3.[56]-27B-FP8`). Sentinel test in
>    `test_model_profiles.py`. **5-minute change.**
> 2. Re-run `test-vl-capabilities.sh` against the coder cluster's actual
>    endpoints to confirm both models still pass 8/9+; capture the run as a
>    memory snapshot. **30 min.**
> 3. The original sidecar-fallback diagnose (the "fallback wired but
>    doesn't run" class) is now SECONDARY but still real — it would fire
>    for genuinely text-only providers (e.g. `openai/gpt-5-nano`). Keep
>    the half-day estimate for that part as a separate concern.
>
> See [[reference-qwen-27b-vl-empirical]] (memory) +
> `docs/lessons/qwen-27b-vl-empirically-supported.md` (in-repo lesson, this
> commit) for the cross-host evidence trail so the next session doesn't
> have to re-derive.

---

### Item 29 — `engine.completion` imports `commands.factory` and reads its internals [layer inversion]

**Affected files:** `ppxai/engine/completion.py` (import at line 47;
reads `CommandFactory._registry` at lines 234/249, `._aliases` at 248,
`._ensure_loaded()` at 229). Shared entrypoint `complete()` (line 165) is
called from `ppxai/tui/completer.py:25`, `ppxai/rich/main.py:34`, and
`ppxai/server/routes/completion.py:17`.

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
`tools.agent.default_subagent` (global JSON config) → 400. The
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
`request value → per-session sub-agent config → tools.agent.default_subagent (global) → 400`.

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

**c. `tool_targets()` fixed backend list (copilot 2026-06-16).** The egress
target enumeration for `web_search`/`get_weather` in
`engine/tools/network_policy.py::_NETWORK_TOOLS` is a hard-coded list of every
backend host a tool could reach (the AC-2 superset-rule fix). **Maintenance
hazard:** if a new `web_search` backend is added to `web_premium.py` and
`_NETWORK_TOOLS` is NOT updated, a run could reach an un-allowlisted host with
no `network_policy_denied` event — a silent AC-2 regression. Mitigation idea:
derive the backend set from the provider config / a single source, or add a
test that asserts `_NETWORK_TOOLS` covers every premium backend.

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
  Tests: `test_agent_system_prompt.py`. **Still optional (not done):** a
  `weak_tool_calling` warning event when a `/task` targets
  `native_tool_calling:false` — now lower value since the framing fix
  addresses the actual behavior; keep as a nice-to-have for SRE audit
  visibility. Needs live trial on Perplexity Sonar to confirm the framing
  actually stops the substitution (mechanism is in; behavior unverified).
- **(a)/(b)** unchanged — promote with the N>1 sub-agent work.
- **(d)** unchanged — only matters if the SSE layer is reworked.

**Branch when ready:** (f)-rebinding + (e)-provider-call land with tier-d
OS-isolation; (a)/(b) with N>1 sub-agents; (d) with an SSE rework; (i) with
a per-model capability-hint pass (cheap, anytime).

---

## Closed (recent)

For full closed-item rationale with commit references, see the per-version
archived snapshots:

- **Post-files-parity v1.18.8 review fixes (closed 2026-06-14):** beyond the
  `/files/*` items (25–28, 30–32), two parallel reviews + live desktop testing
  surfaced and closed: **cross-platform LibreOffice discovery** (`9d1c7550` —
  macOS `soffice`/`.app` was undetected, raster preview dead by default; +
  formatted install card) and its CI-safe test fix (`4b60970f`); **three
  session save/load security findings** (`de3b56d7` — path traversal in
  names, stale attachment file_ids on load, corrupt-load file-store
  corruption); and the **session auto-restore-mode** bug (`1fe60ea5` — web
  client ignored `auto_restore` and used a fragile `confirm()`, so restore
  landed on fresh defaults; `/status` now exposes the mode). All with
  regression tests. See [CHANGELOG.md](../CHANGELOG.md) `[1.18.8]`.

- **Item 28 — OfficeFileView blob-revoke race + attachment text_fallback (closed 2026-06-14):**
  `ef17f748` on `bugfix/v1.18.8`. The attachment renderers (`app.js`) gained an
  `unmounted` flag so the async `.then()` no longer creates a leaked blob URL
  into a detached container; the text-fallback sites now assert a string
  `content` (surface `missing "content" key` instead of `'(empty)'`). Also
  followed through on item 26: the attachment path now branches on
  `libreoffice_available`/content-type and degrades to extracted text (via a
  new shared `OfficeFileView.renderTextFallbackInto()`), so chat-bubble
  attachments degrade like the file tree instead of rendering JSON as a slide
  image / PDF. Web-only; `node --check` clean, DOM = manual-smoke. v1.18.8
  Phase F (3/3). **Follow-up (`84ee33c2`, post-review):** (a) closed a residual
  `renderSlideNavInto` leak — it created the object URL *after* `await
  fetchSlideBlob`, so an unmount mid-fetch leaked the post-await URL; added a
  `disposed` flag (fixes attachment **and** file-tree PPT previews). (b) Fixed
  the **VSCode** twin of the web JSON-as-binary bug: `chatPanel.ts` wrote every
  ok `/files/preview` response to `.png`/`.pdf`, so the item-26 200 JSON
  text_fallback became a garbage image/PDF — now branches on
  `libreoffice_available`/`type` + content-type and falls back to the raw file.

- **Item 26 — `/files/preview` route unification (closed 2026-06-14):**
  `579a2fe8` on `bugfix/v1.18.8`. Both preview routes (path-based in
  `files.py`, id-based in `file_serve.py`) now delegate to one shared
  `render_office_preview()` helper → ONE JSON shape (`type`, `kind`,
  `libreoffice_available`, `total`, `name` always present) and ONE
  failure mode (LibreOffice missing → **200 text_fallback**, never the
  id-route's old 503; legacy `.ppt`/`.doc` → typed message, not a 500).
  id route derives the office ext from `meta.name`/`media_type` (content-
  addressed `meta.path` may lack one). Guard: `TestUnifiedPreviewContract`
  in `test_files_preview_download.py` (runs without office libs via mocked
  probe); 70 passed / 5 office-lib-skipped across preview suites. Unblocks
  future VSCode office-preview delegation. v1.18.8 Phase F (2/3).

- **Item 25 — `/files/read` type-contract consumers (closed 2026-06-14):**
  `2a22807c` on `bugfix/v1.18.8`. Kept the typed server contract (option b);
  fixed every consumer to branch on `type`: `CodeEditorView` refuses any
  non-`text` type (no more base64-as-text / corrupt-on-save), RPF
  save/restore gained the `office` viewType (round-trips `OfficeFileView`),
  the `typeof OfficeFileView !== 'undefined'` deploy-skew guard was dropped
  (errors visibly now), and VSCode `httpClient.readFile` got the real
  `ReadFileResponse` union + branch-on-`type` warning (contract-only, zero
  callers). Guard: `TestReadOfficeTypeContract` in `test_files_route.py`
  (csv/xlsx→office_spreadsheet base64; txt→text+lines; pptx/docx→400 hint).
  Web DOM = manual-smoke (no JS harness); `tsc`/`node --check` clean.
  v1.18.8 Phase F (1/3).

- **Item 30 — coding auto-route notice lost cross-client (closed 2026-06-14):**
  `0f21cee1` on `bugfix/v1.18.8`. `_execute_ai_task` no longer `console.print`s
  the "Auto-routed to <model>" notice (invisible to web/VSCode server-side);
  it rides in `AIResponseResult.content` (the field those clients render —
  they fall back to `message` only when content is empty). Code-block
  extraction runs on the raw output first. Other `console.print` sites in
  the function are live-TUI UX or already in the result. Guard:
  `tests/test_coding_autoroute.py`. The broad agent/utility/handler sweep is
  tracked separately as **open Item 33** (v1.19.x). v1.18.8 Phase E.

- **Item 31 — direct `session.messages` mutation bypasses AppState (closed 2026-06-14):**
  `44bb5dea` on `bugfix/v1.18.8`. Added `SessionManager.pop_orphan_trailing_users()`
  (replaces the `streaming.py` orphan-cleanup loop — now fires the
  `on_messages_changed` callback; the loop fired none before) and a
  `preserve_trailing_user()` context manager (wraps the `chat.py` preflight
  detach/restore — transient no-op, the inner `validate_and_fix_alternation`
  notifies). chat.py post-tool prompt removal routed through the existing
  `remove_last_message()` (also fixes a latent multimodal-cache miss).
  Behaviour preserved (`chat.py:273` already netted to a no-op). Guard:
  `TestMessageMutationHelpers` in `test_session_persistence.py`. v1.18.8 Phase C.

- **Item 32 — command envelope can carry non-JSON objects (closed 2026-06-14):**
  `439a0325` on `bugfix/v1.18.8`. `ConfirmationResult.to_dict()` now runs
  `details` through a recursive `_jsonsafe()` (dataclass→`to_dict()`/`asdict`,
  bytes→marker, unknown→`str`), so the HTTP envelope is always
  `json.dumps`-able. The raw-`Message` `/load` key is preserved for the
  in-process Textual renderer (which never calls `to_dict()`) — audit
  correction: it was **not** consumer-free as first flagged. Guards:
  `test_command_envelope_serialization.py` + parametrized
  `test_to_dict_is_json_serializable` over every `CommandResult` subclass.
  v1.18.8 Phase B.

- **Item 27 — `/files/image/` home-confinement (closed 2026-06-14):**
  `7fb83d8b` on `bugfix/v1.18.8`. `serve_image` swapped
  `str(path).startswith(str(home_dir))` → `_within_tree(path, home_dir)` —
  the third confinement site, which the v1.18.7 fix `09eae96e` had missed
  (it migrated `read_file`/`write_file` only). `TestServeImageConfinement`
  added (sibling-prefix path → 403 via `/files/image/`, verified to fail
  404 against the old check; in-tree image → 200). v1.18.8 Phase A — see
  [plan-v1.18.8-files-parity.md](plan-v1.18.8-files-parity.md).

- **Item 20 — v1.19.x alignment paperwork (closed 2026-05-24):** merged to
  master as `56bc2d38` (Stage-2 fold rebased from `42ed8f00`) + `7a2ea268`
  (C5 §13 + `AGENT_SERVICE_DOWN`) + `45e352fe` (ROADMAP "Pending alignment
  paperwork" subsection removal). Folds all consumer caveats C1–C5 and asks
  A1–A3 into ADR 0003 §6–§13 with Phase 1/5/7 ROADMAP commitments inline.
  `feat/agent-platform-stage-2` (Phase 1 implementation branch) is now
  unblocked.

- **v1.18.3 branch (closed 2026-05-02):** Items 12 (Node.js 20 → v5),
  13 (release.py step 14 silent-failure), 15 (`deploy/shared/AGENTS.md`
  stale copy), 16 (throttle counters in `/usage`), 17 (qwen3-coder-480b
  excluded after rerun confirmed contamination), 18 (NIM probe rerun),
  19 (Qwen3.5 `enable_thinking` config example), plus Tier 1 #1-3 and
  Tier 2 #4-5 from the v1.18.3 NIM engine work. See
  [docs/archive/DEBT-INVENTORY-v1.18.3.md](archive/DEBT-INVENTORY-v1.18.3.md).

- **v1.18.2 branch (closed 2026-04-29):** Items 1 (god-node refactoring
  narrowed to session_restore_ops), 2 (resolveWebviewView contract
  refactor), 4 (focused-subtree graphify runs), 5 (esbuild VSIX bundle),
  6 (Windows `code` CLI shim), 7-9 (Tier 1 observability), 10
  (EngineClientProtocol), 11 (agent.py logger AttributeError). See
  [docs/archive/DEBT-INVENTORY-v1.18.2.md](archive/DEBT-INVENTORY-v1.18.2.md).

---

## Related documents

- [ROADMAP.md](../ROADMAP.md) — feature work + future direction (multi-model
  routing, Anthropic provider, prompt analyzer, etc.)
- [CHANGELOG.md](../CHANGELOG.md) — what shipped per release
- [docs/archive/](archive/) — frozen historical snapshots, including the
  per-version debt inventories
- `docs/TODO-*.md` — in-flight planning for the current branch (kept
  separate from debt — those are not "deferred", they're "planned now")
