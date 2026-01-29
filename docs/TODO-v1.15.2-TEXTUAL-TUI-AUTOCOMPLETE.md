# TODO: Re-Enable Textual TUI Autocomplete (v1.15.2+)

**Status:** ✅ **IMPLEMENTED**
**Priority:** HIGH (Major UX regression)
**Effort:** ~5.5 hours (actual)
**Created:** 2026-01-29
**Completed:** 2026-01-29

## Problem Statement

The Textual TUI has **fully implemented autocomplete logic** but it's **completely disconnected** from the UI and non-functional.

**Evidence:**
- [ppxai/tui/completer.py](../ppxai/tui/completer.py) - Complete `TextualCompleter` class (409 lines)
- [ppxai/tui/widgets/input_box.py:27](../ppxai/tui/widgets/input_box.py#L27) - Completer marked as "unused"
- [ppxai/tui/widgets/completion_popup.py.deprecated](../ppxai/tui/widgets/completion_popup.py.deprecated) - UI widget deprecated

## What's Implemented But Not Working

The `TextualCompleter` class has the **most comprehensive** autocomplete logic of all clients:

| Feature | Implementation Status | UI Integration |
|---------|----------------------|----------------|
| Slash commands | ✅ Dynamic via CommandFactory | ❌ Not shown |
| Subcommands | ✅ 8 types (6 static + 2 dynamic) | ❌ Not shown |
| @file references | ✅ With priority files | ❌ Not shown |
| @context providers | ✅ @file, @clipboard, @url | ❌ Not shown |
| Model names | ✅ Dynamic from provider config | ❌ Not shown |
| Provider names | ✅ Dynamic from PROVIDERS | ❌ Not shown |
| Theme names | ✅ 13 themes | ❌ Not shown |

**Total:** 7/7 features fully coded, 0/7 actually visible to users.

## Root Cause Analysis

### What Happened

1. **Phase 1:** CompletionPopup widget created and integrated
2. **Phase 2:** Some issue occurred (performance? UI conflicts? Textual bugs?)
3. **Phase 3:** CompletionPopup deprecated, autocomplete disabled
4. **Phase 4:** InputBox kept `set_completer()` API but marked it "unused"
5. **Current State:** Code exists, completer initialized, but never called

### Evidence in Code

**[ppxai/tui/widgets/input_box.py](../ppxai/tui/widgets/input_box.py)**
```python
def __init__(self, id: str = None, completer=None):
    super().__init__(id=id)
    self._history: list[str] = []
    self._history_index = -1
    self._completer = completer  # Keep for API compatibility but unused  # LINE 27

def set_completer(self, completer) -> None:
    """Set the completer (kept for API compatibility, currently unused).  # LINE 143

    Args:
        completer: TextualCompleter instance
    """
    self._completer = completer
```

**[ppxai/tui/app.py:222-227](../ppxai/tui/app.py#L222-L227)**
```python
# Initialize autocomplete completer (Phase 1.1)
completer = TextualCompleter(
    working_dir=Path(self._working_dir),
    engine_client=self._engine_client
)
input_box.set_completer(completer)  # Called but does nothing
```

## Investigation Needed

**Before implementing, investigate why it was disabled:**

1. **Check git history** for when `completion_popup.py` was deprecated
2. **Search for related issues** in commit messages
3. **Test Textual version compatibility** - was there a breaking change?
4. **Review performance concerns** - did autocomplete cause lag?
5. **Check for UI conflicts** - did popup interfere with other widgets?

**Git commands to run:**
```bash
# When was it deprecated?
git log --all --full-history -- "**/completion_popup.py*"

# Find related commits
git log --all --grep="autocomplete\|completion" --oneline

# Find when it was marked unused
git log -p --all -S "unused" -- ppxai/tui/widgets/input_box.py
```

## Implementation Options

### Option 1: Re-Enable Original CompletionPopup Widget (Low Effort)

**Approach:**
1. Undeprecate `completion_popup.py.deprecated`
2. Wire it back into InputBox
3. Test and fix any issues that originally caused deprecation

**Pros:**
- Least code changes
- Original design already tested

**Cons:**
- Whatever issue caused deprecation may still exist
- May be incompatible with current Textual version

**Effort:** 2-3 hours

### Option 2: Build New Autocomplete UI with Textual Primitives (Medium Effort)

**Approach:**
1. Create new autocomplete dropdown using Textual `ListView` or `OptionList`
2. Position it below InputBox
3. Handle keyboard navigation (↑/↓, Tab, Enter, Esc)
4. Integrate with existing `TextualCompleter` logic

**Pros:**
- Modern Textual widgets (better maintained)
- Can fix original issues
- Cleaner implementation

**Cons:**
- More work than Option 1
- Needs careful positioning/z-index handling

**Effort:** 4-6 hours

### Option 3: Inline Autocomplete (Like VSCode/Web) (Highest Effort)

**Approach:**
1. Add autocomplete dropdown as separate widget in layout
2. Show/hide based on input focus
3. Use Textual's message passing for coordination

**Pros:**
- Best UX (matches VSCode/Web UX)
- Leverages Textual's layout system
- Most maintainable long-term

**Cons:**
- Most code changes
- Needs layout.tcss updates

**Effort:** 6-8 hours

## Recommended Approach

**Start with Option 1** (re-enable original):
1. Undeprecate `completion_popup.py.deprecated` → `completion_popup.py`
2. Import and use in InputBox
3. Test thoroughly
4. If original issues resurface, pivot to Option 2

**Rationale:**
- Fastest path to feature parity
- Can always refactor later if needed
- Code already exists and was working at some point

## Implementation Plan

### Step 1: Investigation (30 min)

```bash
# Find deprecation history
git log --all --full-history -- "**/completion_popup.py*"

# Check for related issues
git log --all --grep="autocomplete" --oneline | head -20

# Review deprecated file
cat ppxai/tui/widgets/completion_popup.py.deprecated
```

**Document findings:**
- Why was it deprecated?
- What version of Textual was it built for?
- Any known issues?

### Step 2: Undeprecate and Integrate (1-2 hours)

**2.1 Rename file:**
```bash
git mv ppxai/tui/widgets/completion_popup.py.deprecated \
       ppxai/tui/widgets/completion_popup.py
```

**2.2 Update InputBox** ([input_box.py](../ppxai/tui/widgets/input_box.py)):

```python
from ppxai.tui.widgets.completion_popup import CompletionPopup

class InputBox(Static):
    def __init__(self, id: str = None, completer=None):
        super().__init__(id=id)
        self._history: list[str] = []
        self._history_index = -1
        self._completer = completer  # NOW USED
        self._completion_popup: Optional[CompletionPopup] = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static("[bold cyan]>[/bold cyan]", classes="prompt")
            yield Input(
                placeholder="Type a message or /help for commands...",
                id="chat-input"
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input changes for autocomplete."""
        if not self._completer:
            return

        text = event.value

        # Get completions
        completions = self._completer.get_completions(text)

        if completions:
            self._show_completions(completions)
        else:
            self._hide_completions()

    def _show_completions(self, completions: list[tuple[str, str]]) -> None:
        """Show autocomplete popup."""
        if self._completion_popup:
            self._completion_popup.remove()

        self._completion_popup = CompletionPopup(completions)
        self.mount(self._completion_popup)

    def _hide_completions(self) -> None:
        """Hide autocomplete popup."""
        if self._completion_popup:
            self._completion_popup.remove()
            self._completion_popup = None

    def on_completion_popup_selected(self, message: CompletionPopup.Selected) -> None:
        """Handle completion selection."""
        input_widget = self.query_one(Input)

        # Replace current input with completion
        # (This needs logic to handle partial completions)
        input_widget.value = message.completion
        input_widget.cursor_position = len(message.completion)

        self._hide_completions()

    def on_completion_popup_cancelled(self, message: CompletionPopup.Cancelled) -> None:
        """Handle completion cancellation."""
        self._hide_completions()

    def on_key(self, event) -> None:
        """Handle key events for history navigation and completion."""
        # History navigation (existing code)
        if event.key == "up":
            if self._completion_popup:
                # Navigate completion popup
                self._completion_popup.select_previous()
                event.prevent_default()
                event.stop()
            else:
                # Navigate history
                self._navigate_history(-1)
                event.prevent_default()
        elif event.key == "down":
            if self._completion_popup:
                # Navigate completion popup
                self._completion_popup.select_next()
                event.prevent_default()
                event.stop()
            else:
                # Navigate history
                self._navigate_history(1)
                event.prevent_default()
        elif event.key == "escape":
            if self._completion_popup:
                self._hide_completions()
                event.prevent_default()
                event.stop()
        elif event.key == "tab":
            if self._completion_popup:
                # Select current completion
                self._completion_popup.select_current()
                event.prevent_default()
                event.stop()
```

### Step 3: Testing (1 hour)

**Test matrix:**

| Test | Expected Behavior |
|------|------------------|
| Type `/` | Show slash commands |
| Type `/to` | Filter to `/tools` |
| Type `/tools ` | Show subcommands |
| Type `/model ` | Show models for current provider |
| Type `@` | Show context providers |
| Type `@f` | Show `@file` + files starting with 'f' |
| Arrow keys | Navigate completion list |
| Tab/Enter | Select completion |
| Esc | Cancel completion |
| Type more | Update completion list |

**Edge cases:**
- Empty input → No completions
- No matches → Hide popup
- Fast typing → Debounce/throttle
- Popup visibility with theme changes
- Popup z-index with side panel open

### Step 4: Fix Issues (1-2 hours)

Based on testing, fix:
- Performance issues (debounce input handler)
- UI positioning (ensure popup doesn't overlap other widgets)
- Keyboard navigation conflicts
- Theme compatibility

### Step 5: Documentation (30 min)

Update:
- [AUTOCOMPLETE-SUPPORT-ANALYSIS.md](AUTOCOMPLETE-SUPPORT-ANALYSIS.md) - Change Textual TUI from DISABLED to working
- [CHANGELOG.md](../CHANGELOG.md) - Add v1.15.2 entry
- User-facing help text if needed

## Success Criteria

- [ ] All 7 autocomplete features work in Textual TUI
- [ ] Performance is acceptable (no lag on typing)
- [ ] Keyboard navigation is intuitive
- [ ] Popup doesn't interfere with other UI elements
- [ ] Works with all themes
- [ ] No regressions in existing functionality
- [ ] Parity with Rich TUI (at minimum)
- [ ] Exceeds Rich TUI (model/provider autocomplete bonus)

## Estimated Timeline

| Phase | Task | Effort |
|-------|------|--------|
| 1 | Investigation | 30 min |
| 2 | Undeprecate + Integrate | 2 hours |
| 3 | Testing | 1 hour |
| 4 | Bug fixes | 1-2 hours |
| 5 | Documentation | 30 min |
| **Total** | | **5-6 hours** |

## Risks

1. **Original issue resurfaces** - Whatever caused deprecation might still be a problem
   - Mitigation: Investigate first, be ready to pivot to Option 2

2. **Textual API changes** - CompletionPopup might use deprecated Textual APIs
   - Mitigation: Check Textual version compatibility, update imports if needed

3. **Performance regression** - Autocomplete might cause input lag
   - Mitigation: Debounce input handler, limit completion results

4. **UI conflicts** - Popup might interfere with side panel or other widgets
   - Mitigation: Careful z-index management, positioning logic

## Related Issues

- [TODO-v1.15.2-CONTEXT-INJECTOR-PARITY.md](TODO-v1.15.2-CONTEXT-INJECTOR-PARITY.md) - Context provider autocomplete
- [AUTOCOMPLETE-SUPPORT-ANALYSIS.md](AUTOCOMPLETE-SUPPORT-ANALYSIS.md) - Full autocomplete analysis

## Notes

**Why this matters:**
- Textual TUI has the most potential (best code, most features)
- Currently worst UX (no autocomplete at all)
- Fixing this would make it the **best** client overall

**Historical context needed:**
- When was CompletionPopup deprecated?
- What was the specific issue?
- Any related PRs or commits?

Run investigation first before committing to implementation approach.
