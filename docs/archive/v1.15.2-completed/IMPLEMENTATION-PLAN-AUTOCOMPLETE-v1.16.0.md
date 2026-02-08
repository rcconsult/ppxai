# Implementation Plan: textual-autocomplete Integration for v1.16.0

**Date:** 2026-01-27
**Target Release:** v1.16.0 (Q2 2026)
**Estimated Effort:** 1-2 days
**Risk Level:** Low (well-tested library, backward compatible)
**Status:** Awaiting approval

---

## 1. Executive Summary

**Goal:** Replace the disabled custom autocomplete implementation with the mature `textual-autocomplete` library (4.0.6).

**Benefits:**
- ✅ Solves all 5 UI/UX issues (positioning, layout, sorting, limits, lazy loading)
- ✅ Well-tested library (256 ⭐, active maintenance)
- ✅ May become officially recommended by Textualize
- ✅ Fuzzy matching and rich styling out of the box
- ✅ Minimal code changes (refactoring, not rewriting)

**Risks:**
- ⚠️ External dependency (mitigated: MIT license, active maintenance)
- ⚠️ API changes in future versions (mitigated: pin to `^4.0.6`)
- ⚠️ Integration complexity (mitigated: well-documented library)

**Rollback Plan:**
- Keep existing code disabled (not deleted) until v1.16.0 is stable
- Use feature flag for easy enable/disable during testing
- Can revert to v1.15.0 autocomplete-disabled state if issues arise

---

## 2. Current State Analysis

### Files Affected

| File | Lines | Purpose | Action |
|------|-------|---------|--------|
| `ppxai/tui/completer.py` | 409 | Completion logic | **Refactor** (keep logic, change return type) |
| `ppxai/tui/widgets/completion_popup.py` | 145 | Popup UI | **Delete** (replaced by library) |
| `ppxai/tui/widgets/input_box.py` | 81-96 | Tab key handler | **Enable** (uncomment + update) |
| `pyproject.toml` | - | Dependencies | **Add** textual-autocomplete |

### Current Architecture

```
User presses Tab
  ↓
InputBox.on_key (DISABLED - lines 81-96)
  ↓
TextualCompleter.get_completions(text)
  ↓
CompletionPopup.show(completions)  ← BROKEN (fixed offset, single column)
```

### Target Architecture

```
User types / or @
  ↓
AutoComplete wrapper listens to Input changes
  ↓
Dropdown.get_items(text) → calls our adapter
  ↓
CompletionAdapter.get_dropdown_items(text)
  ↓
TextualCompleter.get_completions(text) ← REUSE existing logic
  ↓
Convert to DropdownItem objects
  ↓
textual-autocomplete renders dropdown ← LIBRARY handles positioning, fuzzy match, styling
```

**Key insight:** We keep 90% of existing logic, just change the wrapper and return type.

---

## 3. Implementation Phases

### Phase 1: Dependency Setup (30 minutes)

**1.1 Add dependency to pyproject.toml**

```toml
# pyproject.toml [project.dependencies]
textual-autocomplete = "^4.0.6"
```

**1.2 Install and verify**

```bash
uv add textual-autocomplete
uv sync
python -c "from textual_autocomplete import AutoComplete; print('OK')"
```

**1.3 Update requirements files** (if any)

```bash
uv pip compile pyproject.toml -o requirements.txt
```

**Validation:**
- [ ] Library installs successfully
- [ ] No dependency conflicts
- [ ] Import works

---

### Phase 2: Create Adapter Layer (1-2 hours)

**2.1 Create new adapter module**

Create `ppxai/tui/autocomplete_adapter.py`:

```python
"""
Adapter layer between TextualCompleter and textual-autocomplete library.

This module bridges our existing completion logic with the textual-autocomplete
dropdown system, converting our completion tuples to DropdownItem objects.
"""

from typing import List, Tuple
from textual_autocomplete import DropdownItem
from .completer import TextualCompleter


class CompletionAdapter:
    """Adapter that converts TextualCompleter output to DropdownItem format."""

    def __init__(self, completer: TextualCompleter):
        self.completer = completer

    def get_dropdown_items(self, text: str) -> List[DropdownItem]:
        """
        Get dropdown items for autocomplete.

        Args:
            text: Current input text

        Returns:
            List of DropdownItem objects for textual-autocomplete
        """
        # Get completions from existing logic
        completions = self.completer.get_completions(text)

        # Convert to DropdownItem format
        items = []
        for completion, description in completions:
            items.append(
                DropdownItem(
                    main=completion,           # Display text
                    metadata=description,      # Description/help text
                )
            )

        return items
```

