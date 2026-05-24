# Release Notes - v1.12.4

**Release Date:** 2026-01-03

## Summary

v1.12.4 adds the `/checkpoint` command for managing checkpoints and upgrades the `web_search` tool to use the more reliable `ddgs` package.

## New Features

### `/checkpoint` Command

Full checkpoint management from TUI and VSCode extension:

| Subcommand | Description |
|------------|-------------|
| `/checkpoint status` | View checkpoint configuration |
| `/checkpoint list` | List recent checkpoints (up to 10) |
| `/checkpoint backend <mode>` | Switch backend: `git`, `file`, `auto`, `none` |
| `/checkpoint clear` | Clear old file-based snapshots |
| `/checkpoint info <id>` | Show checkpoint details |
| `/checkpoint undo` | Alias for `/undo` |

**Tab autocomplete** for subcommands and backend options in TUI.

### Web Search Tool Upgrade

- **`ddgs` package** - More reliable DuckDuckGo search
- **Fallback chain** - ddgs → duckduckgo-search → HTML scraping
- **No API key needed** - Works out of the box for all providers
- **Optional dependency** - Install with `pip install ppxai[search]`

## API Endpoints

New HTTP endpoints for checkpoint management:

- `GET /checkpoint/list` - List recent checkpoints
- `POST /checkpoint/backend` - Set checkpoint backend
- `POST /checkpoint/clear` - Clear file-based checkpoints

## Installation

```bash
# Upgrade existing installation
pip install --upgrade ppxai

# With web search support
pip install --upgrade ppxai[search]

# Or download binaries from GitHub Releases
```

## Testing

- 400 tests passing

## Links

- [checkpoint-guide.md](checkpoint-guide.md) - Full checkpoint documentation
- [CHANGELOG.md](../CHANGELOG.md) - Detailed changelog
