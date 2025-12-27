# Bug Report: False Documentation in v1.11.9 Release

**Investigation Date:** 2025-12-27
**Branch:** master (investigating v1.11.9 release)
**Issue Type:** Documentation Drift / False Claims

---

## Executive Summary

The v1.11.9 release (2025-12-27) documented several agent mode features that were **never actually implemented**. The release was essentially a version number bump with aspirational documentation rather than functional code changes.

---

## False Claims in v1.11.9 Documentation

### 1. `/agent on|off` Toggle Command Fix

**Claimed in:**
- [docs/RELEASE-NOTES-v1.11.9.md:11-13](../docs/RELEASE-NOTES-v1.11.9.md#L11-L13)
- [CLAUDE.md:12-14](../CLAUDE.md#L12-L14)

**Claim:**
> **CRITICAL FIX:** `/agent on|off` now correctly toggles agent mode instead of being interpreted as tasks
> - Previously, typing `/agent off` would cause AI to search for things to turn "off" (including killing server processes!)
> - Now properly recognized as toggle commands in both TUI and VSCode extension

**Reality:**
- ❌ NO code changes in [ppxai/commands.py](../ppxai/commands.py) for v1.11.9
- ❌ TUI had TWO blocking bugs preventing agent mode from working at all
- ✅ VSCode extension NEVER had this bug (uses GUI buttons, not text parsing)

**Actual Implementation:** Fixed in v1.12.0 development (2025-12-27 evening) with:
1. Missing logger argument bug fix at line 1398
2. Toggle command routing logic at lines 1349-1353

---

### 2. Agent Configuration Settings

**Claimed in:**
- [docs/RELEASE-NOTES-v1.11.9.md:23-27](../docs/RELEASE-NOTES-v1.11.9.md#L23-L27)
- [ppxai-config.example.json:273-285](../ppxai-config.example.json#L273-L285)

**Claim:**
> **NEW:** Configurable agent settings via `ppxai-config.json`:
> - `tools.agent.max_iterations` (default: 10) - Maximum agent loop iterations
> - `tools.agent.context_char_limit` (default: 2000) - Character limit for context display
> - `tools.agent.min_task_words` (default: 3) - Minimum words required for agent tasks

**Reality:**
- ❌ Config options documented but NOT loaded by engine
- ❌ No code reads `min_task_words` from config
- ❌ No validation for single-word prompts
- ❌ `max_iterations` is hardcoded in ToolManager
- ❌ `context_char_limit` never used

**Code Evidence:**
```python
# ppxai/engine/client.py:108-118 (v1.11.9)
full_config = load_config()
self._shell_config = full_config.get("tools", {}).get("shell", {})
# ❌ MISSING: agent config is NOT loaded
```

**What Actually Works:**
- ✅ `checkpoint_backend` - Loaded and used (v1.12.0)
- ✅ `checkpoint_message` - Loaded and used (v1.12.0)
- ❌ `max_iterations` - NOT loaded (hardcoded default: 5)
- ❌ `context_char_limit` - NOT loaded
- ❌ `min_task_words` - NOT loaded

---

### 3. `/agent/config` API Endpoint

**Claimed in:**
- [docs/RELEASE-NOTES-v1.11.9.md:27](../docs/RELEASE-NOTES-v1.11.9.md#L27)

**Claim:**
> - **`/agent/config` API endpoint** for retrieving agent configuration

**Reality:**
- ❌ Endpoint does NOT exist in [ppxai/server/http.py](../ppxai/server/http.py)
- ❌ No route registered for `/agent/config`
- ❌ No tests for this endpoint

**Existing Endpoints (v1.11.9):**
- ✅ `GET /agent/status` - Agent mode + tools status
- ✅ `POST /agent/enable` - Enable agent mode
- ✅ `POST /agent/disable` - Disable agent mode
- ❌ `GET /agent/config` - **DOES NOT EXIST**

---

### 4. Minimum Word Count Validation

**Claimed in:**
- [docs/RELEASE-NOTES-v1.11.9.md:17-18](../docs/RELEASE-NOTES-v1.11.9.md#L17-L18)

**Claim:**
> - **Minimum word count validation** (default: 3 words) rejects vague single-word tasks
> - `min_task_words` added to built-in dangerous shell patterns

**Reality:**
- ❌ NO word count validation in chat handlers
- ❌ NO warnings for single-word prompts
- ❌ NO code checks `min_task_words` config value

**Search Results:**
```bash
$ grep -r "min_task_words" ppxai/
# NO RESULTS (except in comments and config example)
```

---

## Git History Timeline

### v1.11.9 Release Sequence

1. **2025-12-27 01:36** - Commit `4c5903c` - "feat: v1.11.9 release"
   - Changed files: Version numbers only
   - No functional code changes
   - Empty release notes template

2. **2025-12-27 02:10** - Commit `5cdee38` - "docs: Add proper v1.11.9 release notes"
   - **All false claims added here**
   - No corresponding code implementation
   - Aspirational documentation

3. **2025-12-27 21:43** - Commit `aa6076c` - "docs(v1.12.0): Add agent checkpoint configuration"
   - **Part of v1.12.0 feature branch**
   - Config comment misleadingly says "v1.11.9+"
   - Implementation: Only checkpoint features work

---

## Actual Bugs Fixed in v1.12.0 (Not v1.11.9)

### Bug #1: Missing Logger Argument

**Location:** [ppxai/commands.py:1398](../ppxai/commands.py#L1398)

**Error:**
```python
Unexpected error: TUIEventHandler.__init__() missing 1 required positional argument: 'logger'
```

**Fix:**
```python
# BEFORE (v1.11.9 - BROKEN):
event_handler = TUIEventHandler(console, verbose=self.tools_verbose)

# AFTER (v1.12.0 - FIXED):
event_handler = TUIEventHandler(console, self.logger, verbose=self.tools_verbose)
```

**Impact:** Agent mode completely broken in TUI (immediate crash)

---

### Bug #2: Toggle Command Misinterpretation

**Location:** [ppxai/commands.py:1349-1353](../ppxai/commands.py#L1349-L1353)

**Problem:** `/agent on` treated as task description "on" instead of toggle command

**Fix:**
```python
# v1.12.0: Redirect toggle commands to /tools agent handler
first_word = args.strip().split()[0].lower()
if first_word in ["on", "off", "enable", "disable"]:
    self._tools_agent([first_word])
    return
```

**Impact:** User confusion, dangerous unintended behavior

---

## Why VSCode Extension Never Had These Bugs

The VSCode extension uses GUI buttons that directly call HTTP API endpoints:

```typescript
// vscode-extension/src/httpClient.ts:792-811
async enableAgentMode(): Promise<boolean> {
    const response = await fetch(`${this.baseUrl}/agent/enable`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    });
    // ...
}

async disableAgentMode(): Promise<boolean> {
    const response = await fetch(`${this.baseUrl}/agent/disable`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    });
    // ...
}
```

**No text parsing**, so no toggle command ambiguity.

---

## Documentation vs Implementation Gap

| Feature | Documented | Implemented | Version |
|---------|-----------|-------------|---------|
| `/agent on/off` toggle | v1.11.9 | v1.12.0 | FALSE CLAIM |
| `min_task_words` config | v1.11.9 | NEVER | FALSE CLAIM |
| `max_iterations` config | v1.11.9 | NEVER | FALSE CLAIM |
| `context_char_limit` config | v1.11.9 | NEVER | FALSE CLAIM |
| `/agent/config` endpoint | v1.11.9 | NEVER | FALSE CLAIM |
| Minimum word validation | v1.11.9 | NEVER | FALSE CLAIM |
| Checkpoint backend | v1.12.0 | v1.12.0 | ✅ ACCURATE |
| Checkpoint message | v1.12.0 | v1.12.0 | ✅ ACCURATE |

---

## Recommendations

### Immediate Actions

1. **Correct v1.11.9 documentation**
   - Remove false claims about toggle fix
   - Remove claims about unimplemented config features
   - Add note: "v1.11.9 was a version bump with no functional changes"

2. **Update v1.12.0 release notes**
   - Clearly state: "Fixes `/agent on|off` toggle (NOT fixed in v1.11.9 as claimed)"
   - Document actual first implementation of agent config loading

3. **Implement missing features OR remove documentation**
   - Either wire up `min_task_words`, `max_iterations`, `context_char_limit`
   - OR remove them from config examples and docs

### Process Improvements

1. **Release validation script**
   - Verify all documented features have corresponding tests
   - Grep codebase for config keys mentioned in release notes
   - Check API endpoints actually exist

2. **Documentation-code sync check**
   - CI check: Config examples must have code that loads them
   - API endpoint docs must match registered routes

3. **Honest release notes**
   - "Planned" section for aspirational features
   - "Implemented" section for actual code changes
   - Never claim features are done before they're tested

---

## Impact Assessment

### User Impact

- **Confusion:** Users expect features that don't exist
- **Bug reports:** "Config not working" → because it's not implemented
- **Trust:** Documentation doesn't match reality

### Developer Impact

- **Wasted debugging time:** Investigating why "documented features" don't work
- **Code archaeology:** Need to verify every claim in release notes

### Project Health

- **Technical debt:** Documentation promises not kept
- **Quality signal:** Tests passing ≠ features working

---

## Verification Commands

```bash
# Verify /agent on|off fix status
git show 4c5903c:ppxai/commands.py | grep -A 5 "def handle_agent"
# Result: No toggle command routing logic

# Verify config loading
git show 4c5903c:ppxai/engine/client.py | grep -A 10 "agent.*config"
# Result: Only shell config loaded, no agent config

# Verify API endpoints
git show 4c5903c:ppxai/server/http.py | grep "@app.*agent"
# Result: Only /agent/status, /agent/enable, /agent/disable (no /config)

# Search for min_task_words usage
git show 4c5903c:ppxai/ | grep -r "min_task_words"
# Result: ZERO usages (only in comments)
```

---

## Conclusion

**v1.11.9 was a documentation-only release with false claims.** The advertised features were either:
1. Never implemented (config loading, validation, API endpoint)
2. Implemented later in v1.12.0 (toggle fix, checkpoint system)
3. Only present in VSCode extension, not TUI (agent toggle)

This represents a significant documentation drift event that should be corrected and prevented in future releases.

---

**Document Author:** Claude Sonnet 4.5 (via ppxai debugging session)
**Investigation Context:** Manual TUI testing revealed agent mode crashes
**Artifacts:** Terminal logs showing missing logger crash + toggle command bug
**Git Analysis:** Complete history review from v1.11.8 through v1.12.0 feature branch