**2.2 Update TextualCompleter to support sorting**

Modify `ppxai/tui/completer.py`:

```python
def get_completions(self, text: str, sort: bool = True) -> list[tuple[str, str]]:
    """Get completion suggestions for the given text.

    Args:
        text: Current input text
        sort: Whether to sort results alphabetically (default: True)

    Returns:
        List of (completion, description) tuples
    """
    # ... existing logic ...

    # NEW: Alphabetically sort results if requested
    if sort and completions:
        completions.sort(key=lambda x: x[0].lower())

    return completions
```

**Validation:**
- [ ] Adapter converts tuples to DropdownItem correctly
- [ ] All completion types work (slash commands, @file, @clipboard, @url)
- [ ] Sorting works
- [ ] Unit tests pass

---

### Phase 3: Update InputBox Widget (1-2 hours)

**3.1 Refactor InputBox to use AutoComplete**

Modify `ppxai/tui/widgets/input_box.py`:

```python
from textual.widgets import Input
from textual_autocomplete import AutoComplete, Dropdown
from ..autocomplete_adapter import CompletionAdapter
from ..completer import TextualCompleter


class InputBox(Widget):
    """Chat input box with autocomplete support."""

    def compose(self) -> ComposeResult:
        # Create completer and adapter
        completer = TextualCompleter(
            command_factory=self.command_factory,
            engine_client=self.engine_client,
        )
        adapter = CompletionAdapter(completer)

        # Wrap Input with AutoComplete
        self._input = Input(
            placeholder="Type / for commands, @ for files, or your message...",
            id="chat-input",
        )

        yield AutoComplete(
            self._input,
            Dropdown(
                items=adapter.get_dropdown_items,  # Callback function
                id="autocomplete-dropdown"
            ),
        )

        # OLD CODE (keep commented for reference during migration)
        # yield Input(placeholder="...", id="chat-input")

    # REMOVE THIS (handled by AutoComplete library):
    # def on_key(self, event: events.Key) -> None:
    #     if event.key == "tab":
    #         self._show_completions()  # OLD, DISABLED
```

**3.2 Remove old Tab key handler**

Delete lines 81-96 (the TODO comment and disabled Tab handler).

**3.3 Remove CompletionPopup import**

```python
# DELETE THIS LINE:
# from .completion_popup import CompletionPopup
```

**Validation:**
- [ ] Input renders correctly
- [ ] AutoComplete wrapper doesn't break existing behavior
- [ ] Dropdown appears when typing `/` or `@`
- [ ] Enter key submits message (not captured by dropdown)
- [ ] Escape key dismisses dropdown

---

### Phase 4: Configure Dropdown Behavior (30 minutes)

**4.1 Customize dropdown appearance**

Add CSS to `ppxai/tui/layout.tcss`:

```css
/* Autocomplete dropdown styling */
AutoComplete {
    width: 100%;
}

#autocomplete-dropdown {
    max-height: 15;           /* Show ~15 items */
    border: solid $accent;
    background: $panel;
}

#autocomplete-dropdown > .autocomplete-item--highlighted {
    background: $accent;
    color: $text;
}
```

**4.2 Configure Dropdown options**

```python
# In InputBox.compose()
yield AutoComplete(
    self._input,
    Dropdown(
        items=adapter.get_dropdown_items,
        max_items=100,              # Show up to 100 items (removed old limit)
        fuzzy_search=True,          # Enable fuzzy matching
        case_sensitive=False,       # Case-insensitive matching
        id="autocomplete-dropdown",
    ),
)
```

**Validation:**
- [ ] Dropdown appears at correct position (below cursor)
- [ ] Styling matches ppxaide theme
- [ ] Max items limit works
- [ ] Fuzzy search works (typo tolerance)

---

### Phase 5: File Path Completion (Optional Enhancement, 1 hour)

**5.1 Use built-in PathAutoComplete for @file**

Option A: Keep current file search logic (simpler, immediate)
Option B: Use PathAutoComplete for @file completions (better UX, more work)

**If Option B:**

