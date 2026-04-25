# v1.18.2 — Agent loop HTTP-streaming unification

**Status:** Deferred from v1.18.1.
**Trigger to revisit:** when web/VSCode users complain about
divergent agent UX, OR when ADRs/agents work needs server-side
agent loop control (e.g. cross-client agent state machine).

## Background

v1.18.1's principle was "every command flows through the
factory's `POST /command/<name>`". For most commands this
worked cleanly. **`/agent <task>` is the exception.**

The factory's `handle_agent` runs the autonomous loop in-process:

```python
async def run_agent_loop():
    iteration = 0
    while iteration < max_iterations and not task_complete:
        iteration += 1
        async for event in context.engine_client.chat(prompt, stream=True):
            await event_handler.handle_event(event)
        ...

full_output, summary, success = asyncio.run(run_agent_loop())
return AIResponseResult(message=summary, content=full_output, ...)
```

This works for the TUI (in-process call, console rendering, hot
loop blocks the user's prompt). It does NOT work for HTTP clients:

1. **Blocking** — the HTTP request holds open while the agent
   runs (potentially many minutes). Browsers / proxies time out.
2. **Console-rendered** — `console.print` calls in the loop
   write to the server's stdout, not to a client.
3. **`asyncio.run` inside a route handler** fights FastAPI's
   already-running event loop.
4. **No iteration progress** — the user only sees the final
   `AIResponseResult` after the full loop, not per-iteration
   updates.

So in v1.18.1:
- TUI: factory `handle_agent` works (in-process).
- VSCode: bypasses factory; chatPanel.ts has its own agent loop
  using `_backend.chat`. Validation + UI duplicated client-side.
- Web: bypasses factory; `streamChat('/agent <task>')` ships to
  `/chat` which is now gated by `validate_agent_task` (v1.18.1
  step 5b.1) but the loop itself runs in `/chat`'s normal path.

This is a real divergence the v1.18.1 plan accepts as scope
sacrifice. The validation gate closes the safety hole; the loop
unification stays divergent until v1.18.2.

## Scope when picked up

Make the factory `handle_agent` HTTP-streaming compatible. Three
sub-pieces:

### 1. Factory handler emits SSE events for iteration progress

```python
async def handle_agent(context, args):
    ...
    if isinstance(context, ServerCommandContext):
        # HTTP path: don't asyncio.run, don't console.print.
        # Emit AGENT_RUN_START / AGENT_BEAT / AGENT_RUN_COMPLETE
        # via engine.enqueue_event so the SSE side-channel carries
        # them. Return a NotificationResult immediately; the loop
        # runs as a background task.
        asyncio.create_task(_run_agent_async(context, task, ...))
        return NotificationResult(
            status=ResultStatus.INFO,
            message=f"🤖 Agent started: {task}",
        )
    else:
        # TUI in-process path: existing console-rendered loop.
        ...
```

### 2. AGENT_BEAT event lifecycle (already partially exists in v1.18.0!)

`ppxai/engine/types.py::EventType.AGENT_BEAT` and friends exist.
The Phase 5 work just needs to:
- Make `chat_with_tools` emit them per iteration when called from
  factory's `handle_agent` (currently only the chat tool loop emits
  these, not the explicit /agent flow).
- Verify clients render them — Rich, Textual, web, VSCode all
  have AGENT_BEAT handlers per `tests/test_agent_beat_cross_client_parity.py`.

### 3. Drop client-side agent loops

Once the factory path streams progress correctly:
- VSCode chatPanel.ts deletes `handleAgentCommand` and the
  in-class iteration loop (~150 LoC).
- Web's `_dispatchAgent` simplifies to factory dispatch like
  every other command — no special-case streaming.
- The factory `handle_agent` is the single source.

Estimated cost: ~250 LoC removed (client-side loops) +
~100 LoC added (HTTP-aware factory branch). Net negative.

## Why deferred

v1.18.1 closes the **safety gap** (agent task validation) without
needing to refactor the loop. Two clients keep their bespoke
loops in v1.18.1, but that's pre-existing behavior — not a
regression.

The loop unification is meaningful work:
- New error paths (background task fails after returning OK)
- Cancellation / interrupt protocol over SSE
- Test infrastructure for "did the engine actually emit per-iter
  events?"

Worth its own milestone with focused review.

## Acceptance criteria when picked up

- [ ] `POST /command/agent` with a valid task returns immediately
      and starts a background loop.
- [ ] AGENT_RUN_START / AGENT_BEAT / AGENT_RUN_COMPLETE events
      flow on the SSE stream during the loop.
- [ ] Per-iteration tool calls are visible to the client in
      real-time (not buffered until completion).
- [ ] Esc / SIGINT interrupts the running loop (cancellation
      protocol works over HTTP).
- [ ] VSCode's `handleAgentCommand` deleted; web's
      `_dispatchAgent` simplified to standard factory dispatch.
- [ ] Cross-client parity test extended with HTTP-path coverage.
