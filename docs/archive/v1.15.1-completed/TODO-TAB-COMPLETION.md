# TODO: Readline-Style Tab Completion

**Created:** 2026-01-27
**Branch:** feature/new-tui-command
**Assignee:** Implementation team
**Priority:** Medium (deferred from v1.15.0 autocomplete attempt)

---

## Implementation Checklist

### Phase 1: Basic Tab Handling ⏳
- [ ] Add `tab` key handler in `InputBox.on_key()`
- [ ] Call `event.prevent_default()` to prevent focus loss
- [ ] Add `_handle_tab_completion()` stub method
- [ ] Test: Tab key doesn't change focus when completer is set
- [ ] Test: Tab still works for focus navigation when no completer
- [ ] Test: Shift+Tab works for reverse focus navigation
- [ ] **Estimated time:** 30 minutes

### Phase 2: Single Match Completion ⏳
- [ ] Implement `_insert_completion(completion, text, cursor_pos)` method
- [ ] Handle single match case in `_handle_tab_completion()`
- [ ] Get completions using existing `self._completer.get_completions()`
- [ ] Insert completion at cursor position
- [ ] Update cursor position after insertion
- [ ] Test: `/` + Tab completes to single match
- [ ] Test: `@f` + Tab completes to `@file`
- [ ] Test: Cursor moves to end of completion
- [ ] **Estimated time:** 20 minutes

### Phase 3: Multiple Match Handling ⏳
- [ ] Implement `_find_common_prefix(strings)` helper
- [ ] Implement `_handle_multiple_completions(completions, text, cursor_pos)`
- [ ] Insert common prefix when available
- [ ] Show completion choices when no common prefix
- [ ] Test: `/s` + Tab inserts common prefix `/s`
- [ ] Test: `@` + Tab handles no common prefix
- [ ] Test: `/show @` + Tab shows context providers
- [ ] **Estimated time:** 40 minutes

### Phase 4: Completion Cycling (Optional) ⏳
- [ ] Add `self._completion_state` to `__init__()`
- [ ] Track: (completions, current_index, original_text)
- [ ] Implement cycling logic in `_handle_tab_completion()`
- [ ] Reset state on non-Tab key press
- [ ] Test: Repeated Tab cycles through matches
- [ ] Test: Any other key resets cycle
- [ ] Test: Cycle wraps around to first match
- [ ] **Estimated time:** 20 minutes

### Phase 5: Visual Feedback (Optional) ⏳
- [ ] Add status line message for multiple completions
- [ ] Show "N completions: ..." when cycling
- [ ] Clear message after selection
- [ ] Test: Message appears on Tab press
- [ ] Test: Message clears on selection/timeout
- [ ] **Estimated time:** 30 minutes

---

## Testing Checklist

### Unit Tests
- [ ] Create `tests/test_tab_completion.py`
- [ ] Test: `test_tab_key_prevents_focus_loss()`
- [ ] Test: `test_single_match_completion()`
- [ ] Test: `test_multiple_match_common_prefix()`
- [ ] Test: `test_completion_cycling()`
- [ ] Test: `test_no_completer_allows_focus_change()`
- [ ] Test: `test_cursor_position_after_completion()`
- [ ] Test: `test_completion_with_trailing_whitespace()`

### Manual Testing in ppxaide
- [ ] Test: `/` + Tab → Shows/completes slash commands
- [ ] Test: `@` + Tab → Shows context providers
- [ ] Test: `/show @` + Tab → Shows context providers (critical!)
- [ ] Test: `@file` + Tab → Shows file list
- [ ] Test: Repeated Tab cycles through matches
- [ ] Test: Arrow keys don't interfere with completion
- [ ] Test: Tab without completer changes focus
- [ ] Test: Completion works mid-line (cursor not at end)

---

## Documentation Updates

### Required Documentation
- [ ] Update `docs/RELEASE-NOTES-v1.15.0.md`
  - Add "Readline-Style Tab Completion" section
  - Document behavior differences from textual-autocomplete
- [ ] Update `README.md`
  - Add Tab completion to ppxaide features list
