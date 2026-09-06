# ADR 0008 — Cross-tier cost and shared-resource accounting

**Date:** 2026-07-15
**Status:** **Accepted 2026-09-06 — Option A implemented** (`ppxai/usage_events.py`, taps in `engine/task_runner.py` + `engine/session.py`, rollup in `/cost`). Debt Item 49 closed. See §Sign-off for what was decided on each open question.
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
2. **`/v1/oneshot`** — stateless *to the caller*; ~~builds the provider
   directly, **no `EngineClient`**~~.
3. **`/v1/agent/task`** — a **per-run `EngineClient`** (ADR 0003 D1 isolation);
   one throwaway engine + session per run.

> **Premise update (2026-08-15, v1.19.1 — this ADR is a living draft).**
> Tier 2's description above is **no longer true**. The FU unification made
> *every* `/v1/oneshot` — plain and enriched alike — execute as a
> `kind=oneshot` registry run through `build_task_runner`, and the direct
> non-registry path was **deleted**. That runner constructs a per-run
> `EngineClient` (`ppxai/engine/task_runner.py:218`), so tiers 2 and 3 now
> share one execution path and one client shape; the wire contract of
> `/v1/oneshot` is unchanged.
>
> This **simplifies the decision rather than complicating it**: the sink
> only has to reach two shapes — the long-lived interactive `EngineClient`
> and the per-run one — not three, and a single hook at the run-registry
> boundary covers both background tiers at once. Whoever picks up this ADR
> should re-read the options below with that in mind; some of the
> complexity they weigh against each other was tier-2-specific and has
> evaporated.

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

**SDK consumers raise the stakes (noted 2026-08-15).** ppxai-sre embeds
ppxai to implement its own agents and drives `/v1/oneshot`. An embedder
that runs agents on a shared provider account has no way to attribute or
cap spend while this ADR is unimplemented — the blind spot is not just a
`/cost` under-report in the TUI (debt Item 49), it is a missing API for
anyone building on the platform. That does not by itself decide the
options below, but it means the consumer of this decision is now external,
not only the interactive user.

The consumer has confirmed (2026-08-15) that the collapsed tier shape is
also the one it would consume most cleanly: a **single tap at the
run-registry boundary** covers both background tiers, which is the shape
its own `AuditLogger` already expects. That is evidence for the
registry-boundary option below, not a decision — the options still need
owner sign-off.

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

**Superseded 2026-09-06 by the implementation — kept for the record.** The
state below was true from 2026-07-15 until Option A landed:
- `/cost` and `usage.json` reflect **interactive session only**.
- Oneshot/task token spend against a shared provider budget is **invisible**
  locally — users must not treat `/cost` as their true provider bill when
  background runs are active.
- Per-run task token budgets cap **individual runs**, not aggregate spend.
- KV-cache contention on self-hosted endpoints is **unmodeled**; concurrent
  tiers degrade each other's cost/latency with no local signal.

---

## Sign-off (2026-09-06)

Answers to the four questions this ADR was blocked on.

**1. Which option → A.** A recording seam every tier reports to, with `/cost`
aggregating over it. B (disclose-only) was rejected because the disclosure
already existed in this document and the under-report kept happening; a
correct number beats a documented wrong one. C and D remain open and are not
foreclosed — C is a reconciliation source that can be added later, and A is
the substrate D would need anyway.

**2. Scope → read-only analytics now, enforcement-capable by construction.**
The sink records; nothing reads it to deny a request. But the event carries
`owner` and `run_id`, so an account-wide budget (Option D) becomes a query
against the log rather than a new store. Deliberately not built: enforcement
needs a policy on what happens mid-run when a budget is exceeded, which is a
separate decision with user-visible behaviour.

**3. KV-cache → acknowledge-only.** No metric, no per-request accounting, as
proposed. Gap #2 remains documented rather than modelled; the optional vLLM
`/metrics` operator read is not implemented and stays available as a later
addition. Nothing in Option A depends on it.

**4. Cross-process store → an append-only JSONL log**
(`~/.ppxai/usage/usage-events.jsonl`), not SQLite and not locked `usage.json`.

