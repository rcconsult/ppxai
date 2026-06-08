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

**Branch when ready:** `feat/k8s-session-manager-tests`.

**Trigger to revisit:** when a third-party deploys ppxai multi-tenant,
OR when a security audit demands LDAP/RBAC test coverage, OR when CVE
disclosure procedures need this code to have minimum test coverage.

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

## Closed (recent)

For full closed-item rationale with commit references, see the per-version
archived snapshots:

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
