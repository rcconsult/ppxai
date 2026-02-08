# Tab Completion Implementation Plan

**Date:** 2026-01-27
**Branch:** feature/new-tui-command
**Feature:** Readline-style Tab completion for InputBox widget
**Status:** Planning

---

## Problem Statement

The textual-autocomplete library (v4.0.6) has a critical limitation: it doesn't trigger callbacks for input patterns ending with whitespace or special characters. This breaks completion for:
- `/show @` - Context provider completion in command arguments
- `/show @file ` - File completion after space
- `@` - Context provider completion at cursor

**Root cause:** Library only calls callback when `search_string` contains alphanumeric characters.

**Solution:** Implement readline-style Tab completion with manual trigger control.

---

## Design: Readline-Style Tab Completion

### User Flow

```
User types: "/show @"
User presses: Tab
System:
  1. Intercepts Tab key in on_key()
  2. Gets current text and cursor position
  3. Calls completer.get_completions("/show @")
  4. If 1 match → inserts completion
  5. If multiple → shows popup or cycles through matches
```

### Architecture

```
InputBox (ppxai/tui/widgets/input_box.py)
├── on_key() - Intercepts Tab, Shift+Tab
├── _handle_tab_completion() - Main completion logic
├── _insert_completion() - Inserts single match
├── _show_completion_popup() - Shows multiple matches
└── _cycle_completions() - Cycles through matches on repeated Tab
```

### Key Features

1. **Tab key handling** - Intercept Tab before Textual processes it
2. **Cursor-aware** - Complete at cursor position, not just end of line
3. **Single match** - Auto-insert if only one completion
4. **Multiple matches** - Show popup or cycle with repeated Tab presses
5. **Common prefix** - Insert common prefix, then show remaining options
6. **No external deps** - Pure Textual + our existing completer

---

## Implementation Plan

### Phase 1: Basic Tab Handling (30 min)

**Goal:** Intercept Tab key and prevent focus loss

**Files:**
- `ppxai/tui/widgets/input_box.py`

**Changes:**
```python
def on_key(self, event) -> None:
    """Handle key events for history and Tab completion."""
    if event.key == "up":
        self._navigate_history(-1)
        event.prevent_default()
    elif event.key == "down":
        self._navigate_history(1)
        event.prevent_default()
    elif event.key == "tab":
        # Readline-style Tab completion
        if self._completer:
            self._handle_tab_completion()
            event.prevent_default()  # CRITICAL: Prevent focus change
        # If no completer, let Textual handle Tab (focus navigation)
```

**Critical:** `event.prevent_default()` must be called to stop Tab from changing focus.

**Test:**
- Tab key doesn't change focus
- Tab with no completer still works for focus navigation
- Shift+Tab still works for reverse focus

### Phase 2: Single Match Completion (20 min)

**Goal:** Auto-insert when only one completion available

**New method:**
```python
def _handle_tab_completion(self) -> None:
    """Handle Tab key for completion."""
    if not self._completer:
        return

    input_widget = self.query_one(Input)
    text = input_widget.value
    cursor_pos = input_widget.cursor_position

    # Get completions for text up to cursor
    text_to_complete = text[:cursor_pos]
    completions = self._completer.get_completions(text_to_complete)

    if len(completions) == 0:
        # No matches - do nothing (or beep)
        return
    elif len(completions) == 1:
        # Single match - insert it
        completion_text, _ = completions[0]
        self._insert_completion(completion_text, text, cursor_pos)
    else:
        # Multiple matches - handle in Phase 3
        self._handle_multiple_completions(completions, text, cursor_pos)

def _insert_completion(self, completion: str, original_text: str, cursor_pos: int) -> None:
    """Insert a completion at cursor position."""
    input_widget = self.query_one(Input)

    # Replace text up to cursor with completion
    new_text = completion + original_text[cursor_pos:]
    input_widget.value = new_text
    input_widget.cursor_position = len(completion)
```

**Test:**
- `/` + Tab → completes to `/show` (if only one match starting with /)
- `@f` + Tab → completes to `@file` (if only one match)
- Cursor moves to end of completion

### Phase 3: Multiple Match Handling (40 min)

**Goal:** Show popup or cycle through multiple matches

**Option A: Common Prefix Insertion (bash-style)**
```python
def _handle_multiple_completions(self, completions, text, cursor_pos):
    """Handle multiple completions - insert common prefix."""
    # Find common prefix
    completion_texts = [c[0] for c in completions]
    common_prefix = self._find_common_prefix(completion_texts)

    if common_prefix and len(common_prefix) > len(text[:cursor_pos]):
        # Insert common prefix
        self._insert_completion(common_prefix, text, cursor_pos)
    else:
        # No common prefix - show all options
        self._show_completion_choices(completions)

def _find_common_prefix(self, strings: list[str]) -> str:
    """Find common prefix of strings."""
    if not strings:
        return ""

    prefix = strings[0]
    for s in strings[1:]:
        while not s.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                return ""
    return prefix
```

