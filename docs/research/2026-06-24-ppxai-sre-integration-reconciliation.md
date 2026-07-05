# ppxai-sre integration reconciliation — v1.19.0 ground truth

**Date:** 2026-06-24
**Branch verified:** `feature/v1.19.0` @ `690d8db4` (not yet released)
**Contract of record:** [`../../../ppxai-sre/docs/PPXAI-INTEGRATION-V1.19.md`](../../../ppxai-sre/docs/PPXAI-INTEGRATION-V1.19.md)

## Why this doc exists

The integration doc in ppxai-sre is the **written contract** (caveats C1–C5,
asks A1–A3), but it is keyed off a stale **Phase 1–7** plan and an unmerged
planning branch (`42ed8f00`, last re-verified 2026-05-15). The actual build
went **Increment 1–9 + post-Inc-9 hardening §A–§K**. The wire *shapes* line up,
but the phase→increment mapping no longer maps cleanly, and C5 post-dates the
agreement entirely.

This note is the **code-verified reconciliation**: every C/A item walked
against the shipped tree, so the next `/task` / C5 design decision starts from
ground truth instead of the paper plan. When v1.19.x ships, this folds into the
`MIGRATION-V1.19.md` runbook the integration doc promises.

**Verification method:** each item was confirmed by reading the actual emission
site / request model / persist method — not docstrings or comments. File:line
references below are on `690d8db4`.

## The agreed-in-writing contract (C1–C4, A3)

| Item | Required | Status | Evidence |
|---|---|---|---|
| **C1** typed network-policy events | `NETWORK_POLICY_DENIED`/`_ALLOWED`, 6-key payload `{tool, target_host, target_path, reason, allowlist_rule_id, run_id}` | ✅ **Done, exact** (superset) | Payload built [`engine/agent_scoped_tools.py:150-174`](../../ppxai/engine/agent_scoped_tools.py); `run_id` added + event fired [`server/routes/agent_v1.py:615-623`](../../ppxai/server/routes/agent_v1.py). All 6 keys present; `allowlist_rule_id=None` on deny per contract. Adds `approved_targets` (Item 37h) — strict superset. |
| **C2** `/v1/tokens` pluggable resolver | CRUD + resolver protocol + chain; same code path env/k8s/Vault | ✅ **Framework done**, ⚠️ only **env + file** providers ship | CRUD [`server/routes/tokens_v1.py:78-141`](../../ppxai/server/routes/tokens_v1.py); `SecretProvider` protocol [`server/secrets/base.py:98-146`](../../ppxai/server/secrets/base.py); `ProviderChain` [`server/secrets/chain.py:28-94`](../../ppxai/server/secrets/chain.py); factory [`server/secrets/__init__.py:52-87`](../../ppxai/server/secrets/__init__.py). **k8s + Vault not implemented** — but pluggable (drop a `SecretProvider` impl + a factory clause; no route/chain change). |
| **C3** SSE events channel | live `EventType.*` stream + `?live/since/min_level/category` filters | ✅ **Done** | [`server/routes/agent_v1.py:749-828`](../../ppxai/server/routes/agent_v1.py). Queue subscribe-before-snapshot (no lost events); all four filters present; lifecycle events included. |
| **C4** tools first-class on the run, oneshot shape | mandatory `tools`, same shape `/v1/oneshot` would accept | ✅ **Done** | `/task` request `tools: list[str]` mandatory (`min_length=1`); `/run` `tools: list[str]` [`server/routes/agent_v1.py:213`](../../ppxai/server/routes/agent_v1.py) — same `list[str]` shape, so parity holds. (Note: `/v1/oneshot` itself stays tool-free by design — Option A, Item 37k — so "same shape oneshot *would* accept" is the relevant reading, and it is met.) |
| **A3** `run_id`/`parent_run_id` on `AGENT_RUN_START` | additive event fields | ✅ **Satisfied structurally**, ⚠️ not literally in `data` dict | The registry `agent_run_start` event takes `run_id` as its **partition key** ([`engine/agent_runs.py:608-611`](../../ppxai/engine/agent_runs.py)) — every event is intrinsically run-addressed. `parent_run_id` lives on `RunMeta` ([`agent_runs.py:70`](../../ppxai/engine/agent_runs.py)) and is exposed in `RunMetaResponse` ([`agent_v1.py:236`](../../ppxai/server/routes/agent_v1.py)). The consumer has both — by reading `GET /v1/agent/runs/<id>` + the event's addressing, **not** by parsing `AGENT_RUN_START.data`. See gap §3 below. |

**Verdict:** the four load-bearing caveats + A3 are effectively met. The only
asterisks are deferrable (k8s/Vault providers) or a form-vs-substance nuance
(A3). Nothing here blocks ppxai-sre's v1.19.x features.

## Deferred to v1.20.x — verified still deferred (expected)

| Item | Status | Evidence |
|---|---|---|
| **A1** `CONSENT_DECISION` event | ✅ Confirmed absent | not in `EventType` ([`engine/types.py:166-197`](../../ppxai/engine/types.py)) |
| **A2** pre-tool-call hook | ✅ Confirmed absent | no `pre_execute`/headless policy callable in `engine/tools/`; consent boundary today = `consent_policy` deny/auto gate + AC-1/AC-2 subset rules |

## On-disk shape ppxai-sre reads directly

