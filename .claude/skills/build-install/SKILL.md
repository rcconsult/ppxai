---
name: build-install
description: Rebuild all four ppxai binaries (ppxai, ppxaide, ppxai-server, ppxai-desktop), the VSCode extension VSIX, and the macOS .app + DMG, then install them locally on this system (binaries to ~/.local/bin/, .app to /Applications via DMG mount, VSIX into VS Code). macOS only. Use when the user asks to "rebuild and reinstall", "build and install", "redeploy locally", "install from DMG", or similar.
---

# build-install

End-to-end local install of ppxai on macOS: build all binaries + VSCode
extension + DMG, then install everything to system locations exactly as
a user-side install would. Useful for testing a branch before release,
or for verifying a release artifact after CI uploads the DMG.

## Preconditions

- macOS (Linux equivalent lives in CI workflows, not this skill).
- Working tree at the version you want to ship — version files already
  bumped (see `tests/test_version_consistency.py` for the SoT list).
- `uv` resolvable per CLAUDE.md "uv Resolution" (system or `.uv/uv`).
- `node` + `npm` for the VSCode extension build.
- Apple Silicon vs Intel: `create-macos-app.sh` auto-detects the host
  architecture and writes the DMG name accordingly
  (`ppxai-X.Y.Z-macos-{arm64,intel}.dmg`).

## Steps

The pattern below mirrors the canonical run from 2026-05-02.

### 1. Reset previous build artifacts and build the first binary

```bash
cd /Users/rado/git/utils/ppxai
rm -rf build dist
uv run --no-sync pyinstaller ppxai.spec --noconfirm
```

The first build is run alone because PyInstaller initialises `build/`
state on the first invocation; subsequent builds share enough that
running them in parallel is safe.

### 2. Build the remaining three binaries in parallel

```bash
uv run --no-sync pyinstaller ppxaide.spec --noconfirm        2>&1 | tail -2 &
uv run --no-sync pyinstaller ppxai-server.spec --noconfirm   2>&1 | tail -2 &
uv run --no-sync pyinstaller ppxai-desktop.spec --noconfirm  2>&1 | tail -2 &
wait
ls dist/{ppxai,ppxaide,ppxai-server,ppxai-desktop}
```

All four binaries should appear in `dist/`. Each is roughly 33–40 MB.

### 3. Build the VSCode extension VSIX

Wrap the whole thing in a subshell `( ... )` so the `cd` is scoped and
cannot leak to step 4. Earlier runs ate a `cd vscode-extension` that
persisted into step 4 — `bash scripts/create-macos-app.sh` then
failed with "No such file or directory" because the script lives at
the project root.

```bash
(cd vscode-extension && \
    { [ -d node_modules ] || npm install; } && \
    npm run compile && \
    npx vsce package --allow-missing-repository)
# subshell exits — parent cwd unchanged
```

What each line does:
- `[ -d node_modules ] || npm install` — only on first run / after dep bump
- `npm run compile` — esbuild → `dist/extension.js` (~107 KB minified)
- `npx vsce package --allow-missing-repository` — produces
  `vscode-extension/ppxai-X.Y.Z.vsix` (~128 KB)

Do NOT use a bare `cd vscode-extension && ...` chain without the
surrounding parens. The Bash tool persists the working directory
across calls; a leaked cwd silently breaks downstream steps.

If `npm run compile` fails with `Cannot find module 'esbuild'`, the
v1.18.2 esbuild bundling rewrite never had `npm install` run on this
checkout — run `npm install` first. The size budget gate is 500 KB;
expected size is ~128 KB.

### 4. Build the macOS .app + DMG

```bash
bash scripts/create-macos-app.sh
```

Produces:
- `dist/ppxai.app` — macOS application bundle
- `dist/ppxai-{version}-macos-{arm64|intel}.dmg` — DMG installer
  (~70-75 MB)

### 5. Install binaries to `~/.local/bin/`

```bash
cp dist/ppxai dist/ppxaide dist/ppxai-server dist/ppxai-desktop ~/.local/bin/
```

### 5b. Refresh `~/.ppxai/web/` — server reads from disk, not bundle

