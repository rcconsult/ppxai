# Bug Report: Language Cycle Crash

**Created:** 2026-01-27
**Branch:** feature/new-tui-command
**Severity:** High - Crashes ppxaide TUI
**Status:** Open

---

## Description

The language cycling feature (Ctrl+L) in the side panel crashes ppxaide when cycling to languages that don't have corresponding tree-sitter packages installed.

## Error

```
LanguageDoesNotExist: tree-sitter is available, but no built-in or user-registered language called 'go'.
Ensure the language is installed (e.g. `pip install tree-sitter-ruby`)
Falling back to plain text.
```

## Stack Trace

```
/Users/rado/git/utils/ppxai/ppxai/tui/widgets/side_panel.py:276 in action_cycle_language
│ 276 │   │   │   editor.language = new_lang  # new_lang = 'go'

/Users/rado/git/utils/ppxai/ppxai/tui/widgets/code_editor.py:260 in language
│ 260 │   │   │   self._text_area.language = value  # value = 'go'

textual/widgets/_text_area.py:841 in _watch_language
textual/widgets/_text_area.py:1013 in _set_document
│ 1013 │   │   │   │   raise LanguageDoesNotExist(...)
```

## Root Cause

**File:** `ppxai/tui/widgets/code_editor.py:20-23`

```python
SUPPORTED_LANGUAGES = {
    "javascript", "sql", "rust", "xml", "json", "go", "yaml",
    "toml", "python", "regex", "html", "java", "bash", "css", "markdown"
}
```

This list includes 15 languages, but `pyproject.toml` only installs tree-sitter packages for 9:

**Installed:**
- ✅ tree-sitter-python
- ✅ tree-sitter-javascript
- ✅ tree-sitter-json
- ✅ tree-sitter-yaml
- ✅ tree-sitter-toml
- ✅ tree-sitter-html
- ✅ tree-sitter-css
- ✅ tree-sitter-markdown
- ✅ tree-sitter-bash

**Missing:**
- ❌ tree-sitter-go
- ❌ tree-sitter-sql
- ❌ tree-sitter-rust
- ❌ tree-sitter-xml
- ❌ tree-sitter-java
- ❌ tree-sitter-regex (not a standard package)

## Reproduction Steps

1. Run: `PPXAI_CONFIG_FILE=~/.ppxai/ppxai-config.json uv run ppxaide --trace`
2. Open any file in the side panel (e.g., via `/show .env`)
3. Press Ctrl+L to cycle languages
4. When it reaches 'go', the app crashes

## Impact

- **User Experience:** App crashes, loses work in progress
- **Language Cycling:** Feature is unusable for files that default to missing languages
- **Side Panel:** Cannot view files that trigger unsupported language detection

## Proposed Solutions

### Option 1: Remove Unsupported Languages (Quick Fix)

Update `SUPPORTED_LANGUAGES` to only include installed tree-sitter languages:

```python
SUPPORTED_LANGUAGES = {
    "bash", "css", "html", "javascript", "json",
    "markdown", "python", "toml", "yaml"
}
```

**Pros:**
- Immediate fix, no crashes
- No new dependencies
- 9 languages still covers most use cases

**Cons:**
- Users lose access to go, rust, sql, etc.

### Option 2: Install Missing Tree-Sitter Packages (Complete Fix)

Add to `pyproject.toml`:

```toml
tui = [
    "textual>=0.47.0",
    "textual-image>=0.8.0",
    # Existing
    "tree-sitter>=0.23",
    "tree-sitter-python>=0.25.0",
    "tree-sitter-javascript>=0.25.0",
    "tree-sitter-json>=0.24.8",
    "tree-sitter-yaml>=0.7.2",
    "tree-sitter-toml>=0.7.0",
    "tree-sitter-html>=0.23.2",
    "tree-sitter-css>=0.25.0",
    "tree-sitter-markdown>=0.5.1",
    "tree-sitter-bash>=0.25.1",
    # New
    "tree-sitter-go>=0.25.0",
    "tree-sitter-rust>=0.25.0",
    "tree-sitter-java>=0.25.0",
    # Note: sql, xml, regex may not have official packages
]
```

**Pros:**
- Full language support
- Better user experience

**Cons:**
- Increases dependencies (~5-10 MB)
- Longer install time
- Some languages (sql, xml, regex) may not have packages

### Option 3: Graceful Fallback (Robust Fix)

Wrap language setting in try/except:

```python
def action_cycle_language(self) -> None:
    """Cycle through syntax highlighting languages."""
    # ... existing code ...

    # Update the editor's language
    try:
        editor = self.query_one("#panel-editor", CodeEditor)
        try:
            editor.language = new_lang
        except LanguageDoesNotExist:
            # Language not installed, skip to next
            self.app.notify(
                f"Language '{new_lang}' not installed, skipping",
                title="Syntax",
                severity="warning"
            )
            # Recursively try next language
            self.action_cycle_language()
            return
    except NoMatches:
        pass  # Not in code mode
```

**Pros:**
- No crashes
- Keeps full language list for documentation
- Degrades gracefully

**Cons:**
- More complex logic
- Could loop if all languages missing (needs max attempts)

## Recommendation

**Short-term (v1.15.0):** Option 1 - Remove unsupported languages
**Long-term (v1.16.0):** Option 2 - Install missing packages (except sql/xml/regex if unavailable)

## Fix Checklist

- [ ] Update `SUPPORTED_LANGUAGES` in `ppxai/tui/widgets/code_editor.py`
- [ ] Test language cycling doesn't crash
- [ ] Update documentation to list supported languages
- [ ] Add tests for language cycling
- [ ] Verify `EXTENSION_TO_LANGUAGE` doesn't reference removed languages
- [ ] Consider adding runtime check: `TextArea.available_languages`

## Related Code

- **Bug location:** `ppxai/tui/widgets/side_panel.py:276`
- **Language list:** `ppxai/tui/widgets/code_editor.py:20-23`
- **Dependencies:** `pyproject.toml` (tui extra)
- **Documentation:** `CLAUDE.md` (lists installed tree-sitter packages)

## Testing

```bash
# Reproduce bug
uv run ppxaide --trace
# Open file, press Ctrl+L repeatedly

# After fix, verify no crashes
uv run ppxaide
# Open file, cycle through all languages with Ctrl+L
```

---

**Reporter:** User (rado)
**Assignee:** TBD
**Priority:** High (blocking v1.15.0 if language cycling is enabled)
