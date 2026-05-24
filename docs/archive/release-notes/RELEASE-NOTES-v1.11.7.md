# Release Notes: v1.11.7

**Release Date:** 2025-12-26

## Summary

This release completes the migration to EngineClient (removing ~2,100 lines of legacy code) and adds clickable citations/links across all interfaces.

## Major Changes

### Legacy Code Removed

All legacy code has been removed. EngineClient is now the only client interface:

- **Deleted Files:**
  - `ppxai/client.py` (447 lines - AIClient)
  - `perplexity_tools_prompt_based.py` (1,342 lines - legacy tools client)
  - `tool_manager.py` (299 lines - legacy MCP loader)
- **~2,100 lines of legacy code removed**
- **337 tests passing** (migrated from legacy tests)

### New Features

- **`/tools help <tool-name>`** - Get detailed documentation for any tool
- **Autocomplete for `/tools`** - Tab completion for subcommands and tool names
- **Custom Tool Development Guide** - Comprehensive guide at [docs/custom-tool-development-guide.md](custom-tool-development-guide.md)

## Bug Fixes

### Clickable Citations

- **Perplexity Citations** - `[1]`, `[2]` markers now link to source URLs
  - Perplexity API returns citations as separate metadata array
  - New `inject_citation_urls()` function converts markers to `[1](url)` format

- **TUI Links** - Markdown links now clickable via OSC 8 hyperlinks
  - `convert_markdown_links_to_rich()` transforms `[text](url)` to Rich link format
  - Works in: Ghostty, iTerm2, Kitty, Windows Terminal, GNOME Terminal 3.26+
  - Cross-platform support (macOS, Linux, Windows)

- **VSCode Extension** - Tool responses now display correctly
  - Added `fullResponse` message type for tool-using responses
  - Fixed: Responses weren't showing when tools were enabled

### Other Fixes

- **`/tools list` After Provider Switch** - Now correctly lists tools after `/provider gemini`
- **Tool JSON Leak** - No longer leaks to VSCode during streaming

## Documentation Updates

- Archived legacy documentation to `docs/archive/legacy-tools-docs/`
- Updated all guides for EngineClient architecture
- Added autocomplete documentation across all relevant guides

## Testing

- **337 tests passing**
- Manual testing verified:
  - Perplexity citations clickable in TUI and VSCode
  - Gemini links clickable in TUI and VSCode
  - Tool responses display correctly in VSCode
  - `/tools` autocomplete working

## Compatibility

- **Terminal Support:** OSC 8 hyperlinks work in modern terminals
  - Ghostty (all platforms)
  - iTerm2 (macOS)
  - Kitty (all platforms)
  - Windows Terminal (Windows)
  - GNOME Terminal 3.26+ (Linux)

## Upgrade Notes

This is a drop-in replacement for v1.11.6. No configuration changes required.

## Links

- **GitHub Release:** https://github.com/rcconsult/ppxai/releases/tag/v1.11.7
- **Full Changelog:** [CHANGELOG.md](../CHANGELOG.md)