Each event is one line written with a single `os.write()` to an `O_APPEND`
descriptor. The kernel makes the offset-grab and the write atomic under
`O_APPEND`, so concurrent writers across processes interleave whole lines
rather than fragments — which is exactly the property a shared mutable
counter lacks, and the reason gap #1 could not be fixed by "also call
`save_usage_to_persistent_storage` from the other tiers". The line has a
4096-byte ceiling (the POSIX `PIPE_BUF` floor) enforced in `record_usage`;
a realistic event serialises to ~200 bytes.

SQLite would also have been correct and was rejected on proportion: it
introduces a second storage substrate to a project that persists everything
else as JSON, for a workload that is append-mostly and read-rarely. The
JSONL log is inspectable with `tail`, needs no migration story, and its
failure mode — a truncated final line from a killed process — is handled by
skipping and COUNTING unparseable rows, so a partial total is never
presented as a complete one.

### Is the log a consumer interface?

**No — `/cost` is the interface; the file is an implementation detail.**
Raised by ppxai-sre while this ADR was uncommitted, and worth answering in
the document rather than in a message, because a path read by an out-of-tree
consumer becomes a compatibility surface the moment it ships.

Read `/cost` and its result metadata (`by_tier`, `all_tier_cost`,
`background_cost`, `skipped_usage_events`). Those are named keys with
declared meanings. The JSONL layout, filename and field names are free to
change without a deprecation cycle.

Two hardening changes came out of that exchange, both of which the log
needed regardless of who reads it:

- **Every line carries `v`** (`SCHEMA_VERSION`). A best-effort log needs a
  version MORE than a strict one does: because `record_usage` swallows its
  own failures, a reader meeting an unversioned schema change would see the
  difference as a *gap* rather than an error — silently wrong totals instead
  of a loud break. A line whose `v` is absent or unrecognised is counted as
  skipped, never coerced; guessing at an unknown schema would put a wrong
  number in front of someone budgeting with it.
- **No input can cause a silent drop.** The 4096-byte ceiling now sheds
  identity in stages (unbounded caller strings first, then bounded
  truncation of provider/model/tier) so the line fits by construction. The
  earlier version gave up and returned False on a pathological event, which
  would have been invisible: an append-only log has no sequence number, so a
  missing line is not detectable by any reader, and the claim "a partial
  total is never presented as a complete one" would have been false. Money
  is never shed; identity is.

The one loss that remains genuinely uncountable is an I/O failure — a full
disk, a permission error. That is inherent to a sink that must not raise
into a chat turn, and it is the reason for the contract below.

**What was NOT done, and is not hiding.** The log is best-effort telemetry,
not an audit trail: `record_usage` swallows every failure, because failing a
user's chat turn or killing a running agent over a bookkeeping write would
trade a real operation for an accounting one. Anyone who needs guaranteed
capture must not build on this seam without changing that contract first.

### Implementation map

| Piece | Location |
|---|---|
| Sink + query + rollup | `ppxai/usage_events.py` |
| Background tiers (`oneshot` + `task`) | `ppxai/engine/task_runner.py`, at the F4 usage block |
| Interactive tier (`chat`) | `ppxai/engine/session.py::save_usage_to_persistent_storage` |
| Cross-tier rollup in `/cost` | `ppxai/commands/tools.py::_display_global_usage_report` |
| Tests | `tests/test_usage_events.py` (16) |

**One tap covers both background tiers** because the FU unification made
every `/v1/oneshot` execute as a `kind=oneshot` registry run through
`build_task_runner`. The tier tag reads `RunMeta.kind`, so the two stay
distinguishable in the rollup without two call sites.

**The arithmetic trap, recorded because it is easy to get wrong later.**
Interactive spend is written to `usage.json` AND mirrored into the event
log. `/cost` therefore adds the log's *background* tiers to `usage.json`'s
total and deliberately excludes the log's `chat` bucket — summing both
totals would count every interactive token twice. `usage.json` remains the
base because it holds history from before the sink existed, which the log by
construction does not.
