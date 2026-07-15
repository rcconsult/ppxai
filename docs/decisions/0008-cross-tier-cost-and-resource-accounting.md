# ADR 0008 — Cross-tier cost and shared-resource accounting

**Date:** 2026-07-15
**Status:** Proposed (living draft — may be revised in place until Accepted)
**Related:**
- [`0004-llm-gateway-features.md`](0004-llm-gateway-features.md) — established the stateless `/v1/oneshot` tier that bypasses `EngineClient` (the origin of gap #1 below)
- [`0003-agent-platform-architecture.md`](0003-agent-platform-architecture.md) — established the per-run `EngineClient` (D1 isolation) for `/v1/agent/task`
- `ppxai/engine/session.py::save_usage_to_persistent_storage` — the only writer of `usage.json`
- `ppxai/usage.py` — usage persistence + `/cost` rollup
- `ppxai/server/routes/oneshot.py` — stateless, no `EngineClient`, usage returned then dropped
- `ppxai/server/routes/agent_v1.py` — per-run engine; per-run token budget (`control.tokens_used = engine.session.live_run_tokens`, ~L1045) but no global rollup
- Debt inventory: **Item 49** (this ADR's tracking entry)

---

## Context

ppxai now spends provider tokens through **three independent tiers** that can
run **concurrently for one user against one provider account**:

1. **Interactive session** — Rich/Textual/Web/VSCode `/chat`, one long-lived
   `EngineClient` per session.
2. **`/v1/oneshot`** — stateless; builds the provider directly, **no
   `EngineClient`** (ADR 0004, deliberately, for zero session side-effects).
3. **`/v1/agent/task`** — a **per-run `EngineClient`** (ADR 0003 D1 isolation);
   one throwaway engine + session per run.

Each tier's client-side isolation was a correct decision for its own purpose
(oneshot statelessness; task blast-radius containment). But that isolation
created an **accounting blind spot** that only becomes visible when the tiers
run together — which is exactly the ppxai-sre integration shape (an interactive
operator + background outlook-monitor task + oneshot gateway calls, all on the
same key).

### Gap #1 — local cost view under-reports true provider spend (verified)

`save_usage_to_persistent_storage` (the sole writer of `usage.json`, which
backs the `/cost` command and time-based analytics) is called **only from
interactive paths**: `commands/handler.py:441`, `rich/main.py:623`,
`tui/stream_handler.py:310`, `server/session_manager.py` (the `/chat`
session), `server/streaming.py`. **Neither `oneshot.py` nor `agent_v1.py`
calls it.**

Consequence, for a user running chat + oneshot + task on the **same provider**:

- The provider **bills for all three** (same API key / same account).
- ppxai's `/cost` and `usage.json` reflect **only the interactive session**.
- Oneshot usage is returned in the HTTP response, then **dropped**.
- Task usage lives in the run's own session + run record, and is **never**
  aggregated into `usage.json`.

So the local cost counter **silently under-reports** whenever background
oneshot/task runs are active. If the tiers use *different* providers the
under-report is less misleading (separate bills anyway) but still incomplete.
This is a correctness gap in a number users trust for budgeting.

**Not the same as display-scoping.** The `Ctx:` status badge (v1.19.1 Item 48)
is *correctly* per-engine — each tier's badge shows its own session. That is a
UI-scoping property and is working as intended. This ADR is about the
**money**, which is a shared physical resource the per-engine model does not
represent.

### Gap #2 — no model of shared KV-cache contention (verified absent)

Token *cost* is not the only shared resource. On a **self-hosted inference
endpoint** (vLLM / NIM), the **KV cache is a finite GPU resource** shared
across all concurrent requests, regardless of how many `EngineClient`
instances the client spins up (isolation is client-side; the cache is
server-side):

- Chat + oneshot + task each send their **own** prompt → they **contend** for
  the same KV-cache blocks. Under pressure vLLM preempts/recomputes, raising
  effective token cost + latency for **all three, including interactive chat**.
- Prefix-cache **reuse** only helps requests that share a prefix. The three
  tiers use **different system prompts** (chat = config prompt; oneshot =
  provider default; task = `compose_agent_system_prompt`), so they get **no
  cross-tier cache benefit** — they only compete.

ppxai models **none** of this — there is no KV-cache occupancy/eviction metric
anywhere in the codebase, because the cache is the provider's internal state.
This is not a bug (we can't see hosted-provider cache), but it is an
**operational reality the cost model should at least acknowledge** so a user on
a self-hosted endpoint understands that concurrent tiers degrade each other.

### What DOES exist (so the ADR is grounded)

- **Per-run token budget** (`agent_v1.py` ~L1045): a task run can cap its own
  token spend (`control.tokens_used = engine.session.live_run_tokens`,
  checked per tool iteration). This is **per-run capping**, torn down with the
  run — NOT a session-wide or account-wide budget, and it does not feed
  `usage.json`.
- **`usage.json` rollup** (`usage.py`): time-based analytics for the
  interactive session only.

---

## Decision (PROPOSED — not yet chosen; options for owner sign-off)

The problem is genuinely non-trivial because a "single global counter" naively
sums tiers that may (a) be different providers with different pricing, (b) run
concurrently across process boundaries (server tiers vs. in-TUI session), and
(c) have legitimately separate accounting needs (a per-task bill for a tenant
vs. the operator's own chat). So this ADR frames options rather than forcing
one.

### The unifying idea: a usage sink, keyed by (provider, model, tier, owner)

Introduce **one usage-recording seam** that every token-spending path reports
to — an append-only event, not a mutable counter — carrying:
`{provider, model, tier ∈ {chat, oneshot, task}, owner/run_id, prompt_tokens,
completion_tokens, estimated_cost, ts}`. `usage.json` / `/cost` become a
**query** over that log, filterable by tier and provider, instead of a field
mutated only on the interactive path.

This keeps the tiers' runtime isolation (no shared `EngineClient`) while giving
accounting a **single source of truth** it currently lacks. It also composes
with Item 35 (pluggable persistence channel) — the sink is one such channel.

### Options considered

- **Option A — Recording seam + tier-tagged rollup (recommended direction).**
  Every tier calls a small `record_usage(event)` sink; `/cost` aggregates and
  can break down by tier/provider. Oneshot/task opt in with one call at their
  terminal point. Pro: one truth, honest totals, per-tier visibility, and a
  natural home for a future *account-wide* budget. Con: touches all three
  tiers; needs a concurrency-safe append (cross-process for the server tiers).

- **Option B — Leave tiers isolated; `/cost` explicitly scoped "interactive
  only".** Cheapest: just document that `/cost` excludes oneshot/task and
  surface each run's cost in its own run record / oneshot response. Pro: no
  new plumbing; honest by disclosure. Con: no aggregate view of true spend
  against a shared budget — the user still has to sum three places by hand.

- **Option C — Provider-side reconciliation.** Pull authoritative spend from
  the provider's billing API instead of counting locally. Pro: ground truth,
  immune to our miscounts. Con: not all providers expose it; async/delayed;
  doesn't help self-hosted vLLM (no bill).

- **Option D — Full account-wide budget enforcement** (cap total spend across
  all tiers, not just per-run). Pro: real cost control for the shared-budget
  case. Con: requires a shared, concurrency-safe budget store across the
  in-TUI session and the server process — a distributed-counter problem; large.

**KV-cache (Gap #2)** is *not* solved by any cost option. The proposed
position is **acknowledge, don't model**: document the contention for
self-hosted endpoints, and — if we want a signal — surface vLLM's own
`/metrics` (cache-usage, preemptions) as an *optional operator dashboard read*,
never as something ppxai tries to account per-request.

---

## Why not just "sum a global counter" (the naive fix)

- **Different providers → different pricing.** A single scalar total is
  meaningless when chat is on Perplexity and the task is on NVIDIA. The sink
  must key by (provider, model) or the number lies.
- **Cross-process concurrency.** The interactive session runs in the TUI
  process; oneshot/task run in the server process (possibly many workers). A
  naive shared counter is a race; the append-only log + query sidesteps it.
- **Legitimately separate views.** A tenant's per-task bill and the operator's
  own chat spend are different questions. Tier-tagging answers both from one
  log; a merged scalar answers neither cleanly.

---

## Triggers to revisit / decide

- ppxai-sre runs interactive + background task on **one** provider budget and
  needs a true total (the concrete driver — likely forces Option A soon).
- A user reports `/cost` "wrong" while background runs are active.
- Self-hosted vLLM users hit KV-cache preemption and ask why interactive
  latency spikes when a task runs (forces the Gap #2 documentation at least).
- Any per-tenant billing requirement (forces tier+owner tagging → Option A).

---

## Consequences

**If Option A is chosen (recommended):**
- Enables: honest aggregate cost, per-tier/provider breakdown, a home for a
  future account-wide budget, and alignment with Item 35's persistence channel.
- Requires: a concurrency-safe append sink reachable from both the TUI process
  and the server workers; one `record_usage` call added at each tier's terminal
  point (interactive already persists — retarget it through the sink; oneshot +
  task add one call each); `/cost` reworked from field-read to log-query.

**Until a decision lands (current state, must be disclosed):**
- `/cost` and `usage.json` reflect **interactive session only**.
- Oneshot/task token spend against a shared provider budget is **invisible**
  locally — users must not treat `/cost` as their true provider bill when
  background runs are active.
- Per-run task token budgets cap **individual runs**, not aggregate spend.
- KV-cache contention on self-hosted endpoints is **unmodeled**; concurrent
  tiers degrade each other's cost/latency with no local signal.

---

## Open questions for sign-off

1. **Which option** (A recommended; B if we want cheapest-honest; C/D later)?
2. **Scope of the sink** — tier-tagged rollup only, or also the substrate for
   an account-wide **budget** (Option D) later? (Affects whether the sink is
   read-only analytics or also an enforcement point.)
3. **KV-cache** — acknowledge-only (doc), or add the optional vLLM `/metrics`
   operator read?
4. **Cross-process store** — reuse `usage.json` (file, needs locking) or a
   small SQLite/append-log for the concurrency-safe sink?
