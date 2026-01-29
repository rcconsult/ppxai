# Implementation Plan: Textual TUI Tab Completion (v1.15.2)

**Status:** Ready for Review
**Effort:** 3-4 hours
**Priority:** HIGH (Major UX improvement)
**Created:** 2026-01-29

---

## Overview

Re-enable autocomplete for Textual TUI using minimal tab-based completion instead of dropdown UI.

**Key Decisions:**
1. **Tab-based cycling** - Use existing [ppxai/tui/completer.py](../ppxai/tui/completer.py) logic with simple Tab cycling (proven in [test_tab_focus.py](../test_tab_focus.py))
2. **Terminal-like UX for file commands** - `/show README.md` (no @ prefix) matches standard shell behavior
3. **@ prefix for context injection** - `@file:README.md` only in messages for context injection

**What This Provides:**
- ✅ Slash commands (`/tools`, `/model`, etc.)
- ✅ Subcommands (`/tools enable`, `/checkpoint backend git`)
- ✅ **File arguments for commands** (`/show README.md`, `/edit src/main.py`) - **NEW**
- ✅ @file references with file search (context injection in messages)
- ✅ @clipboard, @url, @git, @tree context providers
- ✅ Dynamic model/provider names from engine
- ✅ Theme name completion

**Design Rationale - File Completion:**

Different completion modes for different contexts:

| Context | Format | Example |
|---------|--------|---------|
| **File commands** | Plain filename | `/show README.md` |
| **Context injection** | `@file:filename` | `Explain @file:README.md` |
| **Other context** | `@provider` | `@git`, `@clipboard`, `@url` |

This matches terminal UX where commands take bare filenames, while `@` is a special syntax for injecting content into messages.

---

## Architecture

```
User types text
    ↓
Input.Changed event → Update completion state (reset if text changes)
    ↓
User presses Tab
    ↓
on_key(event) → completer.get_completions(text)
    ↓
    └─ If matches found:
        1. Replace Input.value with current match
        2. Cycle index for next Tab press
        3. event.prevent_default() + event.stop()
        4. Update status line with "X/Y matches"
    └─ If no matches:
        Show "No matches" in status line
```

**Key Insight:** No threading, no UI popup, no external libraries. Just synchronous Tab handler.

---

## Files to Modify

### 1. Keep (Don't Delete)
- ✅ `ppxai/tui/completer.py` (409 lines) - **KEEP**, contains all completion logic

### 2. Delete (Deprecated UI)
- ❌ `ppxai/tui/widgets/completion_popup.py.deprecated` - DELETE
- ❌ Any references to `textual-autocomplete` library - DELETE

### 3. Modify
- 📝 `ppxai/tui/widgets/input_box.py` - Add Tab handler (~50 lines)
- 📝 `ppxai/tui/app.py` - Update completer initialization (if needed)
- 📝 `docs/AUTOCOMPLETE-SUPPORT-ANALYSIS.md` - Update status from DISABLED to ✅ Working

---

## Phase 1: InputBox Tab Handler (2 hours)

### File: `ppxai/tui/widgets/input_box.py`

**Current State:**
- Line 27: `self._completer = completer  # Keep for API compatibility but unused`
- Line 143-148: `set_completer()` marked as unused

**Changes:**

#### 1.1 Update `__init__()` (Line 21-27)

```python
def __init__(self, id: str = None, completer=None):
    super().__init__(id=id)
    self._history: list[str] = []
    self._history_index = -1
    self._completer = completer  # NOW USED for tab completion

    # Tab completion state
    self._completion_matches: list[tuple[str, str]] = []  # [(text, description), ...]
    self._completion_index = 0
    self._last_completion_text = ""  # Track when to reset cycle
```

#### 1.2 Update `set_completer()` (Line 143-148)

```python
def set_completer(self, completer) -> None:
    """Set the completer for tab completion.

    Args:
        completer: TextualCompleter instance
    """
    self._completer = completer
```

#### 1.3 Add Completion State Reset Handler (New)

```python
def on_input_changed(self, event: Input.Changed) -> None:
    """Reset completion state when user types (not from Tab completion)."""
    if event.input.id != "chat-input":
        return

    # If text changed and it's not our completion, reset cycle
    if event.value != self._last_completion_text:
        self._completion_matches = []
        self._completion_index = 0
        self._last_completion_text = ""
```

#### 1.4 Add Tab Key Handler (New - Core Logic)

