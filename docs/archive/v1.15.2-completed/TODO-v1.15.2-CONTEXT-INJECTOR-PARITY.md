# TODO: Context Injector Feature Parity (v1.15.2)

**Status:** Planning
**Priority:** Medium
**Effort:** Low (2-3 hours)
**Created:** 2026-01-29

## Overview

The engine fully supports 5 context injectors since v1.14.2, but UIs inconsistently expose them:

| Injector | Engine | Rich TUI | Textual TUI | VSCode | Web |
|----------|--------|----------|-------------|--------|-----|
| **@file** | ✅ v1.8.0 | ✅ Full | ✅ Full | ✅ Full | ✅ Full |
| **@git** | ✅ v1.11.4 | ⚠️ No UI | ⚠️ No UI | ✅ Full | ✅ Full |
| **@tree** | ✅ v1.11.4 | ⚠️ No UI | ⚠️ No UI | ✅ Full | ✅ Full |
| **@clipboard** | ✅ v1.14.2 | ❌ Hidden | ✅ Full | ❌ Hidden | ❌ Hidden |
| **@url** | ✅ v1.14.2 | ❌ Hidden | ✅ Full | ❌ Hidden | ❌ Hidden |

**Problem:** Users cannot discover `@clipboard` and `@url` in most clients, and TUIs don't expose `@git`/`@tree` in autocomplete despite working when typed manually.

**Goal:** Achieve 100% feature parity - all 5 injectors autocomplete + documented in all 4 clients.

## Current State Analysis

### Engine (✅ Complete)
- **File:** [ppxai/engine/context.py](../ppxai/engine/context.py)
- **Status:** All 5 injectors fully implemented with hash deduplication, size limits, truncation

### Rich TUI (⚠️ 1/5 Complete)
- **File:** [ppxai/rich/main.py](../ppxai/rich/main.py:167-331)
- **Has:** `@file` only in autocomplete
- **Missing:** `@git`, `@tree`, `@clipboard`, `@url` autocomplete
- **Hint text:** [Line 691](../ppxai/rich/main.py:691) - Only mentions `@file`
- **Comment:** [Line 738](../ppxai/rich/main.py:738) - Outdated, only mentions 3 injectors

### Textual TUI (⚠️ 3/5 Complete)
- **File:** [ppxai/tui/completer.py](../ppxai/tui/completer.py:26-30)
- **Has:** `@file`, `@clipboard`, `@url` in `CONTEXT_PROVIDERS`
- **Missing:** `@git`, `@tree` autocomplete

### VSCode Extension (⚠️ 3/5 Complete)
- **File:** [vscode-extension/src/chatPanel.ts](../vscode-extension/src/chatPanel.ts)
- **Has:** `@file`, `@git`, `@tree` in autocomplete (lines 348-351) and help (lines 1834-1836)
- **Missing:** `@clipboard`, `@url` in autocomplete and help

### Web App (⚠️ 3/5 Complete)
- **File:** [ppxai/web/app.js](../ppxai/web/app.js)
- **Has:** `@file`, `@git`, `@tree` in autocomplete (lines 2198-2199, 2210-2211) and help (lines 1141-1143)
- **Missing:** `@clipboard`, `@url` in autocomplete and help

## Action Items

### 1. Rich TUI - Add All Special Providers (⚠️ Priority 1)

**File:** [ppxai/rich/main.py](../ppxai/rich/main.py)

#### 1.1 Update Autocomplete (Lines 314-331)
Replace file-only autocomplete with special providers + files:

```python
def get_completions(self, document, complete_event):
    text = document.text_before_cursor

    # Check for @reference anywhere in the text
    at_pos = text.rfind('@')
    if at_pos >= 0:
        query = text[at_pos + 1:].lower()

        # Special context providers (NEW)
        CONTEXT_PROVIDERS = [
            ('git', 'Include git diff (staged + unstaged)'),
            ('tree', 'Include project directory structure'),
            ('clipboard', 'Include clipboard text content'),
            ('url', 'Fetch and include URL content'),
        ]

        # Show special providers first
        for provider, desc in CONTEXT_PROVIDERS:
            if provider.startswith(query):
                replace_len = len(text) - at_pos
                yield Completion(
                    f'@{provider}',
                    start_position=-replace_len,
                    display=f'@{provider}',
                    display_meta=desc
                )

        # Then show file completions (existing logic)
        for filename, filepath in self._get_files():
            if not query or query in filename.lower() or query in filepath.lower():
                replace_len = len(text) - at_pos
                yield Completion(
                    '@' + filename,
                    start_position=-replace_len,
                    display=filename,
                    display_meta=filepath
                )
        return

    # ... rest of command autocomplete logic
```

#### 1.2 Update Hint Text (Line 691)
```python
# OLD
console.print("[dim]Tab: autocomplete • @file: reference files • ↑/↓: history • Ctrl-C twice to exit[/dim]\n")

# NEW
console.print("[dim]Tab: autocomplete • @file/@git/@tree/@clipboard/@url: inject context • ↑/↓: history • Ctrl-C twice to exit[/dim]\n")
```

