# TODO v1.16.3 Backlog

Issues identified from debug log review (2026-03-07) and ongoing development.

---

## Bug: /files/list Storm on Session Restore

**Symptom:** On page reload or session restore, multiple `working_dir_changed` SSE events are
emitted back-to-back, triggering one `/files/list` call per event. Observed 3–5 rapid sequential
calls within a few hundred milliseconds.

**Root cause:** `EngineClient.restore_session()` emits `working_dir_changed` during restore,
and the server may also emit it on session creation. If both fire, the file tree receives
duplicate change signals.

**Fix (proposed):** Debounce file tree refresh on `working_dir_changed`: ignore subsequent events
within a 500ms window after the first. Alternatively, suppress `working_dir_changed` emission
during session restore if the working dir hasn't actually changed from the persisted value.

---

## Bug: Validator False Positive — Success-After-Retries Pattern

**Symptom:** `claim_contradicts_result` fires when the AI describes a successful retry:
> "The first attempt failed, but after adjusting the path the command succeeded."

The validator sees a "fail" signal near a "success" signal within the proximity window and
incorrectly flags it as a contradiction.

**Root cause:** The proximity-window heuristic in `validator.py` doesn't account for the
temporal ordering of attempts. A success claim following a described failure is valid, not a
contradiction.

**Fix (proposed):** After detecting a `fail` + `success` co-occurrence, check if the success
claim appears *after* the fail signal in the text (success is the outcome of retrying). Only
flag as contradiction when fail follows success (i.e., the AI claims success but then describes
a failure).

---

## ~~Bug: Server Shell PATH Missing ~/.local/bin~~ — Fixed in v1.16.2

**Fix:** Added `tools.shell.shell_bin` and `tools.shell.login_shell` config keys.
Set `"shell_bin": "/bin/zsh"` and `"login_shell": true` to run commands through your
login shell, sourcing the full user environment (PATH, nvm, pyenv, uv, etc.).

---

## Enhancement: File Tree Double-Click Dir Interaction Refinement

**Current state (v1.16.2):** Single-click = expand/collapse, double-click = cd into dir,
right-click = cd here. Tooltip says "Click: expand | Dbl-click: cd here".

**Feedback:** The 220ms single-click delay for files causes a perceivable lag before the
preview panel opens. Consider reducing to 150ms or making it configurable.

**Related:** The `..` parent entry (added v1.16.2) correctly suppresses when `at_fs_root: true`
is returned by `/files/list`. Verify this works when the server runs on Windows (where the root
is `C:\` and `parent == self` check still holds via `Path.parent`).
