# Release Notes - v1.11.2

**Release Date**: 2025-12-22
**Type**: Security & UX Enhancement Release
**Priority**: High - Adds critical shell command security

---

## Overview

v1.11.2 introduces a comprehensive **shell command consent system** to protect users from potentially dangerous or destructive shell commands executed by AI. This release also includes a critical security fix for command pattern matching and enhances the VSCode extension with a keyboard-friendly consent interface.

---

## Security Features

### 🔒 Shell Command Consent System

A consent-based security system for shell commands executed by AI tools.

**Command Classification**:
- **Safe Commands** (auto-approved): Read-only operations like `ls`, `cat`, `pwd`, `grep`
- **Dangerous Commands** (require consent): Operations like `rm`, `mv`, `chmod`, `sudo`, `curl | bash`
- **Never-Allow Commands** (always blocked): Catastrophic operations like `rm -rf /`, `dd of=/dev/`, fork bombs

**Consent Flow**:
1. AI requests to execute a shell command
2. ppxai classifies the command using regex patterns
3. Safe commands execute automatically
4. Dangerous commands prompt for user consent (y/n/always/never)
5. Never-allow commands are blocked immediately

**User Interface**:
- **TUI**: Interactive prompt with 4 options (y/n/always/never)
- **VSCode**: Keyboard-friendly QuickPick dropdown (no mouse needed!)

**Session-Scoped Consent**:
- Consent decisions persist for the session
- Choose "always" to approve all future uses of a command
- Choose "never" to block all future uses of a command
- Restart to reset all consent decisions

**Configuration**: Customize patterns in `ppxai-config.json`:
```json
{
  "tools": {
    "shell": {
      "require_consent": true,
      "allowed_commands": ["^ls\\s+", "^cat\\s+(?!.*[><])"],
      "dangerous_commands": ["^rm\\s+", "^mv\\s+", "^chmod\\s+"],
      "never_allow": ["rm\\s+-rf\\s+/", "dd\\s+.*of=/dev/"]
    }
  }
}
```

**Files Changed**:
- `ppxai/engine/client.py` - Added `request_shell_consent()` and `_classify_shell_command()`
- `ppxai/engine/session.py` - Added shell consent state tracking
- `ppxai/engine/tools/builtin/shell.py` - Integrated consent checks
- `ppxai/commands.py` - Added TUI consent handler
- `ppxai/server/http.py` - Added `/shell-consent` endpoint
- `vscode-extension/src/chatPanel.ts` - Added QuickPick consent UI
- `ppxai-config.json` - Added default shell patterns
- `ppxai-config.example.json` - Added shell configuration template

**Documentation**: See [docs/shell-consent-guide.md](shell-consent-guide.md)

---

## Critical Security Fix

### 🛡️ Fixed: Command Redirection Bypass

**Issue**: Commands with file redirections (`cat > file`, `echo data > file`) were incorrectly classified as SAFE and bypassed consent.

**Root Cause**: Regex patterns `^cat\s+` and `^echo\s+` were too permissive and matched commands with dangerous redirections.

**Fix**: Updated patterns to use negative lookahead:
- `^cat\s+(?!.*[><])` - Only matches cat for reading, excludes redirections
- `^echo\s+(?!.*>)` - Only matches echo without output redirection

**Impact**: File-writing operations now properly require user consent.

**Security Severity**: High - Could have allowed AI to write arbitrary files without consent

**Files Changed**:
- `ppxai-config.json` - Fixed allowed_commands patterns
- `ppxai-config.example.json` - Fixed allowed_commands patterns
- `docs/shell-consent-guide.md` - Documented pattern syntax

---

## UX Improvements

### ⌨️ Keyboard-Friendly Consent UI (VSCode)

Replaced modal dialogs with keyboard-friendly QuickPick interface.

**Before**:
- Blocking modal popup in center of screen
- Required mouse click to select option
- Interrupted workflow

**After**:
- Non-blocking dropdown at top of screen
- Fully keyboard-driven navigation
- Arrow keys or type to select
- Similar to Command Palette UX

**Visual Design**:
- Icons: `$(check)` Yes, `$(x)` No, `$(check-all)` Always, `$(circle-slash)` Never
- Risk indicators in placeholder (⚠️ DANGEROUS, 🛑 BLOCKED, ✅ SAFE)
- Command preview (truncated to 50 chars)
- Directory context in title

**Applies To**:
- Shell command consent
- File editing consent

**Files Changed**:
- `vscode-extension/src/chatPanel.ts` - Replaced modal with QuickPick

---

## Configuration Updates

### 📝 Shell Configuration Schema

Added `tools.shell` configuration section to `ppxai-config.json`:

```json
{
  "tools": {
    "shell": {
      "require_consent": true,
      "dangerous_commands": [
        "^rm\\s+",
        "^mv\\s+",
        "^dd\\s+",
        "^chmod\\s+",
        "^chown\\s+",
        "^sudo\\s+",
        "^curl.*\\|.*bash",
        "^wget.*\\|.*bash",
        ">\\s*/dev/",
        "^kill\\s+",
        "^pkill\\s+",
        "^killall\\s+"
      ],
      "allowed_commands": [
        "^ls\\s+",
        "^cat\\s+(?!.*[><])",
        "^grep\\s+",
        "^echo\\s+(?!.*>)",
        "^pwd$",
        "^which\\s+",
        "^whoami$",
        "^date$",
        "^uname\\s+"
      ],
      "never_allow": [
        "rm\\s+-rf\\s+/",
        "dd\\s+.*of=/dev/",
        ":\\(\\)\\{\\s*:\\|:\\&\\s*\\};:",
        "mkfs\\.",
        "^\\s*>\\s*/dev/sda"
      ],
      "sandboxed_paths": []
    }
  }
}
```

