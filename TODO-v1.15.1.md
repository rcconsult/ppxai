# TODO: v1.15.1 Bug Fixes

**Created:** 2026-01-28
**Branch:** feature/1-15-1
**Status:** In Progress
**Previous Release:** v1.15.0

---

## Issues to Address

### 1. VSCode Extension - Unused Imports

**Source:** CI build warnings
**Severity:** Low - No functional impact, just code cleanup
**File:** `vscode-extension/src/chatPanel.ts`

**Warnings:**
```
vscode-extension/src/chatPanel.ts#L17: 'SLASH_COMMANDS' is defined but never used
vscode-extension/src/chatPanel.ts#L19: 'isAIForwardedCommand' is defined but never used
vscode-extension/src/chatPanel.ts#L20: 'parseCommand' is defined but never used
vscode-extension/src/chatPanel.ts#L23: 'formatToolsStatus' is defined but never used
vscode-extension/src/chatPanel.ts#L24: 'formatToolsList' is defined but never used
vscode-extension/src/chatPanel.ts#L25: 'formatToolConfig' is defined but never used
vscode-extension/src/chatPanel.ts#L26: 'formatToolHelp' is defined but never used
vscode-extension/src/chatPanel.ts#L27: 'formatAgentStatus' is defined but never used
vscode-extension/src/chatPanel.ts#L28: 'formatCheckpointStatus' is defined but never used
vscode-extension/src/chatPanel.ts#L29: 'formatCheckpointList' is defined but never used
```

**Resolution:**
- [ ] Remove unused imports from chatPanel.ts
- [ ] Verify no regressions in VSCode extension functionality
- [ ] Run TypeScript lint to confirm no warnings

---

### 2. CI Workflow - Already Fixed in v1.15.0

**Status:** ✅ Fixed in v1.15.0 release

The following fixes were applied during v1.15.0 release:

1. **CI test dependency fix** (commit 874c4fb)
   - Changed `uv sync --frozen --dev` to `uv sync --frozen --all-extras`
   - Ensures blinker and TUI dependencies are installed for tests

2. **PyInstaller spec file update** (commit a607df8)
   - Removed non-existent modules (ppxai.main, ppxai.commands.ui, etc.)
   - Added new v1.15.0 modules (commands.factory, rendering.base, etc.)

---

## Testing Checklist

Before releasing v1.15.1:

- [ ] All 1105 tests pass
- [ ] TypeScript lint shows 0 warnings
- [ ] VSCode extension works correctly
- [ ] All v1.15.0 features still work

---

## Release Checklist

- [ ] Update CHANGELOG.md with v1.15.1 entry
- [ ] Create docs/RELEASE-NOTES-v1.15.1.md
- [ ] Merge to master
- [ ] Run `/release v1.15.1`

---

## References

- v1.15.0 release: https://github.com/rcconsult/ppxai/releases/tag/v1.15.0
- CI fix commit: 874c4fb
- PyInstaller fix commit: a607df8
