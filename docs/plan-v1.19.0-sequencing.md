# v1.19.0 iteration — sequencing plan

**Branch:** `feature/v1.19.0` (off `master` @ a1a8cc35, post-v1.18.8)
**Created:** 2026-06-15
**Status:** Active — iteration tracker. This is the source of truth for
*what order* v1.19.x work happens in. ROADMAP.md describes the full
v1.19.x scope; this doc says what THIS iteration does first and what it
explicitly defers.

## Theme

Land **agent-platform Stage 2** (ADR 0003) — the ppxai-sre-blocking
substrate. Everything else v1.19.x-tagged is sequenced *after* it.

## Active this iteration (in order)

Per ROADMAP "Agent platform Stage 2 + v1 gateway extensions" and ADR
0003's MVP build order. Keystone first.

1. **Phase 1 — ADR 0003 Stage 2 primitives** (`feat/agent-platform-stage-2`)
   `engine/agent_runs.py` `AgentRunRegistry` (keystone) + the
   `~/.ppxai/runs/<run_id>/agent-<n>/` namespace; `POST /v1/agent/run`,
   `GET /v1/agent/runs[/<id>]`, `/events` SSE, `/cancel`, `/terminate`;
   `run_id`/`parent_run_id` on `AGENT_RUN_START`; `AGENT_SERVICE_DOWN`.
   ~7-9 d.
2. **Phase 2 — sub-agent primitive** (`spawn_subagent`, consent-gated).
   ~3-4 d.
3. **Phase 3 — run persistence + recovery** (`state.json` checkpoint;
   *conditional* resume on restart). Pairs with ADR 0003 open-decision #5
   (RESOLVED 2026-06-15: checkpoint unconditionally, resume conditionally
   — only if the checkpoint is conclusive AND artifacts don't already
   capture the work; else stays `INTERRUPTED`). Needs a
   resumability/conclusiveness flag in `state.json`. ~2-3 d.
4. **Phase 4 — resource budgets** (`meta.json` token/time/iter caps
   enforced at `chat_with_tools`). ~2 d.
5. **Phase 5 — network policy enforcement** (per-run egress allowlist,
   fail-closed, typed `NETWORK_POLICY_*` events). MVP ship-gate per ADR
   0003 §3 tier-c. ~4-6 d. (`feat/network-policy-enforcement`)
6. **Phase 7 — `/v1/tokens` registry** (should-have; pluggable resolver
   from day one). ~4-6 d. (`feat/v1-tokens-registry`)

### Design decisions (all RESOLVED 2026-06-15 — no open blockers)

- **Q-A (ADR #1, outer loop): A1 — eliminate it.** A run is one
  `chat_with_tools` invocation; no outer continuation loop, no
  `TASK_COMPLETE:` marker. Accepted the small risk (a weak model stopping
  mid-task) for one-loop simplicity. Deletes the ~150 LoC VSCode replica.
  Revisit A2 (server-side re-prompt) only if a specific model regresses —
  not speculatively.
- **Q-D (ADR #3, EngineClient lifecycle): D1 — new EngineClient per
  sub-agent.** Isolation first; optimize later only if profiling shows
  construction is a real bottleneck under fan-out. No benchmark gate.
- **ADR #5 (budget interrupt): conditional resume.** Checkpoint
  unconditionally; resume only if conclusive + work not already in
  artifacts (see Phase 3).

## Deferred — AFTER Stage 2 lands (NOT this iteration's active set)

User decision 2026-06-15:

- **debt Item 3 (k8s session-manager FULL test suite)** — quick-pass DONE
  + merged. Full suite waits until the sub-agent pod sandbox (Phase 1-2)
  exists, so the tests validate the actual sub-agent-in-a-pod security
  boundary end-to-end, not the session-manager in isolation. = ROADMAP
  Phase 6.
- **debt Item 21 (`chat_with_tools` decomposition)** — postponed. Stage 2
  adds run/budget/sub-agent code into this exact function; decompose after
  the shape settles, not before.
- **ROADMAP track B — Anthropic Provider** — deferred; do after Stage 2.
  `feat/anthropic-provider` stays reserved.
- **ROADMAP track C — Prompt Analyzer + Adaptive Routing** — deferred;
  already "(Future)". After Stage 2.

## Deferred to v1.20.x (unchanged from ROADMAP)

Credential broker, `CONSENT_DECISION` event (A1), pre-tool-call hook
(A2), native-provider `oneshot()` parity, rate limiting, OIDC/JWT,
streaming `/v1/oneshot`.

## Also v1.19.x-tagged but independent of Stage 2 (schedule opportunistically)

- **debt Item 29** — `engine.completion` layer inversion (ADR 0007).
  ~1-1.5 d, seam already seeded.
- **debt Item 33** — command-layer `console.print` sweep.
- **debt Item 34** — add `python-docx` to `[data]` extra (small).
- **debt Item 35** — pluggable persistence channel (likely ADR 0008);
  `AgentRunRegistry` from Phase 1 is its first consumer, so it naturally
  follows Phase 1.
