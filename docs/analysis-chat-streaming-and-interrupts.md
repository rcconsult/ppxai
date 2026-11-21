# Analysis: streaming and interrupts in `/chat`

- **Date:** 2026-11-22
- **Measured at:** `feature/v1.19.5` @ `0dc5d91c`. Line numbers are from that commit.
- **Asked by:** tai (tai-gui, a native ppxai client that uses `POST /chat` (SSE) with `{message}` only, and `POST /interrupt` to stop).
- **Status:** analysis only. Nothing here has been fixed or filed. The owner decides what to do.
- **Evidence key:** **verified** means read in the source, found in git history, or reproduced locally (see [How B was reproduced](#how-b-was-reproduced)). **Inferred** means it follows from the code but was not run.

tai reported two behaviours:

- **A.** With tools on, no `stream_chunk` arrives. The whole answer comes at once in `stream_end`. A 1,500-word answer showed nothing for about 18 s.
- **B.** A `POST /interrupt` sent before the first chunk doesn't stop the run.

Both reports are correct. B turned out to be several separate faults.

## A. With tools on, nothing streams

**Confirmed.** `EngineClient.chat()` hands a tool-enabled session to `chat_with_tools` (`engine/chat.py`). Every provider call there passes `stream=False`:

| Call | Line |
|---|---|
| main call | `engine/chat.py:886` |
| prompt-based fallback | `engine/chat.py:944` |
| retry | `engine/chat.py:1468` |

The comment at `engine/chat.py:1070` describes the effect, and `AGENT_INTERMEDIATE_PROSE` (R12 Option 1, v1.17.5) was the mitigation. The line numbers in tai's report have moved slightly since: 869, 926, 1449 and 1051 are now 886, 944, 1468 and 1070.

### 1. Why the tool loop uses `stream=False`

All verified:

- **The choice is as old as the tool loop.** `stream=False` was in the first tool loop, in commit `e82e35ea` ("feat: v1.8.0 - VS Code Extension & Enhanced UX", `engine/client.py` at the time). That loop was prompt-based: it put the tool prompt into a system message and parsed the reply as text. Neither the commit nor the code states a reason.
- **Why it stayed non-streaming.** Commit `4b83950f` (v1.11.7, "fix: Tool JSON no longer leaks to VSCode during streaming") explains it. The loop used to re-request the final answer with `stream=True`, and the model sometimes emitted a new tool call in that second reply. The tool call was then streamed to the client unparsed. The fix was to stop re-requesting and use the `stream=False` reply. That commit also updated `docs/BUG-tool-streaming-sse.md`, which said "`_chat_with_tools()` uses `stream=False` for provider calls". The file was later removed in `1767d43b` (stale-docs cleanup); `git show 4b83950f:docs/BUG-tool-streaming-sse.md` still shows it.
- **The written rationale** is in `docs/archive/TODO-file-upload.md`, item R12 (around lines 1446–1520). At each iteration the engine must decide between "tool calls present, so run them and loop" and "final answer". That decision needs the complete reply and the complete tool-call list. Streaming would need a state machine in each provider adapter to separate prose from tool calls. R12 lists three options:
  - Option 1, `AGENT_INTERMEDIATE_PROSE`, shipped in v1.17.5 (`7f611102`).
  - Option 3, a fully streaming tool loop, was deferred to "v1.18.x" and has not been built.

How the candidate reasons fare:

| Candidate reason | Verdict |
|---|---|
| The branch decision needs the full reply and the tool-call list | **Stated** (R12) |
| Prompt-based parsing needs the full text | **Stated** by the original design, and by the v1.11.7 leak |
| Tool JSON is stripped from the text (`strip_tool_json_from_text`, `engine/chat.py:1065`) | **Depends on it.** The strip runs after the reply is complete |
| Empty-response retry and prompt-based fallback | **Inferred.** Both work on the whole reply, but nothing cites them as a cause |
| Native tool calls only come complete | **No.** Providers already build tool calls from streamed fragments (see 2). The missing piece is in the engine, not in the providers |
| `ResponseValidator` hallucination check | No evidence it was a reason |
| Something provider-specific | Nothing found |

A later side effect, not a cause: `/task` relies on the non-streaming path because that path offloads the SDK call with `asyncio.to_thread`. See `docs/debt-inventory.md` and `docs/agent-platform-call-graphs.md:800`.

### 2. Per provider: does `chat(..., stream=True, tools=...)` work today?

Verified by reading the code, not by running it:

| Provider | Streams text with tools? | Native tool calls | Event shape |
|---|---|---|---|
| `openai_compat` | Yes, tools passed in both branches | Built from deltas by index. All `TOOL_CALL` events come **after** the last text chunk | `{tool, arguments, native: True, tool_call_id}`. `STREAM_END` metadata has `usage` and `tool_calls` |
| `openai_native`, Chat Completions | Yes | Same as `openai_compat` | Same |
| `openai_native`, Responses (`wire/responses.py`) | Yes | Built from `function_call_arguments` deltas, emitted after the stream. Bad JSON silently becomes `{}` | Same keys; tool names un-aliased |
| `gemini` | Yes | `function_call` parts collected, emitted after the stream | Same keys, plus `thought_signature`. Usage and grounding arrive on the last chunk only |
| `anthropic` | Always streams; the `stream` argument is ignored | Emitted from `get_final_message()` after the stream | **Mismatched.** `TOOL_CALL` is `{id, name, arguments}`, with no `tool`, `native` or `tool_call_id`. `STREAM_END` data is a dict, not a string |

Points to note:

- **No provider interleaves tool calls with text.** In native tool mode the text always comes first and the tool calls come last.
- **Anthropic's tool calls don't fit the engine loop.** The engine reads `tc["tool"]` and `tc["tool_call_id"]` (`engine/chat.py` around 995 and 1226). That is a separate bug (inferred, not run). The Anthropic provider ships untested by owner decision.
- **Two streaming branches block the server's event loop.** `openai_compat` (`providers/openai_compat.py:325`) and `gemini` (`providers/gemini.py:365–375`) iterate a synchronous SDK iterator inside an `async` generator, with no thread hop. Each wait for the next chunk blocks every request the server is handling (see B). Their non-streaming branches use `asyncio.to_thread`, which is why the tool loop doesn't show the problem today.
- **Tests that pin streaming with tools:**
  - `tests/test_openai_native.py` (around lines 362 and 611)
  - `tests/test_gemini_native_tool_loop.py:107`
  - No engine-level streaming tool-loop test exists.

### 3. What would break if the tool loop streamed

- **Prompt-based tool mode.** The tool call is JSON inside the text, so streaming the text leaks it to clients. That is the v1.11.7 bug again. Buffering until the JSON is ruled out amounts to not streaming.
- **Native tool mode.** The text comes first and tool calls last, so a tool iteration's streamed text is the model's prose before the tool call. That is exactly what `AGENT_INTERMEDIATE_PROSE` carries today, so the event becomes redundant there.
- **JSON stripping** (`engine/chat.py:1065`) and the **`ResponseValidator`** work on the complete reply. Text a client has already shown could later be changed or flagged.
- **The empty-response retry and the fallback** re-ask after a reply is judged empty or unusable. If streamed, the user would see a reply that is then thrown away.
- **Usage accounting** needs usage from the streaming response. `openai_compat` asks for it with `stream_options include_usage` and has a fallback without it. `openai_native`'s Chat Completions path has no such fallback.
- **Interrupts.** The check at `engine/chat.py:927–928` assumes a blocking call. A streaming loop would check per chunk, which is better.
- **Event loop.** Turning `stream=True` on in the tool loop without first moving the synchronous iterators to a thread would freeze the whole server, including `/task` runs, for the length of every reply.
- **Tests** that pin "no `STREAM_CHUNK` in tool mode" would need updating.

### 4. Options

| Option | Cost | Risk |
|---|---|---|
| (a) Stream every iteration, buffering text until it's known not to be a tool call | High: a per-provider state machine (R12's "60–100 lines per adapter") | Medium. Gains little in prompt-based mode, where the buffer holds everything |
| (b) Stream only in native tool mode, forwarding text chunks as they come | Moderate | Low, if the event-loop fix comes first. In native mode text always precedes tool calls, so the engine learns at stream end whether the text was prose or the answer |
| (c) Keep non-streaming, then re-ask the final answer with `stream=True` | Low code | High: brings back the v1.11.7 leak, and pays for the answer twice |
| (d) Leave it, and document in `docs/api-gateway.md` that `stream_chunk` doesn't happen with tools on | Trivial | None. Clients wait longer |

**Recommendation: (b), with two prerequisites.**

1. Move the synchronous stream iterators in `openai_compat` and `gemini` off the event loop.
2. Normalise Anthropic's `TOOL_CALL` and `STREAM_END` shapes.

Prompt-based mode stays non-streaming. (d) is a reasonable stopgap until then.

### 5. Client impact

Verified:

- **Web** (`web/app.js:2344`) and **VSCode** (`media/webview/main.js:1092`) replace the bubble's content with the `STREAM_END` text. Streamed chunks in tool mode wouldn't hurt them, since the final text wins.
- **Rich** never shows streaming at all. It collects chunks silently and renders once at the end (`rich/event_handler.py:449–461`).
- **ppxaide (Textual)** used to prefer the text it accumulated from chunks. Since `0dc5d91c` it prefers the `STREAM_END` text, like the others. The change was made for ADR 0019 step 6, where Gemini's `[n]` markers exist only in the final text.
- **`AGENT_INTERMEDIATE_PROSE`** is rendered by the two terminal clients: ppxaide (`tui/stream_handler.py:496`) and Rich (`rich/event_handler.py:272`, `:359`). Grepping the web and VSCode sources finds nothing that renders it, so those two stay silent between tool bubbles.

No client relies on there being no `stream_chunk` in tool mode. With (b), the web and VSCode bubbles would show the prose and then be replaced by the final answer at `stream_end`. That is acceptable, but it should be checked with a real tool loop.

## B. An interrupt before the first chunk doesn't stop the run

### 6. Where the interrupt is honoured, and why it doesn't end the run

- **`POST /interrupt` only sets a flag.** It calls `EngineClient.interrupt_stream()` (`engine/client.py:655`), which sets `_interrupted` and `cancel_requested` and kills tool subprocesses. It cancels nothing else.
- **The flag is read only when the provider yields.** With tools off, `engine/chat.py:357` checks it on each event the provider yields. In the tool loop, it is checked at the top of each iteration (`:776`) and after the provider returns (`:927–928`). A provider call that hasn't yielded yet is never cancelled, so the run ends only when the first chunk arrives. **Verified.**
- **With a blocking stream, `/interrupt` itself waits.** In `openai_compat` and `gemini` streaming, the whole server waits for the provider's next chunk. In the reproduction, `POST /interrupt` took **5.63 s** to answer with a blocking fake provider, against **0.02 s** with an async one. **Verified.**
- **The flag belongs to the engine, not to the run.** Every new `chat()` resets it (`engine/client.py:1100`). A second `/chat` on the session therefore wipes an interrupt that the first run has not yet seen. **Verified.**
- **Can the call be cancelled?**
  - Cancelling the asyncio task running the engine step works at once for the `asyncio.to_thread` paths. The background thread finishes on its own and its result is discarded.
  - For the synchronous streaming iterators it doesn't work until they run in a thread, because nothing in them awaits.
  - A run-scoped cancel (a token per run, with `/interrupt` cancelling that run's task) would end the run at once with "Interrupted by user" and `[DONE]`. Inferred.
- **`ModelSwitchInFlightError` from `/chat` is a 500.** **Verified, reproduced.** `/chat` calls `set_provider` at `server/routes/chat.py:383` without handling the error. `/providers` and `/models` map it to 409 (`server/routes/providers.py:62`, `:102`). The guard (`engine/provider_ops.py:161`) also refuses when the named provider is the current one. So `/chat` should map the error to 409, and the guard could skip an unchanged provider.

### 7. The lock and history after an interrupt

- **The chat lock never covers the stream.** **Verified, reproduced.** `/chat` returns its `StreamingResponse` from inside `async with s.lock:` (`server/routes/chat.py:377`, return at `:456`). Leaving that block releases the lock before Starlette starts iterating the generator. The comment "Generator that streams events while holding the lock" (`:447`) is wrong. This happens on every request, not only after a disconnect. In the reproduction a second `/chat` took the lock 0.02 s after it started, while the first run was still waiting for its provider. `/coding_task` has the same pattern (`:482`, `:498`).
- **A client disconnect doesn't stop the engine run.** **Verified, reproduced.**
  - uvicorn 0.38 announces ASGI spec 2.3. Starlette 0.50's `StreamingResponse` then runs its own `listen_for_disconnect` and cancels the response task when the client goes. That cancels `sse_event_generator` where it sits.
  - The engine's pending step was started separately, as `asyncio.ensure_future(engine_iter.__anext__())` (`server/streaming.py`). Nothing cancels that task, so the run continues until its next event and then stays abandoned, half-finished.
  - In the reproduction the client disconnected at 1.97 s and the provider still produced its first chunk at 6.97 s.
  - The generator's own disconnect check (`request.is_disconnected()`, "B11") probably never fires, because Starlette's listener consumes the disconnect message first. Inferred, consistent with the reproduction.
  - The generator's closing code (auto-save, `[DONE]`) does not run either. A "Task exception was never retrieved: StopAsyncIteration" warning is logged for the pending task.
- **A late run does not write its answer into history, but it still interferes.** Verified, reproduced.
  - The abandoned run is never resumed, so its answer is never stored.
  - Its user message is left without an answer, and the next turn's pre-send alternation fix removes it.
  - When the abandoned generator is cleaned up, its `finally` sets `is_streaming=False`, even if a newer run on the session is still going. In the reproduction `is_streaming` turned `False` at 7.87 s while the second run finished at 8.95 s.
  - In tool mode an abandoned run keeps executing tools until it reaches its next event. Inferred.
- **What `is_streaming` reports in that window:** `True` from the start of the abandoned run until its generator is cleaned up. After that it can be wrong for a run that is still live, as above. tai's "1–2 minutes" fits a slow first chunk or Gemini's long thinking before the first chunk. That part is inferred: the reproduction used 6 s.
- **Zombie handling is not involved.** `AGENT_ZOMBIE` (`engine/chat.py:1303–1315`) is a circuit breaker for consecutive failed tool iterations. It has nothing to do with interrupts or disconnects.

### Fixes to consider for B (not decided)

1. **Hold the lock for the stream's lifetime:** take it inside the generator, released in its `finally`. Then decide whether a second `/chat` waits, or gets 409 while a run is in flight.
2. **Clean up the SSE generator** in `try/finally`: cancel `pending_next` and `aclose()` the engine generator. This stops a disconnected run at once, makes its `finally` run on time, and lets the closing code run.
3. **Make interrupts per run:** a token per run, with `/interrupt` cancelling that run's task. Then a new `chat()` can't wipe an interrupt, and a stale run's `finally` can't clear another run's `is_streaming`.
4. **Map `ModelSwitchInFlightError` to 409** in `/chat` and `/coding_task`, and skip the guard when the provider or model is unchanged.
5. **Move the synchronous stream iterators to a thread** (`openai_compat`, `gemini`), so `/interrupt` and every other request stay responsive while a provider streams. This is also prerequisite 1 for option A(b).

## How B was reproduced

A throwaway script ran the real server app (`ppxai.server.http.app`) under uvicorn on `127.0.0.1` in the same process:

- **Fake provider.** Every provider was replaced by a fake that waits 6 s before its first chunk. In `async` mode it uses `await asyncio.sleep`; in `block` mode it uses `time.sleep`, which behaves like the synchronous SDK iterators.
- **No real state or spend.** `HOME` pointed at a temporary directory, the repo's example config was used, and no request left the machine.
- **The sequence:**
  1. Open `/chat` over a raw socket and close it after 1 s.
  2. `POST /interrupt` at 0.5 s.
  3. Send a `/chat` that names the current provider.
  4. Send a second `/chat` with `{message}` only.
  5. Log `is_streaming` and the session's messages every second.

Results, with times since start:

| | `async` fake | `block` fake |
|---|---|---|
| `POST /interrupt` answered after | 0.02 s | 5.63 s |
| `/chat` naming the current provider during the run | HTTP 500 | HTTP 500 |
| Second `/chat` took the lock after | 0.02 s, run one still in flight | 0.02 s |
| Run one's provider after the 1.97 s disconnect | still produced chunk 0 at 6.97 s | still produced chunk 0 at 6.99 s |
| `is_streaming` while run two was live | `False` at 7.87 s (run two ended at 8.95 s) | stayed `True` |
| Final history | `user: two`, `assistant: answer to two` | same |

The script is not kept in the repo. Re-create it from this description if the fixes are taken up; it needs no API keys.