**Option B: Popup Menu (IDE-style)**
```python
def _show_completion_choices(self, completions):
    """Show completion popup with choices."""
    # Create overlay popup with completions
    # Use Textual's OptionList or custom widget
    # Position near cursor
    # Arrow keys to navigate, Enter to select, Escape to cancel
    pass  # Implement popup widget
```

**Recommendation:** Start with Option A (common prefix), add Option B later if needed.

**Test:**
- `/s` + Tab → inserts `/show` (common prefix of /show, /save, /status, etc.)
- Double Tab → shows all `/s*` options
- `@` + Tab → shows @file, @clipboard, @url (no common prefix)

### Phase 4: Completion Cycling (20 min)

**Goal:** Cycle through matches on repeated Tab presses

**State tracking:**
```python
def __init__(self, id: str = None, completer=None):
    super().__init__(id=id)
    self._history: list[str] = []
    self._history_index = -1
    self._completer = completer
    # NEW: Completion state
    self._completion_state = None  # (completions, current_index, original_text)
```

**Cycling logic:**
```python
def _handle_tab_completion(self) -> None:
    """Handle Tab with cycling support."""
    input_widget = self.query_one(Input)
    text = input_widget.value
    cursor_pos = input_widget.cursor_position

    # Check if we're continuing a completion cycle
    if self._completion_state:
        completions, current_index, original_text = self._completion_state

        # Cycle to next completion
        next_index = (current_index + 1) % len(completions)
        completion_text, _ = completions[next_index]
        self._insert_completion(completion_text, original_text, cursor_pos)
        self._completion_state = (completions, next_index, original_text)
        return

    # New completion request
    text_to_complete = text[:cursor_pos]
    completions = self._completer.get_completions(text_to_complete)

    if len(completions) == 0:
        return
    elif len(completions) == 1:
        self._insert_completion(completions[0][0], text, cursor_pos)
        self._completion_state = None
    else:
        # Insert first match, save state for cycling
        completion_text, _ = completions[0]
        self._insert_completion(completion_text, text, cursor_pos)
        self._completion_state = (completions, 0, text_to_complete)

def on_key(self, event) -> None:
    """Handle keys - reset completion state on non-Tab keys."""
    # Reset completion state on any key except Tab
    if event.key != "tab" and self._completion_state:
        self._completion_state = None

    # ... existing key handlers ...
```

**Test:**
- `/s` + Tab → `/show`
- Tab again → `/save`
- Tab again → `/status`
- Tab again → `/show` (cycles back)
- Type any key → resets cycle

### Phase 5: Visual Feedback (30 min)

**Goal:** Show completion hints to user

**Options:**
1. **Status line message** - "3 completions: /show, /save, /status"
2. **Inline hint** - Grayed-out text showing next completion
3. **Popup overlay** - Small box with options

**Recommendation:** Start with status line, add inline hints later.

**Test:**
- Tab shows message in status bar
- Message disappears after selection or timeout

---

## Critical: Preventing Focus Loss

### The Problem

By default, Tab in Textual triggers focus navigation between widgets. We must prevent this.

### Solution 1: event.prevent_default()

```python
def on_key(self, event) -> None:
    if event.key == "tab":
        if self._completer:
            self._handle_tab_completion()
            event.prevent_default()  # <-- CRITICAL
```

**When to prevent:**
- Only when completer is set
- Only when completion is triggered
- Let Tab work for focus when no completer

### Solution 2: Consume event

```python
def on_key(self, event) -> None:
    if event.key == "tab":
        if self._completer:
            self._handle_tab_completion()
            event.stop()  # Stops propagation
            event.prevent_default()  # Prevents default action
```

### Testing Focus Behavior

```python
# Test cases:
1. Tab without completer → focuses next widget
2. Tab with completer → triggers completion, stays focused
3. Shift+Tab → focuses previous widget (always)
4. Tab after completion → continues focus (if no more matches)
```

---

## Rollout Plan

### Step 1: Remove Old Code
- ✅ DONE: Removed textual-autocomplete integration (commit 911c3a6)
- ✅ DONE: Removed autocomplete_adapter.py
- ✅ DONE: Updated pyproject.toml

### Step 2: Implement Basic Tab Completion
- [ ] Add Tab key handler with prevent_default()
- [ ] Implement _handle_tab_completion() stub
- [ ] Test Tab doesn't lose focus

### Step 3: Single Match Completion
- [ ] Implement _insert_completion()
- [ ] Handle single match case
- [ ] Test with `/`, `@f`, `/show`

### Step 4: Multiple Matches
- [ ] Implement common prefix logic
- [ ] Handle multiple matches
- [ ] Test with `/s`, `@` patterns