| Element | Status | Note |
|---|---|---|
| `runs/<run_id>/agent-<n>/` namespace | ✅ Correct | `_slot_dir` [`engine/agent_runs.py:198-199`](../../ppxai/engine/agent_runs.py) |
| `meta.json` | ✅ Written | `persist_meta` (atomic via `mkstemp`, Item 37o) |
| `events.jsonl` | ✅ Written | `append_event`; AuditLogger consumes off-disk, no bus tap |
| **`state.json`** (Inspection Triplet 3rd file) | ❌ **Not written** | comments say "Inc 2-3"; only meta+events exist. See gap §2. |
| `transcript.md` | ❓ Not verified present | not written by `agent_runs.py` persist path |
| `agent_n` multi-slot nesting | ⚠️ **Prepared, always 0** | sub-agents are **sibling top-level runs** linked by `parent_run_id`, never `agent-1/`. See gap §1. |

## The genuine gaps (where we actually stand)

### Gap §1 — `agent_n` is always 0; sub-agents are sibling runs

`spawn_subagent` mints the child as its **own top-level run** (own `agent-0/`
slot) linked by `parent_run_id`, NOT as an `agent-<n>/` slot under the parent
([`engine/tools/agent_spawn.py:258-274`](../../ppxai/engine/tools/agent_spawn.py)).
`agent_n` is never assigned a non-zero value anywhere in `ppxai/`. N=1,
depth=1 (`allow_spawn=False`), parent blocks on one child.

This is **correct and deliberate for the MVP** — the comment at
`agent_spawn.py:262-265` records that an early `child.agent_n=1` attempt made
`get_run` (default `agent_n=0` lookup) unable to find the child →
`_await_child` hung. The flat sibling model avoids that.

But: the `runs/<run_id>/agent-<n>/` namespace ppxai-sre codes against is real
yet **single-slot in practice**. Consumer code reading `agent-0/` works; code
assuming `agent-<n>` with n>0 finds nothing. This is the deferred decision that
**C5 and N>1 fan-out both force** — see gap §4.

### Gap §2 — `state.json` not persisted (Inspection Triplet incomplete)

The doc's Phase 3 promises "run persistence (`state.json` checkpoints)". Only
`meta.json` + `events.jsonl` are written today. A consumer following the doc
literally and expecting the full Triplet (`heartbeat.py` reconstructing
`AgentBeatState` from a checkpoint) **will find no file**. Low-effort to close,
but it is a real divergence from the written plan.

### Gap §3 — A3 form-vs-substance

The information A3 needs (`run_id`, `parent_run_id`) is fully available, but NOT
by parsing the `AGENT_RUN_START` event payload as the doc's "additive fields on
the event" wording implies. Consumer guidance: **read `run_id` from the event's
addressing / `GET /v1/agent/runs/<id>`, and `parent_run_id` from
`RunMetaResponse`** — do not expect them inside `AGENT_RUN_START.data`. Either
ppxai folds the fields into the payload for literal compliance, or the doc is
amended to state the structural form. Decide during the migration rewrite.

### Gap §4 — C5 (agent-served services) entirely unbuilt — and entangled with §1

All of C5.0–C5.5 are **absent** from the shipped tree (verified):

| C5 element | Status |
|---|---|
| `services` field on `POST /v1/agent/run` request | ❌ absent (`AgentRunRequest` has no field) |
| reverse-proxy route `…/services/<name>/...` → bound port | ❌ absent (no route in `server/routes/` or `http.py`) |
| `EventType.AGENT_SERVICE_DOWN` | ❌ absent |
| C5.1 auth surface (`bearer\|session\|none`) | ❌ absent |
| C5.2 bearer token source flexibility | ⚠️ `/v1/tokens` default source exists; no per-service `token_source` swap |
| C5.3 inbound network policy (`allow_inbound`) | ❌ absent (outbound C1 exists; inbound does not) |
| C5.4 restart_policy + drain / terminate API | ❌ absent |
| C5.5 reverse-proxy path semantics (`X-Forwarded-Prefix`) | ❌ absent |

This is **correct, not a regression** — C5 post-dates the `42ed8f00` agreement
and was never folded upstream. outlook-monitor ships the documented workaround
(FastAPI binds its ports directly; per
`ppxai-sre/docs/DESIGN-outlook-agent.md` §"C5 mapping").

**Why C5 and §1 are the same design:** C5's bound-service inspection path is
`runs/<run_id>/agent-<n>/services/<name>/`. You cannot hang a service slot off a
sub-agent that has no real `agent-<n>` slot. And the manager-executor fan-out
(integration doc Phase 2) needs N>1. So **implementing real `agent_n` slots →
unblocks C5 → is what ppxai-sre's long-lived service agents need.** The `/task`
proper-design conversation IS the C5 + `agent_n` conversation.

## Bottom line

- **Written contract (C1–C4, A3): met.** Remaining asterisks are deferrable
  (k8s/Vault token providers) or a form nuance (A3).
- **Three open items, in priority order:**
  1. **C5 agent-served services** — entirely unbuilt; entangled with `agent_n`
     nesting; the big one. (Debt Item 37p.)
  2. **`state.json` persistence** — Phase 3 promise; only 2 of 3 Triplet files
     exist. (Debt Item 37q.)
  3. **A3 literal form** — information available, not in the event payload;
     resolve during migration-doc rewrite. (Debt Item 37r.)
- **Doc hygiene:** the integration doc's Phase 1–7 framing no longer maps to the
  shipped Increment 1–9 + §A–§K. Rewrite as `MIGRATION-V1.19.md` keyed off
  shipped increments once the `/task`/C5 decision lands.