```python
def on_key(self, event) -> None:
    """Handle key events for history navigation and tab completion."""

    # ============================================================
    # TAB COMPLETION
    # ============================================================
    if event.key == "tab":
        input_widget = self.query_one("#chat-input", Input)

        # Only handle if input is focused
        if not input_widget.has_focus:
            return

        if not self._completer:
            return

        text = input_widget.value

        # First Tab press OR text changed: get new completions
        if text != self._last_completion_text or not self._completion_matches:
            self._completion_matches = self._completer.get_completions(text)
            self._completion_index = 0

        if self._completion_matches:
            # Apply current completion
            completion_text, description = self._completion_matches[self._completion_index]

            # Handle different completion types
            if text.rfind('@') >= 0:
                # @file/@clipboard/@url completion: replace from @ to end
                at_pos = text.rfind('@')
                input_widget.value = text[:at_pos] + completion_text
            elif self._is_file_command(text):
                # File commands (/show, /edit, /cat): replace from command to end
                # Example: "/show READ" + Tab → "/show README.md"
                parts = text.split(None, 1)  # Split on first whitespace
                if len(parts) == 2:
                    # Has command + partial filename
                    input_widget.value = f"{parts[0]} {completion_text}"
                else:
                    # Just command, no space yet
                    input_widget.value = f"{parts[0]} {completion_text}"
            elif text.startswith('/'):
                # Slash command/subcommand: replace entire input
                input_widget.value = completion_text
            else:
                # Fallback: replace entire input
                input_widget.value = completion_text

            # Move cursor to end
            input_widget.cursor_position = len(input_widget.value)

            # Track for state management
            self._last_completion_text = input_widget.value

            # Cycle to next completion for next Tab press
            self._completion_index = (self._completion_index + 1) % len(self._completion_matches)

            # Show status
            status_msg = f"Completed: {completion_text}"
            if len(self._completion_matches) > 1:
                # Show cycle position (using previous index since we already incremented)
                current = (self._completion_index - 1) % len(self._completion_matches) + 1
                total = len(self._completion_matches)
                status_msg += f" ({current}/{total}) - Press Tab to cycle"

            self.post_message(self.StatusUpdate(status_msg))

            # CRITICAL: Prevent Tab from moving focus
            event.prevent_default()
            event.stop()
        else:
            # No matches
            self.post_message(self.StatusUpdate("No completions available"))
            event.prevent_default()
            event.stop()

        return  # Don't fall through to history navigation

    # ============================================================
    # HISTORY NAVIGATION (existing code)
    # ============================================================
    if event.key == "up":
        self._navigate_history(-1)
        event.prevent_default()
    elif event.key == "down":
        self._navigate_history(1)
        event.prevent_default()

def _is_file_command(self, text: str) -> bool:
    """Check if text is a file-referencing command (/show, /edit, /cat)."""
    text_lower = text.lower().strip()
    return text_lower.startswith(('/show ', '/edit ', '/cat '))
```

#### 1.5 Add Status Message (New)

```python
class StatusUpdate(Message):
    """Message to update status line with completion info."""

    def __init__(self, text: str):
        super().__init__()
        self.text = text
```

---

## Phase 2: App Integration (30 min)

### File: `ppxai/tui/app.py`

**Current State:** Lines 222-227 already initialize completer and call `set_completer()`

```python
# Initialize autocomplete completer (Phase 1.1)
completer = TextualCompleter(
    working_dir=Path(self._working_dir),
    engine_client=self._engine_client
)
input_box.set_completer(completer)
```

**Changes Needed:**

#### 2.1 Add Status Update Handler (New)

```python
def on_input_box_status_update(self, message: InputBox.StatusUpdate) -> None:
    """Handle completion status messages from InputBox."""
    # Option A: Show in status bar
    status_bar = self.query_one(StatusBar)
    # Could add a temporary badge or notification

    # Option B: Show as toast notification
    self.notify(message.text, timeout=2)

    # Option C: Update a dedicated completion hint area
    # (Future: add a hint line below input box)
```

#### 2.2 Update Completer on Directory Change (Existing)

Verify that `/cd` command updates completer's working_dir:

```python
async def _handle_cd_command(self, new_dir: Path) -> None:
    """Handle /cd command."""
    self._working_dir = str(new_dir)

    # Update completer if it exists
    input_box = self.query_one(InputBox)
    if input_box._completer:
        input_box._completer.update_working_dir(new_dir)
```

---

## Phase 3: Completer Updates (1 hour)

### File: `ppxai/tui/completer.py`

#### 3.1 Add Context Provider Parity (Lines 26-30)

