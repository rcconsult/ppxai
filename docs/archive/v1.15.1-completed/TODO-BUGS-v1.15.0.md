# TODO: Bug Fixes for v1.15.0

**Created:** 2026-01-27
**Branch:** feature/new-tui-command
**Status:** In Progress

---

## Critical Bugs

### 1. Language Cycle Crash ✅ RESOLVED

**File:** `BUG-LANGUAGE-CYCLE-CRASH.md`
**Status:** ✅ Resolved (2026-01-27)
**Severity:** High - Crashes ppxaide TUI
**Blocking:** No (fixed)

**Issue:** Ctrl+L language cycling crashed when reaching unsupported languages (go, rust, sql, xml, java, regex).

**Root Cause:** `SUPPORTED_LANGUAGES` included 15 languages, but only 9 tree-sitter packages were installed.

**Resolution:** Added all 15 tree-sitter packages to `pyproject.toml`:
- [x] tree-sitter-go, tree-sitter-rust, tree-sitter-java
- [x] tree-sitter-sql, tree-sitter-xml, tree-sitter-regex
- [x] All 15 languages now work correctly
- [x] Commit: 6eb83e2

**Verified:** Language cycling (Ctrl+L) works for all languages

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
- [x] ppxaide launches without crash
- [x] Language cycling (Ctrl+L) doesn't crash
- [x] All 15 supported languages work correctly
- [x] Theme cycling (Ctrl+T) works
- [x] File viewing in side panel works
- [x] Markdown rendering works
- [x] Code syntax highlighting works

### Integration Tests
- [x] TUI + engine integration works
- [x] Command execution works
- [x] Session save/load works
- [x] Bootstrap context loads
- [x] Token/cost tracking displays

### Regression Tests
- [x] Rich TUI (ppxai) still works
- [x] Server (ppxai-server) still works
- [x] VSCode extension still connects
- [x] All 1105 tests pass

---

## References

- Bug reports: `BUG-*.md` files in root
- Release notes: `docs/RELEASE-NOTES-v1.15.0.md`
- Phase 7 plan: `docs/PHASE-7-POLISH-RELEASE.md`
- CHANGELOG: `CHANGELOG.md`