`ppxai-server` reads the web UI from `~/.ppxai/web/` at request time
(see `ppxai/server/routes/static.py::WEB_UI_DIR`). `ppxai-desktop`
auto-installs that directory **only when it doesn't exist** —
subsequent launches don't refresh it. So a freshly-rebuilt server
binary still serves stale JS/CSS unless `~/.ppxai/web/` is also
synced. Caught on 2026-05-02 v1.18.3 build-install: Item 16's
CompositeResult handler in `web/shared/result-renderer.js` was
present in the binary AND the .app bundle, but the server still
served the old file because nobody refreshed the on-disk copy.

```bash
TS=$(date +%Y%m%d-%H%M%S)
[ -d ~/.ppxai/web ] && mv ~/.ppxai/web ~/.ppxai/web.backup.$TS
cp -R ppxai/web ~/.ppxai/web
```

The backup is per-run-timestamp and uses the same `.backup.*`
convention as `ppxai-config.json` backups, so cleanup is uniform.

If you only changed Python code (no `web/` edits), this step is a
no-op functionally — but it's cheap (~3 MB copy) and the alternative
is silent staleness.

### 6. Install the .app from the DMG (real install, not just `cp dist/ppxai.app`)

When the user asks to "install the DMG" they mean running the install
flow that an end user would run — mount, copy, unmount. Don't just
`cp dist/ppxai.app /Applications/` (that bypasses the DMG):

```bash
DMG="dist/ppxai-$(grep '^version' pyproject.toml | head -1 | cut -d'"' -f2)-macos-$(uname -m | sed 's/x86_64/intel/').dmg"

# If a previous mount is still attached from `open <dmg>`, reuse it; otherwise mount.
MOUNT="/Volumes/ppxai Desktop"
if ! [ -d "$MOUNT" ]; then
    hdiutil attach "$DMG" -nobrowse
fi

rm -rf /Applications/ppxai.app
cp -R "$MOUNT/ppxai.app" /Applications/
hdiutil detach "$MOUNT"
```

Notes:
- The volume name from `create-macos-app.sh` is `ppxai Desktop` (with
  the space). Adjust if you change the script's `DISPLAY_NAME`.
- The `arm64`/`intel` suffix in the DMG name is from `uname -m`
  passed through the script; mirror that here so we pick the file
  that was actually built.

### 7. Install the VSCode extension

```bash
code --install-extension vscode-extension/ppxai-*.vsix --force
```

`--force` overwrites a previously-installed version of the same
extension. A fresh load of any open VS Code window picks up the new
build automatically; no restart needed.

### 8. Verify versions agree AND web sync took effect

```bash
~/.local/bin/ppxai --version
~/.local/bin/ppxaide --version
~/.local/bin/ppxai-server --version
~/.local/bin/ppxai-desktop --version
/Applications/ppxai.app/Contents/MacOS/ppxai-desktop --version
```

All five should print the same `X.Y.Z`. If `ppxai-desktop` reports a
stale version, the v1.17.7 fix (PyInstaller hidden-import for
`ppxai.version`) regressed — investigate before shipping.

Then sanity-check the on-disk web sync against a known-recent string.
Pick something from `ppxai/web/` that you know was added in this
branch — e.g. for v1.18.3 Item 16, `CompositeResult` was added to
`result-renderer.js`:

```bash
diff -q ppxai/web/shared/result-renderer.js ~/.ppxai/web/shared/result-renderer.js
# Expected: no output (files identical)
```

If `diff` reports a difference, step 5b didn't run or didn't take —
re-run it before claiming the install is complete. A 0-output diff
proves the on-disk copy matches what the binaries expect.

## Don't

- Don't sign the DMG / .app from this skill — code signing is a
  separate release-CI step. This is a local-test build.
- Don't push or tag from here — that's `/release v1.x.y`.
- Don't run on Linux/Windows. Use this skill's flow as a reference for
  the platform-specific commands but the macOS .app + DMG path doesn't
  translate.

## When to extend

If the build flow changes (new spec file, new platform, new asset),
update this skill and the `tests/test_version_consistency.py` sentinel
in the same commit so they stay in sync. The CLAUDE.md "Files Updated
by Release Script" table is the canonical list of touched files.
