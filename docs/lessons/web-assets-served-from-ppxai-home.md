# Web UI is served from `~/.ppxai/web`, never the source tree

**TL;DR:** Every client — `ppxai-server`, `ppxai-desktop`, and `uv run` alike —
serves the web UI from a single directory (`~/.ppxai/web` by default), **not**
from the repo's `ppxai/web/` and **not** from the PyInstaller bundle. So editing
`ppxai/web/...` has **no visible effect** until you either sync that dir or set
`PPXAI_WEB_DIR`. (v1.19.0 adds the override.)

**Verify with:**
```bash
grep -n "_resolve_web_ui_dir\|PPXAI_WEB_DIR\|WEB_UI_DIR" ppxai/server/routes/static.py
# WEB_UI_DIR = _resolve_web_ui_dir()  → PPXAI_WEB_DIR env, else ~/.ppxai/web
```

## Why this trips people up

`WEB_UI_DIR` is a module-level constant in `static.py`. There is no
"serve from source when running from a checkout" branch — `uv run ppxai-server`
from the repo still reads `~/.ppxai/web`, the same as the installed binary. The
result: you edit a `.js`/`.css` in `ppxai/web/`, reload the browser, and see
the **old** asset, because the server never looked at your edit.

The fix while iterating (v1.19.0+):
```bash
PPXAI_WEB_DIR=$PWD/ppxai/web ~/.local/bin/ppxai-server   # or: uv run ppxai-server
```
The override takes precedence over `~/.ppxai/web`; no per-edit sync needed.
Without it, you must `cp -R ppxai/web ~/.ppxai/web` after each change (this is
build-install step 5b).

## The `.app` wrinkle (mechanism unconfirmed)

The macOS `ppxai-desktop` bundle ships a build-time copy at
`Contents/Resources/web` (`scripts/create-macos-app.sh` copies `ppxai/web/*`
there at build time). That copy is **not consulted at runtime** —
`WEB_UI_DIR` is hardcoded to `~/.ppxai/web`, and the `.app` has **no launcher
wrapper** (just the raw binary in `Contents/MacOS/`):

```bash
grep -rn "Resources/web\|copytree\|WEB_UI_DIR" ppxai/ scripts/   # no runtime copy into ~/.ppxai/web
ls /Applications/ppxai.app/Contents/MacOS/                        # binaries only, no launcher script
```

During a v1.19.0 web trial, `~/.ppxai/web/` was **observed** reverting to the
`.app`'s build-time snapshot after the `.app` was launched (served `index.html`
mtime matched the bundle; a newer file had vanished) — but **no code that does
this could be found**. Treat the cause as unconfirmed. Practical rule:

- **Don't trial web changes against the `.app`.** Use `PPXAI_WEB_DIR`, or sync
  `~/.ppxai/web` and run `ppxai-server`/`ppxai-desktop`.
- If you do launch the `.app`, **re-sync `~/.ppxai/web` afterward** before
  trusting what's served.

## Related

- [config-source-resolution.md](config-source-resolution.md) — the sibling
  trap: `./ppxai-config.json` + `./.env` in a checkout shadow `~/.ppxai`
  versions when you `uv run` from the repo (why `uv run` showed no providers).
  Same root cause family: CWD/home resolution differs from "the source tree."