```python
from textual_autocomplete import PathAutoComplete

class FileCompletionAdapter:
    """Adapter for file path completions using PathAutoComplete."""

    def __init__(self, engine_client):
        self.engine_client = engine_client

    def get_file_dropdown(self, text: str):
        """Get file completions using PathAutoComplete."""
        # Extract @file query
        at_pos = text.rfind('@')
        if at_pos >= 0 and text[at_pos:at_pos+5] == '@file':
            query = text[at_pos+5:].strip()
            root = self.engine_client.get_working_dir()

            # Use PathAutoComplete
            path_ac = PathAutoComplete(
                root=root,
                ignore_patterns=[".git", "node_modules", "__pycache__"]
            )
            return path_ac.get_items(query)

        return []
```

**Recommendation:** Start with Option A (keep existing logic), consider Option B for v1.17.0.

**Validation:**
- [ ] @file completions work
- [ ] File paths are correct
- [ ] Ignore patterns work (.git, node_modules, etc.)

---

### Phase 6: Testing (2-3 hours)

**6.1 Unit Tests**

Create `tests/tui/test_autocomplete_adapter.py`:

```python
import pytest
from ppxai.tui.autocomplete_adapter import CompletionAdapter
from ppxai.tui.completer import TextualCompleter
from textual_autocomplete import DropdownItem


def test_adapter_converts_slash_commands():
    """Test adapter converts slash command completions."""
    completer = TextualCompleter(...)
    adapter = CompletionAdapter(completer)

    items = adapter.get_dropdown_items("/sh")

    assert len(items) > 0
    assert all(isinstance(item, DropdownItem) for item in items)
    assert any(item.main == "/show" for item in items)


def test_adapter_converts_file_completions():
    """Test adapter converts @file completions."""
    # ... test @file logic ...


def test_adapter_sorts_alphabetically():
    """Test adapter sorts results."""
    # ... test sorting ...
```

**6.2 Integration Tests**

Create `tests/tui/test_autocomplete_integration.py`:

```python
from textual.pilot import Pilot
from ppxai.tui.app import PPXAIDEApp


async def test_autocomplete_slash_command():
    """Test autocomplete appears when typing /."""
    app = PPXAIDEApp()
    async with app.run_test() as pilot:
        # Type "/"
        await pilot.press("/")

        # Check dropdown appears
        dropdown = app.query_one("#autocomplete-dropdown")
        assert dropdown.display

        # Check items are present
        items = dropdown.query(".autocomplete-item")
        assert len(items) > 0


async def test_autocomplete_file_completion():
    """Test autocomplete for @file."""
    # ... test @file ...


async def test_autocomplete_escape_dismisses():
    """Test Escape key dismisses dropdown."""
    # ... test Escape key ...
```

**6.3 Manual Testing Checklist**

- [ ] **Slash commands:**
  - [ ] Type `/` → dropdown appears
  - [ ] Type `/sh` → shows /show, /show-config, etc.
  - [ ] Arrow keys navigate
  - [ ] Enter selects completion
  - [ ] Escape dismisses
  - [ ] Fuzzy matching works (e.g., `/chk` matches `/checkpoint`)

- [ ] **@file completions:**
  - [ ] Type `@file` → shows file list
  - [ ] Typing path filters results
  - [ ] Alphabetically sorted
  - [ ] Ignores .git, node_modules, __pycache__
  - [ ] No 100 file limit (test in large repo)

- [ ] **@clipboard and @url:**
  - [ ] Type `@clip` → shows @clipboard
  - [ ] Type `@url` → shows @url

- [ ] **Subcommands:**
  - [ ] Type `/status ` → shows session, tokens, performance
  - [ ] Type `/tools ` → shows list, enable, disable

- [ ] **Provider/model names:**
  - [ ] Type `/provider ` → shows perplexity, gemini, openai, ollama
  - [ ] Type `/model ` → shows models for current provider

- [ ] **Edge cases:**
  - [ ] Empty input → no dropdown
  - [ ] No matches → empty dropdown
  - [ ] Rapid typing → no lag
  - [ ] Long file paths → truncated properly
  - [ ] Special characters in paths

**Validation:**
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] Manual testing checklist complete
- [ ] No regressions in existing functionality

---

### Phase 7: Cleanup and Documentation (1 hour)

**7.1 Delete old code**

After v1.16.0 is stable (1-2 weeks in production):

```bash
# Delete old completion popup
rm ppxai/tui/widgets/completion_popup.py

# Remove from __init__.py
# Edit ppxai/tui/widgets/__init__.py and remove:
# from .completion_popup import CompletionPopup
```

**7.2 Update documentation**

Update `docs/v1.15.0-AUTOCOMPLETE-AND-SHOW-ANALYSIS.md`:

