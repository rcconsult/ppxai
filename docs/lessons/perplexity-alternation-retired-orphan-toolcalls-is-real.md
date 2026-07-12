# The recurring tools-chat 400 is orphan `assistant.tool_calls`, not Perplexity alternation

**TL;DR:** Perplexity Sonar has **relaxed** its old strict
user/assistant alternation rule — consecutive same-role messages,
assistant-first, and tool round-trips are all accepted (200) as of
2026-07-13. The 400 that keeps coming back on tools-enabled chats is
the **provider-agnostic** orphan `assistant.tool_calls` error
(`"An assistant message with 'tool_calls' must be followed by tool
messages ... tool_call_ids did not have response"`), which fires on
OpenAI and any OpenAI-compatible endpoint whenever an assistant message
carrying `tool_calls` reaches the wire without its matching `tool`
replies.

**Verify with:**
`grep -n "def strip_orphan_tool_calls" ppxai/engine/session.py` (the
single cleanup pass), and
`grep -n "strip_orphan_tool_calls" ppxai/engine/chat.py` (the outbound
guards before the in-loop provider calls). Live-check the alternation
claim: send `[{"role":"user"},{"role":"user"}]` to `sonar` — it returns
200, not the historical "messages must alternate" 400.

## Why this trips people up

The error was *first* seen against Perplexity (`sonar`) years of
release-notes ago, so every recurrence gets pattern-matched to
"Perplexity alternation" and fixed at the session-history alternation
layer. Two things make that the wrong frame:

1. **Perplexity relaxed the rule.** Verified live across all four Sonar
   models (2026-07-13): consecutive user/user, consecutive
   assistant/assistant, assistant-first, `assistant(tool_calls)+tool`
   round-trips, and double-system all return **200 OK**. Only
   `[user, tool]` (orphan tool) and `[assistant]`-alone still 400, and
   they return a **generic** `{'message':'invalid request'}` — never
   the "alternate" wording. An empty-content assistant returns
   `{'message':'Message content was empty','type':'invalid_message'}`.

2. **The real 400 is OpenAI's, and provider-agnostic.** The verbatim
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

Before adding an Nth alternation patch for "Perplexity", confirm the
actual on-the-wire error string first — it is almost certainly the
orphan-tool_calls case above.

## Related

- `tests/test_orphan_toolcalls_regression.py` — pins both the
  prompt-preservation and mid-loop-guard behaviors.
- `docs/lessons/config-source-resolution.md` — reproducing live-provider
  behavior requires the *real* config/key, not the repo default.
