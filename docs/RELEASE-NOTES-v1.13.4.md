# Release Notes - v1.13.4

**Release Date:** 2026-01-08

## Overview

This release focuses on improving error handling, LLM guidance, and corporate proxy support. Based on debug log analysis, we identified common LLM tool usage mistakes and added helpful guidance to prevent them.

## What's New

### SSL Certificate Support for Corporate Proxies

Added `SSL_CERT_FILE` environment variable support for all providers. This enables ppxai to work behind corporate SSL inspection proxies (like Fortinet).

```bash
# Set your corporate CA certificate
export SSL_CERT_FILE="/path/to/corporate-ca.cer"
ppxai-server
```

### Standardized Error Logging

All providers now include full Python traceback in error events, making debugging easier when issues occur with API calls.

### Improved LLM Tool Guidance

Based on analysis of actual tool usage patterns, we've improved tool descriptions and error messages to help LLMs make better choices:

#### Windows Shell Warnings
The `execute_shell_command` tool now explicitly warns that bash-specific syntax doesn't work on Windows:
- Heredocs (`<<EOF`)
- Command substitution (`$()`)
- Bash builtins

#### Better Parameter Documentation
The `apply_patch` tool now emphasizes that both `file_path` AND `unified_diff` are required, preventing common "missing arguments" errors.

#### Actionable Error Tips
When files aren't found, error messages now suggest the appropriate tool to use:
- `"Tip: Use insert_text with line_number=1 to create a new file"`
- `"Tip: Use read_file or list_directory to verify the path"`

#### Line Number Validation
Invalid line range errors in `delete_lines` now suggest checking file length first with `read_file`.

## Cleanup

### Removed docs/archive/
Deleted 39 obsolete documentation files (~13KB) that were no longer relevant. The content is preserved in the v1.13.3 git tag for historical reference.

## Upgrade Instructions

1. Download the new binaries from [GitHub Releases](https://github.com/rcconsult/ppxai/releases/tag/v1.13.4)
2. Replace your existing binaries in `~/.ppxai/bin/`
3. If using VSCode extension, install the new `.vsix` file

## Full Changelog

See [CHANGELOG.md](../CHANGELOG.md) for complete details.