```markdown
## Autocomplete Status (Updated v1.16.0)

✅ **ENABLED** - Now using `textual-autocomplete` library

Previous issues (v1.15.0):
- ❌ Fixed positioning → ✅ FIXED (cursor-based)
- ❌ Single column → ✅ FIXED (library handles layout)
- ❌ No sorting → ✅ FIXED (alphabetical)
- ❌ 100 file limit → ✅ FIXED (removed limit)
- ❌ No lazy loading → ✅ FIXED (library handles)
```

Update `CHANGELOG.md`:

```markdown
## [1.16.0] - 2026-0X-XX

### Added
- **Autocomplete:** Enabled autocomplete using `textual-autocomplete` library
  - Cursor-based positioning (no more fixed offset)
  - Fuzzy matching for typo tolerance
  - Alphabetically sorted results
  - Removed 100 file limit
  - Multi-column layout for better UX

### Changed
- **Dependencies:** Added `textual-autocomplete = "^4.0.6"`

### Removed
- **Internal:** Removed custom `CompletionPopup` widget (replaced by library)

### Fixed
- All 5 autocomplete UI/UX issues from v1.15.0
```

Update `README.md`:

```markdown
**ppxaide features (v1.16.0+):**
- ✅ **Smart autocomplete** - Tab completion for commands, files, context providers
- Modern async architecture with real-time streaming
- 17+ themes (vs 6 in Rich TUI) - cycle with Ctrl+T
...
```

**7.3 Update CLAUDE.md**

Remove the autocomplete disabled section (lines 81-96) and update project overview.

**Validation:**
- [ ] Old code deleted
- [ ] Documentation updated
- [ ] CHANGELOG entry complete
- [ ] README reflects new feature

---

## 4. Migration Strategy

### Backward Compatibility

**v1.15.0 → v1.16.0:**
- ✅ No breaking changes to user-facing features
- ✅ Same keybindings (Tab for autocomplete)
- ✅ Same completion types (slash commands, @file, etc.)
- ✅ Graceful degradation if library fails to load

**Graceful Degradation:**

```python
# In InputBox.compose()
try:
    from textual_autocomplete import AutoComplete, Dropdown
    USE_AUTOCOMPLETE = True
except ImportError:
    USE_AUTOCOMPLETE = False
    logger.warning("textual-autocomplete not installed, autocomplete disabled")

if USE_AUTOCOMPLETE:
    yield AutoComplete(self._input, Dropdown(...))
else:
    # Fallback to plain Input (like v1.15.0)
    yield self._input
```

### Feature Flag (Optional)

For extra safety during rollout:

```python
# In ppxai/config.py
ENABLE_AUTOCOMPLETE = os.getenv("PPXAI_ENABLE_AUTOCOMPLETE", "true").lower() == "true"

# In InputBox.compose()
if USE_AUTOCOMPLETE and ENABLE_AUTOCOMPLETE:
    yield AutoComplete(...)
```

Users can disable if issues arise:
```bash
PPXAI_ENABLE_AUTOCOMPLETE=false ppxaide
```

---

## 5. Rollback Plan

### If Issues Arise Post-Release

**Option 1: Disable via environment variable**
```bash
PPXAI_ENABLE_AUTOCOMPLETE=false ppxaide
```

**Option 2: Hotfix release (v1.16.1)**
```python
# Set default to disabled
ENABLE_AUTOCOMPLETE = os.getenv("PPXAI_ENABLE_AUTOCOMPLETE", "false").lower() == "true"
```

**Option 3: Revert to v1.15.0**
```bash
git revert <commit-hash>
# Rebuild and release v1.16.1 without autocomplete
```

### Known Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Library has bugs | Low | Medium | Test thoroughly, use stable version 4.0.6 |
| Performance issues | Low | Low | Library is well-optimized |
| Keybinding conflicts | Low | Low | Test all keybindings |
| Dependency conflicts | Very Low | Medium | Test installation on clean env |
| Breaking API changes | Very Low | High | Pin to `^4.0.6` (only patch updates) |

---

## 6. Success Criteria

### Must-Have (Blocker for v1.16.0 release)

- [ ] Autocomplete works for all completion types (slash, @file, @clipboard, @url)
- [ ] No regressions in existing functionality
- [ ] All tests pass (unit + integration)
- [ ] Performance is acceptable (no lag on typing)
- [ ] Dropdown positioning is correct (cursor-based, not fixed)

### Should-Have (High priority)

