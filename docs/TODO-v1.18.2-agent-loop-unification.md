# v1.18.2 — Agent loop HTTP-streaming unification

**Status:** Deferred from v1.18.1. **Re-scoped 2026-05-03** —
investigation shows the original premise was partly outdated.
See "Refined scope" section below. **Superseded by**
[ADR 0003 — Agent platform architecture](decisions/0003-agent-platform-architecture.md),
which folds this refactor into the v1.19.x agent-platform plan.
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

## Refined scope after 2026-05-03 investigation

The original "Background" section above was written before v1.18.0
shipped `EventType.AGENT_BEAT` and before v1.18.1 added the
`/chat` route's `validate_agent_task` gate. Code state today:

### What's already in place (premise correction)

1. **AGENT_RUN_START / AGENT_BEAT / AGENT_RUN_COMPLETE already fire**
   from `engine/chat.py` (lines 559, 875, 1066, 1138). They're
   emitted by `chat_with_tools` per tool-iteration. AppState
   subscribes; web (`web/app.js`), VSCode (`chatPanel.ts`), and
   ppxaide (`tui/event_handler.py`) all render them. The original
   plan's step 2 ("make `chat_with_tools` emit them per iteration")
   is **done** — but those events track the **inner** tool loop
   inside ONE `chat()` call, not the outer multi-iteration
   continuation loop in `handle_agent`.

2. **Web does NOT run a client-side loop.** `_dispatchAgent`
   (`web/shared/command-dispatcher.js`) calls
   `app.streamChat('/agent <task>')` → hits `POST /chat` → the
   gate at `server/routes/chat.py:206` runs `validate_agent_task`
   → if it passes, the message goes through engine's normal chat
   path. There IS no outer iteration loop on the web client.
   AGENT_BEAT events stream over SSE from `chat_with_tools`'s
   inner tool loop. This client is already aligned.

3. **VSCode IS the actual divergence.**
   `chatPanel.ts::handleAgentCommand` (lines 1143–1279) runs the
   same multi-iteration outer loop the TUI factory does — for
   `iteration in 1..maxIterations`, build a continuation prompt,
   `_backend.chat(prompt)`, watch for `TASK_COMPLETE:` in the
   accumulated response. ~150 LoC of client-side iteration logic.

4. **TUI factory `handle_agent` runs the outer loop in-process**
   via `asyncio.run(run_agent_loop())`. Per iteration it builds a
   continuation prompt, calls `engine_client.chat(prompt)` (which
   internally runs `chat_with_tools` and emits AGENT_BEAT events),
   then text-matches `TASK_COMPLETE:` to decide whether to continue.

### The two design questions to answer FIRST

The outer multi-iteration continuation loop is meta-orchestration
on top of `chat_with_tools`'s inner tool loop. They aren't the
same thing:

- **Inner loop** (`chat_with_tools`) — model calls tools, sees
  results, calls more tools, eventually gives a final text
  response. Stops when the model stops calling tools.
- **Outer loop** (`handle_agent` / `handleAgentCommand`) — if the
  model's final text doesn't say `TASK_COMPLETE:`, send a
  continuation prompt and run another inner loop. Up to
  `max_iterations`.

**Question A:** Do we keep the outer loop?
- Keeping it gives multi-pass agent behavior (model goes "I did X,
  let me also Y" without saying TASK_COMPLETE).
- Eliminating it means relying solely on the inner tool loop —
  the model finishes one chat turn, you're done. Behavioral
  change for TUI users.

**Question B:** If we keep it, where does it run?
- Server-side as a background task: matches the TODO's plan,
  requires cancellation/lifecycle management, BUT eliminates the
  client divergence.
- Client-side per-client: status quo. VSCode + TUI each run their
  own. Two implementations to maintain.

### Recommended path forward

1. **Phase A (small, high-leverage):** delete VSCode's
   `handleAgentCommand` and route `/agent <task>` through
   `streamChat('/agent <task>')` exactly like web does. The
   `/chat` route's existing validate_agent_task gate covers the
   safety check. This drops ~150 LoC and aligns VSCode with web —
   the user gets the same single-iteration behavior web users
   already get. The downside is VSCode users lose the outer
   continuation loop (the model needs to do everything in one
   chat turn, OR keep calling tools without stopping).

2. **Phase B (bigger, separate decision):** if the outer loop is
   actually load-bearing (Question A), reimplement it server-side
   as a background task so TUI + web + VSCode all get it. This is
   the original TODO's plan. Defer until we have user signal that
   the outer loop is missed.

3. **Phase C:** drop `validate_agent_task`'s side-effect-only
   handling once `prompt_text` (v1.18.3) gets enough field use to
   confirm the auto-resume UX.

The real architectural question is Question A. If the answer is
"the outer loop is overkill, modern models do enough in one turn",
then Phase A is the whole fix and we can also strip the outer
loop from `handle_agent` for symmetry. If the answer is "the outer
loop is genuinely valuable", we need the bigger Phase B refactor.

Pick a direction before implementing.
