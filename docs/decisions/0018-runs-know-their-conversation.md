# ADR 0018: Runs know their conversation; a result merges once

- **Status:** Implemented (2026-11-02, `feature/v1.19.5`). Accepted 2026-11-02 (owner).
- **Deciders:** owner (owns both ppxai and tai)
- **Target:** v1.19.5.
- **Related:** ADR 0011 (`/task` and `/run`, `execution.collect`, the plain merge),
  ADR 0017 (tai launches the server as its child), `tests/test_run_session_contract.py`
  (the fence).

## Context

tai, a terminal client, lists runs and collects their results into a
conversation. Two gaps stood in its way:

1. **A run had no idea which conversation launched it.** `RunMeta` carried
   no conversation field, and `GET /v1/agent/runs` filtered only by owner
   and `?kind=`. A client with several conversations could not show "the
   runs of this conversation".
2. **A merge went wherever the caller happened to be, any number of times.**
   `POST /sessions/merge-run-result` appended the run's task and result as
   a user/assistant pair to the caller's ACTIVE conversation. Load another
   conversation after launching a run, collect, and the result landed in
   the wrong one; collect twice and it landed twice. The TUIs did the same
   in-process (`InProcessTaskBackend.collect`).

Two things are called a "session" in this code and only one is meant here.
`X-Session-Id` names a server-side per-client engine slot
(`server/state.py`); the **conversation** name is
`engine.session.session_name` (`session_20261102_...`), which survives
restarts and changes on `/session new|load`. This ADR uses the second, and
the field is named `session_id` because that is the name tai asked for.

## Decision

1. **`RunMeta.session_id: str | None`** holds the conversation name. The
   server/engine stamps it from the launching client's active conversation:
   `POST /v1/agent/run` and `/v1/agent/task` read it from the engine slot
   named by `X-Session-Id` (no header, no stamp; an unknown slot id is a
   lookup only, never a new engine, and also no stamp), and the in-process
   `InProcessTaskBackend.launch` reads it from its session provider. There
   is **no body field**: the caller cannot claim another conversation. A raw
   /v1 call with no conversation context, and every `/v1/oneshot` run, gets
   `None`. A sub-agent inherits its parent's value in
   `AgentRunRegistry.start_run`. Old metas without the field load as `None`.
2. **`RunMeta.merged_at: float | None`** (epoch seconds) is set once, on the
   first successful merge.
3. **One guard, `AgentRunRegistry.claim_merge`**, serves both the HTTP route
   and the TUI's `merge_result`. It refuses with `already_merged` if
   `merged_at` is set, and with `session_mismatch` if the run has a
   `session_id` that is not the caller's active conversation. A run whose
   `session_id` is `None` still merges into the active conversation, but
   once. Nothing is ever appended to a conversation that is not loaded. The
   HTTP refusals are 409 with a **dict** `detail`:
   `{"code": "session_mismatch", "message", "run_session_id"}` and
   `{"code": "already_merged", "message", "merged_at"}`. The older 409s
   (no result) and the 403s keep plain-string details. The TUI path keeps
   its `(bool, str)` contract, with the refusal's message as the string.
4. **`GET /v1/agent/runs`** gains `?session=<conversation name>` and
   `?status=<status>`, combinable with `?kind=`. An unknown status is a 400,
   like an unknown kind; the valid set is `RUN_STATUSES` in
   `engine/agent_runs.py`.
5. **Clients.** Web and VSCode show the 409's `message` instead of
   "[object Object]" and treat `already_merged` as done. The TUIs go
   through the in-process path.
6. **The fence** is `tests/test_run_session_contract.py`: the two response
   fields, the two filters and both 409 shapes. A failure there is a
   deliberate contract break for tai.

`/v1/agent/*` stays officially unsealed. Only the fields and shapes the
fence pins are promised; everything else on it keeps evolving.

## Consequences

- A client can scope its run list to a conversation, and a result can no
  longer land in the wrong conversation or twice.
- The claim is recorded before the append and rolled back if the append
  raises, so a failed merge does not burn the run's one merge. The check is
  synchronous and loop-confined; there is no cross-process lock, so two
  servers sharing one runs directory could in theory both merge. Not
  addressed.
- A run launched from a conversation can only be collected while that
  conversation is loaded. Collecting elsewhere now fails with a message
  naming the run's conversation instead of polluting the active one. The
  run is still finalized (the ack succeeds); only the merge is refused.
- Runs from before this change have `session_id` `None` and keep the old
  "merge into the active conversation" behaviour, once.
- `RunMeta` gains two additive fields; nothing is removed or repurposed.