### Step 5: Cycling (Optional)
- [ ] Add completion state tracking
- [ ] Implement cycling on repeated Tab
- [ ] Test cycle behavior

### Step 6: Polish
- [ ] Add status line hints
- [ ] Handle edge cases (empty input, cursor mid-text)
- [ ] Update documentation

---

## Testing Strategy

### Unit Tests

```python
# tests/test_tab_completion.py

def test_single_match_completion():
    """Tab completes single match."""
    input_box = InputBox(completer=mock_completer)
    # Simulate typing "/" and pressing Tab
    # Assert completion inserted

def test_multiple_match_common_prefix():
    """Tab inserts common prefix for multiple matches."""
    pass

def test_tab_preserves_focus():
    """Tab completion doesn't lose focus."""
    pass

def test_no_completer_allows_focus_change():
    """Tab without completer allows focus navigation."""
    pass
```

### Manual Testing

```bash
# Start ppxaide
uv run ppxaide

# Test cases:
1. Type "/" → Press Tab → Should complete to first match
2. Type "@" → Press Tab → Should show @file/@clipboard/@url
3. Type "/show @" → Press Tab → Should complete context providers
4. Type "@file" → Press Tab → Should show file list
5. Press Tab repeatedly → Should cycle through matches
6. Type text, press Tab, press letter → Should reset cycle
```

---

## Expected Outcomes

### Before (textual-autocomplete)
- ❌ `/show @` + anything → No dropdown appears
- ❌ Library controls when completion triggers
- ❌ Trailing whitespace breaks completion

### After (readline-style)
- ✅ `/show @` + Tab → Shows context provider completions
- ✅ User controls when completion triggers (Tab press)
- ✅ Works with all patterns (whitespace, special chars, etc.)
- ✅ Familiar UX for terminal users
- ✅ No external dependencies

---

## Code Size Estimate

| Component | Lines | Complexity |
|-----------|-------|------------|
| Tab key handler | ~10 | Low |
| _handle_tab_completion() | ~30 | Medium |
| _insert_completion() | ~15 | Low |
| _handle_multiple_completions() | ~25 | Medium |
| _find_common_prefix() | ~10 | Low |
| Cycling logic | ~20 | Medium |
| **Total** | **~110 lines** | **Medium** |

Compare to textual-autocomplete integration: ~200 lines (adapter + integration + deps)

---

## Risks & Mitigations

### Risk 1: Tab loses focus
**Mitigation:** Use `event.prevent_default()` and thorough testing

### Risk 2: Completion conflicts with history navigation
**Mitigation:** Only trigger on Tab, not arrow keys

### Risk 3: Cursor position handling
**Mitigation:** Test mid-line completion thoroughly

### Risk 4: User expects auto-complete (IDE-style)
**Mitigation:** Document the readline-style behavior clearly

---

## Documentation Updates

After implementation:
1. Update [docs/RELEASE-NOTES-v1.15.0.md](RELEASE-NOTES-v1.15.0.md) - Add Tab completion feature
2. Update [README.md](../README.md) - Mention Tab completion in ppxaide features
3. Add usage guide to [docs/](.) - "How Tab Completion Works"
4. Update inline help (`/help`) - Document Tab key

---

## Branch Protection Reminder

**CRITICAL:** Never change branch without explicit user permission!

Current branch: `feature/new-tui-command`

Before any branch operations:
1. Ask user: "Should I switch to [branch]?"
2. Wait for confirmation
3. Only proceed if user says yes

This rule applies to:
- `git checkout`
- `git switch`
- `git merge`
- Any command that changes HEAD

---

## Commit Strategy

### Commits for this implementation:

1. `feat(tui): add Tab key handler for readline-style completion`
2. `feat(tui): implement single match Tab completion`
3. `feat(tui): add multiple match handling with common prefix`
4. `feat(tui): add completion cycling on repeated Tab presses`
5. `feat(tui): add visual feedback for Tab completion`
6. `docs: document readline-style Tab completion`

### Push to remote:

```bash
git push origin feature/new-tui-command
```

**Never push to master without user approval!**

---

## Success Criteria

- [ ] Tab completion works for all patterns: `/`, `@`, `/show @`, `@file`, etc.
- [ ] Tab key doesn't lose focus when completer is active
- [ ] Single match auto-completes
- [ ] Multiple matches show choices or cycle
- [ ] No external dependencies beyond Textual
- [ ] All tests pass
- [ ] Documentation updated
- [ ] User confirms it works as expected

---

## References

- Bash completion: https://www.gnu.org/software/bash/manual/html_node/Programmable-Completion.html
- Textual Key events: https://textual.textualize.io/guide/events/#key
- Existing completer: [ppxai/tui/completer.py](../../ppxai/tui/completer.py)
- InputBox widget: [ppxai/tui/widgets/input_box.py](../../ppxai/tui/widgets/input_box.py)
