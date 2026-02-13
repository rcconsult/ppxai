# Release Notes - v1.12.3

**Release Date:** January 3, 2026

## Summary

Time-based usage analytics with persistent storage across sessions. Track your API spending over 24 hours, weeks, months, or all time with detailed breakdowns by provider and model.

## New Features

### Persistent Usage Storage

Usage data now persists across sessions in `~/.ppxai/usage/usage.json`:

- **Automatic saving** - Usage saved after each chat (VSCode) or on exit (TUI)
- **No duplicates** - Same session updates existing entry instead of creating duplicates
- **Shared storage** - Both TUI and VSCode extension contribute to the same usage history

### Time-Based Usage Commands

New `/usage` sub-commands for historical usage reports:

| Command | Description |
|---------|-------------|
| `/usage 24h` | Usage for last 24 hours |
| `/usage week` | Usage for last 7 days |
| `/usage month` | Usage for last 30 days |
| `/usage year` | Usage for last 365 days |
| `/usage all` | All-time usage |

**Example output:**
```
Usage Report: Last 7 Days
Period: 2025-12-27 to 2026-01-03

  Sessions: 12
  Total tokens: 45,230
  Estimated cost: $0.2261

By Provider:
| Provider   | Tokens | Cost    | Sessions |
|:-----------|-------:|--------:|---------:|
| perplexity | 32,500 | $0.1825 |        8 |
| gemini     | 12,730 | $0.0436 |        4 |

By Model:
| Provider   | Model              | In     | Out   | Cost    |
|:-----------|:-------------------|-------:|------:|--------:|
| perplexity | sonar-pro          | 28,000 | 4,500 | $0.1825 |
| gemini     | gemini-2.0-flash   | 11,200 | 1,530 | $0.0436 |

Recent Sessions:
  2026-01-03 00:13 - 1,432 tokens, $0.0075
  2026-01-03 00:07 - 1,422 tokens, $0.0073
  2026-01-02 23:58 - 20,787 tokens, $0.0046
```

### HTTP Endpoints (VSCode Extension)

New API endpoints for usage analytics:

| Endpoint | Description |
|----------|-------------|
| `GET /usage/report?period=week` | Aggregated usage report |
| `GET /usage/sessions?limit=20` | List recorded sessions |

### Auto-Save Behavior

| Interface | When Usage is Saved |
|-----------|---------------------|
| TUI | On `/quit` or `/exit` |
| VSCode | After each chat message |

## Files Changed

| File | Description |
|------|-------------|
| **NEW** `ppxai/usage.py` | Persistent usage storage module |
| `ppxai/commands.py` | Added `/usage <period>` commands |
| `ppxai/server/http.py` | Added `/usage/report`, `/usage/sessions` endpoints |
| `ppxai/engine/session.py` | Added `save_usage_to_persistent_storage()` method |
| `vscode-extension/src/chatPanel.ts` | Added time-based usage command handling |
| `vscode-extension/src/httpClient.ts` | Added `getUsageReport()` method |
| **NEW** `tests/test_usage_persistence.py` | 14 new tests |

## Testing

- **414 tests passing** (14 new usage persistence tests)
- Tested on TUI and VSCode extension
- Verified shared storage works correctly between interfaces

## Upgrade Notes

- No breaking changes
- Existing sessions will start accumulating in usage history
- Old usage data (pre-v1.12.3) is not migrated - only new sessions are recorded

## What's Next

- **v1.12.4** - Gemini dedicated provider with native search grounding
- **v1.13.0** - AGENTS.md support for project context

---

**Full Changelog:** [v1.12.2...v1.12.3](https://github.com/rcconsult/ppxai/compare/v1.12.2...v1.12.3)