**Files Changed**:
- `ppxai-config.json` - Added tools.shell configuration
- `ppxai-config.example.json` - Added tools.shell template
- `ppxai/config.py` - Extended `load_config()` to return tools section

---

## Test Results

**Total Tests**: 308
**Passing**: 308
**Skipped**: 0
**Pass Rate**: 100%

**New Tests**:
- Configuration loading with shell patterns
- Command classification (safe/dangerous/never)
- Integration test with EngineClient and consent handlers
- Pattern matching edge cases

**Verification**:
- ✅ TUI shell consent prompt working
- ✅ VSCode shell consent QuickPick working
- ✅ File editing consent QuickPick working
- ✅ Safe commands auto-approved
- ✅ Dangerous commands prompt for consent
- ✅ Never-allow commands blocked
- ✅ Session-scoped consent persists
- ✅ Pattern fix prevents redirection bypass

---

## Documentation

### New Documentation:
- [docs/shell-consent-guide.md](shell-consent-guide.md) - Comprehensive shell consent guide (500+ lines)
  - Command classification reference
  - Consent flow explanation
  - Configuration examples
  - Pattern syntax guide
  - Security best practices
  - Troubleshooting guide
  - Advanced topics (custom handlers, enterprise integration)
  - FAQ section

### Updated Documentation:
- [README.md](../README.md) - Added shell consent feature description
- [SECURITY.md](../SECURITY.md) - Added shell command consent section
- [CLAUDE.md](../CLAUDE.md) - Updated to v1.11.2 with feature list
- [docs/README.md](README.md) - Added link to shell consent guide

---

## Performance

**Benchmarks** (compared to v1.11.1 baseline):
- **TTFT**: No change (consent is async and non-blocking)
- **Total**: No change (minimal overhead from pattern matching)
- **Throughput**: No change

**Consent Overhead**:
- Pattern matching: < 1ms per command
- UI prompt: User-driven (no performance impact)

---

## Upgrade Guide

### From v1.11.1:

**No breaking changes** - this is a drop-in replacement.

```bash
# Update via pip
pip install --upgrade ppxai

# Or via uv
uv pip install --upgrade ppxai
```

**What's New for Users**:
1. Shell commands now prompt for consent when dangerous
2. VSCode consent UI is now keyboard-friendly
3. Customize patterns in `ppxai-config.json` if needed

**Configuration**:
- Default shell patterns work for most use cases
- Copy `ppxai-config.example.json` to customize patterns
- See [docs/shell-consent-guide.md](shell-consent-guide.md) for examples

---

## Known Issues

None.

---

## Migration Notes

### For Users:

**If you use shell tools (`/tools enable`)**:
- Dangerous commands will now prompt for consent
- Safe read-only commands still run automatically
- Use "always" option to approve all instances of a command
- Use "never" option to block all instances of a command

**If you customize shell patterns**:
- Update `ppxai-config.json` with your allowed/dangerous/never patterns
- Use negative lookahead `(?!...)` to exclude dangerous patterns
- Test with `uv run python -c "from ppxai.config import load_config; ..."`

### For VSCode Extension Users:

**Keyboard-friendly consent**:
- Consent prompts now appear as dropdowns at top of screen
- Navigate with arrow keys or type to filter
- Press Enter to confirm, Escape to cancel (defaults to "No")
- No mouse needed!

### For Developers:

**If you're using the engine layer**:
- `EngineClient` now accepts `shell_consent_callback` parameter
- Callback signature: `async (command: str, working_dir: str, risk_level: str) -> tuple[bool, str]`
- Returns `(approved: bool, response: str)` where response is 'y', 'n', 'always', or 'never'

**If you're extending the tool system**:
- Shell tool automatically checks consent before execution
- Classification is based on patterns in `ppxai-config.json`
- Consent decisions are session-scoped

---

## Next Release (v1.11.3)

**Target**: Performance optimizations and additional security features

Potential features:
- Command sandboxing to specific directories
- Audit log for all consent decisions
- Rate limiting for shell commands
- Additional tool consent types

See [ROADMAP.md](../ROADMAP.md) for details.

---

## Credits

**Security Review**: Multi-round testing of shell consent flow
**Pattern Testing**: Verified against common command patterns
**UX Design**: Keyboard-friendly QuickPick implementation
**Documentation**: Comprehensive security and configuration guides

---

## Related Links

- **GitHub Release**: https://github.com/rcconsult/ppxai/releases/tag/v1.11.2
- **PyPI**: https://pypi.org/project/ppxai/1.11.2/
- **Documentation**: [docs/shell-consent-guide.md](shell-consent-guide.md)
- **Security**: [SECURITY.md](../SECURITY.md)

---

**Last Updated**: 2025-12-22
**Release Type**: Minor
**Upgrade Priority**: High (adds critical security features)
