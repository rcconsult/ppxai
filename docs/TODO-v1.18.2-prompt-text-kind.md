# v1.18.2 — `prompt_text` side-effect kind (free-text follow-up)

**Status:** Deferred from v1.18.1.
**Trigger to revisit:** any command that wants to ask the user a
free-text question and act on the typed reply (currently only
`/agent <vague>` would benefit, but `/save` / `/export` could too).

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

## Why deferred

v1.18.1's friendlier `NotificationResult` rejection (with the
question framing + concrete examples) covers 95% of the UX value.
The user types `/agent fix` → reads the nudge → retypes
`/agent <fuller>`. One extra round-trip vs the prompt_text
auto-resume — but the architectural cost of a new kind +
two client renderers + parity test is meaningful, and worth its
own PR for review.
