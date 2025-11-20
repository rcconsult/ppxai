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
- Communicates only with the Perplexity API
- Requires users to provide their own API keys via `.env` file

**Security considerations:**
- Keep your `.env` file and API keys secure
- Do not commit `.env` files to version control
- Be cautious when sharing session exports as they may contain sensitive conversation data
