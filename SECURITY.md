# Security Policy

## Supported Versions

We are currently supporting the latest version of ppxai with security updates.

| Version | Supported          |
| ------- | ------------------ |
| Latest  | :white_check_mark: |
| Older   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in ppxai, please report it by:

1. **Opening a GitHub Issue** with the label "security" (for non-critical issues)
2. **Creating a private security advisory** on GitHub (for critical vulnerabilities)

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### What to Expect

- We will acknowledge your report within 48 hours
- We will investigate and provide updates on the status
- Once fixed, we will credit you in the release notes (unless you prefer to remain anonymous)

### Scope

Please note that ppxai is a terminal UI application that:
- Stores session data locally in `~/.ppxai/`
- Communicates only with configured AI provider APIs
- Requires users to provide their own API keys via `.env` file

**Security considerations:**
- Keep your `.env` file and API keys secure
- Do not commit `.env` files to version control
- Be cautious when sharing session exports as they may contain sensitive conversation data

## Security Features

### Shell Command Consent (v1.11.2)

ppxai includes a **consent-based security system** for shell commands executed by the AI:

**Command Classification:**
- **Safe Commands** (auto-approved): Read-only operations like `ls`, `cat`, `pwd`, `grep`
- **Dangerous Commands** (require consent): Potentially destructive operations like `rm`, `mv`, `chmod`, `sudo`
- **Never-Allow Commands** (always blocked): Catastrophic operations like `rm -rf /`, `dd of=/dev/`, fork bombs

**Consent Flow:**
1. AI requests to execute a shell command
2. ppxai classifies the command using regex patterns
3. Safe commands execute automatically
4. Dangerous commands prompt for user consent (y/n/always/never)
5. Never-allow commands are blocked immediately with error message

**Configuration:**
Customize command patterns in `ppxai-config.json` under `tools.shell`:
- `allowed_commands` - Safe commands that bypass consent
- `dangerous_commands` - Commands requiring user approval
- `never_allow` - Commands that are always forbidden

**Session-Scoped Consent:**
- Consent decisions persist for the duration of the session
- Choose "always" to approve all future uses of a command
- Choose "never" to block all future uses of a command
- Restart the application to reset all consent decisions

### File Editing Consent (v1.11.0)

ppxai requires **user consent before modifying files**:

**File Editing Tools:**
- `apply_patch` - Apply unified diff patches
- `replace_block` - Search and replace text blocks
- `insert_text` - Insert text at specific lines
- `delete_lines` - Delete line ranges

**Safety Features:**
- User consent required before any file modification
- Consent persists per-file for the session
- Atomic operations with automatic rollback on failure
- Clear diff preview before applying changes

**Best Practices:**
- Review AI-generated file edits carefully before approving
- Use version control (git) to track changes
- Keep backups of important files
- Test consent flow with non-critical files first

### API Key Security

**Never share your API keys:**
- API keys provide full access to your AI provider account
- Keep `.env` files out of version control (add to `.gitignore`)
- Use environment-specific API keys when possible
- Rotate keys periodically

**Configuration Security:**
- `ppxai-config.json` can be committed (no secrets)
- `.env` should never be committed (contains API keys)
- Use `PPXAI_CONFIG_FILE` environment variable for custom config locations
- Validate configuration with: `python -c "from ppxai.config import validate_config; print(validate_config())"`
