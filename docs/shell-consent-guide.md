# Shell Command Consent Guide

**Version:** v1.11.2
**Last Updated:** 2025-12-22

## Overview

ppxai v1.11.2 introduces a **consent-based security system** for shell commands executed by AI. This system protects users from potentially dangerous or destructive shell commands while allowing safe operations to proceed automatically.

## Why Shell Command Consent?

AI-powered shell command execution is powerful but carries inherent risks:

- **Destructive Commands:** `rm -rf` can delete critical files
- **Privilege Escalation:** `sudo` can modify system settings
- **Remote Exploits:** `curl | bash` can execute malicious scripts
- **System Damage:** `dd` can overwrite disk partitions

The consent system provides **defense in depth** by:
1. **Classifying commands** based on risk level
2. **Requesting user approval** for dangerous operations
3. **Blocking catastrophic commands** automatically
4. **Logging all consent decisions** for audit trails

## Command Classification

Commands are classified into three categories:

### 1. Safe Commands (Auto-Approved ✅)

Read-only operations that cannot harm the system:

| Command | Purpose | Example |
|---------|---------|---------|
| `ls` | List directory contents | `ls -la /home/user` |
| `cat` | Display file contents (read-only) | `cat package.json` |
| `grep` | Search in files | `grep "error" app.log` |
| `pwd` | Print working directory | `pwd` |
| `which` | Locate command | `which python` |
| `whoami` | Show current user | `whoami` |
| `date` | Display date/time | `date` |
| `uname` | Show system info | `uname -a` |

**Behavior:** Execute immediately without prompting user.

**Important:** `cat` and `echo` are only safe for **reading/displaying**. Commands with redirections like `cat > file` or `echo data > file` will be classified as **dangerous** and require consent.

### 2. Dangerous Commands (Require Consent ⚠️)

Operations that can modify files, change permissions, or affect system state:

| Command | Risk | Example |
|---------|------|---------|
| `rm` | File deletion | `rm -f temp.txt` |
| `mv` | File movement | `mv old.txt new.txt` |
| `chmod` | Permission changes | `chmod 755 script.sh` |
| `chown` | Owner changes | `chown user:group file.txt` |
| `sudo` | Root privileges | `sudo apt install package` |
| `curl \| bash` | Remote execution | `curl https://example.com/install.sh \| bash` |
| `wget \| bash` | Remote execution | `wget -O- https://example.com/setup \| bash` |
| `kill` | Process termination | `kill -9 1234` |
| `pkill` | Process termination | `pkill python` |
| `killall` | Process termination | `killall node` |

**Behavior:** Prompt user for consent with command details and risk level.

### 3. Never-Allow Commands (Always Blocked ❌)

Catastrophic operations that can destroy the system:

| Command | Danger | Example |
|---------|--------|---------|
| `rm -rf /` | System deletion | `rm -rf /` or `rm -rf /*` |
| `dd of=/dev/*` | Disk overwrite | `dd if=/dev/zero of=/dev/sda` |
| Fork bombs | Resource exhaustion | `:()\{ :\|:& \};:` |
| `mkfs.*` | Filesystem destruction | `mkfs.ext4 /dev/sda1` |
| `> /dev/sda` | Disk corruption | `echo "data" > /dev/sda` |

**Behavior:** Reject immediately with error message. Never prompt for consent.

## Consent Flow

### 1. AI Requests Shell Command

The AI tool system requests to execute a command:

```python
# AI calls the execute_shell_command tool
{
  "tool": "execute_shell_command",
  "command": "rm -f /tmp/test.txt",
  "working_dir": "/home/user/project"
}
```

### 2. Command Classification

ppxai analyzes the command using regex patterns:

```python
# Check never-allow patterns first
if matches_never_allow_pattern(command):
    return DENY, "Command is forbidden"

# Check allowed patterns
if matches_allowed_pattern(command):
    return APPROVE, "Command is safe"

# Check dangerous patterns
if matches_dangerous_pattern(command):
    return REQUEST_CONSENT, "Command requires approval"

# Default: require consent for unknown commands
return REQUEST_CONSENT, "Unknown command requires approval"
```

### 3. User Consent (for Dangerous Commands)

#### TUI Consent Prompt

```
⚠️  Shell Command Consent Required

Command:      rm -f /tmp/test.txt
Directory:    /home/user/project
Risk Level:   DANGEROUS
Classification: File deletion command

Allow this command? (y/n/always/never):
```

**Options:**
- `y` - Approve this command once
- `n` - Deny this command once
- `always` - Approve all future uses of this command pattern
- `never` - Deny all future uses of this command pattern

