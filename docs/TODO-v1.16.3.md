# TODO v1.16.3 Backlog

Issues identified from debug log review (2026-03-07) and ongoing development.

All items from initial backlog were resolved in v1.16.2:

| Item | Resolution |
|------|-----------|
| `/files/list` storm on session restore | Fixed — 300ms debounce on `working_dir_changed` |
| Validator FP: success-after-retries | Fixed — only checks most recent tool call |
| Shell subprocess PATH missing `~/.local/bin` | Fixed — `shell_bin` + `login_shell` config keys |
| File tree single-click 220ms lag | Fixed — reduced to 150ms |
| `at_fs_root` Windows edge case (`C:\`) | Verified — `Path('C:\\').parent == Path('C:\\')` is True |

No open items for v1.16.3 yet.
