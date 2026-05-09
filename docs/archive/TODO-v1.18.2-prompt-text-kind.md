# v1.18.2 — `prompt_text` side-effect kind (free-text follow-up)

**Status:** Closed 2026-05-03 (landed in v1.18.3).
**Original deferral:** from v1.18.1; trigger was any command that
wants to ask the user a free-text question and act on the typed
reply. `validate_agent_task` rejection is the first user.

## Background

v1.18.1's `prompt_quick_pick` lets the engine present N choices;
the chosen value IS the literal next args (per ADR Q3 (b),
no server continuation state). That works when the answer is one
of a finite set.

For free-text follow-ups (e.g. "what file should I fix? in which
function?") quick-pick is the wrong shape. The user types prose,
not picks.

`prompt_text` would be the analogue:

```json
{
  "kind": "prompt_text",
  "title": "I need more detail to run safely",
  "question": "What file or area should I fix? Add any acceptance criteria.",
  "command_to_resume": "agent",
  "original_args": "fix",   // optional: the original brief task
  "placeholder": "...",      // optional: placeholder shown in input
  "request_id": "..."        // optional: opaque ID for telemetry
}
```

Client handling:
- **Web** — render as a chat input prompt with the question above
  the input box. User types reply; client re-issues
  `POST /command/<command_to_resume>` with
  `args = <original_args> — <user_reply>` (the em-dash separator
  is so handlers can distinguish original vs elaboration if they
  want to).
- **VSCode** — `vscode.window.showInputBox({prompt: question})`.
  Same resume protocol.
- **TUI** — interactive prompt via Rich/Textual.

Per ADR Q3 (b) precedent: **no server-side continuation state**.
The resume args carry everything needed.

## Scope when picked up

1. Add `PROMPT_TEXT = "prompt_text"` to `SideEffectKind` constants
   in `ppxai/commands/results.py`.
2. Update the taxonomy sentinel test in
   `tests/test_command_envelope.py` (`EXPECTED_KINDS_V1` →
   `EXPECTED_KINDS_V1_2` or rename without breaking).
3. Add web handler in `ppxai/web/shared/side-effects.js`.
4. Add VSCode handler in `vscode-extension/src/sideEffectsHandler.ts`.
5. Update the cross-client parity test in
   `tests/test_vscode_step5a_helpers.py::TestCrossClientParity`.
6. **Convert** `validate_agent_task` rejection from
   `NotificationResult` to `NotificationResult` + `prompt_text`
   side-effect. The notification message stays as fallback for
   clients that don't honor the kind (open-enum invariant).
7. Document in `CLAUDE.md` "Critical Architecture Pattern: Command
   Dispatch via Envelope" alongside `prompt_quick_pick`.

Estimated cost: ~120 LoC + tests.

## Implementation summary (2026-05-03)

All 7 scope items landed:

1. `SideEffectKind.PROMPT_TEXT = "prompt_text"` in `ppxai/commands/results.py`.
2. `EXPECTED_KINDS_V1` in `tests/test_command_envelope.py` extended;
   the parity sentinel test in `tests/test_vscode_step5a_helpers.py`
   covers both web + VSCode now.
3. Web handler in `ppxai/web/shared/side-effects.js` — renders an
   inline form with a question and an input, on submit dispatches
   `/<command_to_resume> <original_args> — <reply>` via the
   command dispatcher. Submit listener bound once via the
   `_promptTextWired` sentinel (mirrors quick-pick's pattern).
4. VSCode handler in `vscode-extension/src/sideEffectsHandler.ts` —
   uses `vscode.window.showInputBox({prompt, placeHolder})`. On
   non-empty reply, dispatches via `dispatchCommandFromSideEffect`.
5. Cross-client parity test passes — both clients honor `prompt_text`.
6. `validate_agent_task` now adds the side-effect on every rejection.
   The notification message stays as the user-visible nudge for TUI
   clients (open-enum invariant — they ignore unknown kinds and the
   user retypes manually).
7. CLAUDE.md / `docs/patterns/command-envelope.md` updated alongside
   `prompt_quick_pick`.

8 new tests in `tests/test_prompt_text_side_effect.py` covering
constant exposure, validator behavior on short/empty/valid tasks,
metadata backward compat, and renderer presence checks.

## Why deferred

v1.18.1's friendlier `NotificationResult` rejection (with the
question framing + concrete examples) covers 95% of the UX value.
The user types `/agent fix` → reads the nudge → retypes
`/agent <fuller>`. One extra round-trip vs the prompt_text
auto-resume — but the architectural cost of a new kind +
two client renderers + parity test is meaningful, and worth its
own PR for review.
