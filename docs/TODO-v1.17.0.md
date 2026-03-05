# TODO: v1.17.0 Backlog

---

## ppxaide Key Bindings Cleanup

### Problem

Key binding management in ppxaide is inconsistent and fragile:

- App-level bindings defined in `BINDINGS` in `ppxai/tui/app.py`
- Widget-level overrides scattered in `on_key()` across `ChatTextArea`, `InputBox`, `FileTree`
- Some keys consumed at widget level before reaching app bindings (discovered: `ctrl+tab`,
  `ctrl+enter` — fixed with guards, but the pattern is error-prone)
- Terminal-specific workarounds (`ctrl+enter=text:\x1b[13;5u`, `ctrl+tab=text:\x1b[9;5u`)
  leak into user's ghostty config because Textual can't negotiate Kitty protocol reliably
- No single place to see all effective bindings or reason about key routing

### Desired State

- Centralized key routing: one place decides which widget handles what, explicit pass-through
  for the rest — avoid mixing `_on_key` (priority) and `on_key` (normal) inconsistently
- `ChatTextArea` and `InputBox` should only consume keys they explicitly own; all others
  bubble up to the app unconditionally
- Ghost keys (ctrl+enter, ctrl+tab) should be handled via Textual's Kitty protocol
  negotiation (`\x1b[>1u`) rather than per-user terminal config workarounds
- Single source of truth for key bindings, ideally with a `/keys` command that shows
  the effective binding table at runtime

### Scope

- `ppxai/tui/widgets/input_box.py` — audit all `event.stop()` / `event.prevent_default()` calls
- `ppxai/tui/widgets/chat_text_area.py` — same audit
- `ppxai/tui/widgets/file_tree.py` — same audit
- `ppxai/tui/app.py` — consolidate `BINDINGS`, remove redundant widget-level overrides
- `docs/LINUX-TERMINAL-SETUP.md` — update if ghostty keybind workaround becomes unnecessary

### Priority

Low — current state works, just messy. Address in v1.17.0 polish pass.

---

## ~~Web App: Right Panel View Framework (`RightPanelFrame`)~~

**Completed in v1.16.2** — see `docs/TODO-v1.16.2.md` Feature 11. All 5 phases done.