- [ ] Update `CHANGELOG.md`
  - Add entry under [Unreleased]
- [ ] Update inline `/help` command
  - Document Tab key for completion
- [ ] Create `docs/TAB-COMPLETION-GUIDE.md` (optional)
  - User guide for Tab completion
  - Examples of usage patterns

---

## Code Review Checklist

Before marking as complete:
- [ ] All unit tests pass
- [ ] Manual testing confirms all patterns work
- [ ] No regressions in existing functionality
- [ ] Code follows project style guidelines
- [ ] No external dependencies added
- [ ] Documentation is clear and complete
- [ ] Commit messages follow conventional commits format
- [ ] User has tested and approved the feature

---

## Dependencies

### Required Code
- ✅ `ppxai/tui/completer.py` - Existing completer logic
- ✅ `ppxai/tui/widgets/input_box.py` - Widget to modify
- ✅ `pyproject.toml` - No new dependencies needed

### No External Dependencies
- ❌ `textual-autocomplete` - Removed (incompatible)
- ✅ `textual` - Already included
- ✅ Python stdlib - For common prefix logic

---

## Known Issues & Decisions

### Issue 1: textual-autocomplete Limitation
**Problem:** Library doesn't trigger on trailing whitespace
**Decision:** Implement custom readline-style completion
**Status:** ✅ Decision made, plan created

### Issue 2: Auto-complete vs Manual Tab
**Problem:** Users might expect IDE-style auto-complete
**Decision:** Use readline-style (Tab to trigger)
**Rationale:**
  - Works with all patterns
  - Familiar to terminal users
  - User controls when to complete
**Status:** ✅ Documented in plan

### Issue 3: Popup vs Cycling
**Problem:** How to show multiple completions
**Decision:** Start with cycling, add popup later if needed
**Rationale:**
  - Cycling is simpler (~20 lines)
  - Popup requires widget creation (~100 lines)
  - Can add popup in v1.16.0
**Status:** ✅ Documented in plan

---

## Deferred Features (v1.16.0+)

### Future Enhancements
- [ ] Popup overlay for multiple completions
- [ ] Inline hint (grayed-out text) showing next completion
- [ ] Fuzzy matching in completion search
- [ ] Completion history (prefer recent completions)
- [ ] Tab completion for file paths mid-command
- [ ] Customizable completion trigger key

---

## Rollback Plan

If implementation fails or causes issues:

1. **Revert commits:**
   ```bash
   git revert <commit-hash>
   ```

2. **Remove Tab handler:**
   - Remove `tab` case from `on_key()`
   - Remove completion methods
   - Keep `set_completer()` stub for compatibility

3. **Document decision:**
   - Update plan with failure reason
   - Mark as "Deferred indefinitely" if needed

---

## Success Criteria

### Must Have
- ✅ Tab completion works for `/`, `@`, `/show @`, `@file`
- ✅ Tab key doesn't lose focus
- ✅ No external dependencies
- ✅ All tests pass
- ✅ User confirms it works

### Should Have
- ✅ Common prefix insertion
- ✅ Multiple match handling
- ✅ Documentation complete

### Nice to Have
- ⏳ Completion cycling
- ⏳ Visual feedback
- ⏳ Status line hints

---

## Timeline

**Total estimated time:** 2-2.5 hours
- Phase 1: 30 min
- Phase 2: 20 min
- Phase 3: 40 min
- Phase 4: 20 min (optional)
- Phase 5: 30 min (optional)
- Testing: 20 min
- Documentation: 20 min

**Target completion:** After v1.15.0 release (not blocking)

---

## References

- Implementation plan: [docs/TAB-COMPLETION-IMPLEMENTATION-PLAN.md](TAB-COMPLETION-IMPLEMENTATION-PLAN.md)
- Current InputBox: [ppxai/tui/widgets/input_box.py](../ppxai/tui/widgets/input_box.py)
- Completer logic: [ppxai/tui/completer.py](../ppxai/tui/completer.py)
- Textual Key events: https://textual.textualize.io/guide/events/#key
