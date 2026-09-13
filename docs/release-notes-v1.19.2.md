# Release Notes — v1.19.2

> **Scope:** A bugfix-class follow-up to v1.19.1. A Gemini fleet refresh
> opened the branch; a live Windows web-UI trial of `gemini-3.8-flash`
> (2026-09-13) then surfaced five defects, four of them older than the
> branch. **No new features, no config-shape changes, no command renames.**
> The v1 API gateway (`POST /v1/oneshot`, bearer auth) and the
> `/v1/agent/*` surface are **byte-identical to v1.19.1** — ppxai-sre and
> any other consumer is unaffected.

## Branch

`feature/gemini-v1.19.2` (from master @ v1.19.1). All changes are
fix/test/docs/chore.

**Read "Changed behaviour" before upgrading** if you switch models while a
response is streaming: that now stops with a warning instead of silently
corrupting the transcript.

## Changed behaviour — a model or provider switch mid-response is refused

Switching models while a tool loop was still streaming stripped the
in-flight assistant turn from the history (`reset_for_model_switch`, the
normal context reset). The loop then appended its tool result to a history
whose matching assistant turn was gone, and Gemini answered **400** on its
turn-ordering rule about a second later. The existing outbound sanitizer
covers orphan `tool_calls` and empty assistants, not turn ordering, so it
did not catch this.

The switch is now **refused before anything is mutated**, and every client
tells you why:

| Surface | What you see |
|---|---|
| `/model …`, `/provider …` (all clients) | an error result: *"A response is still in progress. Wait for it to finish, or stop it, before switching the model."* |
| `POST /models`, `POST /providers` | **HTTP 409** with that text in `detail` |
| Textual TUI (`ppxaide`) | a warning toast |
| Web UI | the same error, and the dropdown snaps back to the model in use |
| VSCode | the server's reason in the failure message (the client used to report *Switched to …* on a failed switch) |

Wait for the response to finish, or stop it, then switch. Only the
context-resetting form of a switch is refused — the one every user-facing
switch takes. Session restore, the chat request's own `model` field and the
coding-mode toggle use the non-resetting form and are unaffected.
(`fc16ef32`)

## Fixed

- **Responses-wire tool loops were entirely broken.** The converter emitted
  the chat-completions shape (`role: tool`, `assistant.tool_calls`) on the
  OpenAI Responses wire, so every tool round trip on `gpt-5.6-terra`,
  `gpt-5.3-codex` and `gpt-5-pro` answered
  `400 Unknown parameter: 'input[N].tool_calls'`. It now emits
  `function_call` / `function_call_output` items. Verified end-to-end
  against the live API; the previous unit test had encoded the bug and was
  retargeted. (`f54f1954`)
- **Tool calls were being discarded on 15 shipped fact rows.**
  `parallel_tool_calls` was still at the conservative default on rows whose
  models emit several calls per turn, so ppxai executed one and silently
  dropped the rest — a multi-tool turn cost twice the round trips it
  needed. Every flip was measured live with a per-family control: the
  Gemini 3.x Flash line, Gemma 4, the GPT-5 / 4.1 / 4o lines, and
  `gpt-5.3-codex*` / `gpt-5-pro*` on the Responses wire. Two families
  stay serial on purpose, behind guard tests: `gemini-3.1-pro*` returned a
  malformed call on 2 of 3 parallel attempts, and `o3*` / `o3-mini*`
  returned exactly one call on every trial. (`b757d9c7`, `f74ce2af`)
- **Perplexity `sonar` only tool-calls on `/v1/responses`.** Tool calling
  is refused outright on chat-completions for that model. Its facts block
  in the shipped `ppxai-config.json` was partial, which let its
  `parallel_tool_calls` fall to `false` and discard the second of the two
  calls it emits; the block is now complete (ADR 0012 Q0d). Three other
  partial blocks (`gpt-5.5-pro`, `gpt-5.4-pro`, `gpt-5.3-codex`) are
  rescued by their shipped rows and are recorded rather than patched.
  (`f74ce2af`)
- **`/preview` answered "Internal Server Error" on Windows.** The iframe URL
  was built from a backslash path against a forward-slash working
  directory, so the prefix never matched and the whole native path was
  percent-encoded into the URL. Both sides are normalised now; the fix is
  fenced by source-text tests. (`3caf3ff1`)
- **The usage log silently lost events on Windows.** Concurrent appends
  went through the CRT's `O_APPEND`, which is seek-then-write rather than
  atomic; 29–79 of 200 concurrent writes vanished with `skipped_lines == 0`.
  Appends are serialised behind a lock. (`57e87604`)
- **Unhandled route errors now reach ppxai's own log.** An exception
  escaping a route went to uvicorn's stderr only; `~/.ppxai/logs` showed the
  request line and then nothing, which is why the `/preview` 500 had to be
  diagnosed from the browser console. The server now writes the traceback
  to its log and answers a generic JSON 500 (`error: internal_error`) that
  points at `/debug-log on`. The exception text stays off the wire.
  (`fc16ef32`)

## Model catalog

- **Gemini 3.6 / 3.7 / 3.8 Flash** have fact rows (`gemini-3.6-flash*`,
  `gemini-3.7-flash*`, `gemini-3.8-flash*`). Their tier is **inherited from
  the 3.5 line, not benchmarked**, and the rows say so. (`b757d9c7`)
- No GA Gemini 3.x Pro exists yet; `gemini-3.1-pro*` keeps its measured
  serial-only row (above).

## Known limitations

- The 409 refusal is proven by tests against the real engine facade, not
  by a live mid-stream switch on the installed binaries. A quick `/model`
  during a streaming reply in the web UI is the acceptance check.
- **Debt Item 73** (filed on this branch): `ppxai.rendering.textual_renderer`
  and `ppxai.tui.app` form an import cycle that only works when the app is
  imported first. `tests/test_preview_tui_renderer_gap.py` fails to collect
  when run alone, on master too; it passes inside the full suite. No
  runtime path is affected today.
- The example-config prices for the new Gemini rows are not part of this
  release; set them in your own `ppxai-config.json` if `/cost` matters.

## Verification

Full suite on Windows at `fc16ef32`: **5,830 passed, 32 skipped, 0 failed**
(the 32 are the known platform gates). The Responses-wire fix was
verified three ways: a shape check on the converter output, a hand-built
round trip on the live API, and ppxai's own converter output posted to the
live API. Every new guard was mutation-tested — removing the engine check,
the route mapping, the command catch, the `exc_info` flag or the handler
registration each fails its own test.

Local install verified on Windows: all four binaries and the VSIX report
1.19.2, the on-disk web UI matches the source tree by hash, and the
gateway smoke passes its perimeter checks.