- [ ] Fuzzy matching works
- [ ] Alphabetical sorting works
- [ ] 100 file limit removed
- [ ] Documentation updated
- [ ] Manual testing checklist complete

### Nice-to-Have (Can defer to v1.17.0)

- [ ] PathAutoComplete for @file (vs current file search)
- [ ] Completion icons/badges
- [ ] Multi-column layout
- [ ] Virtual scrolling for 1000+ items

---

## 7. Timeline

### Estimated Breakdown

| Phase | Task | Estimated Time |
|-------|------|----------------|
| 1 | Dependency setup | 30 min |
| 2 | Create adapter layer | 1-2 hours |
| 3 | Update InputBox | 1-2 hours |
| 4 | Configure dropdown | 30 min |
| 5 | File path completion | 1 hour (optional) |
| 6 | Testing | 2-3 hours |
| 7 | Cleanup & docs | 1 hour |
| **Total** | **7-10 hours (1-2 days)** | |

### Suggested Schedule

**Day 1: Core Implementation**
- Morning: Phases 1-2 (dependency + adapter)
- Afternoon: Phases 3-4 (InputBox + dropdown config)
- End of day: Basic manual testing

**Day 2: Testing and Polish**
- Morning: Phase 6 (comprehensive testing)
- Afternoon: Fix bugs, Phase 7 (cleanup + docs)
- End of day: Ready for PR

**Week 1 post-merge:**
- Monitor for issues
- Gather user feedback
- Hotfix if needed

**Week 2-3 post-merge:**
- Stable, can delete old code
- Plan v1.17.0 enhancements

---

## 8. Review Questions

Before proceeding, please review and answer:

### Technical Decisions

1. **Adapter approach:** Do you approve the adapter layer pattern (keep existing logic, convert return types)?
   - ✅ Yes, proceed
   - ⏸️ Review needed
   - ❌ Different approach

2. **File completions:** Use existing file search logic (Option A) or PathAutoComplete library (Option B)?
   - ✅ Option A (simpler, immediate)
   - ✅ Option B (better UX, more work)
   - ⏸️ Decide later

3. **Feature flag:** Include environment variable toggle for extra safety?
   - ✅ Yes, add `PPXAI_ENABLE_AUTOCOMPLETE`
   - ❌ No, not needed (library is stable)

4. **Old code:** When to delete `completion_popup.py`?
   - ✅ After v1.16.0 is stable (1-2 weeks)
   - ⏸️ Keep until v1.17.0
   - ❌ Delete immediately

### Scope Questions

5. **v1.16.0 scope:** Include only autocomplete, or also add other features (tabs, file browser)?
   - ✅ Autocomplete only (focused release)
   - ⏸️ Add tabs (tabbed outputs)
   - ⏸️ Add file browser
   - ✅ All three features

6. **Testing coverage:** Acceptable testing level for v1.16.0?
   - ✅ Unit tests + manual testing (faster release)
   - ⏸️ Full integration tests required (slower, more thorough)

### Release Questions

7. **Release timeline:** When to target v1.16.0 release?
   - ⏸️ After current v1.15.0 release (1-2 weeks)
   - ⏸️ Immediate (include in v1.15.0)
   - ⏸️ Later (Q2 2026)

8. **Documentation priority:** Update docs before or after implementation?
   - ✅ After implementation (typical)
   - ⏸️ Before (TDD style)
   - ⏸️ Concurrent

---

## 9. Approval Checklist

- [ ] **Technical approach** reviewed and approved
- [ ] **Scope** defined (autocomplete only vs. multiple features)
- [ ] **Timeline** acceptable (1-2 days)
- [ ] **Risk mitigation** satisfactory
- [ ] **Rollback plan** clear
- [ ] **Success criteria** agreed upon
- [ ] **Testing strategy** sufficient

---

## 10. Next Steps (Post-Approval)

1. **Create feature branch**
   ```bash
   git checkout feature/new-tui-command
   git pull origin feature/new-tui-command
   git checkout -b feature/autocomplete-v1.16.0
   ```

2. **Start Phase 1:** Add dependency
   ```bash
   uv add textual-autocomplete
   ```

3. **Implement phases 2-7** following this plan

4. **Create PR** when complete
   - Reference this implementation plan
   - Include testing results
   - Tag reviewers

5. **Monitor post-merge** for issues

---

**Plan Status:** ⏸️ **AWAITING APPROVAL**
**Prepared By:** Claude (Assistant)
**Review By:** User
**Approval Date:** TBD