**Change:** Add missing `@git` and `@tree` context providers

```python
# OLD (Lines 26-30)
CONTEXT_PROVIDERS = [
    ('@file', 'Include file contents'),
    ('@clipboard', 'Include clipboard contents'),
    ('@url', 'Fetch and include URL contents'),
]

# NEW
CONTEXT_PROVIDERS = [
    ('@file', 'Include file contents'),
    ('@git', 'Include git diff (staged + unstaged)'),
    ('@tree', 'Include project directory structure'),
    ('@clipboard', 'Include clipboard text content'),
    ('@url', 'Fetch and include URL content'),
]
```

This achieves context injector parity as documented in [TODO-v1.15.2-CONTEXT-INJECTOR-PARITY.md](TODO-v1.15.2-CONTEXT-INJECTOR-PARITY.md).

#### 3.2 Update `get_completions()` to Support File Commands (Lines 93-112)

**Change:** Detect file commands and return plain filenames (no @ prefix)

```python
def get_completions(self, text: str) -> list[tuple[str, str]]:
    """Get completion suggestions for the given text.

    Args:
        text: Text to complete

    Returns:
        List of (completion_text, description) tuples
    """
    # Priority 0: File commands (/show, /edit, /cat) - return plain filenames
    text_lower = text.lower().strip()
    if text_lower.startswith(('/show ', '/edit ', '/cat ')):
        return self._complete_file_argument(text)

    # Priority 1: @context providers (anywhere in text)
    at_pos = text.rfind('@')
    if at_pos >= 0:
        return self._complete_context_provider(text, at_pos)

    # Priority 2: Slash commands (at start of line)
    if text.startswith('/'):
        return self._complete_command(text)

    # No completions for regular text
    return []
```

#### 3.3 Add File Argument Completion Method (New)

```python
def _complete_file_argument(self, text: str) -> list[tuple[str, str]]:
    """Complete file arguments for /show, /edit, /cat commands.

    Returns plain filenames (no @ prefix) for terminal-like UX.

    Args:
        text: Full input text (e.g., "/show REA")

    Returns:
        List of (filename, filepath) tuples
    """
    # Extract the file query after the command
    parts = text.split(None, 1)  # Split on first whitespace
    if len(parts) < 2:
        # Just "/show" with no query - return all files
        query = ""
    else:
        # "/show READ" - extract "READ"
        query = parts[1].strip()

    # Remove @ prefix if user typed it (for backward compatibility)
    query = query.lstrip('@')

    # Get files matching query
    completions = []
    for filename, filepath in self._get_files():
        if not query or query.lower() in filename.lower() or query.lower() in filepath.lower():
            # Return plain filename (no @ prefix)
            completions.append((filename, filepath))

    return completions[:20]  # Limit to 20 completions
```

---

## Phase 4: Testing (1 hour)

### Test Matrix