#### 1.3 Update Code Comment (Line 738)
```python
# OLD
# This ensures @git/@tree/@file context injection always works

# NEW
# This ensures @file/@git/@tree/@clipboard/@url context injection always works
```

---

### 2. Textual TUI - Add Git/Tree Providers (⚠️ Priority 2)

**File:** [ppxai/tui/completer.py](../ppxai/tui/completer.py)

#### 2.1 Update CONTEXT_PROVIDERS (Lines 26-30)
```python
# OLD
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

---

### 3. VSCode Extension - Add Clipboard/URL (⚠️ Priority 3)

**File:** [vscode-extension/src/chatPanel.ts](../vscode-extension/src/chatPanel.ts)

#### 3.1 Update File Picker Autocomplete (Lines 348-351)
```typescript
// OLD
{ name: '@git', path: 'Include git diff' },
{ name: '@tree', path: 'Include project structure' },

// NEW
{ name: '@git', path: 'Include git diff' },
{ name: '@tree', path: 'Include project structure' },
{ name: '@clipboard', path: 'Include clipboard contents' },
{ name: '@url', path: 'Fetch URL contents (e.g., @https://...)' },
```

#### 3.2 Update Help Text (Lines 1834-1836)
```typescript
// OLD
helpText += '- `@file` - Reference a file\n';
helpText += '- `@git` - Include git diff\n';
helpText += '- `@tree` - Include project structure\n';

// NEW
helpText += '- `@file` - Reference a file\n';
helpText += '- `@git` - Include git diff\n';
helpText += '- `@tree` - Include project structure\n';
helpText += '- `@clipboard` - Include clipboard contents\n';
helpText += '- `@url` - Fetch URL contents (e.g., @https://example.com)\n';
```

#### 3.3 Update Special Providers List (Line 544)
```typescript
// OLD
const specialContextProviders = ['tree', 'git'];

// NEW
const specialContextProviders = ['tree', 'git', 'clipboard', 'url'];
```

**Note:** URL pattern detection should skip `@url` prefix when checking for actual URLs:
- `@clipboard` → Skip, let backend handle
- `@url` → Skip, let backend handle
- `@https://...` → This is the actual URL pattern (already handled by backend)

---

### 4. Web App - Add Clipboard/URL (⚠️ Priority 4)

**File:** [ppxai/web/app.js](../ppxai/web/app.js)

#### 4.1 Update Autocomplete Fallback (Lines 2198-2199)
```javascript
// OLD
{ label: '@git', description: 'Include git diff', value: '@git' },
{ label: '@tree', description: 'Include project structure', value: '@tree' },

// NEW
{ label: '@git', description: 'Include git diff', value: '@git' },
{ label: '@tree', description: 'Include project structure', value: '@tree' },
{ label: '@clipboard', description: 'Include clipboard contents', value: '@clipboard' },
{ label: '@url', description: 'Fetch URL (e.g., @https://...)', value: '@url' },
```

#### 4.2 Update Second Fallback (Lines 2210-2211)
Same change as 4.1 (code appears twice)

#### 4.3 Update Help Text (Lines 1141-1143)
```javascript
// OLD
helpText += '- `@file` - Reference a file\n';
helpText += '- `@git` - Include git diff\n';
helpText += '- `@tree` - Include project structure\n';

// NEW
helpText += '- `@file` - Reference a file\n';
helpText += '- `@git` - Include git diff\n';
helpText += '- `@tree` - Include project structure\n';
helpText += '- `@clipboard` - Include clipboard contents\n';
helpText += '- `@url` - Fetch URL contents (e.g., @https://example.com)\n';
```

---

### 5. Update Shared Command Definitions (Optional)

**Files:**
- [vscode-extension/src/shared/commands.ts](../vscode-extension/src/shared/commands.ts:164,169,184)
- [ppxai/web/shared/commands.js](../ppxai/web/shared/commands.js:146,151,166)

Update usage strings that mention `@file` to include other providers:

```typescript
// Example: /test command
usage: '/test <code or @file/@git>',
```

---

## Testing Checklist

### Per-Client Testing

For **each client** (Rich TUI, Textual TUI, VSCode, Web):

#### Autocomplete Tests
- [ ] Type `@` → Shows all 5 providers in autocomplete
- [ ] Type `@f` → Shows `@file` + files starting with 'f'
- [ ] Type `@g` → Shows `@git` provider
- [ ] Type `@t` → Shows `@tree` provider
- [ ] Type `@c` → Shows `@clipboard` provider
- [ ] Type `@u` → Shows `@url` provider
- [ ] Type `@http` → Shows URL suggestion or files matching "http"
- [ ] Tab completion works for each provider
- [ ] Autocomplete doesn't break file path completion