#### VSCode Extension Consent Modal

```
┌─────────────────────────────────────────┐
│  Shell Command Consent Required         │
├─────────────────────────────────────────┤
│                                         │
│  Command:  rm -f /tmp/test.txt         │
│  Directory: /home/user/project          │
│  Risk: DANGEROUS                        │
│                                         │
│  This command will delete files.        │
│                                         │
│  [ Yes, Once ]  [ Yes, Always ]         │
│  [ No, Once  ]  [ No, Never   ]         │
│                                         │
└─────────────────────────────────────────┘
```

### 4. Command Execution or Denial

Based on user response:

- **Approved:** Command executes and output is returned to AI
- **Denied:** Error message returned to AI, command not executed

## Configuration

### Default Configuration

ppxai includes sensible defaults in `ppxai-config.json`:

```json
{
  "tools": {
    "shell": {
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

**Note:** `tools.shell.require_consent` is not a real toggle. It is parsed by `get_shell_config()` (`ppxai/config/tools.py`) but never read by the consent decision path (`ppxai/common/consent.py`, `ppxai/engine/consent_ops.py`) — setting it has no effect. Shell command consent cannot currently be disabled; see the [FAQ](#q-can-i-disable-shell-consent-entirely) below.

### Customizing Command Patterns

You can customize patterns to match your security requirements:

#### Example: Allow npm and git commands

```json
{
  "tools": {
    "shell": {
      "allowed_commands": [
        "^ls\\s+",
        "^cat\\s+(?!.*[><])",
        "^pwd$",
        "^npm\\s+(install|run|test)",
        "^git\\s+(status|log|diff|add|commit)"
      ]
    }
  }
}
```

**Note:** The pattern `^cat\\s+(?!.*[><])` uses a negative lookahead `(?!.*[><])` to ensure `cat` commands with redirections (`>` or `<`) are **not** matched as safe. This prevents dangerous file-writing operations like `cat > file.txt` from bypassing consent.

#### Example: Block all package managers

```json
{
  "tools": {
    "shell": {
      "dangerous_commands": [
        "^rm\\s+",
        "^mv\\s+",
        "^apt\\s+",
        "^yum\\s+",
        "^dnf\\s+",
        "^brew\\s+",
        "^npm\\s+install",
        "^pip\\s+install"
      ]
    }
  }
}
```

#### Example: Sandbox to project directory only

```json
{
  "tools": {
    "shell": {
      "sandboxed_paths": [
        "/home/user/projects/myproject"
      ],
      "never_allow": [
        "cd\\s+\\.\\.",
        "cd\\s+/",
        "cd\\s+~"
      ]
    }
  }
}
```

### Pattern Syntax

Patterns use Python regex syntax:

| Pattern | Meaning | Example |
|---------|---------|---------|
| `^cmd` | Start of command | `^rm` matches `rm file` but not `safe_rm file` |
| `cmd$` | End of command | `pwd$` matches only `pwd`, not `pwd extra` |
| `\\s+` | One or more spaces | `ls\\s+` matches `ls -la` |
| `.*` | Any characters | `curl.*bash` matches `curl url \| bash` |
| `\|` | Pipe character | `\\|` (escaped) |
| `[abc]` | Character class | `[a-z]` matches any lowercase letter |

**Important:** Always escape special regex characters with `\\`:
- Pipe: `\\|`
- Parentheses: `\\(` and `\\)`
- Curly braces: `\\{` and `\\}`
- Plus: `\\+`
- Asterisk: `\\*`
- Dot: `\\.`

## Session-Scoped Consent

### How It Works

Consent decisions are stored in-memory for the session:

```python
# Example: Internal consent state
consent_decisions = {
    "rm\\s+": "always",      # All rm commands approved
    "chmod\\s+": "never",    # All chmod commands denied
}
```

### Consent Options

| Option | Scope | Persistence | Example |
|--------|-------|-------------|---------|
| `y` (Yes, once) | Single command | Current invocation | Approves `rm file.txt` once |
| `n` (No, once) | Single command | Current invocation | Denies `rm file.txt` once |
| `always` | Pattern match | Entire session | Approves all `rm *` commands |
| `never` | Pattern match | Entire session | Denies all `chmod *` commands |

### Clearing Consent

Consent decisions are **not** persisted to disk. To reset:

1. **Restart TUI (ppxai or ppxaide):**
   ```bash
   # Exit and restart
   /quit
   uv run ppxai    # or: uv run ppxaide
   ```

2. **Restart ppxai-server (for VSCode):**
   ```bash
   # Kill and restart
   pkill ppxai-server
   ppxai-server
   ```

## Security Best Practices

### 1. Review Command Patterns Regularly

Audit your `ppxai-config.json` patterns periodically:

```bash
# Check current configuration
cat ppxai-config.json | jq '.tools.shell'
```

### 2. Use Least Privilege

Only allow commands that AI actually needs:

```json
{
  "tools": {
    "shell": {
      "allowed_commands": [
        "^ls\\s+",
        "^cat\\s+",
        "^grep\\s+"
      ]
    }
  }
}
```

### 3. Test Patterns Before Deployment

Create test commands to verify patterns work correctly:

```python
# Test script: test_patterns.py
from ppxai.common.consent import classify_shell_command