| Test Case | Input | Expected Behavior |
|-----------|-------|-------------------|
| **Slash Commands** | `/` + Tab | Show all commands (`/help`, `/model`, `/tools`, etc.) |
| | `/to` + Tab | Complete to `/tools` |
| | `/tools` + Tab (cycle) | Cycle through `/tools`, `/tree`, etc. |
| **Subcommands** | `/tools ` + Tab | Show subcommands (`enable`, `disable`, `list`, etc.) |
| | `/tools e` + Tab | Complete to `enable` |
| | `/checkpoint backend ` + Tab | Show `git`, `file`, `auto`, `none` |
| **Dynamic Completions** | `/model ` + Tab | Show models from current provider |
| | `/provider ` + Tab | Show all providers |
| | `/theme ` + Tab | Show theme names + `list` subcommand |
| **File Commands** | `/show ` + Tab | Show files (plain filenames, no @) |
| | `/show READ` + Tab | Complete to `/show README.md` |
| | `/edit src/m` + Tab | Complete to `/edit src/main.py` |
| | `/cat ` + Tab | Show files (alias of /show) |
| **Context Providers** | `@` + Tab | Show all 5 providers (`@file`, `@git`, `@tree`, `@clipboard`, `@url`) |
| | `@f` + Tab | Show `@file` + files starting with 'f' (as `@file:filename`) |
| | `@g` + Tab | Show `@git` + `@file:` files starting with 'g' |
| | `tell me about @` + Tab | Context providers work mid-message |
| **Cycling** | `/to` + Tab + Tab + Tab | Cycle through `/tools`, `/tree` (if exists), back to `/tools` |
| | `/show RE` + Tab + Tab | Cycle through README.md, RELEASE.md, etc. |
| **Reset** | `/tools e` + Tab, then type `n` | Reset completion state, new query `/tools en` |
| **No Matches** | `/xyz` + Tab | Show "No completions available" |
| | `/show nonexistent` + Tab | Show "No completions available" |
| **Focus** | Tab completion | Input keeps focus (doesn't jump to buttons) |
| **History** | `↑` / `↓` keys | History navigation still works |

### Edge Cases

| Test Case | Expected Behavior |
|-----------|-------------------|
| Empty input + Tab | No completions |
| `/tools enable` (complete command) + Tab | No completions (or re-suggest?) |
| `/show @README.md` + Tab | Strip @ prefix, complete as filename |
| Multiple `@file` refs in one message | Each @ triggers separate completion |
| `/show README.md` in message | `@` completion still works for context injection |
| Tab with no completer set | No-op (graceful degradation) |
| `/cd` command → `/show ` + Tab | File completions update to new directory |
| `/show ` with 1000 files | Show first 20 matches (performance limit) |

### Performance Tests

| Test Case | Expected Time |
|-----------|--------------|
| Tab completion with 100 files | < 50ms |
| Tab completion with 1000 files | < 200ms (cached) |
| First Tab after `/cd` | < 500ms (rebuilds file cache) |

---

## Phase 5: Cleanup (30 min)

### 5.1 Delete Dead Code

#### Remove Deprecated Files

```bash
# Remove deprecated completion popup widget
git rm ppxai/tui/widgets/completion_popup.py.deprecated

# Clean orphaned bytecode from deleted autocomplete_adapter.py
rm -f ppxai/tui/__pycache__/autocomplete_adapter.cpython-*.pyc
rm -f ppxai/tui/widgets/__pycache__/completion_popup.cpython-*.pyc

# Rebuild pycache after cleanup
find ppxai/tui -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
```

#### Update Code Comments

**File:** `ppxai/tui/widgets/input_box.py`

Line 27 currently says:
```python
self._completer = completer  # Keep for API compatibility but unused
```

This comment will be removed by our Phase 1 implementation (completer is now USED).

Line 143-148 docstring:
```python
def set_completer(self, completer) -> None:
    """Set the completer (kept for API compatibility, currently unused).
```

Update to:
```python
def set_completer(self, completer) -> None:
    """Set the completer for tab-based autocomplete.
```

### 5.2 Verify No Dead References

```bash
# Check for any remaining references to deprecated code
grep -r "textual-autocomplete\|completion_popup\|autocomplete_adapter" ppxai/ --include="*.py"

# Should return no results (or only this plan document)
```

### 5.3 Summary of Removed Code

| Item | Type | Reason |
|------|------|--------|
| `completion_popup.py.deprecated` | Widget UI | Failed attempts with dropdown (fixed positioning, textual-autocomplete library) |
| `autocomplete_adapter.cpython-*.pyc` | Bytecode | Orphaned from deleted autocomplete_adapter.py source file |
| `completion_popup.cpython-*.pyc` | Bytecode | Old bytecode from deprecated file |
| "unused" comments in `input_box.py` | Comments | Completer is now active, not unused |

**Kept (Not Deleted):**
- ✅ `ppxai/tui/completer.py` (409 lines) - **USED** for tab completion logic
- ✅ `TextualCompleter` class - Core autocomplete engine

### 5.4 Update Documentation

#### File: `docs/AUTOCOMPLETE-SUPPORT-ANALYSIS.md`

Update table (Lines 13-21):

```markdown
| Feature | Rich TUI | Textual TUI | VSCode | Web App |
|---------|----------|-------------|--------|---------|
| **Slash Commands** | ✅ Full | ✅ **Full (Tab-based)** | ✅ Full | ✅ Full |
| **Subcommands** | ✅ 6 types | ✅ **8 types (Tab-based)** | ❌ None | ❌ None |
| **@file References** | ⚠️ Files only | ✅ **Full (Tab-based)** | ✅ Files + @git/@tree | ✅ Files + @git/@tree |
| **Model Names** | ❌ None | ✅ **Dynamic (Tab-based)** | ❌ None | ❌ None |
| **Provider Names** | ❌ None | ✅ **Dynamic (Tab-based)** | ❌ None | ❌ None |
| **Theme Names** | ✅ Yes | ✅ **Yes (Tab-based)** | ❌ N/A | ❌ N/A |
| **Tool Names** | ✅ Yes (/tools help) | ✅ **Yes (Tab-based)** | ❌ None | ❌ None |
```

#### File: `docs/TODO-v1.15.2-TEXTUAL-TUI-AUTOCOMPLETE.md`

Add at top:

```markdown
**Status:** ✅ IMPLEMENTED (v1.15.2)
**Implementation:** Tab-based completion (no dropdown UI)
```

#### File: `CHANGELOG.md`

Add entry:

```markdown
## [1.15.2] - 2026-01-XX

### Added
- **Textual TUI:** Re-enabled tab-based autocomplete for all features
  - Slash commands, subcommands, @context providers, models, providers, themes
  - Simple Tab cycling (no dropdown UI) - maintains focus in input widget
  - 8 subcommand types including dynamic model/provider completion
- **Context Provider Parity:** All clients now expose @git and @tree
  - Textual TUI: Added @git, @tree to autocomplete
  - Rich TUI: Added @git, @tree, @clipboard, @url to autocomplete (see TODO-v1.15.2-CONTEXT-INJECTOR-PARITY.md)
  - VSCode/Web: Added @clipboard, @url to autocomplete

### Fixed
- Textual TUI autocomplete regression (disabled since v1.11.4)
- Inconsistent context provider discovery across clients

### Removed
- Deprecated completion_popup.py widget (replaced by tab-based completion)
```

---

## Success Criteria

- [ ] All 7 autocomplete features work in Textual TUI (slash, subcommands, @file, @context, models, providers, themes)
- [ ] Tab completion maintains focus (doesn't navigate to other widgets)
- [ ] Cycling through completions works (Tab → Tab → Tab)
- [ ] Completion state resets when user types new text
- [ ] Status line shows "X/Y matches - Press Tab to cycle"
- [ ] No performance lag (< 50ms for typical completions)
- [ ] Works with all context providers (@file, @git, @tree, @clipboard, @url)
- [ ] Dynamic model/provider completions use live engine data
- [ ] `/cd` command updates file completions to new directory
- [ ] History navigation (↑/↓) still works
- [ ] No regressions in existing functionality

---

## Estimated Timeline

| Phase | Task | Effort |
|-------|------|--------|
| 1 | InputBox Tab handler implementation | 2 hours |
| 2 | App integration + status updates | 30 min |
| 3 | Completer updates (file commands + context providers) | 1 hour |
| 4 | Testing (all features + edge cases) | 1.5 hours |
| 5 | Cleanup + documentation | 30 min |
| **Total** | | **~5.5 hours** |

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Tab handler conflicts with existing key bindings | Test with all key bindings, use `event.prevent_default()` + `event.stop()` |
| Completion state gets out of sync | Reset on `Input.Changed` event when text differs from last completion |
| Performance with large file trees | Use existing 5-second cache in `TextualCompleter._get_files()` |
| Status updates spam the UI | Use toast notifications with timeout, or dedicated hint area |
| @file completion breaks with spaces in paths | Already handled by completer (returns full paths with spaces) |

---

## Future Enhancements (Out of Scope)

- Dropdown UI for completions (like original CompletionPopup)
- Fuzzy matching for file paths
- Preview of file contents on hover
- Syntax highlighting in completion descriptions
- Multi-column completion display
- Mouse support for selecting completions

**For v1.15.2:** Simple tab completion is sufficient. These can be added later if needed.

---

## References

- [test_tab_focus.py](../test_tab_focus.py) - Proof of concept
- [ppxai/tui/completer.py](../ppxai/tui/completer.py) - Complete autocomplete logic
- [docs/TODO-v1.15.2-TEXTUAL-TUI-AUTOCOMPLETE.md](TODO-v1.15.2-TEXTUAL-TUI-AUTOCOMPLETE.md) - Investigation
- [docs/TODO-v1.15.2-CONTEXT-INJECTOR-PARITY.md](TODO-v1.15.2-CONTEXT-INJECTOR-PARITY.md) - Context provider parity
- [docs/AUTOCOMPLETE-SUPPORT-ANALYSIS.md](AUTOCOMPLETE-SUPPORT-ANALYSIS.md) - Feature matrix

---

## Approval

**Ready for Implementation:** ✅ / ❌

**Reviewer Comments:**

---

**Notes:**
- This plan assumes `TextualCompleter` is production-ready (it is - 409 lines, comprehensive)
- No external dependencies needed
- No threading complexity
- Maintains backward compatibility (set_completer API unchanged)
- Can be implemented in a single feature branch
