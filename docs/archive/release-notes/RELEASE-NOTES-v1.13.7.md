# Release Notes - v1.13.7

**Release Date:** 2026-01-09

## Summary

This release adds hot-reload configuration across all clients (TUI, server, VSCode, web app), fixes several post-v1.13.6 bugs, and introduces a distinctive TUI icon with bold `>_` symbol for better taskbar visibility.

## New Features

### Hot Reload Configuration

Edit your `ppxai-config.json` and apply changes without restarting:

| Client | How to Reload |
|--------|---------------|
| TUI | `/config reload` |
| Server | `POST /config/reload` |
| VSCode | Command Palette: "ppxai: Reload Configuration" |
| Web App | Settings menu: "Reload Config" |

### TUI Status Bar Toggles

The `/status` command now actually toggles and saves settings:

```
/status datetime  # Toggle date/time display (persists to config)
/status version   # Toggle version display (persists to config)
/status cwd       # Toggle working directory display (persists to config)
```

### TUI Icon

New distinctive icon with bold white `>_` symbol on the purple speech bubble for better taskbar visibility at small sizes (16px, 24px, 32px).

## Bug Fixes

### `'EngineClient' object has no attribute 'provider_id'`

Fixed attribute error in `client.py` - changed `self.provider_id` to `self.provider_name`.

### `'SessionManager' object has no attribute 'get_total_usage'`

Fixed method name in `/status` command - changed `session.get_total_usage()` to `session.get_usage()`.

### Private function exposed

Renamed `_find_config_file()` to public `find_config_file()` for use by the new config reload feature.

## Files Changed

| File | Change |
|------|--------|
| `ppxai/config.py` | Added `set_tui_config()`, `reload_config()`, renamed `find_config_file()` |
| `ppxai/commands.py` | Fixed `/status` usage method, added `/config` command handler |
| `ppxai/engine/client.py` | Fixed `provider_id` → `provider_name` |
| `ppxai/server/http.py` | Added `POST /config/reload` endpoint |
| `ppxai/ui.py` | Updated help text for `/status` toggles |
| `ppxai/web/app.js` | Added `reloadConfig()` method |
| `ppxai/web/index.html` | Added "Reload Config" menu item |
| `vscode-extension/src/httpClient.ts` | Added `reloadConfig()` method |
| `vscode-extension/src/extension.ts` | Added `ppxai.reloadConfig` command |
| `vscode-extension/package.json` | Registered reload config command |
| `ppxai.spec` | Changed TUI icon to `ppxai-tui.ico` |
| `resources/ppxai-tui.ico` | New TUI icon with bold `>_` |
| `tests/test_config.py` | Updated function references |

## Testing

- **593 tests passing**
- Custom endpoint integration tests verified

## Upgrade Instructions

1. Download the new binaries from [GitHub Releases](https://github.com/rcconsult/ppxai/releases/tag/v1.13.7)
2. Replace your existing binaries
3. For VSCode: Install the new `.vsix` extension

No configuration changes required.