config = {
    "allowed_commands": ["^ls\\s+"],
    "dangerous_commands": ["^rm\\s+"],
    "never_allow": ["rm\\s+-rf\\s+/"],
}

# Test safe command
assert classify_shell_command("ls -la", config) == "safe"

# Test dangerous command
assert classify_shell_command("rm -f file.txt", config) == "dangerous"

# Test never-allow command
assert classify_shell_command("rm -rf /", config) == "never"
```

`classify_shell_command(command, config)` is a module-level function in `ppxai/common/consent.py` (not a `ConsentManager` method) — pass it the same `shell_config` dict `get_shell_config()` builds. The `ConsentManager` class itself lives in `ppxai/common/consent.py` and takes `shell_config` as an `__init__` argument; there is no `load_shell_config()` method.

### 4. Monitor Consent Decisions

Enable debug logging to track consent requests:

```bash
# TUI: Enable debug logging
/debug-log on

# VSCode: Check server logs
tail -f ~/.ppxai/logs/server-debug.log
```

### 5. Use Git for Auditing

Track configuration changes with version control:

```bash
# Add ppxai-config.json to git
git add ppxai-config.json
git commit -m "feat: Restrict shell commands to read-only operations"
```

### 6. Educate Users

Document your organization's shell command policy:

```markdown
# Team Shell Command Policy

## Allowed Commands
- File reading: `cat`, `less`, `head`, `tail`
- Directory listing: `ls`, `find`, `tree`
- Search: `grep`, `rg`, `ag`

## Forbidden Commands
- File deletion: `rm`
- Permission changes: `chmod`, `chown`
- Package installation: `apt`, `yum`, `brew`, `npm install`

## Requires Approval
- Version control: `git commit`, `git push`
- Process management: `kill`, `pkill`
```

## Troubleshooting

### Commands Not Being Classified Correctly

**Problem:** Safe command is asking for consent.

**Solution:** Check pattern syntax and order:

```json
{
  "allowed_commands": [
    "^ls\\s+",      // ✅ Correct: matches "ls -la"
    "^ls",          // ❌ Wrong: too broad, matches "lsblk"
    "ls",           // ❌ Wrong: matches "false-ls-command"
  ]
}
```

### Consent Prompts Not Appearing

**Problem:** AI executes dangerous commands without asking.

**Solution:** Consent is always required for `dangerous`/unknown-risk commands — it cannot be turned off. If a command is slipping through unprompted, it's almost always because it matches an `allowed_commands` pattern too broadly. Check which pattern matched:

```bash
# Inspect your allowed_commands patterns for over-broad matches
cat ppxai-config.json | jq '.tools.shell.allowed_commands'
```

### Pattern Regex Errors

**Problem:** Application crashes with regex error.

**Solution:** Test patterns with Python regex tester:

```python
import re

# Test pattern compilation
pattern = r"^rm\s+"
try:
    re.compile(pattern)
    print(f"✅ Pattern valid: {pattern}")
except re.error as e:
    print(f"❌ Pattern invalid: {e}")
```

### Commands Always Blocked

**Problem:** Legitimate commands are always denied.

**Solution:** Check if pattern is in `never_allow`:

```json
{
  "never_allow": [
    "rm\\s+-rf\\s+/",      // ✅ Only blocks "rm -rf /"
    "^rm\\s+",             // ❌ Blocks ALL rm commands
  ]
}
```

## Advanced Topics

### Custom Consent Handlers

`EngineClient(shell_consent_callback=...)` takes a plain async function, not a
request/response object pair. The real signature (see
`ppxai/engine/client.py`):

```python
async def shell_consent_callback(command: str, working_dir: str, risk_level: str) -> tuple[bool, str]:
    """
    Args:
        command: The shell command the AI wants to run
        working_dir: Working directory for the command
        risk_level: "safe", "dangerous", or "never" (ShellRiskLevel)

    Returns:
        (approved, response) where response is one of "y", "n", "always", "never"
        (ConsentResponse) — "always"/"never" are remembered for the rest of
        the session, "y"/"n" apply to this command only.
    """
