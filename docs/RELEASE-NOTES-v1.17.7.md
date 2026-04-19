# Release Notes — v1.17.7

## Summary

**Patch release — fixes a stale-version bug in `ppxai-desktop`.** The desktop launcher binary had been misreporting its version since at least v1.17.4; the fresh v1.17.6 binary still returned `"ppxai-desktop 1.17.4"` when queried with `--version`. This release fixes the root cause so the binary version always matches the source of truth.

No feature changes. No schema changes. Drop-in patch.

## Fix

- **`ppxai-desktop --version` now reports the correct version.** Root cause: `ppxai-desktop.py` used `from ppxai.version import __version__` inside a `try/except ImportError`, which silently fell back to a **hardcoded string** in the frozen PyInstaller binary. The import fails in the frozen binary because `ppxai/__init__.py` imports `config` and `engine` modules that transitively pull in `pydantic`, `openai`, `rich`, `prompt_toolkit`, `fastapi`, and `uvicorn` — all **excluded** from the desktop spec to keep the launcher small.

  Fix: load `ppxai/version.py` directly by file path via `importlib.util.spec_from_file_location`, bypassing `ppxai/__init__.py` and the excluded-packages chain. Works in both dev mode (reads from the source tree) and frozen mode (reads from `sys._MEIPASS/ppxai/version.py`). The PyInstaller spec now ships `ppxai/version.py` as a `datas` entry so the file is actually staged in `_MEIPASS`.

  **No more hardcoded version string in `ppxai-desktop.py`** — future releases can't silently drift this value.

## Affected users

Anyone who downloaded `ppxai-desktop-macos-arm64`, `ppxai-desktop-macos-intel`, `ppxai-desktop-linux-amd64`, `ppxai-desktop-windows.exe` from the v1.17.6 GitHub release. The binaries launch and work fine — they just report the wrong version when asked. Re-download v1.17.7 to get correct `--version` output.

## Verified

On macOS Intel with a fully-clean PyInstaller build (`rm -rf build/ppxai-desktop dist/ppxai-desktop`):

```
$ ~/.local/bin/ppxai-desktop --version
ppxai-desktop 1.17.7
```

## Not changed

- No engine behavior changes
- No client behavior changes
- No provider or model changes
- No test changes — `Message.text_content()` is unaffected

## Upgrade notes

Drop-in patch. No migration needed.

## Commits

```
c6e0328c fix(ppxai-desktop): load version from ppxai/version.py by file path
```
