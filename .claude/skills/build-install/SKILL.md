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

```bash
cd vscode-extension
[ -d node_modules ] || npm install            # only on first run / after dep bump
npm run compile                               # esbuild → dist/extension.js (107 KB minified)
npx vsce package --allow-missing-repository   # → ppxai-X.Y.Z.vsix (~128 KB)
cd ..
```

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

### 8. Verify versions agree

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