```

Implement custom consent logic for programmatic control:

```python
from ppxai.engine import EngineClient

async def custom_shell_consent(command: str, working_dir: str, risk_level: str) -> tuple[bool, str]:
    """Custom consent handler with logging and policy enforcement."""

    # Log request
    print(f"🔔 Consent requested: {command} (risk={risk_level})")

    # Apply custom policy
    if "production" in working_dir:
        # Never allow shell commands in production
        return (False, "never")

    # Fall back to your own UI prompt for dev environments
    approved = await my_ui_prompt(command, working_dir, risk_level)
    return (approved, "y" if approved else "n")

# Use custom handler
engine = EngineClient(shell_consent_callback=custom_shell_consent)
```

### Integration with External Approval Systems

Connect to enterprise approval workflows:

```python
import os

async def enterprise_consent(command: str, working_dir: str, risk_level: str) -> tuple[bool, str]:
    """Request approval from external system."""

    # Call approval API
    response = await approval_api.request_approval(
        user=os.getenv("USER"),
        command=command,
        directory=working_dir,
        risk_level=risk_level,
    )

    return (response.approved, "y" if response.approved else "n")
```

### Command Whitelisting by Directory

Allow different commands in different directories:

```python
async def directory_based_consent(command: str, working_dir: str, risk_level: str) -> tuple[bool, str]:
    """Different rules for different directories."""

    # Allow destructive commands in /tmp for the rest of the session
    if working_dir.startswith("/tmp"):
        return (True, "always")

    # Deny all writes in /etc for the rest of the session
    if working_dir.startswith("/etc"):
        return (False, "never")

    # Fall back to your own UI prompt for other directories
    approved = await my_ui_prompt(command, working_dir, risk_level)
    return (approved, "y" if approved else "n")
```

**Note:** `ConsentRequest` (`ppxai/common/consent.py`) is an internal dataclass
used by `ConsentManager`/`SyncConsentManager` to bundle prompt data for the
built-in TUI/VSCode/web callbacks — it is not what your callback receives, and
`ConsentDecision` (`ppxai/constants.py`) is a plain `str, Enum` of
`"yes"|"no"|"always"|"never"`, not a constructible response object. Don't call
`ConsentDecision(approved=..., ...)`; it raises `TypeError`.

## Frequently Asked Questions

### Q: Can I disable shell consent entirely?

**A:** No. Shell command consent cannot currently be disabled. `tools.shell.require_consent` is parsed by config loading but never read by the consent decision path, so setting it to `false` has no effect — dangerous/unknown-risk commands always prompt. The closest you can get is broadening `allowed_commands` so more commands auto-approve, or supplying a `shell_consent_callback` that always approves (see [Custom Consent Handlers](#custom-consent-handlers)) — the latter still runs on every request, it just doesn't prompt a human.

### Q: How do I allow all git commands?

**A:** Add git pattern to `allowed_commands`:

```json
{
  "allowed_commands": [
    "^git\\s+"
  ]
}
```

### Q: What happens if I choose "always" by mistake?

**A:** Restart the TUI (ppxai or ppxaide) to reset consent decisions. Consider using version control to track changes.

### Q: Can consent decisions be saved across sessions?

**A:** Not currently. This is a security feature to prevent unauthorized persistence of dangerous command approvals.

### Q: How do I debug pattern matching?

**A:** Enable debug logging:

```bash
/debug-log on
```

Then review logs in `~/.ppxai/logs/tui-debug.log`.

### Q: Can I use environment variables in patterns?

**A:** No, patterns are static regex. Consider custom consent handlers for dynamic logic.

## See Also

- [File Editing Guide](file-editing-guide.md) - User consent for file modifications
- [Agentic Workflow Plan](archive/v1.15.1-completed/v1.11.0-agentic-workflow-plan.md) - Technical implementation details
- [Security Policy](../SECURITY.md) - Overall security documentation
- [Configuration Guide](README.md) - ppxai configuration system

## Support

For questions or issues with shell command consent:

1. Check the [FAQ](#frequently-asked-questions) above
2. Review [SECURITY.md](../SECURITY.md) for security best practices
3. Open an issue on GitHub with the "security" label
4. Include your `ppxai-config.json` (redact secrets!)

---

**Version:** v1.11.2
**Last Updated:** 2025-12-22
**License:** MIT
