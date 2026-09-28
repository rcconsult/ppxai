# The recurring tools-chat 400 is orphan `assistant.tool_calls`, not provider alternation

**TL;DR:** The 400 that keeps coming back on tools-enabled chats is the
**provider-agnostic** orphan `assistant.tool_calls` error (`"An assistant
message with 'tool_calls' must be followed by tool messages ...
tool_call_ids did not have response"`), which fires on OpenAI and any
OpenAI-compatible endpoint whenever an assistant message carrying
`tool_calls` reaches the wire without its matching `tool` replies. Do not
pattern-match it to a provider-specific alternation rule — see the dated
history below for why that used to be the wrong frame specifically for
Perplexity, which is now moot (ADR 0015 removed Perplexity as a chat
provider; its chat-completions API retired 2026-09-27).

**Verify with:**
`grep -n "def strip_orphan_tool_calls" ppxai/engine/session.py` (the
single cleanup pass), and
`grep -n "sanitize_outbound" ppxai/engine/chat.py` (the outbound guards
before the in-loop provider calls — chat.py calls the composed
`sanitize_outbound`, which runs the orphan strip plus the empty-assistant
strip; the bare `strip_orphan_tool_calls` name resolves only in
`session.py`). A live check against any current chat provider: send
`[{"role":"assistant","tool_calls":[...]}]` with no following `tool`
message — the 400 comes back on the missing tool reply, not on message
ordering.

## Why this trips people up

**History (Perplexity chat provider, removed 2026-09-27 by ADR 0015 —
kept for the pattern, not because it is still reachable):** the error was
*first* seen against Perplexity (`sonar`) years of release-notes ago, so
every recurrence got pattern-matched to "Perplexity alternation" and fixed
at the session-history alternation layer. Two things made that the wrong
frame, while Perplexity was still a chat provider:

1. **Perplexity had relaxed its old strict alternation rule.** Verified
   live across all four Sonar models (2026-07-13): consecutive user/user,
   consecutive assistant/assistant, assistant-first,
   `assistant(tool_calls)+tool` round-trips, and double-system all
   returned **200 OK**. Only `[user, tool]` (orphan tool) and
   `[assistant]`-alone still 400'd, and they returned a **generic**
   `{'message':'invalid request'}` — never the "alternate" wording. An
   empty-content assistant returned
   `{'message':'Message content was empty','type':'invalid_message'}`.
   This entire Sonar-specific behavior is no longer reachable through
   ppxai — Perplexity is search/grounding-only now (ADR 0014).

2. **The real 400 is OpenAI's, and provider-agnostic — still true today.**
   The verbatim
   `"tool_call_ids did not have response messages"` with
   `param: messages.[N].role` is OpenAI's `invalid_request_error`
   format, not Perplexity's. It bites whenever the transcript contains
   an `assistant.tool_calls` whose `tool` reply is missing — from a
   Ctrl-C / cancel between adding the assistant message and appending
   tool results, from the loop-detect user injection, or from an
   interrupted `/task` run.

## What's actually true

- The cleanup that removes orphans lives in **one** pure function,
  `strip_orphan_tool_calls(messages)` in `ppxai/engine/session.py`
  (module scope, so both the persistent history repair
  `SessionManager.validate_and_fix_alternation` and the chat tool-loop
  can call it).
- The `chat_with_tools` pre-flight runs the fix **once** before the
  `while iteration` loop. Iterations 2+ (and the empty-after-tools
  retry) send `session.get_messages()`; without an outbound orphan
  guard there, a mid-turn orphan reaches the provider. Those guards are
  in `ppxai/engine/chat.py` before the provider calls (grep above).
- Stripping a *tail* orphan can expose a trailing user that the model
  had already begun answering (via the removed `tool_calls`). That user
  prompt was sent — it is **not** an unsent draft — so the
  trailing-user drop must keep it (`orphan_exposed_trailing_user` guard
  in `session.py`), or the question silently vanishes and reappears on
  every retry (the recurring `DROPPED UNSENT USER PROMPT` log line).

Before adding an Nth alternation patch for any provider, confirm the
actual on-the-wire error string first — it is almost certainly the
orphan-tool_calls case above.

## Related

- `tests/test_orphan_toolcalls_regression.py` — pins both the
  prompt-preservation and mid-loop-guard behaviors.
- `docs/lessons/config-source-resolution.md` — reproducing live-provider
  behavior requires the *real* config/key, not the repo default.