#### Functional Tests
- [ ] `@file` - Injects file content correctly
- [ ] `@git` - Shows git diff when typed manually
- [ ] `@tree` - Shows directory tree when typed manually
- [ ] `@clipboard` - Injects clipboard content (requires pyperclip)
- [ ] `@https://example.com` - Fetches URL content (requires httpx)
- [ ] Multiple providers in one message work (e.g., `@git @tree`)
- [ ] Context deduplication works (same content not injected twice)
- [ ] Size limits respected (100KB per file, 200KB total)

#### UI/Help Tests
- [ ] `/help` shows all 5 context providers
- [ ] Hint/status text mentions context providers
- [ ] Error messages for missing dependencies (clipboard, URL fetch)

### Integration Tests
- [ ] All clients produce identical behavior for same input
- [ ] Backend `context_injected` events emitted for all providers
- [ ] `/context show` command lists all injected contexts correctly

---

## Dependencies

### Already Installed
- `httpx` - Required for `@url` (already in requirements)
- `pyperclip` - Required for `@clipboard` (already in requirements)

### Platform Notes
- **Clipboard (Linux):** Requires `xclip` or `xsel` installed
- **Clipboard (macOS/Windows):** Works out of the box with pyperclip
- **URL Fetching:** Requires network access

---

## Documentation Updates

### Files to Update
1. [docs/context-injection.md](../docs/context-injection.md)
   - Already documents all 5 providers correctly ✅
   - No changes needed

2. [README.md](../README.md)
   - Check if context providers are mentioned
   - Update examples if needed

3. [CLAUDE.md](../CLAUDE.md)
   - Update v1.14.2 highlights to emphasize all clients now expose `@clipboard/@url`

4. [CHANGELOG.md](../CHANGELOG.md)
   - Add v1.15.2 entry:
     ```markdown
     ## [1.15.2] - YYYY-MM-DD
     ### Added
     - Context injector feature parity: All clients now expose @clipboard and @url in autocomplete
     - Rich TUI: Added @git, @tree, @clipboard, @url to autocomplete
     - Textual TUI: Added @git, @tree to autocomplete
     - VSCode/Web: Added @clipboard, @url to autocomplete and help text

     ### Fixed
     - Inconsistent context provider discovery across clients
     ```

---

## Estimated Effort

| Task | Files | Lines Changed | Time |
|------|-------|---------------|------|
| Rich TUI autocomplete | 1 | ~30 | 30 min |
| Rich TUI hints/comments | 1 | ~3 | 5 min |
| Textual TUI providers | 1 | ~2 | 5 min |
| VSCode autocomplete | 1 | ~5 | 10 min |
| VSCode help text | 1 | ~3 | 5 min |
| Web autocomplete | 1 | ~8 | 10 min |
| Web help text | 1 | ~3 | 5 min |
| Testing (all clients) | - | - | 60 min |
| Documentation | 2-3 | ~10 | 15 min |
| **Total** | **~8 files** | **~64 lines** | **~2.5 hours** |

---

## Success Criteria

- [ ] All 4 clients show identical autocomplete for `@` (5 providers + files)
- [ ] All help texts mention all 5 context providers
- [ ] All functional tests pass for all providers in all clients
- [ ] Documentation updated (CHANGELOG, CLAUDE.md if needed)
- [ ] No regressions in existing `@file` functionality
- [ ] Code comments accurate (no outdated provider lists)

---

## Notes

### Why This Matters
- **Discoverability:** Users can't use features they don't know exist
- **Consistency:** Same UX across all clients reduces confusion
- **Documentation:** Help text matches implementation reality

### Design Decision: URL Pattern
The `@url` autocomplete suggestion is educational - users should type:
- `@https://example.com` (actual syntax)
- NOT `@url https://example.com` (would be clearer but changes existing behavior)

Backend already handles URL pattern detection via regex: `r'@(https?://[^\s<>\"\']+)'`

### Backward Compatibility
- All changes are additive (new autocomplete entries)
- No breaking changes to existing behavior
- Users who type providers manually will see no difference

---

## Related Documents

- [docs/context-injection.md](../docs/context-injection.md) - User-facing guide (already complete)
- [docs/bootstrap-context-guide.md](../docs/bootstrap-context-guide.md) - Bootstrap context (different feature)
- [ppxai/engine/context.py](../ppxai/engine/context.py) - Implementation reference
- [CHANGELOG.md](../CHANGELOG.md) - Release notes

---

## Implementation Order

1. **Start with TUIs** (quickest wins, most users)
   - Rich TUI autocomplete + hints
   - Textual TUI providers list

2. **Then Web/VSCode** (shared users)
   - VSCode autocomplete + help
   - Web autocomplete + help

3. **Test thoroughly** (critical for UX)
   - Per-client functional tests
   - Cross-client consistency tests

4. **Update docs** (final step)
   - CHANGELOG entry
   - CLAUDE.md if needed

---

**Ready to implement:** All changes are small, isolated, and low-risk. No architectural changes needed - engine already supports everything.
