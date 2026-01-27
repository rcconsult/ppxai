# TODO: Bug Fixes for v1.15.0

**Created:** 2026-01-27
**Branch:** feature/new-tui-command
**Status:** In Progress

---

## Critical Bugs

### 1. Language Cycle Crash ⚠️ HIGH PRIORITY

**File:** `BUG-LANGUAGE-CYCLE-CRASH.md`
**Status:** ⏳ Open
**Severity:** High - Crashes ppxaide TUI
**Blocking:** Yes (if language cycling is enabled)

**Issue:** Ctrl+L language cycling crashes when reaching unsupported languages (go, rust, sql, xml, java, regex).

**Root Cause:** `SUPPORTED_LANGUAGES` includes 15 languages, but only 9 tree-sitter packages are installed.

**Quick Fix:**
- [ ] Remove unsupported languages from `SUPPORTED_LANGUAGES` in `ppxai/tui/widgets/code_editor.py`
- [ ] Keep only: bash, css, html, javascript, json, markdown, python, toml, yaml
- [ ] Test language cycling with Ctrl+L
- [ ] Verify no references to removed languages in `EXTENSION_TO_LANGUAGE`
- [ ] Update documentation

**Timeline:** 30 minutes
**Assignee:** TBD

---

## Medium Priority Bugs

(None currently)

---

## Low Priority Bugs

(None currently)

---

## Bug Fix Process

1. **Report:** Create `BUG-{name}.md` with details
2. **Triage:** Add to this TODO with priority
3. **Fix:** Implement solution and test
4. **Verify:** Check no regressions
5. **Document:** Update CHANGELOG
6. **Close:** Mark bug as resolved

---

## Resolved Bugs

(None yet)

---

## Testing Checklist

Before marking v1.15.0 ready for release:

### Critical Features
- [ ] ppxaide launches without crash
- [ ] Language cycling (Ctrl+L) doesn't crash
- [ ] All 9 supported languages work correctly
- [ ] Theme cycling (Ctrl+T) works
- [ ] File viewing in side panel works
- [ ] Markdown rendering works
- [ ] Code syntax highlighting works

### Integration Tests
- [ ] TUI + engine integration works
- [ ] Command execution works
- [ ] Session save/load works
- [ ] Bootstrap context loads
- [ ] Token/cost tracking displays

### Regression Tests
- [ ] Rich TUI (ppxai) still works
- [ ] Server (ppxai-server) still works
- [ ] VSCode extension still connects
- [ ] All 1105 tests pass

---

## References

- Bug reports: `BUG-*.md` files in root
- Release notes: `docs/RELEASE-NOTES-v1.15.0.md`
- Phase 7 plan: `docs/PHASE-7-POLISH-RELEASE.md`
- CHANGELOG: `CHANGELOG.md`
