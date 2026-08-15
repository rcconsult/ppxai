# Handoff — `session_provider` is the CONVERSATION seam, not the result seam

**Written:** 2026-08-10, from the Windows host, on `bugfix/v1.19.1`.
**For:** the ppxai-sre session and anyone building a headless embedder.
**Protocol:** `docs/handoff-seam-watcher.md`.

New surface on `engine/task_backend.py` that was **not** in the A4 design, so
it gets the same stop-before-build treatment the `build_task_runner`
extraction got. Reviewed by the consumer session, whose correction is the
substance of this note.

---

## The correction, first, because it is the whole point

I described `session_provider` to the consumer as *"the seam where your
PolicyEngine-gated results would land."* **That is wrong**, and building to
that reading produces the wrong thing. The consumer caught it:

> ppxai-sre's autonomous agent has no conversation. It's scheduled, headless,
> set-and-forget. There is no active session, no transcript anyone is reading,
> and a user/assistant pair is not a meaningful destination for a run result.

Look at what the seam actually feeds — `merge_result` does exactly one thing:

```python
session.add_message(Message(role="user", content=meta.task))
session.add_message(Message(role="assistant", content=result))
```

It injects a **conversation turn**. It exists because U4 says a collected run
enters the conversation, the HTTP clients get that via
`POST /sessions/merge-run-result`, and an in-process client has no request to
hang it off. The bug it fixed was TUI sessions being message-less, which broke
session restore.

**So: `session_provider` is the third integration point for INTERACTIVE
embedders — TUI, web, VSCode. It is not an integration point for headless
ones.** ppxai-sre's results belong in its `AuditLogger` JSONL and its
suggestions sink: durable, queryable, and not shaped like a chat turn.

If this ever gets written down as "Path D's result destination", someone
builds an agent that merges audit records into a phantom session. That is the
specific mistake this file exists to prevent.

## Nothing is asked of a headless consumer

The parameter is optional and fails soft in the right direction:

```python
if self._session_provider is None:
    return False, "no session to merge into"
```

`collect()` then reports `"collected (not merged: no session to merge into)"`
— the run is **finalized**, the result is on the run record, and the caller is
**told**. A headless consumer passes nothing and everything works. No ask, no
migration.

## What the surface actually is

| | |
|---|---|
| `InProcessTaskBackend(registry=None, session_provider=None)` | usable standalone; inject your own registry (the three-method `TaskRunRegistry` surface) |
| `configure_task_backend(session_provider=None, on_change=None)` | the **process-wide singleton** composition root — layers `sweep_orphans()` and the AppState mirror hook |
| `merge_result(run_id)` | in-process equivalent of `POST /sessions/merge-run-result` |
| `auto_merge_if_configured(run_id)` | the `execution.collect="auto"` path, mirroring web's `_autoMergeIfConfigured` |

`configure_task_backend` is **opt-in**, deliberately. A consumer that
constructs its own backend never touches the singleton, never gets the orphan
sweep, and never gets an AppState hook it has no AppState for. The composition
root is a choice, not a tax.

## The pair-or-nothing rule, since it looks like a detail and isn't

`merge_result` appends **both** messages or neither.
`validate_and_fix_alternation` drops a leading assistant message and collapses
same-role neighbours, so a lone merged message of either role can silently
vanish from the next provider request. Caught live in the U4 trial: the model
answered *"no passphrase appeared"* while the merge sat dropped.

Irrelevant to a headless consumer, load-bearing for anyone who does use it.

## If a genuinely embedder-shaped result seam is ever wanted

**Not built, and deliberately not.** Recorded because the consumer proposed
the right shape and it should not be re-derived:

> the shape that serves both is not "give me your session" — that presumes a
> conversation — it's "here is a finished result, do what you like with it":
> an `on_result(run_id, meta, result)` callback.

The TUI's implementation would append to the session; ppxai-sre's would write
an audit record. That inverts the dependency, so ppxai needs no concept of
"session" to serve a headless consumer.

`session_provider` is today a strictly narrower special case of that, and it
is fine as such. Build the general form when a real requirement arrives, not
speculatively — the same rule that kept `extra_tools` out of the wire.

## Process note, on my side of the seam

The consumer observed that my confidence level was steering their review: they
tested the egress ceiling **because I labelled it a belief**, and passed the
Gemini grounding claim **because I stated it as fact** — and the fact was
wrong (`f72c10c7` asserted "Gemini refuses the combination" without my ever
having sent that request; corrected in `23d8695a`).

That is a bad control loop, and the fix is mine: **a claim about external API
behaviour that I have not executed gets marked unverified in the commit
message**, not only when I happen to feel unsure. Their scrutiny should key
off whether something *was tested*, not off how certain I sounded.
